# Microsoft Graph mailbox preparation — no live activation

## Current n8n parity finding (takes precedence over a provider assumption)

The inspected exports establish **Gmail API / Google OAuth2**, not a Microsoft
credential: `n8n-nodes-base.gmail` with `gmailOAuth2`, display name `Charly Account`.
No Sender address or Reply-To is exported. `library@kbc.ac.uk` remains an unverified
identity expectation, not an instruction to change mailbox/provider. The explicit
`Youmna@kentbusinesscollege.com` address is the borrow-request ADMIN RECIPIENT and
the student templates' contact link; neither establishes the From or Reply-To.

Graph cannot consume that Google connection. Do not create a new Microsoft app or
switch providers merely to fill the current Graph settings. First inspect the
existing connection's account identity and its managed/custom Google OAuth setup,
without exporting tokens, and verify From/send-as and Reply-To against a previous
genuine sent message. An existing appropriate OAuth app may be reusable subject to
its authorized redirect URI, scopes, ownership and a separate secure authorization
for Django. Gmail transport is now implemented separately in `gmail_client.py`,
and selected by default without enabling sending. Its independently authorized
refresh token still needs secure configuration. The Graph client cannot consume
that grant. Reusing the same SMTP address through Microsoft would need
separate evidence of its mailbox/authorization there; a domain proves neither.

No provider or identity was activated. The Microsoft-specific checklist below is
conditional on a separately verified Microsoft mailbox decision, not a requirement
to replace the existing n8n sender.

## Sender evidence

The supplied event workflow export uses Gmail OAuth2 credential display name
`Charly Account` (attachment d816c66a..., Pasted text.txt:171). The reminder export
uses the same credential (698180f0..., line 44), with senderName `KBC Library`.
Neither export provides an explicit sender address or Reply-To. The announcement
export uses another credential, `gmail approve`; announcements remain excluded.
No tokens, credential values or pinned recipient data were exported or displayed.

`backend/config/settings.py` has SMTP DEFAULT_FROM_EMAIL fallback
`KBC Library <library@kbc.ac.uk>`. This supports the expected institutional address
but does NOT prove the actual n8n From identity, Google send-as alias, or existence
of that mailbox in Microsoft 365. Graph sender remains explicitly unconfigured.

Required identity proof: inspect the From and Reply-To of an existing genuine
library email, or the authenticated account address shown in n8n's connection UI,
without exporting credentials. Confirm any alias against the actual From header.
No workflow, credential or live service was accessed/changed in this task.

## Existing configuration evidence

Only local environment KEY NAMES were inspected. MICROSOFT_TENANT_ID,
MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET and old Graph-related keys are defined.
Their values were not displayed/copied and their validity/approval was not assumed.
The new sender intentionally consumes LIBRARY_GRAPH_* instead. Those keys were
not found in the inspected local .env; runtime overrides elsewhere remain unverified.
Legacy credentials are not imported automatically, particularly previously exposed
secrets. No local source establishes Application Mail.Send, Admin Consent or scope.

The existing GraphClient is retained: client credentials, token caching/renewal,
HTML sendMail, Retry-After, safe errors, accepted/uncertain outcomes and recipient
allowlist. No separate sender, credential store, queue or migration was added.

## Small local additions

- Empty LIBRARY_GRAPH_REPLY_TO now explicitly uses the configured Sender address.
  An explicit approved different Reply-To still wins. Validation precedes token
  acquisition; a recipient is never changed to the Reply-To or test inbox.
- Optional LIBRARY_GRAPH_MAILBOX_ID accepts the sender mailbox's Entra USER object
  UUID. It targets the existing /users/{id}/sendMail route if SMTP differs from UPN.
  Empty preserves the existing address-as-UPN route. This is NOT the app/client ID
  or enterprise application's service-principal object ID.
- SMTP Sender, UPN and optional mailbox ID must be confirmed to refer to the SAME
  authorized mailbox. Use the approved primary SMTP address for the first test;
  this change does not assume arbitrary aliases can be used as From.
- All live-delivery gates remain default off and allowlist remains default empty.

Files: backend/config/settings.py, backend/library/email_policy.py,
backend/library/graph_client.py, backend/library/test_graph_mailbox_setup.py,
and this document.

## What the Microsoft 365 administrator must supply/confirm

1. Confirm the old n8n From, then verify an Exchange Online mailbox for that exact
   approved library identity. Provide primary SMTP, UPN and optional mailbox USER
   object ID. A Gmail credential/domain alone proves none of these Microsoft facts.
