# Phase 1 design record: user-local timezone display

This document records the Phase 1 implementation and its then-pending schema.
For current persistence, models, migration and activation behavior, see
[Phase 2](phase2-timezones-email-schema.md). In particular, preferences now persist
and the isolated runner now permits migrations on its disposable test database.

## Implemented locally

- React detects `Intl.DateTimeFormat().resolvedOptions().timeZone` on use; absolute
  timestamps render in the viewer's timezone, including seasonal rule changes.
- DateFields remain literal calendar dates. No React loan-duration formula was
  introduced; the existing model-backed preview remains authoritative.
- API DateTimes serialize as UTC. Naive incoming timestamps are rejected rather
  than interpreted using a viewer or server timezone. Booking/creation timestamps
  come from the server, not from a client clock.
- Library Django Admin lists/readonly timestamps have device-local display.
  Editable native Admin datetime widgets retain Django's server-timezone input
  semantics and show a labelled device-time preview; their values are not rewritten
  by JavaScript. The existing confirmation/checkout readonly protection is retained.
- The authenticated observation endpoint below validates a browser timezone for
  either a student or staff account. Login/session refresh, focus, visibility and
  periodic checks notice device changes. It does **not** save a preference.
- Existing delivery, timestamp protection, update_fields, historical deadlines,
  Cairo/London cutover behavior and the model's shared 30 + delivery_days formula
  are retained. No records are reclassified or recalculated by this update.
- Return-history lateness comes from the backend, not the viewer's calendar day.
- Pure, side-effect-free helpers cover immutable student-zone policy values,
  recipient timestamp formatting and reminder eligibility. They are not wired to
  an email queue/worker/scheduler or to new-policy loan confirmation.

## Phase 1 timestamp display contract

Booking, borrowing, return, support/request activity and history timestamps now
show a local clock time and timezone label, not just a converted date. They use
the shared `formatLibraryTimestamp`; date-only values continue to use calendar
formatting without acquiring a fictional midnight. The feedback page recomputes
its timestamp label when the device timezone changes instead of retaining a
memoized label for the previous timezone.

Timestamp strings must carry an explicit ISO-8601 offset (`Z` or `+/-HH:MM`).
The frontend parses the identified instant once and lets Intl perform the device
conversion. It does not append Z, shift hours manually, or guess a timezone for
unlabelled strings. Invalid timestamps/calendar dates use the display fallback;
invalid dates are not silently rolled into another calendar day.

Phase 1 verification passed 59 isolated backend tests and 10 Node tests, plus
TypeScript checking. Existing Cairo/London deadline expectations were preserved.
Added coverage includes equivalent offset representations, different national
DST dates, skipped/repeated hours, historical calendar values and unchanged loan
deadlines/confirmation instants after reads and note edits in all four target
timezones. No database columns, migrations or email integration were added.

`TIME_ZONE` remains `Europe/London` for compatibility, **not** as the viewer's or
recipient's preference. UTC storage already follows from USE_TZ and UTC-aware
timestamps; API fields explicitly use UTC. Changing Django's default now would
also change `Resource.date_added`'s implicit model default (and the seed fallback).
That model-default change needs a separately approved migration review. Loan
calculations/overdue checks are explicit and independent of the active timezone.

## Authenticated observation contract (not persistent settings)

`POST /api/auth/timezone-observation/`, authenticated with the current user's token:

```json
{"timeZone": "America/New_York"}
```

The response is explicit about the storage blocker:

```json
{"observedTimeZone": "America/New_York", "savedTimeZone": null,
 "saved": false, "status": "storage_required"}
```

Unknown fields (including user IDs or confirmation timestamps), missing/invalid
IANA identifiers and unauthenticated requests are rejected. The endpoint writes
neither user nor loan data. Browser observations are not saved email preferences
and must never be used as an ad-hoc authoritative loan calendar.

## Proposed columns ONLY -- no model fields or migrations added

Use the existing UserProfile OneToOne to AUTH_USER_MODEL for both learners and
staff. Do not repurpose phone/student-id columns, auth timestamps or cache entries.

| Model | Proposed field | Definition / purpose |
| --- | --- | --- |
| UserProfile | time_zone | CharField(max_length=100, null=True, blank=True), validated IANA identifier; no default zone |
| UserProfile | time_zone_updated_at | DateTimeField(null=True, blank=True), server UTC observation timestamp |
| Loan | calculation_policy | CharField(max_length=20, null=True, blank=True): cairo_v1 / london_v1 / user_local_v1; NULL means unclassified |
| Loan | calculation_timezone | CharField(max_length=100, null=True, blank=True), immutable validated IANA key |
| Loan | operational_timezone | CharField(max_length=100, null=True, blank=True), immutable authoritative overdue/return calendar |
| Loan | confirmation_local_date | DateField(null=True, blank=True), immutable date of the original approved_at-or-borrowed_at in calculation_timezone |

All four Loan fields are written together or left NULL together. No new FK is
required: Loan.borrower already references the user; its profile supplies the
approved preference. The snapshot must remain independent of later profile edits.
Loan PK remains varchar(50). Existing user/loan/book relationships and deletion
rules are unchanged.

An explicit operational timezone is necessary to preserve verified historical
calendar semantics: the previous local implementation used a Cairo calculation
anchor but London overdue boundaries for legacy loans. Do not infer the deployed
production behavior from that local implementation. For new user_local_v1 loans,
both calendar zones equal the student's saved timezone at first confirmation.
The local date snapshot also prevents later tzdata corrections from silently
changing the original calendar-day anchor during a delivery edit.

