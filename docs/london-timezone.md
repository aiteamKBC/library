# London timezone rollout

Historical phase record: current absent-boundary behavior retains original Cairo
for new legacy confirmations; see the
[current cutover checklist](loan-cutover-operational-checklist.md). A configured
London transition remains supported and must be an approved valid UTC instant.

This is the earlier rollout record. Current persistence/schema behavior is in
[Phase 2](phase2-timezones-email-schema.md); that phase adds an additive migration
and tests it only in an isolated in-memory database.

The original loan calculation compatibility policy below remains in place.
Display and recipient-timezone requirements are now superseded by
[user-local-timezones.md](user-local-timezones.md). React timestamps are device-local;
API timestamps are UTC. `USE_TZ` remains enabled and DateFields are never shifted.

## Required activation configuration

If `LIBRARY_LONDON_CUTOVER_AT` is configured, it must be an approved, immutable
ISO-8601 UTC instant (`Z` or `+00:00`). Empty/absent means no London transition is
configured and new legacy confirmations retain Cairo. There is deliberately no
default London date. Do not choose one from the current clock or invent a past
deployment date, and do not change a genuinely activated boundary afterward.
The fixed values in test settings/fixtures are synthetic and are not deployment
instructions.

Nonempty invalid London configuration blocks legacy confirmations with a
validation error. Reading records and saving unrelated fields remains
possible. No existing deadlines or timestamps are rewritten at startup.

The first confirmation is `approved_at`, falling back to `borrowed_at`:

- Before the boundary: extract the Cairo calendar date, including on later
  delivery edits.
- At/after the boundary: extract the London calendar date.
- Add exactly 30 calendar days plus the total delivery days in both cases.

The request creation time and delivery-edit time never select the policy.
Existing confirmed timestamps are protected. Missing legacy confirmation data
does not get inferred from a deadline or filled with the current edit time.
Checkout with an existing deadline preserves that deadline; delivery edits which
need an unavailable confirmation fail explicitly.

The read-only staff endpoint `GET /api/loans/{id}/return-date-preview/?deliveryDays=N`
uses the same model calculation as saving. The UI does not duplicate the formula.
Pending-request previews are estimates at request time; confirmation is definitive
if the London calendar day changes in between.

## Local verification (no existing databases or external services)

From `backend`, use `venv/Scripts/python.exe -B run_isolated_tests.py library`.
This entry point removes inherited application configuration, skips `.env`, uses
an in-memory SQLite test database, and blocks network/database-service/mail sends.
Migration modules are disabled: disposable tables are built from models without
executing migration files or accessing an existing database.

From `frontend`, use the installed Node executable with
`--test src/lib/libraryDates.test.mjs`. These tests use synthetic responses and
block real fetch/socket connections. They do not load Vite or `.env` files.
Type-check with the installed TypeScript CLI and `--noEmit --project tsconfig.app.json`.

No schema migration, historical data migration, email queue, email scheduler,
or n8n change is included. Before deployment, approve the boundary, verify legacy
confirmation completeness, coordinate all application instances, and review the
separate n8n SQL/session timezone and reminder cutover. Do not deploy this code
with an unapproved boundary or with mixed application versions.
