# Final loan timezone cutover — prepared locally, NOT activated

## Historical evidence and limits

The former pre-T HTTP 400 has since been fixed: an absent London transition now
retains Cairo for new legacy confirmations. See the current
[blocker closure and 17-request rollout checklist](loan-cutover-operational-checklist.md).

The reviewed Git baseline (`079ded8`) configures `TIME_ZONE = Africa/Cairo` and
`USE_TZ = True`. Its Loan.save validates/saves/synchronizes copies; it does not
establish the later automatic 30 + delivery_days formula. Its API exposes a
writable calendar due date. Thus neither the original application timezone nor a
saved due date proves how every historical record was calculated.

The subsequent local London implementation introduces an explicit
LIBRARY_LONDON_CUTOVER_AT, without a production default. Its documented and tested
dates are synthetic. Existing schema 0024 introduces nullable policy snapshots
without backfilling history. None of those facts proves a real London deployment
or an actual historical London activation instant.

No production database, deployment history, .env or running-process configuration
was inspected or changed in this task. Do not invent a London timestamp or infer
one from a request date, a deadline, a local test or a Git commit date.

## Approved policy

Let T be the immutable, explicitly approved UTC activation instant:

- First confirmation AT/AFTER T: read and lock the student's saved IANA timezone;
  persist user_local_v1, calculation_timezone, operational_timezone and the local
  date of the first confirmation. Due date = that date + 30 calendar days + total
  delivery_days. Changing country/profile later does not change that snapshot.
- Before T: do not reclassify existing history. Keep every stored date, original
  approved_at/borrowed_at and existing snapshot exactly as stored. An unclassified
  historical record remains unclassified.
- The user explicitly clarified that old deadlines must remain FIXED even when
  delivery_days itself changes. Once T is reached, old delivery edits update the
  number only; they do not recalculate due_date or increment email_deadline_revision.
  Preview follows exactly that rule. Direct attempts to overwrite the protected
  deadline are rejected. Returns and approved-to-borrowed transitions retain it.
- Old records with no trustworthy confirmation anchor are preserved conservatively,
  without classifying their timezone. A missing historical due date is never
  reconstructed automatically; a checkout/recalculation needing it fails clearly.
- New post-T delivery edits continue using the frozen student calendar and original
  confirmation date, never the edit date or the student's later country.

The first timestamp is approved_at, falling back to borrowed_at. Request creation
time, requested_from and delivery-edit time do not choose the cohort. First
confirmation is a server-generated aware instant. Stored timestamps remain UTC;
due_date remains DateField. No data migration or backfill is needed or included.

The fixed T also retains historical deadline protection if the new-confirmation
flag is later disabled. Never erase/move T as a rollback shortcut. Before a future
T is reached, existing behavior remains in effect; setting a future boundary does
not freeze records early.

## Exact future configuration — not applied here

```text
LIBRARY_USER_LOCAL_CUTOVER_AT=<approved immutable UTC ISO-8601 instant, ending Z or +00:00>
LIBRARY_USER_LOCAL_POLICY_ENABLED=true
```

No literal activation date is supplied here. Approve and record T externally in
the deployment/change record, in UTC, with the approved code revision. Set that
same exact value for all application processes; do not set it from now() in code
or change it on subsequent restarts. USE_TZ stays True. The application default
timezone and email/n8n activation settings are unchanged by this task.

London history is NOT required for first confirmations at/after T: the student
policy path does not consult LIBRARY_LONDON_CUTOVER_AT. Leave that setting as it
is; do not populate it with a fictional historical date. If real London activation
is later proven, retain its actual approved boundary for the legacy path.

Before T (or while new-confirmation policy is disabled), first confirmations use
the original Cairo calendar when no London transition is configured. An explicitly
configured London boundary remains supported and must be valid. This selects the
legacy calculation calendar, not the student's personal timezone, and does not
classify or recalculate any stored historical record.

## Activation procedure — future authorization only

1. Verify existing timezone/policy columns are already available and the intended
   code is ready. This task performs no migration or production schema query.
2. Ensure students who will confirm have a linked account and valid saved timezone.
   Missing/invalid timezone/account causes an atomic, clear rejection, not a guess.
3. Approve T and coordinate all application instances. Quiesce confirmations and
   finish in-flight approval transactions; avoid mixed policy/code/configuration.
4. At the approved change window, configure the two values above and start the
   intended application instances at/after T. These operational steps are NOT
   performed by this task. No retrospective timestamp should be invented later.
5. Confirm one synthetic/development scenario at/after the boundary and verify
   the first timestamp, frozen student zone, date + 30 + delivery_days and untouched
   historical dates. Production validation requires its own authorization.

Remaining blockers: approval/recording of T, authorized process rollout and actual
student preference readiness. No historical London date needs to be approved just
to enable either the original Cairo legacy path or the post-T student path.

## Local implementation and tests

- `backend/library/models.py`: historical_deadline and save/calculation/preview
  protection, including explicit rejection of a historical deadline overwrite.
- `backend/library/test_final_loan_cutover.py`: synthetic boundary, midnight,
  Cairo/London/New York/Dubai, winter/summer and DST, admin/API, travel, delivery,
  unknown history, missing timestamp/deadline and immutable-date regressions.
- This document. No email/n8n code, .env, activation default or migration changed.

Tests use the existing `run_local_postgres_tests.py --schema-only` runner with a
fresh synthetic localhost PostgreSQL cluster. Tables are created directly from
models, migration execution is forbidden, external requests/mail are blocked,
and the temporary database server is stopped after the run. Boundary literals
in tests are fixtures only and must never be used as production activation dates.

Verification: 183 tests on isolated PostgreSQL 17.12; 182 passed, one existing
migration round-trip test deliberately skipped because migration execution is
forbidden. All 26 final-cutover tests and real PostgreSQL concurrency tests ran.
No migrations were created, modified or executed; the synthetic server stopped.
