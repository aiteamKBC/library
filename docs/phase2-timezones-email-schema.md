# Phase 2: persisted timezones and email schema

## Scope and activation

Implemented locally on eslam-branch. Migration 0024 is additive and was applied
only to disposable in-memory SQLite databases. No existing/shared database was
opened, no .env loaded by the isolated runner, and no email, webhook, Graph client,
worker or scheduler was started. Existing n8n routes remain unchanged. No runtime
event handler creates EmailOutbox/EmailAttempt records in this phase.

Two new tables: library_email_outbox and library_email_attempt. Existing tables
gain three UserProfile fields and five Loan fields. library_notification_log and
its unique(loan, notification_type) constraint are unchanged. No EmailJobState,
duplicate user table, inferred timezone or historical policy backfill was added.

## User preferences

UserProfile's existing OneToOne user relationship supports students and staff:

| Column | Definition |
| --- | --- |
| time_zone | nullable varchar(100), validated IANA identifier; no timezone default |
| time_zone_source | browser/manual; empty only while preference is missing |
| time_zone_updated_at | nullable server timestamp, timezone-aware UTC |

A database check requires the three values to be complete together, or all
missing. ZoneInfo validation happens at the API/service boundary. No timezone is
inferred from email/IP. The frontend detects the device zone on authenticated
login/session refresh and device changes. Focus/visibility explicitly re-observe
even an unchanged local zone, so returning to an already-open device is not hidden
by its cache after another device changed the saved browser preference. Periodic
checks deduplicate unchanged zones. Current preferences remain available
offline through UserProfile.

POST /api/auth/timezone-observation/ accepts only {"timeZone": "IANA/name"}.
It saves the current authenticated user's browser preference, except that an
existing manual preference is preserved. Responses expose savedTimeZone, source,
updatedAt, saved and status (saved/manual_preserved/stale_ignored). This replaces
Phase 1's explicit storage_required response.

PUT /api/auth/timezone-preference/ accepts only timeZone and source. source=manual
sets an explicit preference; source=browser explicitly returns to device-following
mode. The frontend API exposes setMyTimezone for this contract; no new settings
screen was added. Both endpoints reject target user IDs and posted timestamps.

The service locks the user/profile and orders updates by server observation time.
Older in-flight updates cannot replace newer preferences. Automatic observations
never overwrite a saved manual choice. Native Admin fields are read-only to avoid
an alternative update route bypassing those rules. Auth/profile responses expose
the saved zone/source, update time and missing/invalid/valid status.

An external mailbox without an account has no profile preference. Future email
creation must use a separately verified recipient configuration or hold the
message as blocked; it must not silently assume London, UTC or the operator's zone.

## Immutable loan calendar

| Column | Definition |
| --- | --- |
| calculation_policy | nullable cairo_v1/london_v1/user_local_v1 |
| calculation_timezone | nullable validated IANA snapshot |
| operational_timezone | nullable validated authoritative overdue/return calendar |
| confirmation_local_date | nullable immutable first-confirmation calendar date |
| email_deadline_revision | nonnegative bigint, baseline 0 |

The four calendar fields are either all NULL (unclassified history) or all present.
Database checks also bind Cairo/London policy names to their calculation zones and
require user_local_v1 operational/calendar zones to agree. The snapshot becomes
immutable once confirmed. It is not derived from requested_from, a device clock,
request creation date or the time of a delivery edit.

At first confirmation, the server retains approved_at then borrowed_at precedence.
It saves the selected policy, IANA zones and local date in the same transaction as
the deadline. Formula stays: original local date + 30 calendar days + total
delivery_days. Later delivery edits use that frozen local-date anchor, so travel,
preference changes and tzdata corrections cannot reset it. Notes, equal delivery
values and approved-to-borrowed transitions preserve the saved deadline. Missing
original confirmation data is never filled with an edit timestamp.

For classified rows, overdue/return comparisons use operational_timezone, not the
administrator's device or the recipient's reminder timezone. Unclassified rows
retain Phase 1's explicit London operational behavior for reading/status checks;
they are not thereby classified, and their deadline recalculation is blocked.

### Explicit activation guards

- LIBRARY_USER_LOCAL_POLICY_ENABLED defaults to false.
- LIBRARY_USER_LOCAL_CUTOVER_AT has no production value. Enabling the flag without
  an approved aware UTC boundary fails closed.
- At/after the approved new boundary, confirmation requires a linked student
  account and valid saved student timezone. The approving staff member's zone is
  irrelevant. No fallback for missing identity/preference is assumed.
- Before that boundary (or with the flag off), the existing
  LIBRARY_LONDON_CUTOVER_AT compatibility path remains. It still requires its own
  approved UTC configuration. New confirmations on that path capture Cairo/London
  metadata, with Phase 1's London operational calendar.
- Existing confirmed rows with NULL policy metadata are never reclassified from
  either flag/cutover. They remain readable and allow unrelated saves, but delivery
  recalculation needs a separately authorized, evidence-based classification.

No production cutover was chosen. Production was reported not to have activated
the prior London rollout; deployment/release evidence is still needed to classify
any environment's historical Cairo/London rows correctly. Do not copy synthetic
test boundaries into production or use a guessed backfill.

