# Phase 4A — local readiness fixes (no activation)

## Cutover: configuration decision remains blocked

With `LIBRARY_USER_LOCAL_POLICY_ENABLED=False`, first confirmation still selects
the approved Cairo/London legacy policy using `LIBRARY_LONDON_CUTOVER_AT`. An empty
cutover cannot safely establish which policy applies. Disabling student-local
policy does not implicitly select either city. This remains fail-closed; no date,
fallback, policy activation or historical classification is introduced.

`Loan.first_confirmation_policy` now validates the confirmation instant before
comparisons, so missing/naive/incorrectly typed input raises ValidationError rather
than TypeError. Existing snapshots/deadlines bypass first-policy selection. Tests
cover no-op saves/checkout preserving a nonstandard saved date, and an intentional
delivery edit continuing to use its frozen Cairo anchor without a configured
cutover. A synthetic student-local cutover is used only in tests, never settings.

Operator decision still required: approve the real transition policy/boundary.
The library must not be activated by inventing a timestamp in this change.

## Timezone reminder reactivation: implemented

The old enqueue path returned any matching idempotency row unchanged. Consequently
a reminder cancelled when travel moved the local date backwards remained cancelled
even when the same calendar-day slot became eligible again.

The scheduler now locks Loan then the existing Outbox row. It may reactivate the
SAME UUID/event/idempotency key only when all of these remain true:

- The current loan is eligible now under its current recipient timezone/date.
- The cancellation reason is local-day expiry or an invalid local reminder time.
- Source, recipient, address, role, event, due date, local day and revision match.
- There is no accepted timestamp, no recorded attempt and attempts_count is zero.
- Event ownership/handoff/live gates remain satisfied (fake-only isolated settings
  retain their existing test exception).

It refreshes local timezone, UTC window and public payload without resetting
attempt history. Accepted, uncertain, inflight, failed, blocked, returned,
source-changed and previously attempted messages are never resurrected by this
path. A genuinely changed due date gets its own NEW revision/key. Concurrent
schedulers serialize on the same loan; workers still use their fenced leases.

## Exact recipient allowlist: implemented, deny-all by default

New setting: `LIBRARY_EMAIL_RECIPIENT_ALLOWLIST`, a comma-separated list of explicit
mailbox addresses, default empty. Matching is case-insensitive on the full address.
Wildcards/domain-only/display-name entries are not supported; any malformed entry
fails the configuration closed. There is no allow-all switch.

Both Worker eligibility and GraphClient.send enforce the allowlist. The latter
checks BEFORE acquiring a token and before sendMail, including with fake
transports or a cached token. Worker denial is `blocked / recipient_not_allowlisted`
with no submission attempt. A direct client denial is a known non-submission
failure, not uncertain. Changing authorization after a claim is checked again.

The original recipient is never changed, substituted or redirected. An allowed
test mailbox does NOT authorize emails whose recipient is a student's address.
An empty/invalid allowlist also prevents a real worker from starting or the live
handoff guard from claiming ownership. Staff may explicitly retry a blocked
message once its actual recipient has been authorized, subject to existing rules.

All existing feature flags stay default false. No `.env` was changed; no actual
address/secret was configured. n8n workflows and legacy send paths are unchanged.
The allowlist governs the new Graph flow, not a global kill switch for old n8n/SMTP.

## Changed files

- `backend/config/settings.py`: new empty allowlist configuration.
- `backend/library/email_policy.py`: exact-address parsing and deny-all gates.
- `backend/library/email_worker.py`: block unauthorized recipients before attempt.
- `backend/library/graph_client.py`: recipient guard before any external request.
- `backend/library/email_scheduler.py`: locked, narrowly scoped reactivation.
- `backend/library/models.py`: aware-confirmation validation before policy choice.
- `backend/library/test_email_readiness.py`: new regression and guard tests.
- `backend/library/test_email_system.py`: explicitly authorize synthetic fixtures
  under the new gate; previous test expectations retained.
- `backend/config/schema_test_runner.py`, `backend/config/test_settings.py`,
  `backend/run_isolated_tests.py`, `backend/run_local_postgres_tests.py`: opt-in
  schema-only test setup. It creates fresh synthetic model tables directly with
  SchemaEditor, never executes migrations, forbids MigrationExecutor.migrate and
  skips the existing migration round-trip test for this run.
- This document; Phase 3 documentation links to these additional safeguards.

## Verification method

```text
backend/venv/Scripts/python.exe -B backend/run_local_postgres_tests.py --schema-only --pg-bin <installed-local-PostgreSQL-bin>
```

Only a brand-new temporary PostgreSQL cluster on 127.0.0.1/random port is allowed,
using synthetic users/databases/data. Test environment is cleared, .env skipped,
and SMTP/webhook/socket/other database connections blocked. Only fake Graph clients
and fake transports are used. The local test cluster is stopped in finally.

Regression coverage includes timezone travel/re-eligibility, US/UK/Egypt DST
transitions, changed deadlines/revisions, concurrent reactivation/claims, preventing
replay after any attempt, allowlist revocation, zero token calls for rejected
recipients, no recipient substitution, default-off gates and legacy date stability.

Local results: targeted email/readiness suite 90 passed; full library suite 157
tests, 156 passed and one deliberately skipped (the existing migration round-trip
test). All PostgreSQL locking/concurrency tests ran. Both runs used PostgreSQL
17.12 with schema-only setup and fake transports; test clusters stopped afterward.
No migration files were created, modified or executed.

## Before any future real-mail test

Approve an explicit test recipient and sender/Reply-To; verify rotated Entra
credentials, application send permission and mailbox scope with Microsoft 365.
Use a separate synthetic database/queue, authorize only the real test inbox in
the allowlist, and obtain explicit activation approval. Never rely on --limit 1.
Complete the n8n ownership handoff/reconciliation before event production use.
No Graph/n8n/service/production activation or email transmission occurred here.
