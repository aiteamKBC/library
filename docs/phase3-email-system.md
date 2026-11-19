# Phase 3: local Django email implementation

## AI Team authorization verified (local test profile only)

The owner completed Google consent and the TEST SENDER ONLY confirmation for
`aiteam.kbc@gmail.com`. Host, Origin and one-use confirmation state all matched;
the session was valid. Existing GmailClient refresh verification succeeded before
encrypted persistence, then a NEW `--verify --profile ai-team-test` process loaded
the saved DPAPI grant, refreshed it again and verified the same Google identity.

The separate AI Team vault is saved outside Git. Its usage remains test_only;
production_sender_approved and n8n_identity_confirmed are both false. The grant
does not replace the original library profile or assert a historical n8n sender.
No message was sent. Gmail/Graph sending, credential approval, enqueue, worker
and scheduler were not activated. No Neon/n8n change or deployment occurred.

## Separate AI Team test grant and local timeout

The explicit `--profile ai-team-test` connects a new Google test account using the
same existing OAuth client and callback. It does not inherit the library account,
Sender or Reply-To, or require an n8n identity assertion. Its owner confirms the
verified Google identity as TEST SENDER ONLY. The encrypted record is separate:
`%LOCALAPPDATA%\KBC-Library\oauth\gmail-ai-team-test.dpapi`. Existing `gmail.dpapi`
is untouched, and neither file can be overwritten by the bootstrap.

Test grants record `credential_usage=test_only`, `n8n_identity_confirmed=false`
and `production_sender_approved=false`. The normal application vault loader
rejects these records; authorizing a test account cannot replace the application
sender. Worker, scheduler, event routing, allowlist and live flags stay unchanged.

```powershell
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --authorize --profile ai-team-test --timeout-minutes 30
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --verify --profile ai-team-test
```

The expired ten-minute attempt returned `google_sign_in_or_consent_required`;
Google subsequently redirected to a receiver that had already shut down. The
old authorization code is not reused. The timeout is now configurable from 1 to
60 minutes (default remains 10), with a fresh 30-minute AI Team session. Callback
and confirmation validation share the same bounded deadline and retain one-use
state, S256 PKCE and exact origin/redirect checks. This changes only the local
bootstrap lifetime, not Google token expiry, borrowing dates or reminders.

173 tests passed for test-profile separation, followed by 67 focused OAuth/Gmail
tests including two additional lifetime regressions. Google Sign-In/consent and
the local test-account confirmation must finish before real encrypted persistence;
refresh is verified without sending a message. No production activation occurred.

## Confirmation form fix

The failed live attempt ended with `discovered_google_account_confirmation_required`
before refresh verification or DPAPI. The old diagnostic grouped several checks.
The confirmation HTML response used Referrer-Policy `no-referrer`, which makes
Chromium native form POSTs send Origin `null`; the strict Origin check rejected it.
This exact browser behavior and rejection were reproduced with a fresh isolated
Chrome profile and synthetic loopback form. No real account/cookies were involved.

Only the confirmation HTML now uses Referrer-Policy `origin`. The callback path
and authorization code stay out of Referer; the Origin remains verifiable.
Origin `null`, foreign Host/Origin, bad nonce, expired session and missing identity
checkbox remain rejected. Sender confirmation remains optional, and leaving it
unchecked saves an empty Sender without assuming that a Google login is the old
n8n From. Terminal diagnostics now separate validation, token refresh and DPAPI
storage with fixed codes/boolean checks; no raw headers, codes or tokens are logged.

165 tests passed on isolated PostgreSQL, including a real offline Chrome native
form regression: old no-referrer rejection, successful current-user DPAPI save with
only the identity checkbox, and rejection without that checkbox. Existing email,
timezone/scheduler, Graph, Gmail and allowlist tests remain green. A new live OAuth
session is required after the failed attempt; no old authorization code is reused.

## Existing dotenv client connection update

The current local .env DOES contain the supplied Google client pair, under literal
labels `Client ID` and `Client secret`. The original assignment parser skipped
these space-separated labels and the bootstrap accepted only downloaded JSON.
`gmail_oauth_config.py` now reads ONLY recognized Google fields, accepts these
existing aliases plus LIBRARY_GMAIL_*/GOOGLE_*/GOOGLE_OAUTH_* equivalents, validates
the Google client-ID shape and rejects conflicting values. No .env or credential
value was changed. No Microsoft/n8n/database credential is reused as a Google key.
Settings normalize the same aliases; vault conflicts also consider those values.

