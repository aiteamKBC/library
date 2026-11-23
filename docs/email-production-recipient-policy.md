# Production email recipient and timezone policy

This change adds two explicit configuration choices. It does not enable email,
change n8n ownership, install services, or update any user profile or loan date.
The default behavior remains an exact recipient allowlist and a required saved
recipient timezone.

## Recipient modes

`LIBRARY_EMAIL_RECIPIENT_MODE=allowlist` is the default. The existing
`LIBRARY_EMAIL_RECIPIENT_ALLOWLIST` must contain valid exact mailboxes before
live delivery can start. Empty or malformed allowlists deny sending.

`LIBRARY_EMAIL_RECIPIENT_MODE=source_scoped` is an explicit production choice.
It permits a message only when its current database source authorizes that
particular recipient. Being a registered user alone is insufficient.

| Recipient | Required source relationship |
| --- | --- |
| Student | Active account matching the Loan borrower or BookRequest requester. The recipient address must match both the current source email and the current account email. |
| Administration | Active staff/admin/librarian account in `LIBRARY_EMAIL_ADMIN_USER_IDS`, matching its current email. Only `loan_submitted` and `book_request_submitted` have administration recipients. |

The event, source type and ID, foreign key, recipient ID/key/role, template key,
and event/reminder kind must agree. A missing/deleted source, mismatched address,
unknown mode, unsupported role, or missing message context denies delivery.
Student delivery requires a linked source owner. Administration notifications
can still reference a legitimate source whose borrower/requester is absent or
inactive, provided the administration recipient meets its own requirements.

The source API currently accepts a submitted borrower/requester email alongside
the linked account. Matching only that submitted address would allow a caller to
target an unrelated mailbox, so the account-email match is also mandatory in
`source_scoped`. A stale or differing source email is blocked for review, never
silently rewritten or redirected. The default allowlist behavior is unchanged.

The stored n8n-compatible `loan_submitted.admin` template version also retains
its designated administration recipient check. Changing the current template
compatibility flag does not change the audience of an already queued template.

Source validation runs in the worker and again at the provider boundary. No
transaction or row lock is held across the external provider request. Recipient
mode does not replace event ownership, credential approval, enqueue/worker/send
flags, n8n handoff, provider selection, or any retry/uncertain-result safeguards.

## Optional missing-timezone fallback

`LIBRARY_EMAIL_FALLBACK_TIMEZONE` defaults to an empty string. With that default,
accounts lacking a valid saved timezone retain the existing blocked behavior.

An operator may explicitly choose a valid IANA timezone, for example
`LIBRARY_EMAIL_FALLBACK_TIMEZONE=Europe/London`, after deciding the intended
calendar for recipients who have not saved their own timezone.

Resolution is shared by event creation, reminder scheduling, and worker delivery:

1. A valid saved profile timezone takes precedence.
2. An absent profile or an exactly empty/null saved timezone may use the configured
   fallback for a linked recipient account.
3. A nonempty invalid saved timezone stays blocked. An invalid/empty fallback
   does not supply a timezone. A missing recipient account remains blocked.

The fallback is used only for email rendering and reminder eligibility. It does
not write `UserProfile`, invent a browser observation, change loan confirmation
policy, recalculate due dates, or alter historical records. A later valid saved
preference takes precedence at scheduling and delivery time.

Reminder keys, recipient-local 09:00-to-midnight windows, overdue cadence and
expiry checks remain unchanged. The fallback does not make twice-daily scheduler
invocations equivalent to sending at 09:00 in every recipient timezone.

Existing blocked/shadow messages are not automatically replayed by these settings.
Accepted and uncertain messages remain protected against automatic resubmission.
The `email_queue_status` field `active_loans_without_timezone` still measures
missing profile data; it can remain nonzero when an email fallback is configured.

## Deployment boundary

Deploy the code while the existing email activation flags remain off. Choose
the recipient mode and missing-timezone policy before enabling live ownership.
Apply the same application settings to web producers, the scheduler and the
worker; the worker's dedicated direct database configuration stays separate.

Before handoff, reconcile any reminders already sent by n8n on the cutover day,
then stop the overlapping n8n email routes without disabling unrelated overdue
state processing. Do not set `LIBRARY_EMAIL_N8N_HANDOFF_CONFIRMED` until this is
actually complete. The outbox cannot deduplicate an external n8n send it never
recorded.

For the existing server setup, the socket, worker and two timers are already
defined. Live activation must remove the temporary smoke-test `Restart=no`
override, reload systemd, enable the socket and timers, and restart web producers
after their environment changes. The oneshot worker does not need independent
boot enablement. Keep the configured bounded worker and recovery path.

The production activation check is one authorized real source event through
outbox commit, socket wake, provider acceptance and receipt. Isolated unit tests
do not establish that a live email was delivered.

## Focused isolated validation

With the project's Python environment, from the repository root:

```sh
backend/.venv/bin/python -B backend/run_isolated_tests.py --schema-only \
  library.test_email_recipient_policy library.test_email_timezone_fallback
```

The existing harness excludes application configuration and production databases,
blocks external networking and email, and creates synthetic in-memory model
tables. These policy changes do not modify PostgreSQL locking or systemd code.