## Revision and mutation boundaries

Loan.save locks the current database row inside a transaction, calculates the
final date through the existing model path and compares the date actually being
persisted. A real date change increments the stored revision exactly once; notes,
same dates and changes excluded by update_fields do not. Row creation establishes
baseline 0; changing an existing date (including NULL transitions) increments it.
Both keyword and legacy positional update_fields preserve automatic fields.

Stale conflicting deadline edits fail with a reload message rather than overwrite
newer dates. Repeated equal partial delivery edits are no-ops for the counter.
API, direct saves and Admin share this implementation; metadata/revision are
read-only through API/Admin. Admin rolls back and reports validation failures.

The public Loan manager rejects update/bulk_update of state, confirmation,
delivery, deadline, policy or revision fields, and rejects bulk_create. Use the
model path. _base_manager/SQL are deliberate framework/maintenance bypasses; they
are used only for explicit synthetic historical fixtures in tests, not app writes.
Any future data operation using those bypasses needs separate authorization and
must maintain the same invariants. No DB trigger was installed.

## Outbox and attempts

EmailOutbox uses a UUID PK. event_id is indexed but not unique because one event
can have multiple recipients. idempotency_key is mandatory, nonempty and unique.
The schema stores event type/kind, recipient identity/email/role/timezone snapshot,
template/version, JSON-object payload, deadline/date/local-day snapshots, retry
availability, expiry, attempt count, lease token/owner/expiry, provider tracing and
sanitized error code/summary. Absolute timestamps require aware values and are
normalized to UTC. No raw provider-response column was introduced.

Loan and BookRequest FKs are optional SET_NULL; both inherit the existing varchar(50)
PKs. At most one source FK is present. source_type/source_id survive deletion so
history is not lost. Optional recipient-user FK also uses SET_NULL. Message
identity/timezone snapshots remain independent of profile edits or deletion.

Statuses: blocked (safe default), pending, retry_wait, claimed, submitting,
accepted, failed, uncertain, cancelled. Ready states require a timezone; reminders
require due-date/revision/local-date/expiry snapshots. Leased states require all
lease fields; other states require them cleared. Accepted requires accepted_at and
means provider acceptance, not proof of delivery. Uncertain is a distinct state,
not an instruction to auto-retry. Indexes cover status/availability, lease expiry
and loan/deadline revision. Missing-recipient-zone messages can remain blocked.

EmailAttempt has a mandatory PROTECT FK to Outbox and unique(message_id,
attempt_number). Attempt numbers start at 1. It records start/end, result, HTTP
status, trace IDs, owner/lease and sanitized errors. Database checks protect
number/HTTP/result/time consistency. Instance and public-queryset deletion are
blocked; Outbox deletion with attempts raises ProtectedError. Retention requires
a separately approved maintenance process. Native email Admin views are read-only.

## What Phase 3 must implement

- A single authoritative email owner per event during n8n/Graph handoff; no parallel
  new sender was activated. NotificationLog must remain compatible until then.
- Transactional event enqueue after a successful business operation, stable event
  IDs and validated minimal template payloads. Event messages are immediate.
- Reminder planning at recipient-local 09:00 on stored due_date, then overdue days
  1/3/5/7/9..., converted to UTC using that day's DST rules. due_date remains a
  literal calendar date, never converted into a different date.
- Current-day-only eligibility, expiry and no missed-day catch-up. The existing
  pure timing helpers prepare these rules; no live scheduler exists.
- Re-evaluate unsent reminders when preference changes, preserving logical keys
  and accepted history. Suppress duplicates and backward reminder progression
  after travel. Do not recalculate the loan deadline.
- Cancellation/expiry after return, source deletion or deadline/revision change,
  plus final eligibility checks immediately before submission.
- PostgreSQL claim locking/SKIP LOCKED, lease fencing, atomic attempt creation and
  attempts_count updates, bounded retry/backoff and explicit uncertain review.
  Attempt creation does not automatically adjust counters in this schema phase.
- Graph authentication/sending, templates, monitoring, rate limits, retention and
  real PostgreSQL/concurrency/integration tests. No Graph calls were made here.

## Local verification and limitations

The isolated runner clears inherited application configuration, skips .env and
forces an in-memory SQLite test database. Socket, external PostgreSQL and all
email/webhook delivery paths are blocked. Phase 2 now permits existing/new
migration files to execute only in that disposable database.

Generate/check schema via `run_isolated_tests.py --makemigrations` and
`run_isolated_tests.py --makemigrations --check --dry-run`. Run tests via
`run_isolated_tests.py library`. A MigrationExecutor test migrates from 0023 to
0024 and back, preserving historical dates/timestamps/delivery/profile data and
NotificationLog; added policy/preference fields remain NULL and revisions 0.

SQLite tests verify schema constraints, stale-instance/repeated-edit safeguards,
API/Admin/direct-save revisions, ownership/manual precedence, snapshots and DST.
They do not establish PostgreSQL row-lock behavior. A genuine threaded PostgreSQL
test is included but skipped without an isolated PostgreSQL database. No local
PostgreSQL/Docker executables were available; none was installed or connected.
That test and deployment locking/index/rollback review remain pre-production work.