`connect_gmail_oauth.py --check` now loads Google-only fields from backend/.env,
reports source NAMES/presence only, and does not initialize Django's app/DB.
Actual local checks confirmed BOTH normalized Django values match the existing
file; Gmail send, enqueue, worker and scheduler flags all remained false. This
proves local loading, not Google acceptance of the secret or redirect registration.

```powershell
# Uses the existing client pair; no JSON download or new client required.
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --authorize --discover-account
```

`--discover-account` is explicit when the prior Google account email is unknown.
It omits a guessed login hint. After Google consent, HTTPS UserInfo must provide
a verified email and stable sub. A local same-origin, nonce-protected confirmation
form then requires the owner to confirm this is Charly Account before saving.
The optional, default-unchecked Sender box is ONLY for confirming that this exact
address matches n8n's previous From. Leaving it unchecked does not invent a Sender
or replace an alias. No grant is saved before account confirmation; refresh is
verified through the existing GmailClient before encrypted persistence.

The only manual browser fallback is `http://127.0.0.1:8765/oauth2/start`; Google
authorization codes, secrets and tokens are never printed as links. `--no-browser`
supports explicit manual opening. A callback that actually succeeds at Google
establishes registration of the exact redirect; a local configuration check cannot
establish that fact. Known Google errors are reduced to a fixed safe code list.

159 isolated PostgreSQL tests passed after these changes (147 previous + 12 config
and account-confirmation tests). The live authorization command was started using
the existing local credentials; its completion depends on the owner's actual
Google consent and account confirmation. No email or live worker is used.

## Direct local Google authorization bootstrap (current recommended connection)

`backend/connect_gmail_oauth.py` now prepares the one-time connection directly,
without Django app startup, unrelated environment loading, any database connection, worker,
scheduler or sending. The earlier Playground procedure below is an alternative;
use this local flow for state/PKCE, Google identity verification and encrypted
storage. OAuth Client/secret availability is still required; a workflow's
credential display name and internal credential ID are not a reusable OAuth app.

Local inspection found no Google/Gmail/OAuth entries in the available project
environment or current process, no matching downloaded OAuth client JSON in the
inspected locations, and only `id`/`name` in the two Charly Account workflow
credential references. This does not establish that no client exists in Google
Cloud. No n8n credential store, token or secret was extracted.

### Human Google access boundary (nothing here was executed in Cloud)

