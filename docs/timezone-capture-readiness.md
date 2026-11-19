# Timezone capture readiness — local UI/session fixes

No cutover, real database or email system was activated or modified.

## Implemented

- A shared React session snapshot now consumes the existing Backend response for
  student/admin login, session refresh, device observation and explicit preference.
  It uses savedTimeZone/source/updatedAt, never assumes the observed zone was saved.
- Timezone failures publish a visible warning without clearing authentication.
  Requests have an eight-second bound; success is not claimed on timeout, missing
  saved timezone or an HTTP error. The widget shows the last confirmed setting.
- Retry repeats the failed operation, including a manual preference. Background
  device observations do not silently replace or hide a failed manual selection.
- An authenticated timezone widget offers an IANA input/datalist, manual save and
  an explicit "Use device timezone" action. It reuses timezone-preference; no new
  Backend validation/storage/API or timezone defaults were introduced. It floats
  above the application's fixed navigation so the warning remains visible.
- Subscriptions update the student and React admin immediately. Late observations,
  older profile responses and responses after logout/account changes cannot undo
  a successful manual choice or replace another account's session data.
- Native Django Admin still only displays device time; its own timezone capture
  was not duplicated. Staff can use the React admin with the same account.

## Files

- frontend/src/lib/api.ts — confirmed session state, error/retry, timeout and races.
- frontend/src/hooks/useLibrarySession.ts — subscribed session and preference actions.
- frontend/src/components/feature/TimezoneSettings.tsx — shared warning/preferences UI.
- frontend/src/App.tsx — widget placement for authenticated students and admins.
- frontend/src/lib/timezoneSession.test.mjs — fake-transport and rendered-UI tests.
- This document.

## Pre-cutover confirmation blocker resolved subsequently

The original review reproduced HTTP 400 with the student policy disabled and no
London boundary. The later Cairo compatibility fix removes that unnecessary
requirement for new legacy confirmations while preserving existing saved dates.
See [the current rollout checklist](loan-cutover-operational-checklist.md).

For a separately approved rollout, first expose the existing timezone capture
with cutover off, verify actual saved profile values and linked borrower accounts
for pending confirmations, then approve/document the immutable UTC user-local
boundary and coordinate activation. Post-boundary confirmations use saved student
timezones without requiring a fictional London history. Users without valid zones
remain clearly blocked from new-policy confirmations rather than being guessed.

## Verification

- Frontend: 23 tests passed (12 new), including failure/retry, login surviving a
  capture failure, backend-confirmed session values, manual preservation, stale
  responses, account switching, timeout and React-rendered warning/controls.
- TypeScript --noEmit --incremental false: passed.
- Backend: 61 tests passed on fresh isolated PostgreSQL 17.12, using schema-only
  setup (no migrations). Includes persistence, manual protection, cutover failure
  and historical/new loan calendar regressions. Temporary server stopped.
- Tests use synthetic users and fake HTTP only. UI checks render React markup;
  no running application or production browser/backend was contacted.

No Neon, .env, n8n, Graph, migration, deployment, push or live cutover operation
was performed. Existing feature defaults remain unchanged.
