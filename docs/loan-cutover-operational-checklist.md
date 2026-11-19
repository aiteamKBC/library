# Loan cutover blocker closure and 17-request operational checklist

## Local result

The prior HTTP 400 came from treating an OPTIONAL London migration as mandatory
for every legacy confirmation. The Git baseline `079ded8`,
`backend/config/settings.py:143`, explicitly uses Africa/Cairo, with USE_TZ=True
at line 145. The earlier local calculation record also identifies a Cairo anchor
(`docs/user-local-timezones.md`). There is no reviewed evidence of a real London
activation date. This supports retaining the ORIGINAL Cairo path for new legacy
confirmations, not inventing a London transition or classifying historical rows.

Current behavior:

- Empty/absent LIBRARY_LONDON_CUTOVER_AT: new legacy confirmations use the Cairo
  calendar explicitly, independent of global/active Django timezone. First local
  confirmation date + 30 calendar days + total delivery_days remains the formula.
- A nonempty valid London boundary retains the existing Cairo-before/London-after
  selection. A malformed nonempty boundary still fails clearly; no silent fallback.
- Student-local flag false: legacy confirmations can continue without collecting
  student timezones first. They do NOT save a guessed timezone to UserProfile.
- Student-local flag true and confirmation >= approved student-local T: use the
  student's saved IANA snapshot. A missing student-local T or profile zone still
  fails; the Cairo path never bypasses the new policy's required inputs.
- Existing due dates, first timestamps, snapshots and unclassified history are
  not rewritten. Once the approved student-local boundary is reached, pre-T
  deadlines stay fixed even if delivery_days changes, as explicitly requested.

Only source behavior was reviewed. No actual production loan or activation
history was queried; the count of 17 requests comes from the user.

## Concrete SELECT-only readiness tool

An operator may run this LATER on an explicitly verified/authorized environment:

```text
python manage.py check_loan_timezone_readiness --expected-borrow-count 17 --require-ready
```

This command was NOT run against Neon. It uses SELECT only, performs no profile
creation, account linking, preference save, loan transition or external request.
It prints loan IDs and reason codes without names/emails or inferred countries.
Technical readiness errors make --require-ready exit unsuccessfully.

The output separates requested_total, requested_borrow and requested_notify. If
the user's 17 includes Notify enrollments, do NOT treat them as 17 borrow requests;
reconcile the count and use the verified number. Recheck the count immediately
before activation because the queue can change.

For EACH of the 17 borrow requests, record in the authorized operational tracker:

| Check | Pass criterion | Action if missing |
| --- | --- | --- |
| Request | still requested, loan_type=borrow | reconcile queue; exclude Notify |
| Borrower FK | linked to the actual requesting student | verify ownership, then use an authorized existing account-link workflow; never auto-link by email alone |
| Account | active and confirmed to belong to requester | resolve identity/account status before activation |
| Profile | existing UserProfile for that account | student's authenticated login creates/loads their own profile |
| IANA zone | valid saved IANA identifier | student opens Library/logs in and confirms the existing device/manual setting |
| Provenance | browser/manual source plus aware server saved timestamp | complete through the existing authenticated preference endpoints |
| Manual choice | remains authoritative if selected | do not overwrite from admin device, country, email or IP |
| Circulation | copy availability and normal approval rules still pass | resolve through existing library workflow; timezone readiness alone does not guarantee approval |

The tool automatically checks FK, account activity, profile, IANA and provenance.
Identity ownership and normal circulation checks still require their existing
authorization/workflow. READY from this tool is technical timezone readiness,
not permission to confirm or send an email.

Use one checklist entry per loan ID. Completion target: verified borrow count 17,
ready=17, blocked=0 (or the explicitly reconciled current count). Do not fill a
default country to make the report pass. Do not hold legacy confirmations while
collecting preferences: the repaired Cairo path can continue before T. Any loan
confirmed before T becomes historical and its saved due date stays fixed after T.

## Exact rollout order — not executed

1. **Deploy code separately, with student-local OFF.** In a later authorized
   deployment include the Cairo fix, existing browser capture/manual chooser and
   historical deadline protection. Leave email/Graph flags off and n8n unchanged.
   Preserve a genuinely configured London boundary if one exists; do not fabricate
   a value. Verify legacy confirmation/preview on a synthetic development record.
2. **Collect preferences while confirmations continue.** Students authenticate and
   confirm their detected or manual IANA zone using the existing UI. Existing
   sessions can refresh. React admin login captures the staff user's own zone;
   native Django Admin display alone does not. No bulk defaults/backfill.
3. **Complete the requested-loan checklist.** Resolve every outstanding account
   link/zone and run the SELECT-only checker in the authorized environment. Ensure
   future borrowers authenticate and save a valid zone before their first new-
   policy confirmation. A user without a trusted zone cannot be approved after T
   under the approved policy; do not replace that requirement with a guess.
4. **Approve and permanently record T in UTC.** Set one immutable ISO-8601 instant
   ending Z/+00:00, after readiness is complete. Record the same T with the release
   identity and operator authorization; never generate it from now() in code.
5. **Coordinate activation across instances.** Briefly quiesce confirmations and
   finish in-flight approvals; configure the approved values and restart the
   authorized instances consistently, avoiding mixed code/flags. Resume approvals
   at/after T. No retrospective date selection. This coordination is future
   operational work; no process configuration changed in this task.

Final future settings:

```text
LIBRARY_USER_LOCAL_POLICY_ENABLED=true
LIBRARY_USER_LOCAL_CUTOVER_AT=<approved immutable UTC ISO-8601 timestamp>
LIBRARY_LONDON_CUTOVER_AT=<retain only an already-proven transition; otherwise absent/empty>
```

No real activation date is supplied here. Keep T after activation even if the
new-confirmation flag is later turned off, so historical date protection remains.
No global TIME_ZONE/USE_TZ change, migration, email activation or n8n change is
required for this fix. The unavoidable decision is authorization of the actual T
and rollout window; there is no remaining need to invent/approve London history.

## Verification scope

Tests run on fresh isolated localhost PostgreSQL, schema-only without migration
execution, synthetic users/loans and blocked external delivery. They cover original
Cairo summer/winter/midnight, delivery days, API/preview/Admin, valid and invalid
London settings, student-local boundaries and missing zones, unchanged history,
and SELECT-only readiness for 17 synthetic missing/valid/mixed requests. Production
queue readiness is intentionally not claimed without the operator's actual result.

Local results: targeted compatibility/checklist suite 67 passed; complete library
suite 194 tests, 193 passed and one migration round-trip test deliberately skipped.
All PostgreSQL concurrency tests ran. No migration was executed and both temporary
test servers stopped. Previous missing-boundary failure assertions were updated
explicitly for the approved restored Cairo behavior; malformed-boundary failures,
real configured London boundaries and historical-date protections remain tested.