1. The owner of the Google account actually used by Charly Account opens
   [Google Cloud credentials](https://console.cloud.google.com/apis/credentials).
   Select the existing company project and inspect Google Auth Platform > Clients
   for a company-controlled reusable WEB client. No known owner/client is assumed.
2. If none is accessible/suitable, use an authorized company project (create one
   only if permitted), enable Gmail API, and configure Google Auth Platform's
   Branding, Audience and Data Access. Internal audience applies only to eligible
   organization accounts; for an external test app add the actual account as a
   test user. Testing grants expire in 7 days for Gmail scopes; sustained use needs
   the appropriate approved consent/publishing status. Organization policy may
   require a Google Workspace administrator's approval.
3. Reuse a suitable web client or create **KBC Library Django** of type **Web
   application**. Register EXACTLY this Authorized redirect URI:
   `http://127.0.0.1:8765/oauth2/callback`. Do not remove n8n's existing redirect or
   revoke its grant. This creates an application identity, not a different Gmail
   sender account. Download its client JSON to a private location OUTSIDE Git.
4. Independently confirm the n8n authenticated Google account and actual prior
   message From/Reply-To (including any send-as alias). Do not substitute
   `library@kbc.ac.uk`, a recipient/contact email, or the current browser account.

The account owner can attempt these steps with their own Google login; if Cloud
denies project/client creation, only the organization's authorized administrator
can grant access or create/download the client. Local code cannot bypass this.
[Google web authorization and redirect rules](https://developers.google.com/identity/protocols/oauth2/web-server),
[Google identity scopes](https://developers.google.com/identity/openid-connect/openid-connect).

### Local commands after the client is available

From `backend`, using its existing Python environment (no extra packages):

```powershell
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --check
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --check --client-file "C:\private\google-client.json"
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --authorize --client-file "C:\private\google-client.json" --expected-account "ACTUAL_N8N_GOOGLE_ACCOUNT" --sender "CONFIRMED_N8N_FROM"
.\venv\Scripts\python.exe -B connect_gmail_oauth.py --verify
```

Replace non-secret placeholders with the independently confirmed identities. No
secret/token is accepted as a command-line argument. Optional `--reply-to` retains
an approved different address; empty follows the existing sender fallback policy.
Omitting `--sender` permits storing the grant but leaves sending unconfigured;
the verified Google login is not assumed to be the old n8n From/send-as identity.

Authorization opens the system browser, binds ONLY 127.0.0.1:8765, requests
`gmail.send` + `openid email` (basic identity, no mailbox reading), Offline access
and explicit consent/account selection. It validates an expiring one-use state,
exact Host/path/registered redirect and S256 PKCE. The callback/code never appears
in HTTP logs or terminal output. UserInfo is read over Google's HTTPS endpoint and
requires a verified email matching the independently confirmed account. Unused
ID tokens are not trusted/decoded as proof of identity.

Before saving, the EXISTING GmailClient refreshes the NEW grant and Google
UserInfo must match the same email AND stable Google sub. This proves refresh and
identity, not mail delivery or send-as/Gmail API activation; no message is sent.
The loopback listener shuts down after completion/failure or a ten-minute timeout.
It is not a recurring service or deployed API endpoint.

Credentials/refresh token are saved only on success under
`%LOCALAPPDATA%\KBC-Library\oauth\gmail.dpapi`, encrypted with current-user Windows
DPAPI (not machine-wide). Access/ID tokens are not persisted, no plaintext fallback
exists, Git locations and overwriting an existing grant are rejected. The vault
is specific to that Windows user/machine; it is not a production deployment secret
store or a portable backup. Protect the source client JSON; do not commit/share
it or copy it into the project.

For a FUTURE authorized local application startup, point
`LIBRARY_GMAIL_CREDENTIALS_FILE` at that vault using process configuration; no .env
edit is needed. Settings read credential/identity values only and reject conflicts
with separately supplied Gmail values. No provider, live/approval flag, owned
event, allowlist, scheduler or recipient is changed. The real running Django
process was not reconfigured. Production needs its approved secret manager and a
separate deployment decision.

147 tests passed on fresh isolated PostgreSQL with fake Google traffic and
synthetic DPAPI vaults, including all 133 previous email tests and 14 new bootstrap
tests. No migrations, Neon/n8n changes, real authorization exchange, mail or deploy.
The actual local --check reported no client and no saved grant; Cloud/client
access and the account owner's consent are the remaining external prerequisites.

## Gmail transport completion (current provider configuration)

`LIBRARY_EMAIL_PROVIDER=gmail` is now the CODE DEFAULT. It does not enable any
delivery gate. GraphClient remains available with explicit `graph` selection and
its original credentials/gates. There is no provider failover. The original
Graph-specific implementation notes further below are historical, not instructions
to fill Microsoft settings to activate the Gmail provider.

`gmail_client.py` sends MIME HTML encoded as base64url through Gmail API and uses
the Google OAuth2 refresh-token grant. `email_transport.py` holds shared results,
bounded HTTP/timeout/no-redirect helpers; Graph exports retain their old public
result/helper names. `email_providers.py` selects exactly one client. Worker and
n8n handoff checks now use the selected provider's independent activation gates.
No models, schema, migrations, loan calculations, events or reminder cadence change.

Tokens are memory-only in the client, refreshed under a per-client thread lock
before expiry. The approved refresh token is supplied by secure runtime
configuration, never copied from n8n or persisted in outbox/attempts/logs. Its
revocation/expiry returns `gmail_reauthorization_required`; repeat authorization
is then necessary, rather than falsely promising that consent can never expire.
Scope information, if returned by the token endpoint, must authorize sending.

The explicit Google ACCOUNT email targets `/users/{account}/messages/send` instead
of `me`, so the wrong account's grant is rejected by Gmail. From is a separate
verified sender setting; Gmail send-as aliases must be approved/verified beforehand.
No code default invents either address. Empty Reply-To uses that confirmed Sender;
an explicit approved override wins. Optional sender display name defaults empty.
Do not infer any identity from DEFAULT_FROM_EMAIL or institutional contact links.

Allowlist validation precedes both OAuth and sending, including cached-token sends.
No recipient is redirected or substituted. Gmail 200 needs a valid returned
message ID; accepted means API acceptance, not guaranteed inbox delivery. The
existing provider_request_id stores `gmail:<message-id>` for correlation. Stable
MIME Message-ID aids investigation, not Gmail-side deduplication guarantees.

401 invalidates the cached token for the next RECORDED worker attempt, without a
hidden send retry. Quota/rate rejection and structured matching Gmail 5xx errors
use the worker's existing bounded backoff and Retry-After. Submission timeout,
408/504, ambiguous gateway failure and malformed success remain UNCERTAIN with no
automatic resubmission. Token refresh failure occurs before message submission
and can be safely retried. Raw provider errors/credentials are not logged/stored.
This deliberately handles gateway timeouts more cautiously than general retry
guidance. [Gmail errors](https://developers.google.com/workspace/gmail/api/guides/handle-errors).

The worker saves `_email_provider` in the existing payload before the first
attempt; it blocks a retry under a different provider. Attempts predating this
metadata belong to the historical Graph implementation. Never change provider
or sender/grant identities while work is in flight: stop workers and review the
queue first. Accepted/uncertain rows remain ineligible for automatic retry.

### Settings required later (no .env was changed)

| Setting | Required meaning |
| --- | --- |
| LIBRARY_EMAIL_PROVIDER | gmail (default); graph only by explicit selection |
| LIBRARY_GMAIL_CLIENT_ID | company-approved existing Google OAuth web client |
| LIBRARY_GMAIL_CLIENT_SECRET | its securely supplied secret; never source/chat |
| LIBRARY_GMAIL_REFRESH_TOKEN | NEW grant for Django, same verified Google account |
| LIBRARY_GMAIL_ACCOUNT_EMAIL | actual Google account authenticated by Charly Account |
| LIBRARY_GMAIL_SENDER | confirmed prior From; verified send-as alias if different |
| LIBRARY_GMAIL_SENDER_NAME | optional confirmed display name |
| LIBRARY_GMAIL_REPLY_TO | prior approved Reply-To, or empty to use confirmed Sender |
| LIBRARY_EMAIL_RECIPIENT_ALLOWLIST | exact authorized test inbox only initially |
| LIBRARY_GMAIL_SEND_ENABLED | false by default, explicit future activation only |
| LIBRARY_GMAIL_CREDENTIALS_APPROVED | false by default; approval of grant/account/sender/scopes |

The existing enqueue/worker/scheduler/n8n-handoff/owned-events gates are retained.
For original n8n templates and the fixed corporate borrow-request admin recipient,
enable the existing compatibility mode only during the separately approved setup;
validate its ONE matching active admin account and saved timezone before enqueue.
No existing queued template or target is rewritten by this integration.

### One-time authorization by the responsible Google account owner

1. Confirm Charly Account's actual login and a genuine message's From/Reply-To.
   Identify the company-controlled EXISTING Google Cloud project/OAuth web client,
   Gmail API and consent configuration. Reuse a suitable existing client. A managed
   n8n-owned OAuth app is not automatically reusable; only if no suitable client
   is available does the administrator need another approved Google client.
2. Use [Google OAuth Playground](https://developers.google.com/oauthplayground/)
   with **Use your own OAuth credentials**, Google endpoints, Offline access and
   Consent Screen. Its approved redirect must be
   `https://developers.google.com/oauthplayground`. Enter credentials privately.
3. Request ONLY `https://www.googleapis.com/auth/gmail.send`, sign into the EXACT
   confirmed account, approve and exchange the authorization code. Securely supply
   the NEW refresh token with that same client ID/secret to Django's secret
   configuration. Do not copy n8n tokens or revoke its existing consent. Do not
   run Playground's Step 3 send request or share token-bearing screenshots/links.

Google's shared Playground credentials have a 24-hour revocation policy; own
approved client credentials avoid that Playground-specific expiry. External apps
in Testing normally issue 7-day refresh tokens for Gmail scopes; use the correct
approved internal/production consent configuration for sustained operation.
Other revocation/expiry conditions still apply.
[Google OAuth lifecycle](https://developers.google.com/identity/protocols/oauth2#expiration).
No OAuth exchange or Cloud/consent change was performed during implementation.

Local verification: 133 tests passed on a fresh isolated PostgreSQL cluster,
including 25 new Gmail/provider tests and the existing worker, scheduler, Graph,
allowlist and n8n-template regression suites. Fake HTTP transports only; the
runner blocked external connections/mail, skipped migrations and stopped the
temporary PostgreSQL server afterward. No Neon, n8n, real .env, live mail or
deployment was involved.

### First real test (future authorization only; not executed)

Use a dedicated local test database with a synthetic loan/user and their real,
explicitly authorized TEST inbox and verified timezone. Set allowlist to ONLY that
inbox, keep Scheduler OFF, own ONLY `manual_email`, acknowledge ownership of that
isolated test event, configure approved Gmail identities/grant and enable ONLY
the necessary enqueue/worker/Gmail/credential gates. Never change production n8n
routing for this test. Queue one manual email with a fresh requestId; review its
recipient/body and run one bounded worker batch. The allowlist is the safeguard,
not `--limit 1`. Check attempt, Gmail message ID, Sent Mail and actual receipt,
From/Reply-To. Stop afterward. Unknown acceptance stays uncertain. The automated
isolated runner blocks networking and is not the real-email test environment.

## Staged n8n template and recipient parity

The subsequent user decision keeps the approved recipient-local Due Today 09:00
and overdue days 1, 3, 5, 7, ... policy. It does NOT restore n8n's due-soon window,
once-only overdue cadence, or a separate immediate overdue email. Operational
`process_overdue` remains unchanged. Bulk announcements remain excluded.

`LIBRARY_EMAIL_N8N_COMPAT_ENABLED` defaults FALSE; no `.env` was edited. When it is
later explicitly enabled, NEW outbox rows for seven shared template keys use
version 2 from `library/n8n_email_reference.json` and
`library/templates/library/emails/n8n/`. Existing version-1 rows retain their
original rendering. Changing this flag never enables worker, enqueue, ownership,
Graph sending or any connection; those independent gates remain in force.

| Django key | n8n source node | Recipient |
| --- | --- | --- |
| loan_submitted.student | loan_submitted | original loan borrower email |
| loan_submitted.admin | library_borrow_request | Youmna@kentbusinesscollege.com |
| borrow_confirmed.student | borrow_confirmed | original loan borrower email |
| loan_returned.student | loan_returned | original loan borrower email |
| notify_available.student | notify_available | original loan borrower email |
| due_today.student | Send Due Date Reminder | original loan borrower email |
| overdue.student | Send Overdue | original loan borrower email |

HTML/copy, institutional contact links and subject wording come from the supplied
exports. Static Django variables replace the n8n expressions; HTML stays escaped.
Expression markers and surrounding subject whitespace are removed. The reminder
sentence changes only from "due soon" to "due today" to match the approved policy.
The old webhook overdue template is not a second sender of the scheduled event.
Other approved Phase-3 events have no equivalent connected template in the exports
and retain their version-1 templates; no missing n8n route is assumed to exist.

In parity mode the borrow-request admin configuration must resolve to EXACTLY ONE
active authorized staff account matching the exported corporate recipient (case
insensitively); otherwise the source transaction fails clearly rather than sending
to different/multiple administrators. Validate this and that account's saved
timezone BEFORE enabling enqueue/parity mode. No user/profile was edited locally
outside synthetic tests. Admin-only borrower contact fields and copy number now
provide the original template data. Student recipients are never redirected to a
test address, and the existing recipient allowlist still applies.

The source subjects for some event nodes contain interpolation syntax without a
leading n8n expression marker. Local exports alone cannot prove how those subjects
appeared in previously sent mail; a genuine sent-message sample is needed for
byte-for-byte runtime parity. The new renderer interpolates the reviewed fields
and rejects CR/LF in subjects; it does not execute arbitrary expressions.

Provider identity is still UNVERIFIED: Charly Account is Gmail API / Google OAuth2,
not Microsoft. Its account email/From/send-as/Reply-To is absent from exports. No
credentials were copied. The subsequently added Gmail transport needs its own
approved grant; the existing Graph transport cannot use the Google credential.
See the provider correction at the
start of `microsoft-graph-mailbox-readiness.md` before any activation decision.

This is code, not activation. No production database, n8n configuration, SMTP,
Graph tenant, server service or `.env` was changed by this phase. No real mail
was sent. Existing schema 0024 is reused; no additional migration is required.
The working branch is `eslam-branch`; existing team edits remain in place.

Phase 4A adds a default-empty Graph recipient allowlist and safe reminder
reactivation after timezone travel. See [the readiness fixes](phase4a-email-readiness.md)
for the additional activation prerequisite and migration-free test mode.

## Files and event boundary

- `backend/library/email_events.py`: transactional producers and recipient
  resolution. Loan.save invokes the producer after saving/synchronizing copies,
  inside its existing atomic transaction. BookRequest.save now wraps persistence
  and its first-create producer in an atomic transaction. No on_commit-only gap.
- `email_models.py`: existing records/constraints retained. On insert the unique
  database index, rather than a racy validation query, arbitrates idempotency.
- `email_policy.py` / `config/settings.py`: independent, default-off gates and
  explicit event ownership. New Graph settings have no Azure/SMTP/Gmail fallback.
- `email_templates.py` / `templates/library/emails/message.html`: versioned
  English subjects/content, autoescaped Django HTML, existing purple/gold brand.
- `graph_client.py`: app-only token cache/renewal, bounded HTTP requests, no POST
  replay/redirect, HTML sendMail, sanitized result vocabulary.
- `email_worker.py`: claims, submission fences, attempts, recovery, retry and
  restricted staff retry. `email_scheduler.py`: current-day reminders only.
- Commands: `process_email_outbox`, `schedule_email_reminders`,
  `email_queue_status`. The first processes a bounded batch then exits; the
  scheduler also runs once. No service, loop, cron or supervisor was installed.
- `views.py`, `serializers.py`: manual queue API, UUID idempotency, subject
  validation; dormant per-event legacy-webhook routing guard for future handoff.
  This guard changes no current routing while flags are off.
- `admin.py`: read-only queue/attempt monitoring, safe retry action with a Django
  admin audit entry. No accepted/uncertain message can be retried by that action.
- Tests/runners: `test_email_system.py`, `run_isolated_tests.py`,
  `run_local_postgres_tests.py`, `config/test_settings.py`. The earlier isolation
  assertion in `test_user_timezones.py` additionally recognizes the fresh local
  PostgreSQL test database; its SQLite assertions are preserved.

| Event | Recipient | Trigger / logical identity |
| --- | --- | --- |
| loan_submitted | student + configured administrators | first pending/reserved borrow request |
| book_request_submitted | student + configured administrators | first BookRequest save |
| notify_registered | student | first pending notify enrollment |
| borrow_confirmed | student | first approval/checkout, not approved-to-borrowed again |
| reservation_confirmed | student | reserved-to-confirmed; replaces borrow_confirmed |
| notify_available | student notify enrollment | return releases availability; one enrollment message |
| book_now_available | waiting borrower | return releases availability; distinct return cycle |
| loan_returned | student | first returned transition; existing signed feedback URL |
| due_date_changed | student | persisted date actually changed after confirmation; revision |
| loan_cancelled | student | first cancelled transition, admin or student |
| manual_email | borrower | staff-only existing send_email action; caller UUID |
| due_today | student | saved due_date, local 09:00 on that day |
| overdue | student | local 09:00, overdue day 1, 3, 5, 7, ... |

Each row has a recipient role/template key; submission events share one event_id
between student/admin, with different subjects and copy. Event UUIDs incorporate
the source id and original request timestamp. Database unique idempotency keys
protect retries/concurrent producers. No bulk announcements or BookRequest
cancellation messages are implemented. NotificationLog remains unchanged.

The existing n8n attachments were inspected for their Gmail template nodes:
loan_submitted, borrow_confirmed, loan_overdue, loan_returned, notify_available,
library_borrow_request, due-date/overdue reminders, and the manual announcement.
The new registry uses the existing HTML brand pattern and feedback route, without
copying n8n expressions, SQL, pinned personal data or embedded credential metadata.
There are 15 version-1 template keys (13 events, two dual-recipient submissions).
Manual content is plain text escaped into HTML, not executable HTML. Internal
notes, private return notes, evidence files and credentials are not in payloads.

## Recipient timezone and dates

The user FK's current saved UserProfile.time_zone is authoritative. The outbox
records a snapshot; the worker refreshes it immediately before preparing a
submission. Event instants remain offset-bearing ISO strings and are formatted
with ZoneInfo using the offset/DST valid on the EVENT date. Student and admin can
therefore see different wall times for exactly the same instant. DateField
values use date.fromisoformat and calendar formatting, never timestamp conversion.

Missing/invalid zones block immediate events (`recipient_timezone_missing`).
Guest/email-only recipients have no guessed zone and are held. No email/IP/server
fallback exists. Missing-zone reminders are not assigned an invented local day;
the scheduler reports a count and a sanitized loan-id warning. Monitoring also
counts active loans without a saved zone. A future explicit timezone registration
or a separately approved fallback policy is required for those recipients.

Admin recipients must be explicitly configured by active account IDs with email
addresses and staff/library roles, each with their own profile zone. Missing zones
hold individual admin messages. Missing/invalid admin ID/address configuration
fails the source transaction clearly before commit: validate it BEFORE enabling
enqueue. The required existing schema cannot represent an unknown email address;
the system never invents one. Admin recipients are not inferred from the old
Gmail account or from ALL staff accounts.

No loan formula, immutable confirmation, cutover or historical date is changed.
Existing guards on LIBRARY_LONDON_CUTOVER_AT and the separately approved
LIBRARY_USER_LOCAL_POLICY_ENABLED / LIBRARY_USER_LOCAL_CUTOVER_AT remain in place.
No cutover date has been chosen. A missing required cutover/confirmation/profile
still blocks first confirmation as in Phase 2 rather than silently adopting a new
calculation policy. Operational overdue-state processing is unchanged.

## Scheduler

Run once per minute LATER under a separately approved process supervisor. For
each active borrowed OR overdue loan, derive TODAY in the recipient's saved IANA
zone, and construct that calendar day's 09:00 in that zone -> UTC. Never add 24h
to yesterday's UTC time. The helper validates wall-time round trips, chooses the
first occurrence if ambiguous, and skips a nonexistent local 09:00.

The scheduler queues only after today's 09:00 and before next local midnight.
After downtime it can send today's still-current slot; it NEVER enumerates missed
days. If the service is unavailable at 09:00, exact punctual delivery is not
guaranteed. The batch limit caps new messages, not scans, preventing starvation
behind older loans. Calendar due dates remain unchanged.

Keys include source incarnation, recipient, role, due date, deadline revision,
event and local day/overdue offset. They exclude timezone and execution time.
Accepted reminder history prevents regression to a previously sent earlier day
after travel. A zone change before sending refreshes eligibility; if the same
day's new 09:00 is still ahead, available_at is rescheduled. A day that is no
longer current is cancelled; the scheduler can create the current day's slot.
Changing due_date/returning/cancelling invalidates unsent snapshots transactionally.
The worker also checks status, returned_at, date, revision, zone and local window
at the durable submission boundary. No EmailJobState table/catch-up cursor needed.

## Worker, attempts and delivery limits

1. Short transaction claims pending/retry_wait using PostgreSQL SKIP LOCKED,
   a UUID lease token, owner and expiry. SQLite is permitted ONLY in isolation.
2. Lock order for subsequent work is Loan then Outbox, matching the producers.
   Revalidate ownership/recipient/source/reminder. Render escaped HTML.
3. Persist an incremented numbered EmailAttempt and submitting status BEFORE HTTP,
   commit, then call Graph outside database locks. Lease length defaults to 180s;
   token and send requests each have a 25s timeout. No hidden sendMail retry.
4. Finalize only if the same lease token still owns submitting. Accepted means
   Graph 202, not inbox delivery. No delivery/read receipt tracking is implied.
5. 429/5xx retry with exponential backoff+jitter, respecting Retry-After;
   default maximum five attempts. Authentication failure before send is safe to
   classify separately. Rejected 401 invalidates cached token for a later attempt.
6. Submission timeout/lost response/unexpected success code -> uncertain. Expired
   claimed lease can be reclaimed; expired submitting lease -> uncertain, including
   its started attempt. Accepted/uncertain are never automatically resubmitted.
7. Staff may retry blocked/definitively failed messages only after current-source,
   timezone, ownership and retry-budget checks. Shadow/n8n-owned rows cannot be
   replayed by the action. No network call runs inside an admin/API retry request.

Notify entries move to their existing notify/history state only after a known
Graph acceptance. Changes after an external submission has started cannot recall
an email already accepted by Microsoft. There is deliberately no claim of exactly
once inbox delivery: client-request-id is tracing, not provider deduplication.
If Graph accepts then the process dies before durable acknowledgement, the row
requires uncertain review against provider/sent-mail evidence; never blindly retry.

`email_queue_status` reports state counts, oldest due age and missing-zone active
loans without addresses/payloads. Django Admin shows queue and immutable attempts.
External alert thresholds, log retention/redaction/access controls, lease tuning,
supervision/restart and capacity checks remain server-operations work, not services
installed by this local task. Queue retention needs separately approved policy.

## Default-off activation settings (names only, no values)

- LIBRARY_EMAIL_ENQUEUE_ENABLED
- LIBRARY_EMAIL_WORKER_ENABLED
- LIBRARY_EMAIL_SCHEDULER_ENABLED
- LIBRARY_GRAPH_SEND_ENABLED
- LIBRARY_GRAPH_CREDENTIALS_APPROVED
- LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED
- LIBRARY_EMAIL_OWNED_EVENTS (explicit allowlist; empty by default)
- LIBRARY_EMAIL_ADMIN_USER_IDS (explicit active staff account IDs)
- LIBRARY_GRAPH_TENANT_ID / CLIENT_ID / CLIENT_SECRET / SENDER / REPLY_TO

All booleans default false. New credential keys do not fall back to previously
exposed Azure credentials, SMTP DEFAULT_FROM_EMAIL or old Gmail OAuth. With enqueue
alone, rows are blocked shadows, not a backlog to replay on activation. A real
worker refuses to start without all live gates/configuration; GraphClient checks
them again per send. Injected transports/clients require isolated-test settings.

The existing staff manual-email API is preserved when enqueue is disabled. When
enqueue is enabled it queues instead of synchronous SMTP and requires a stable
requestId UUID, subject and message; a replay with changed content is rejected.
It returns HTTP 202 plus messageId/status, not a delivery claim. Callers must keep
the same requestId across transport retries and use a fresh one for a new message.
No existing frontend manual-email sender was found that needed conversion.

## Safe handoff checklist — future approval required; nothing activated here

1. Review code/test results and approve templates, administrator account IDs,
   recipient timezone onboarding (including guests/admins), sender and Reply-To.
   Confirm public FRONTEND_BASE_URL/feedback links. Do not use old Gmail sender by
   assumption. Entra credentials must be newly rotated/approved and securely set
   outside this task. Verify application Mail.Send consent and mailbox scoping
   with Microsoft 365; IDs alone prove neither permission nor mailbox ownership.
2. Inventory existing n8n event and Daily 8am mail ownership. Plan an operator-led
   handoff with no overlapping senders. In particular, loan_submitted and
   notify_registered are one handoff group because n8n shares their current route.
   Do not disable the Daily 7am overdue STATE processing. Do not add bulk mail.
3. Review blocked shadow rows without replaying history. Reconcile any legacy
   NotificationLog/n8n sends for the activation local day; the new outbox cannot
   infer sends made externally. Choose an approved handoff window AFTER the old
   reminder slot or otherwise explicitly reconcile that day. No date is chosen
   by this implementation. Verify old overdue/due-soon senders are excluded for
   the newly owned events before acknowledging handoff.
4. Only then configure ownership/handoff and independent activation flags under
   a separately authorized deployment. The dormant Django webhook guard suppresses
   ONLY live, explicitly owned event routes. It cannot suppress n8n's independent
   SQL scheduler: the acknowledgement is an operational prerequisite, not proof
   that any external workflow has been stopped by code.
5. Separately arrange bounded worker invocations/restart and frequent scheduler
   execution, health/uncertain/backlog monitoring and a controlled first-mail check.
   None of these processes or Microsoft/n8n changes were performed here.

## Isolated verification

From the repository root, using installed binaries only:

```text
backend/venv/Scripts/python.exe -B backend/run_isolated_tests.py library
backend/venv/Scripts/python.exe -B backend/run_isolated_tests.py --makemigrations --check --dry-run
backend/venv/Scripts/python.exe -B backend/run_local_postgres_tests.py --pg-bin <local-PostgreSQL-bin>
```

The runner clears inherited application configuration, never reads .env, blocks
socket networking/webhooks/SMTP, and uses fake Graph transports. SQLite is in
memory. PostgreSQL mode creates a NEW empty temporary cluster bound to 127.0.0.1
on a random unprivileged port, with a synthetic role and database names. Psycopg
is guarded to allow only those local test database identities. Existing migration
files run only there. The exact temporary cluster is stopped in finally; no
production backup/data is loaded. Temporary cluster/logs are synthetic and may be
removed later under normal workspace cleanup, not confused with real backups.

Coverage includes all events, dual recipients/shared IDs, escaping/private fields,
transaction rollback, duplicate keys/races, Cairo/London/New York/Dubai winter/
summer/mismatched DST transitions, 09:00 boundaries, timezone changes, revisions,
return/cancel, API/Admin/manual permissions, 429/5xx retry limits, accepted and
uncertain states, expired leases, stale workers, parallel workers, SKIP LOCKED and
parallel schedulers. PostgreSQL tests run on actual PostgreSQL, not SQLite mocks.
No real Graph/Microsoft permissions, mailbox or delivery acceptance is verified.

Local verification on 18 November 2026:

- PostgreSQL 17.12, brand-new synthetic local cluster: **134 passed, 0 skipped**,
  including real concurrent workers, schedulers, idempotency and deadline revision.
- In-memory SQLite: **129 passed, 5 skipped** (the five PostgreSQL-only cases).
- Frontend existing timezone suite: **11 passed, 0 skipped**.
- TypeScript `--noEmit --incremental false`: passed.
- Isolated `makemigrations --check --dry-run`: no changes detected.
- Test PostgreSQL instances stopped after verification. No shared database used.

## Primary references

- [Entra client credentials and .default](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-client-creds-grant-flow)
- [Graph sendMail and 202 semantics](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
- [Graph Retry-After guidance](https://learn.microsoft.com/en-us/graph/throttling)