2. In Entra App registrations, identify/prepare the dedicated library application:
   Directory (tenant) ID and Application (client) ID. Create a newly approved,
   rotated client secret for secure future configuration, with managed expiry.
   No secret should be embedded in source or reused merely because its key exists.
3. **Authorization model:** prefer Exchange Application RBAC, registering the
   enterprise-app service principal and assigning `Application Mail.Send` scoped
   to the library mailbox only. Grants are additive: an unscoped Entra Mail.Send
   grant defeats a narrower RBAC grant. If retaining the Entra Application Mail.Send
   + Admin Consent route, verify its effective mailbox restriction; do not assume
   adding scoped RBAC constrains it. Existing Application Access Policies are a
   separate legacy restriction model, not the preferred new RBAC configuration.
   [Microsoft guidance](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
4. For RBAC, run `Test-ServicePrincipalAuthorization` with the library mailbox as
   Resource and check Application Mail.Send InScope=True; test another mailbox's
   authorization as out of scope. Also review independent Entra grants: the RBAC
   test does not evaluate those. No email needs to be sent to test a disallowed
   mailbox. [Authorization test](https://learn.microsoft.com/en-us/powershell/module/exchangepowershell/test-serviceprincipalauthorization?view=exchange-ps).
5. Confirm Reply-To policy: absent a different approved policy, use the same
   confirmed library mailbox. Name one explicitly authorized recipient TEST inbox.

No tenant/account/permission/consent state was verified through a live Microsoft
connection here. A syntactically valid UUID or a local approval flag is not proof.

## Environment names for later authorized setup (no values added)

| Setting | Purpose |
| --- | --- |
| LIBRARY_GRAPH_TENANT_ID | verified mailbox tenant directory ID |
| LIBRARY_GRAPH_CLIENT_ID | approved app's Application/client ID |
| LIBRARY_GRAPH_CLIENT_SECRET | newly approved rotated secret, configured securely later |
| LIBRARY_GRAPH_SENDER | confirmed library primary SMTP address; not a guessed Gmail identity |
| LIBRARY_GRAPH_MAILBOX_ID | optional mailbox USER UUID if SMTP != UPN |
| LIBRARY_GRAPH_REPLY_TO | optional explicit policy override; empty follows Sender |
| LIBRARY_EMAIL_RECIPIENT_ALLOWLIST | exact authorized test recipient address only |

The provider scope remains `https://graph.microsoft.com/.default`; it is not a
permission grant. Existing delivery flags/ownership gates are not bypassed.

## First real-mail test plan — future approval, NOT executed

1. Obtain identity and authorization confirmations above and an approved test inbox.
2. Prepare a separate test application environment/database with synthetic users,
   staff and one synthetic loan while enqueue/worker/send flags are OFF. Do not
   use Neon production, a production copy, existing student messages or a live
   production n8n route. Do not alter n8n's workflows or production ownership.
3. Give the synthetic recipient its own verified IANA timezone; the allowlist must
   contain ONLY its real authorized test inbox. Keep Scheduler OFF throughout.
4. In that dedicated test environment ONLY, after explicit authorization configure
   verified Graph values and enable the existing enqueue/worker/Graph/credentials
   gates. Own ONLY `manual_email`, and acknowledge that isolated manual test's
   ownership. This does not assert handoff of production n8n events.
5. Use the existing staff manual-email API on the synthetic loan with a fresh
   requestId UUID to create ONE HTML outbox message. Verify its actual recipient,
   template, saved zone and that the queue has no other pending messages.
6. Invoke the existing worker for one bounded batch, --limit 1, under supervision.
   The allowlist and dedicated queue are the safeguards; the limit alone is not.
   The normal isolated unit-test runner deliberately blocks real networking and
   clears credentials, so it is NOT the tool for this later authorized live test.
7. Check the attempt/provider request ID and Graph acceptance, then verify actual
   From, Reply-To, HTML, local times and receipt using the test inbox/Sent Items or
   authorized message trace. HTTP 202 is acceptance, not proof of inbox delivery.
   [sendMail semantics](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0).
8. Stop after this one test. Unknown acceptance stays uncertain with no blind
   retry. Do not start reminders, replay shadow messages, move production event
   ownership or turn on a recurring worker as part of this test.

## Local verification

97 tests passed using a fresh isolated PostgreSQL 17.12 cluster, direct synthetic
model tables (no migrations) and fake Graph transports. Includes seven new mailbox
tests: default/explicit Reply-To, mailbox-ID target, bad configuration before auth,
no legacy credential/Sender inference, allowlist and disabled delivery gates.
The temporary server stopped afterward. No real email, Graph/Entra request, n8n
execution, Neon connection, .env edit, deployment or production change occurred.