## Proposed migration/activation plan -- NOT executed

1. Approve the columns and identity/fallback decisions below. Create an additive,
   nullable schema migration in a subsequent authorized task; no default Cairo,
   London or UTC preference should populate historical rows automatically.
2. Audit deployed release history and the actually activated cutover configuration.
   The earlier London rollout was reported as local-only/not activated in production.
   Do not invent an activation date or assume this proves every environment's data.
3. In a separately approved data operation, classify only verified records:
   historical Cairo anchors as cairo_v1; genuinely activated London anchors as
   london_v1. Derive snapshots from the original aware confirmation, never from
   requested_at, due_date, current profile timezone or edit time. Preserve every
   stored due_date, delivery_days and original timestamp. Unknown records stay
   unclassified and cannot have their deadlines recomputed by guessing.
4. Implement persistent self-service timezone updates on request.user's profile
   only. Use validated IANA keys and server observation times, with concurrency
   protection so older in-flight observations cannot overwrite newer ones. Expose
   missing/invalid preferences to monitoring. Do not switch the observation
   response's saved flag until a durable write actually succeeds.
5. Approve a separate immutable UTC user-local activation boundary. No value is
   supplied here. Preserve any verified older London boundary; do not repurpose it.
6. Enable new-policy confirmation only after schema and classification readiness.
   Lock the loan/student profile in a consistent transaction, read the **student's
   saved timezone** (approved requirement), obtain server UTC confirmation time,
   persist immutable policy/timezones/date and the derived deadline atomically.
   A request created before the boundary but first confirmed after it uses the new
   policy. Repeat confirmations, travel and preference changes cannot reset it.
7. Update authoritative overdue/return checks to use each verified operational
   snapshot. Admin/viewer timezone must never alter persisted status. Current
   legacy London-day behavior remains until that approved transition; no new
   user-local loan policy has been activated by this task.
8. Only then consider Django TIME_ZONE=UTC with explicit compatible model defaults,
   Admin input semantics and regression tests. Do not change that setting alone.

## Email architecture and required future integration

The current backend still calls the existing n8n webhook; manual mail uses
send_mail. NotificationLog remains unchanged. No Graph sender, Outbox, Attempt,
background worker or scheduler was added or invoked.

For the future EmailOutbox + EmailAttempt implementation:

- Resolve each recipient to a saved, valid IANA preference. Staff are supported by
  UserProfile too; a hardcoded/guest email address is not proof of an account or
  preference. Missing/invalid preferences hold the affected message and alert an
  administrator; do not infer a zone from email, IP, device cache or server default.
- Store Outbox recipient timezone snapshot, scheduled_at/available_at UTC,
  reminder_local_date, expires_at UTC, due-date snapshot, deadline revision and a
  unique logical key. Optional Loan/BookRequest FKs inherit their varchar(50) PKs;
  retain immutable source identifiers when sources are deleted. Attempt requires
  its Outbox FK and unique(message_id, attempt_number). No such tables exist here.
- Deadline revision persistence and transactional cancellation/enqueue remain
  future work. The pure helper takes a supplied revision; it does not maintain one.
- Due Today is due_date; Overdue days are 1,3,5,7,9,... in the recipient's current
  saved timezone at 09:00. Convert that local execution instant to UTC. Check the
  recipient's current local date only, not missed dates. A missing local 09:00 is
  skipped; an ambiguous 09:00 uses its first occurrence once.
- Logical identity includes loan, recipient identity/role, due date/revision and
  reminder day, but excludes timezone/execution instant. Travel reschedules an
  unsent logical reminder rather than creating a duplicate. Never replay an
  accepted reminder; never move backward to an earlier accepted reminder slot.
- A timezone change requires re-evaluating unsent plans and current-day eligibility.
  Last accepted reminder progress must be read from durable storage under the
  concurrency protocol; helper key generation alone cannot enforce delivery dedupe.
- Before submission recheck returned/cancelled status, current deadline/revision,
  recipient preference and expiry. Invalidate stale reminders. Coordinate claim
  leases and attempts; external uncertain submissions must not be blindly retried.
- Format absolute timestamps using that message's validated recipient-zone
  snapshot, with zone/offset visible. Keep the stored due date as a date.
- Event-driven approval/cancellation/return/deadline-update messages are immediate;
  do not pass them through the 09:00 reminder gate.
- Real scheduling/delivery is **not complete** until persistence, workers,
  scheduler, database uniqueness/locking, Graph integration and concurrency/
  integration tests exist. Pure helper tests do not establish those guarantees.

## Decisions/blockers before activation

- Approved: new loan calculation timezone is the student's saved timezone at
  confirmation, not the approving administrator's timezone.
- Still requires approval: schema/migration execution, real historical policy
  evidence, actual user-local cutover instant, and any fallback for missing/invalid
  preferences. Current recommendation is hold/block, not assume a timezone.
- Define last-active-device preference ownership when multiple devices report
  different zones. Observations must be ordered using server time, not client time.
- Loans with no linked borrower account and administrative mailbox recipients
  without profiles need explicit identity/preferences before user-local activation.
- The library must accept that two recipients can receive a reminder for the same
  stored date at different UTC instants; this does not change the authoritative
  loan status or loan deadline.

## Verification

Use the existing isolated test entry point. It clears inherited application
configuration, never loads .env, blocks external database/socket/mail calls and
builds only synthetic in-memory SQLite tables. Migration modules are disabled;
no migration files execute. Node tests also block real networking and avoid Vite.
No production/shared database, n8n, Graph, live worker or scheduler was accessed.
