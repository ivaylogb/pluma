# Pluma cross-tool report

Generated: 2026-05-15T20:59:31+00:00

Tools run:
  - funnel-researcher
  - integration-watcher

## Correlation matrix

| Tool | Layer 2 | Layer 3 | Layer 4 | Total |
|---|---|---|---|---|
| funnel-researcher | 2 | 1 | 0 | 3 |
| integration-watcher | 1 | 1 | 1 | 3 |

## Cross-tool findings (5)

### Cross-match 1 — Mechanical match

**Reason:** both cite `docs/persons.md:23-24`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H1: SDK/API surface does not signal that POST /v1/accounts returning 200 is not progress [Layer 2]**

**Claim:** The largest dropoff bucket (34% silent abandonment + 14% "200 but unchanged" = 48% of dropoffs) shares one mechanism: developers POST the fields named in `requirements.currently_due`, get a 200 back with the updated `Account` object, and treat that as "submitted, awaiting Stripe." There is no surface-level indication in the SDK's `Account.modify` / `modify_async` signature, return shape, or docstring that the caller MUST re-read `requirements.currently_due` on the returned object and that an unchanged or only-shrunk-then-restored `currently_due` array is the actual signal of submission failure. The `Account` Python class documents `requirements` as `Optional[Requirements]` (sdk/stripe/_account.py:1503) with no indication that a successful `modify()` call may return the same `currently_due` it received. The 14% "200 without progress" signal is the smoking gun: those developers DID re-read but their submissions silently failed validation (no errors raised, fields under-specified) and there is no mechanism by which a developer learns this without diffing `currently_due` themselves.

**Evidence:**
- sdk/stripe/_account.py:1983–1993 (`modify` / `modify_async`): the SDK exposes `Account.modify(id, **params)` returning `"Account"`. No docstring, no warning about partial acceptance, no helper to surface "your submitted fields did not clear currently_due." The same pattern appears in `_static_request` at sdk/stripe/_account.py:1995–2001.
- sdk/stripe/_account.py:1156–1158 (`Requirements.currently_due`): typed as `Optional[List[str]]` with description "Fields that need to be resolved to keep the account enabled." No mention that this is the post-submit verification surface.
- docs/persons.md:91 ("Stripe typically disables payouts on the account if we don't receive the information by the `current_deadline`") and docs/persons.md:23–24 (the canonical wait-loop description) — the docs treat re-reading `currently_due` as one bullet in a list, not as the *primary* feedback channel after every write.
- openapi spec3.yaml:5856–5862 (`currently_due` schema): "Fields that need to be resolved to keep the account enabled. If not resolved by `current_deadline`, these fields will appear in `past_due` as well, and the account is disabled." — describes the consequence, not the diff-after-write protocol.
- dropoff signal: 34% of dropoffs at `requirements_satisfied` are `currently_due` non-empty 7+ days after last POST with no further calls — median 3 calls before quit. Combined with the 14% "200 but currently_due unchanged" signal (median 5 calls), this is 48% of dropoffs failing on a mechanism the API surface does not flag.
- qualitative signal: stripe-python issue #1227 (typed access to `tos_acceptance.service_agreement` crashes) demonstrates that developers ARE writing typed gating logic against the returned Account object; they want a machine-readable signal of progress, and the SDK does not provide one.

**Proposed change:** Add an explicit docstring to `Account.modify` and `Account.modify_async` documenting (a) that a 200 does not mean `currently_due` is cleared, (b) the required post-write protocol (diff `requirements.currently_due` and `requirements.errors[]`), and (c) the existence of per-capability requirements that are NOT visible on `Account.requirements`. This is the minimal Layer-2 surface change that addresses both the 34% silent-abandonment and 14% no-progress signals.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "sdk/stripe/_account.py",
      "action": "insert_after",
      "at_line": 1982,
      "new_content": "    # NOTE: A 200 response from modify()/modify_async() does NOT mean the\n    # submitted fields have cleared the account's verification requirements.\n    # After every successful call, you MUST:\n    #   1. Read `account.requirements.currently_due` on the returned object.\n    #      If it is non-empty, the account is not yet satisfied and you must\n    #      submit the remaining fields (or correct fields that failed silent\n    #      validation -- a 200 with `currently_due` unchanged means your\n    #      submission was accepted but did not clear any requirement).\n    #   2. Read `account.requirements.errors[]` for per-field validation\n    #      failures (e.g. invalid_address_city_state_postal_code,\n    #      verification_document_failed_greyscale). These describe WHY a\n    #      submitted field did not clear `currently_due`.\n    #   3. Separately read each requested capability's own `requirements`\n    #      hash via Account.retrieve_capability(account, capability) --\n    #      capability-level requirements are NOT mirrored into\n    #      `account.requirements` and a capability can stay inactive even\n    #      when `account.requirements.currently_due` is empty.\n    #   4. Subscribe to the `account.updated` webhook to catch asynchronous\n    #      transitions out of `requirements.pending_verification` (see\n    #      docs/persons.md).\n    # See docs/persons.md \"Verification process\" for the full loop."
    }
  ]
}
```

**How to verify:** The 34% silent-abandonment bucket and the 14% "200 without progress" bucket should both shrink. Specifically: median developer calls before quit in the 34% bucket should rise above 3 (developers loop instead of abandoning), and the 14% bucket should compress as developers learn to inspect `requirements.errors[]` (the 13% errors-populated bucket may transiently grow as those developers stop abandoning and start surfacing the error). Target: `requirements_collected → requirements_satisfied` pass rate moves from 63.4% toward 75%+. If only the 34% bucket shrinks but the 14% bucket does not, this hypothesis is partially correct and Hypothesis 2 is the dominant remaining cause.

---

**integration-watcher — F1: Three of seven integrations create an account, read `requirements.currently_due`, and never POST any of the required fields back — they enter an indefinite GET-poll loop waiting for a state transition the API cannot make without their submission [Layer 4]**

**Pattern claim:** The most common stall in this cohort is not an error, it's a missing submission step. After `POST /v1/accounts` returns a populated `requirements.currently_due` array, the integration reads it (sometimes once, sometimes via the capabilities endpoint) and then issues only GET requests against the account, never POSTing the listed fields back. The account therefore cannot progress and the integration has no signal to act on, because by Stripe's contract the requirements array only changes in response to data the integration provides (or to Stripe-side review of data already provided).

**Cohort prevalence:** 3 of 7 integrations exhibit the pattern fully (dev_c3d4, dev_e5f6, dev_i9j0). Their calls account for 57 of 150 cohort calls (38%). All three never reach `charges_enabled=true` in the observed window.

**Trace evidence:**
- `dev_c3d4` (traces:17–22, 24, 26, 28, 38, 43, 48, 64, 76, 82): one POST /v1/accounts (traces:17) producing `currently_due=[business_type,representative,tos_acceptance,external_account]`, then 12 GETs on the account and 2 GETs on capabilities, no POST to /v1/accounts/{account} or /v1/accounts/{account}/persons ever issued. Final check at traces:82 still shows `transfers=inactive`, and the inline annotation explicitly notes "no POST ever issued" repeatedly (traces:22, 24, 26, 28, 38, 43, 48, 64, 76).
- `dev_e5f6` (traces:32–37, 39–42, 44–47, 49, 51–52, 63, 65, 69–70, 73–74, 77, 79, 84): one POST /v1/accounts (traces:32), one POST /v1/accounts/{account} that only *requests* card_payments/transfers capabilities (traces:34), then 15 GETs on a specific capability and 7 on the capabilities collection while `requirements.currently_due=[business_profile.mcc, business_profile.url, representative, external_account, company.tax_id]` (traces:35) sits unaddressed. At traces:77 the integration re-issues `POST /v1/accounts/{account}/capabilities/{capability} requested=true` — re-requesting an already-requested capability — instead of POSTing the requirements. Gives up at traces:84.
- `dev_i9j0` (traces:86–93, 96–97, 101, 103, 111, 118, 136, 142): POST /v1/accounts (traces:86), POST /v1/account_links (traces:87), then 5 GETs in 27 minutes against `requirements.currently_due=[<full set>]` (traces:88–92, annotated "tight poll loop right after redirect, before user finished"), then two more Account Link regenerations (traces:96, 101) and trailing GETs ending in abandonment (traces:142). The integration is using hosted onboarding correctly in shape but is polling the account state instead of listening for `account.updated`, and has no fallback when the user drops out of the hosted flow.

**Product evidence:**
- `docs/hosted_vs_custom.md:107–112` (the Stripe-hosted onboarding "Request capabilities" section) tells the integration to "set the desired capabilities' `requested` property to true" at create time but never shows what to do next with the `requirements.currently_due` returned by the create call. The next section the reader encounters (lines 114–119) is about prefill, not about submitting requirements back. The worked code block at `docs/hosted_vs_custom.md:88–95` ends with the account creation curl and does not show a follow-up POST against `/v1/accounts/{account}`.
- `docs/persons.md:21–24` (the only place in the docs that names the post-create loop) says "Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute for additional requirements. Obtain any required information from the connected account and update the `Account`." This sentence is correct but it is buried inside the API-verification guide; an integrator following the hosted-onboarding quickstart never reaches it before they write the polling loop the traces show.
- `docs/capabilities.md:477–481` confirms the contract: "When your connected account is successfully created, you can [retrieve a list] of its requirements ... The values for `payouts_enabled` and `charges_enabled` indicate whether payouts and charges are enabled for the account." The doc shows the GET but doesn't show what to do with the returned `requirements` hash, so re-reading the same GET is a plausible mis-reading of "retrieve a list."
- `openapi:60–125` (the `/v1/account_links` POST schema) requires `account` and `type` but does not document a relationship to `requirements.currently_due`, reinforcing the dev_i9j0 mental model that creating an Account Link is itself the requirement-submission step.

**Proposed change:** Insert a new "What to do with the create response" subsection into `docs/hosted_vs_custom.md` immediately after the account-creation curl example, explicitly naming the three-step loop (read `requirements.currently_due` → POST those fields against `/v1/accounts/{account}` or `/v1/accounts/{account}/persons` → wait for `account.updated`) and link it to the verification guide. This is the cheapest single edit that addresses the largest share of the cohort's stalled traffic. The deeper Layer 2 problem — that an API onboarding flow has no way to be told "you forgot to POST" — is not addressable by a docs edit.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 105,
      "new_content": "### What to do with the create response\n\nThe response to `POST /v1/accounts` includes a `requirements.currently_due` array. This array is **the integration's worklist**, not just a status display. The account will not progress toward `charges_enabled=true` until you POST those fields back, either by:\n\n- `POST /v1/accounts/{account}` for account-level fields (e.g. `business_profile.url`, `company.tax_id`, `tos_acceptance`, `external_account`), or\n- `POST /v1/accounts/{account}/persons` for person-level fields (e.g. `representative`, `owner`, `verification.document`).\n\nPolling `GET /v1/accounts/{account}` will not change the state of the account on its own — if `currently_due` is non-empty, the API is waiting on you. Only after `currently_due` is empty will the account transition to `disabled_reason=requirements.pending_verification`, at which point Stripe is doing asynchronous review and you should listen for `account.updated` webhooks rather than poll. See [Handle verification with the API](handling-api-verification.md) for the full submission loop."
    }
  ]
}
```

**How to verify:** In a follow-up cohort over a comparable window, the count of integrations that issue more than 5 consecutive `GET /v1/accounts/{account}` calls *without an intervening POST against `/v1/accounts/{account}` or `/v1/accounts/{account}/persons`* should drop substantially. The finding fails if integrations continue the same pattern (account create → GET-only poll loop) at the same rate after the docs change, which would indicate the cause is not "developers didn't know to POST" but something else (e.g., they don't have the data to POST yet, which is a different problem in a different layer).


### Cross-match 2 — Categorical match

**Reason:** same Layer 2, shared surface `docs/persons.md`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H1: SDK/API surface does not signal that POST /v1/accounts returning 200 is not progress [Layer 2]**

**Claim:** The largest dropoff bucket (34% silent abandonment + 14% "200 but unchanged" = 48% of dropoffs) shares one mechanism: developers POST the fields named in `requirements.currently_due`, get a 200 back with the updated `Account` object, and treat that as "submitted, awaiting Stripe." There is no surface-level indication in the SDK's `Account.modify` / `modify_async` signature, return shape, or docstring that the caller MUST re-read `requirements.currently_due` on the returned object and that an unchanged or only-shrunk-then-restored `currently_due` array is the actual signal of submission failure. The `Account` Python class documents `requirements` as `Optional[Requirements]` (sdk/stripe/_account.py:1503) with no indication that a successful `modify()` call may return the same `currently_due` it received. The 14% "200 without progress" signal is the smoking gun: those developers DID re-read but their submissions silently failed validation (no errors raised, fields under-specified) and there is no mechanism by which a developer learns this without diffing `currently_due` themselves.

**Evidence:**
- sdk/stripe/_account.py:1983–1993 (`modify` / `modify_async`): the SDK exposes `Account.modify(id, **params)` returning `"Account"`. No docstring, no warning about partial acceptance, no helper to surface "your submitted fields did not clear currently_due." The same pattern appears in `_static_request` at sdk/stripe/_account.py:1995–2001.
- sdk/stripe/_account.py:1156–1158 (`Requirements.currently_due`): typed as `Optional[List[str]]` with description "Fields that need to be resolved to keep the account enabled." No mention that this is the post-submit verification surface.
- docs/persons.md:91 ("Stripe typically disables payouts on the account if we don't receive the information by the `current_deadline`") and docs/persons.md:23–24 (the canonical wait-loop description) — the docs treat re-reading `currently_due` as one bullet in a list, not as the *primary* feedback channel after every write.
- openapi spec3.yaml:5856–5862 (`currently_due` schema): "Fields that need to be resolved to keep the account enabled. If not resolved by `current_deadline`, these fields will appear in `past_due` as well, and the account is disabled." — describes the consequence, not the diff-after-write protocol.
- dropoff signal: 34% of dropoffs at `requirements_satisfied` are `currently_due` non-empty 7+ days after last POST with no further calls — median 3 calls before quit. Combined with the 14% "200 but currently_due unchanged" signal (median 5 calls), this is 48% of dropoffs failing on a mechanism the API surface does not flag.
- qualitative signal: stripe-python issue #1227 (typed access to `tos_acceptance.service_agreement` crashes) demonstrates that developers ARE writing typed gating logic against the returned Account object; they want a machine-readable signal of progress, and the SDK does not provide one.

**Proposed change:** Add an explicit docstring to `Account.modify` and `Account.modify_async` documenting (a) that a 200 does not mean `currently_due` is cleared, (b) the required post-write protocol (diff `requirements.currently_due` and `requirements.errors[]`), and (c) the existence of per-capability requirements that are NOT visible on `Account.requirements`. This is the minimal Layer-2 surface change that addresses both the 34% silent-abandonment and 14% no-progress signals.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "sdk/stripe/_account.py",
      "action": "insert_after",
      "at_line": 1982,
      "new_content": "    # NOTE: A 200 response from modify()/modify_async() does NOT mean the\n    # submitted fields have cleared the account's verification requirements.\n    # After every successful call, you MUST:\n    #   1. Read `account.requirements.currently_due` on the returned object.\n    #      If it is non-empty, the account is not yet satisfied and you must\n    #      submit the remaining fields (or correct fields that failed silent\n    #      validation -- a 200 with `currently_due` unchanged means your\n    #      submission was accepted but did not clear any requirement).\n    #   2. Read `account.requirements.errors[]` for per-field validation\n    #      failures (e.g. invalid_address_city_state_postal_code,\n    #      verification_document_failed_greyscale). These describe WHY a\n    #      submitted field did not clear `currently_due`.\n    #   3. Separately read each requested capability's own `requirements`\n    #      hash via Account.retrieve_capability(account, capability) --\n    #      capability-level requirements are NOT mirrored into\n    #      `account.requirements` and a capability can stay inactive even\n    #      when `account.requirements.currently_due` is empty.\n    #   4. Subscribe to the `account.updated` webhook to catch asynchronous\n    #      transitions out of `requirements.pending_verification` (see\n    #      docs/persons.md).\n    # See docs/persons.md \"Verification process\" for the full loop."
    }
  ]
}
```

**How to verify:** The 34% silent-abandonment bucket and the 14% "200 without progress" bucket should both shrink. Specifically: median developer calls before quit in the 34% bucket should rise above 3 (developers loop instead of abandoning), and the 14% bucket should compress as developers learn to inspect `requirements.errors[]` (the 13% errors-populated bucket may transiently grow as those developers stop abandoning and start surfacing the error). Target: `requirements_collected → requirements_satisfied` pass rate moves from 63.4% toward 75%+. If only the 34% bucket shrinks but the 14% bucket does not, this hypothesis is partially correct and Hypothesis 2 is the dominant remaining cause.

---

**integration-watcher — F3: When `requirements.errors` reports a document-level failure (e.g. `verification_document_failed_greyscale`), integrations attempt to re-resolve by re-POSTing the same field shape, because the error catalog entry names the cause but not the resolution path — and there is no error catalog in the product artifacts at all [Layer 2]**

**Pattern claim:** dev_k1l2 receives `requirements.errors=[verification_document_failed_greyscale]` (traces:117) and responds by uploading the document again with the same shape twice (traces:119, 134), at which point the integration stalls (traces:137, 138, 141, 145, 147) — annotated "cannot self-resolve document error." The trace cohort has no separate error catalog in the product artifacts; error codes appear inline in `docs/persons.md` with a one-line "Resolution" column but no actionable code paths. The integration's repeated re-upload is the natural fallback when the error message names a cause ("greyscale") but the resolution lives in a separate doc.

**Cohort prevalence:** 1 of 7 integrations exhibits this specific document-error pattern in full (dev_k1l2). It accounts for 11 of 150 cohort calls (~7%): traces:105–109, 112–113, 115–117, 119, 132, 134, 137–138, 141, 145, 147. The pattern is structurally distinct from Finding 1 (the integration *is* POSTing) and Finding 2 (the integration is not in pending_verification — it's in an error state with an actionable requirement). I include it as a third finding rather than collapse it because the proposed change is different (it's a product-artifact gap, not a docs-flow gap).

**Trace evidence:**
- `dev_k1l2` traces:117 first surfaces `requirements.errors=[verification_document_failed_greyscale]` after a document upload (traces:116). The integration re-uploads at traces:119, gets the same error at traces:132, re-uploads again at traces:134, and from traces:137 onward issues read-only GETs annotated "cannot self-resolve document error." The integration never reaches `charges_enabled=true`.
- For context, dev_g7h8 traces:54 returns `parameter_unknown` after a POST shaped as `additional_owners=[{first_name}]` (an Accounts v1 legacy shape). The integration recovers by switching to the Persons API shape at traces:56, but only after two failed POSTs (traces:54, 55). The error code by itself did not name the shape change required.

**Product evidence:**
- The artifact tree lists "errors / error catalog" as `[no error catalog found]` — there is no `errors.md` or equivalent. Error codes are catalogued inline in `docs/persons.md:281–290` (the upload error table), which lists `verification_document_failed_greyscale` alongside ~30 other codes and gives a single shared resolution row: "The upload failed because of a problem with the file. Ask your account user to provide a new file that meets these requirements: Color image (8,000 pixels by 8,000 pixels or smaller); 10 MB or less; ..." The resolution row is correct but it is shared across all upload errors, so the specific code does not point to the specific fix.
- `sdk/stripe/_account.py:856–957` enumerates all `code` enum values for `requirements.errors` (including `verification_document_failed_greyscale` at line 911) as a flat list. The SDK exposes the code as a string but provides no enum-to-resolution mapping, so an integrator inspecting the error in code has no programmatic way to distinguish "re-upload as color" from "re-upload as larger file" from "re-upload with both sides."
- `openapi:5938–6038` (the `account_requirements_error` schema) defines `code`, `reason`, and `requirement` fields. The `reason` field is described as "An informative message that indicates the error type and provides additional details about the error" — but the traces show dev_k1l2 retrying the same shape, suggesting the `reason` string at runtime does not include the resolution ("upload a color scan, not a greyscale scan") or the integration is not surfacing it.

**Proposed change:** Add a dedicated `errors.md` or `error_catalog.md` to the product artifacts that maps each `requirements.errors.code` value to (a) the specific cause, (b) the specific resolution (e.g. "re-upload the document in color, not greyscale; greyscale scans are rejected before review"), and (c) a flag indicating whether the resolution is the same as a previous attempt (so the integration knows that re-POSTing without a real change will produce the same error). Because this requires authoring new content per error code, I'm marking the structured edit as not applyable — it is a product-content change, not a single-file edit.

```json
{
  "applyable": false,
  "reason": "Requires authoring a new error catalog file mapping each requirements.errors.code value (the enum is defined at sdk/stripe/_account.py:856–957 and openapi:5942–6037) to a specific cause/resolution pair. This is per-code content authoring with Stripe risk/compliance sign-off, not a mechanical edit of an existing file. A short-term Layer 3 mitigation would be to add a 'Common document re-upload failures' subsection to docs/persons.md near the existing upload error table at lines 281–290 that calls out greyscale/blurry/wrong-side as the three most common causes and explicitly states that re-uploading the same file will produce the same error — but the full fix is a product-artifact gap."
}
```

**How to verify:** In a follow-up cohort, the count of integrations that produce two or more consecutive `POST /v1/accounts/{account}/persons` calls with `verification[document][front]=file_*` where the previous response surfaced a `verification_document_failed_*` error in `requirements.errors` should drop. The finding fails if integrations continue to re-upload the same shape after the error catalog is published — which would suggest the integration is not reading `requirements.errors` at all (a different finding, in Layer 4) rather than misinterpreting it.


### Cross-match 3 — Mechanical match

**Reason:** both cite `docs/persons.md:22-22`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: The async `pending_verification` transition has no surfaced "you must subscribe to webhooks" gate [Layer 3]**

**Claim:** The 17% bucket (`disabled_reason == requirements.pending_verification`, integration stops listening to `account.updated`, median only 2 calls before quit) is distinct from Hypotheses 1 and 2: these developers DID submit, DID see Stripe accept the submission, and the account went into asynchronous verification — but they do not realize the resolution arrives via webhook, not via API polling. The mechanism is that `requirements.pending_verification` and `requirements.disabled_reason = requirements.pending_verification` (openapi spec3.yaml:5879, 5903–5908) are terminal states for the synchronous flow: no further API call will reveal the verification result. `docs/persons.md` does mention the webhook requirement at lines 22 and 491–492, but it appears in the "Verification process" preamble and is not co-located with any of the per-error rows in the document verification tables (docs/persons.md:264–290) where a developer would land when troubleshooting. The median of 2 calls before quit (lower than every other failure bucket) confirms these are developers who hit the wall fast and gave up — they don't even know there's a wall to wait at.

**Evidence:**
- docs/persons.md:22 ("Establish a Connect webhook URL... to watch for activity, especially `account.updated` events"): mentioned once, as item 1 of a three-item list, with no callout that this is REQUIRED (not optional) for any onboarding flow that hits async verification.
- docs/persons.md:491–492 ("Stripe can take anywhere from a few minutes to a few business days to verify an image"): explains the async timing but does not say "you will not learn the result via polling; you must use webhooks."
- docs/persons.md:48 (`pending_verification` in the requirements properties table): defined, but the definition does not state which signal informs the developer when verification completes.
- openapi spec3.yaml:5903–5908 (`pending_verification` in `account_requirements`): "Fields that are being reviewed... If the review fails, these fields can move to `eventually_due`, `currently_due`, `past_due` or `alternatives`." — describes the state transitions but not the notification channel.
- dropoff signal: 17% of dropoffs hit `disabled_reason == requirements.pending_verification` and quit after a median of 2 calls. The low call count specifically distinguishes this from H1/H2 (3–5 calls) — these developers are not in a polling loop at all; they hit the state and stop.

**Proposed change:** Add an explicit notice at the top of the verification-process section in `docs/persons.md` — at the point where `pending_verification` is first introduced — that asynchronous verification results arrive via `account.updated` webhook ONLY, and that any integration onboarding accounts must subscribe before the first account create.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/persons.md",
      "action": "insert_after",
      "at_line": 48,
      "new_content": "\n> #### `pending_verification` resolves asynchronously via webhook only\n>\n> When `requirements.pending_verification` is non-empty (or `requirements.disabled_reason == \"requirements.pending_verification\"`), Stripe is performing the verification asynchronously. The result — verification success, or new fields moving back into `currently_due` / `errors[]` — is delivered **only** via an `account.updated` webhook event. Polling `GET /v1/accounts/{account}` will return the same `pending_verification` state until the verification completes (which can take anywhere from a few minutes to several business days).\n>\n> If your integration does not have a Connect webhook endpoint subscribed to `account.updated` *before* you create your first connected account, you will not receive the resolution signal and the account will appear permanently stuck in `pending_verification`. Configure your webhook endpoint in your [webhook settings](https://dashboard.stripe.com/account/webhooks) first.\n"
    }
  ]
}
```

**How to verify:** The 17% `pending_verification` bucket should shrink, and specifically the median calls before quit metric (currently 2) should rise — developers who learn that webhook subscription is the resolution mechanism will either (a) set up webhooks and not appear in the dropoff at all, or (b) wait longer before abandoning. Target: 17% bucket falls below 8%, and `requirements_satisfied → charges_enabled` pass rate (currently 85.3%) also improves marginally because the same mechanism causes some accounts to appear stuck downstream.

**integration-watcher — F1: Three of seven integrations create an account, read `requirements.currently_due`, and never POST any of the required fields back — they enter an indefinite GET-poll loop waiting for a state transition the API cannot make without their submission [Layer 4]**

**Pattern claim:** The most common stall in this cohort is not an error, it's a missing submission step. After `POST /v1/accounts` returns a populated `requirements.currently_due` array, the integration reads it (sometimes once, sometimes via the capabilities endpoint) and then issues only GET requests against the account, never POSTing the listed fields back. The account therefore cannot progress and the integration has no signal to act on, because by Stripe's contract the requirements array only changes in response to data the integration provides (or to Stripe-side review of data already provided).

**Cohort prevalence:** 3 of 7 integrations exhibit the pattern fully (dev_c3d4, dev_e5f6, dev_i9j0). Their calls account for 57 of 150 cohort calls (38%). All three never reach `charges_enabled=true` in the observed window.

**Trace evidence:**
- `dev_c3d4` (traces:17–22, 24, 26, 28, 38, 43, 48, 64, 76, 82): one POST /v1/accounts (traces:17) producing `currently_due=[business_type,representative,tos_acceptance,external_account]`, then 12 GETs on the account and 2 GETs on capabilities, no POST to /v1/accounts/{account} or /v1/accounts/{account}/persons ever issued. Final check at traces:82 still shows `transfers=inactive`, and the inline annotation explicitly notes "no POST ever issued" repeatedly (traces:22, 24, 26, 28, 38, 43, 48, 64, 76).
- `dev_e5f6` (traces:32–37, 39–42, 44–47, 49, 51–52, 63, 65, 69–70, 73–74, 77, 79, 84): one POST /v1/accounts (traces:32), one POST /v1/accounts/{account} that only *requests* card_payments/transfers capabilities (traces:34), then 15 GETs on a specific capability and 7 on the capabilities collection while `requirements.currently_due=[business_profile.mcc, business_profile.url, representative, external_account, company.tax_id]` (traces:35) sits unaddressed. At traces:77 the integration re-issues `POST /v1/accounts/{account}/capabilities/{capability} requested=true` — re-requesting an already-requested capability — instead of POSTing the requirements. Gives up at traces:84.
- `dev_i9j0` (traces:86–93, 96–97, 101, 103, 111, 118, 136, 142): POST /v1/accounts (traces:86), POST /v1/account_links (traces:87), then 5 GETs in 27 minutes against `requirements.currently_due=[<full set>]` (traces:88–92, annotated "tight poll loop right after redirect, before user finished"), then two more Account Link regenerations (traces:96, 101) and trailing GETs ending in abandonment (traces:142). The integration is using hosted onboarding correctly in shape but is polling the account state instead of listening for `account.updated`, and has no fallback when the user drops out of the hosted flow.

**Product evidence:**
- `docs/hosted_vs_custom.md:107–112` (the Stripe-hosted onboarding "Request capabilities" section) tells the integration to "set the desired capabilities' `requested` property to true" at create time but never shows what to do next with the `requirements.currently_due` returned by the create call. The next section the reader encounters (lines 114–119) is about prefill, not about submitting requirements back. The worked code block at `docs/hosted_vs_custom.md:88–95` ends with the account creation curl and does not show a follow-up POST against `/v1/accounts/{account}`.
- `docs/persons.md:21–24` (the only place in the docs that names the post-create loop) says "Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute for additional requirements. Obtain any required information from the connected account and update the `Account`." This sentence is correct but it is buried inside the API-verification guide; an integrator following the hosted-onboarding quickstart never reaches it before they write the polling loop the traces show.
- `docs/capabilities.md:477–481` confirms the contract: "When your connected account is successfully created, you can [retrieve a list] of its requirements ... The values for `payouts_enabled` and `charges_enabled` indicate whether payouts and charges are enabled for the account." The doc shows the GET but doesn't show what to do with the returned `requirements` hash, so re-reading the same GET is a plausible mis-reading of "retrieve a list."
- `openapi:60–125` (the `/v1/account_links` POST schema) requires `account` and `type` but does not document a relationship to `requirements.currently_due`, reinforcing the dev_i9j0 mental model that creating an Account Link is itself the requirement-submission step.

**Proposed change:** Insert a new "What to do with the create response" subsection into `docs/hosted_vs_custom.md` immediately after the account-creation curl example, explicitly naming the three-step loop (read `requirements.currently_due` → POST those fields against `/v1/accounts/{account}` or `/v1/accounts/{account}/persons` → wait for `account.updated`) and link it to the verification guide. This is the cheapest single edit that addresses the largest share of the cohort's stalled traffic. The deeper Layer 2 problem — that an API onboarding flow has no way to be told "you forgot to POST" — is not addressable by a docs edit.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 105,
      "new_content": "### What to do with the create response\n\nThe response to `POST /v1/accounts` includes a `requirements.currently_due` array. This array is **the integration's worklist**, not just a status display. The account will not progress toward `charges_enabled=true` until you POST those fields back, either by:\n\n- `POST /v1/accounts/{account}` for account-level fields (e.g. `business_profile.url`, `company.tax_id`, `tos_acceptance`, `external_account`), or\n- `POST /v1/accounts/{account}/persons` for person-level fields (e.g. `representative`, `owner`, `verification.document`).\n\nPolling `GET /v1/accounts/{account}` will not change the state of the account on its own — if `currently_due` is non-empty, the API is waiting on you. Only after `currently_due` is empty will the account transition to `disabled_reason=requirements.pending_verification`, at which point Stripe is doing asynchronous review and you should listen for `account.updated` webhooks rather than poll. See [Handle verification with the API](handling-api-verification.md) for the full submission loop."
    }
  ]
}
```

**How to verify:** In a follow-up cohort over a comparable window, the count of integrations that issue more than 5 consecutive `GET /v1/accounts/{account}` calls *without an intervening POST against `/v1/accounts/{account}` or `/v1/accounts/{account}/persons`* should drop substantially. The finding fails if integrations continue the same pattern (account create → GET-only poll loop) at the same rate after the docs change, which would indicate the cause is not "developers didn't know to POST" but something else (e.g., they don't have the data to POST yet, which is a different problem in a different layer).


### Cross-match 4 — Mechanical match

**Reason:** both cite `docs/persons.md:22-22`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: The async `pending_verification` transition has no surfaced "you must subscribe to webhooks" gate [Layer 3]**

**Claim:** The 17% bucket (`disabled_reason == requirements.pending_verification`, integration stops listening to `account.updated`, median only 2 calls before quit) is distinct from Hypotheses 1 and 2: these developers DID submit, DID see Stripe accept the submission, and the account went into asynchronous verification — but they do not realize the resolution arrives via webhook, not via API polling. The mechanism is that `requirements.pending_verification` and `requirements.disabled_reason = requirements.pending_verification` (openapi spec3.yaml:5879, 5903–5908) are terminal states for the synchronous flow: no further API call will reveal the verification result. `docs/persons.md` does mention the webhook requirement at lines 22 and 491–492, but it appears in the "Verification process" preamble and is not co-located with any of the per-error rows in the document verification tables (docs/persons.md:264–290) where a developer would land when troubleshooting. The median of 2 calls before quit (lower than every other failure bucket) confirms these are developers who hit the wall fast and gave up — they don't even know there's a wall to wait at.

**Evidence:**
- docs/persons.md:22 ("Establish a Connect webhook URL... to watch for activity, especially `account.updated` events"): mentioned once, as item 1 of a three-item list, with no callout that this is REQUIRED (not optional) for any onboarding flow that hits async verification.
- docs/persons.md:491–492 ("Stripe can take anywhere from a few minutes to a few business days to verify an image"): explains the async timing but does not say "you will not learn the result via polling; you must use webhooks."
- docs/persons.md:48 (`pending_verification` in the requirements properties table): defined, but the definition does not state which signal informs the developer when verification completes.
- openapi spec3.yaml:5903–5908 (`pending_verification` in `account_requirements`): "Fields that are being reviewed... If the review fails, these fields can move to `eventually_due`, `currently_due`, `past_due` or `alternatives`." — describes the state transitions but not the notification channel.
- dropoff signal: 17% of dropoffs hit `disabled_reason == requirements.pending_verification` and quit after a median of 2 calls. The low call count specifically distinguishes this from H1/H2 (3–5 calls) — these developers are not in a polling loop at all; they hit the state and stop.

**Proposed change:** Add an explicit notice at the top of the verification-process section in `docs/persons.md` — at the point where `pending_verification` is first introduced — that asynchronous verification results arrive via `account.updated` webhook ONLY, and that any integration onboarding accounts must subscribe before the first account create.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/persons.md",
      "action": "insert_after",
      "at_line": 48,
      "new_content": "\n> #### `pending_verification` resolves asynchronously via webhook only\n>\n> When `requirements.pending_verification` is non-empty (or `requirements.disabled_reason == \"requirements.pending_verification\"`), Stripe is performing the verification asynchronously. The result — verification success, or new fields moving back into `currently_due` / `errors[]` — is delivered **only** via an `account.updated` webhook event. Polling `GET /v1/accounts/{account}` will return the same `pending_verification` state until the verification completes (which can take anywhere from a few minutes to several business days).\n>\n> If your integration does not have a Connect webhook endpoint subscribed to `account.updated` *before* you create your first connected account, you will not receive the resolution signal and the account will appear permanently stuck in `pending_verification`. Configure your webhook endpoint in your [webhook settings](https://dashboard.stripe.com/account/webhooks) first.\n"
    }
  ]
}
```

**How to verify:** The 17% `pending_verification` bucket should shrink, and specifically the median calls before quit metric (currently 2) should rise — developers who learn that webhook subscription is the resolution mechanism will either (a) set up webhooks and not appear in the dropoff at all, or (b) wait longer before abandoning. Target: 17% bucket falls below 8%, and `requirements_satisfied → charges_enabled` pass rate (currently 85.3%) also improves marginally because the same mechanism causes some accounts to appear stuck downstream.

**integration-watcher — F2: Once `requirements.currently_due=[]` and `disabled_reason=requirements.pending_verification`, integrations have no documented signal channel and fall back to high-frequency `GET /v1/accounts/{account}` polling that returns success-coded "unchanged" responses for days [Layer 3]**

**Pattern claim:** The trace shape for accounts that have submitted everything is a long run of identical GETs returning `charges_enabled=false`, `requirements.currently_due=[]`, `disabled_reason=requirements.pending_verification`. The 200-coded "no change" responses are indistinguishable from any other successful GET, and the docs that describe this state direct the integration to listen for `account.updated` webhooks — but the quickstart and SDK do not show how to wire that up in the same flow as the create call, so integrations build their own polling loops instead.

**Cohort prevalence:** 3 of 7 integrations exhibit this specific sub-pattern (dev_a1b2, dev_g7h8, dev_m3n4). Their pending_verification poll calls account for roughly 27 of 150 cohort calls (18%): dev_a1b2 traces:10–16, 23, 25; dev_g7h8 traces:68, 72, 75, 78, 81, 83, 85, 95, 98, 100, 110; dev_m3n4 traces:131, 133, 135, 139, 140, 143, 144, 146, 148, 150. Only dev_a1b2 is observed reaching `charges_enabled=true` (traces:29), roughly 2 days and 14 hours after the requirements were cleared.

**Trace evidence:**
- `dev_a1b2` traces:10 first reports `currently_due=[] disabled_reason=requirements.pending_verification`; traces:11–16, 23, 25 are 8 GETs across ~58 hours on the same account, all 200, all identical state, annotated "account.updated webhook poll" — confirming the integration is polling *because* it does not trust or has not wired up the webhook. State flips at traces:29.
- `dev_g7h8` traces:68 enters `pending_verification` after a clean POST sequence; traces:72, 75, 78, 81, 83, 85, 95, 98, 100, 110 are 10 GETs over ~6 days, all returning unchanged. The integration never reaches `charges_enabled=true` in the observed window.
- `dev_m3n4` traces:131 enters `pending_verification`; traces:133, 135, 139, 140, 143, 144, 146, 148, 150 are 9 GETs over ~7 days, all unchanged. traces:149 shows a single capabilities check (`transfers=pending`), then traces:150 abandons monitoring.

**Product evidence:**
- `docs/persons.md:22` instructs the integrator to "Establish a [Connect webhook] URL in your webhook settings to watch for activity, especially `account.updated` events." This is correct but it is the only place this is said, and the hosted-onboarding flow (`docs/hosted_vs_custom.md:317–325`) repeats the webhook instruction only at the end of the integration ("Identify and address requirement updates"), after the integrator has likely already shipped a polling loop.
- `docs/hosted_vs_custom.md:351–355` describes the return URL and notes "No state is passed with this URL. After a connected account is redirected to the `return_url`, determine if the account has completed onboarding. Retrieve the account and check the `requirements` hash for outstanding requirements. Alternatively, listen to the `account.updated` event..." The word "Alternatively" frames the webhook as optional, which is consistent with dev_i9j0 and dev_a1b2's behavior of polling instead.
- `sdk/stripe/_account.py:97–101` (the `Account` class docstring) and `sdk/stripe/_account.py:1971–1980` (the `retrieve` method) expose no affordance for "wait for state change" or "subscribe." The SDK shape itself nudges integrations toward `Account.retrieve` loops because that is the only operation the SDK surfaces for monitoring account state.
- `openapi:2133–2177` (GET `/v1/accounts/{account}`) returns the same `account` schema regardless of whether anything has changed since the last call; there is no `If-Modified-Since` or change-cursor affordance in the spec.

**Proposed change:** Edit `docs/persons.md` to add a concrete worked example of the webhook listener for `account.updated` immediately adjacent to the existing bullet that names it (line 22), and change the wording in `docs/hosted_vs_custom.md:355` from "Alternatively, listen to the `account.updated` event" to "We strongly recommend you listen to the `account.updated` event..." so the docs stop framing webhooks as optional in the API-onboarding path. The structured edit below covers only the wording change in `hosted_vs_custom.md`, because the `persons.md` insertion text needs a working webhook example that I would want a docs author to vet.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "replace",
      "from_line_start": 355,
      "from_line_end": 355,
      "expected_content": "No state is passed with this URL. After a connected account is redirected to the `return_url`, determine if the account has completed onboarding. [Retrieve the account](https://docs.stripe.com/api/accounts/retrieve.md) and check the [requirements](https://docs.stripe.com/api/accounts/object.md#account_object-requirements) hash for outstanding requirements. Alternatively, listen to the `account.updated` event sent to your webhook endpoint and cache the state of the account in your application. If the account hasn’t completed onboarding, provide prompts in your application to allow them to continue onboarding later.",
      "new_content": "No state is passed with this URL. After a connected account is redirected to the `return_url`, determine if the account has completed onboarding. We strongly recommend you listen to the `account.updated` event sent to your webhook endpoint and cache the state of the account in your application: this is the only signal Stripe emits when the account transitions out of `requirements.pending_verification`, and polling `GET /v1/accounts/{account}` on this state will return the same `200`-coded unchanged response for hours or days. If you have not yet wired up a webhook endpoint, you can [retrieve the account](https://docs.stripe.com/api/accounts/retrieve.md) on demand and check the [requirements](https://docs.stripe.com/api/accounts/object.md#account_object-requirements) hash, but do so on user action (e.g. when they revisit your app), not on a fixed polling interval. If the account hasn’t completed onboarding, provide prompts in your application to allow them to continue onboarding later."
    }
  ]
}
```

**How to verify:** In a follow-up cohort, the number of `GET /v1/accounts/{account}` calls per account that returns `disabled_reason=requirements.pending_verification` should fall (a typical healthy integration would show 1–2 GETs around webhook receipt rather than 8–10 over multi-day windows). The finding fails if integrations continue polling at the same rate after the docs change, which would suggest that the cause is the absence of a "wait for state change" affordance in the SDK (a Layer 2 product change, not addressable by docs).


### Cross-match 5 — Mechanical match

**Reason:** both cite `docs/persons.md:264-290`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: The async `pending_verification` transition has no surfaced "you must subscribe to webhooks" gate [Layer 3]**

**Claim:** The 17% bucket (`disabled_reason == requirements.pending_verification`, integration stops listening to `account.updated`, median only 2 calls before quit) is distinct from Hypotheses 1 and 2: these developers DID submit, DID see Stripe accept the submission, and the account went into asynchronous verification — but they do not realize the resolution arrives via webhook, not via API polling. The mechanism is that `requirements.pending_verification` and `requirements.disabled_reason = requirements.pending_verification` (openapi spec3.yaml:5879, 5903–5908) are terminal states for the synchronous flow: no further API call will reveal the verification result. `docs/persons.md` does mention the webhook requirement at lines 22 and 491–492, but it appears in the "Verification process" preamble and is not co-located with any of the per-error rows in the document verification tables (docs/persons.md:264–290) where a developer would land when troubleshooting. The median of 2 calls before quit (lower than every other failure bucket) confirms these are developers who hit the wall fast and gave up — they don't even know there's a wall to wait at.

**Evidence:**
- docs/persons.md:22 ("Establish a Connect webhook URL... to watch for activity, especially `account.updated` events"): mentioned once, as item 1 of a three-item list, with no callout that this is REQUIRED (not optional) for any onboarding flow that hits async verification.
- docs/persons.md:491–492 ("Stripe can take anywhere from a few minutes to a few business days to verify an image"): explains the async timing but does not say "you will not learn the result via polling; you must use webhooks."
- docs/persons.md:48 (`pending_verification` in the requirements properties table): defined, but the definition does not state which signal informs the developer when verification completes.
- openapi spec3.yaml:5903–5908 (`pending_verification` in `account_requirements`): "Fields that are being reviewed... If the review fails, these fields can move to `eventually_due`, `currently_due`, `past_due` or `alternatives`." — describes the state transitions but not the notification channel.
- dropoff signal: 17% of dropoffs hit `disabled_reason == requirements.pending_verification` and quit after a median of 2 calls. The low call count specifically distinguishes this from H1/H2 (3–5 calls) — these developers are not in a polling loop at all; they hit the state and stop.

**Proposed change:** Add an explicit notice at the top of the verification-process section in `docs/persons.md` — at the point where `pending_verification` is first introduced — that asynchronous verification results arrive via `account.updated` webhook ONLY, and that any integration onboarding accounts must subscribe before the first account create.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/persons.md",
      "action": "insert_after",
      "at_line": 48,
      "new_content": "\n> #### `pending_verification` resolves asynchronously via webhook only\n>\n> When `requirements.pending_verification` is non-empty (or `requirements.disabled_reason == \"requirements.pending_verification\"`), Stripe is performing the verification asynchronously. The result — verification success, or new fields moving back into `currently_due` / `errors[]` — is delivered **only** via an `account.updated` webhook event. Polling `GET /v1/accounts/{account}` will return the same `pending_verification` state until the verification completes (which can take anywhere from a few minutes to several business days).\n>\n> If your integration does not have a Connect webhook endpoint subscribed to `account.updated` *before* you create your first connected account, you will not receive the resolution signal and the account will appear permanently stuck in `pending_verification`. Configure your webhook endpoint in your [webhook settings](https://dashboard.stripe.com/account/webhooks) first.\n"
    }
  ]
}
```

**How to verify:** The 17% `pending_verification` bucket should shrink, and specifically the median calls before quit metric (currently 2) should rise — developers who learn that webhook subscription is the resolution mechanism will either (a) set up webhooks and not appear in the dropoff at all, or (b) wait longer before abandoning. Target: 17% bucket falls below 8%, and `requirements_satisfied → charges_enabled` pass rate (currently 85.3%) also improves marginally because the same mechanism causes some accounts to appear stuck downstream.

**integration-watcher — F3: When `requirements.errors` reports a document-level failure (e.g. `verification_document_failed_greyscale`), integrations attempt to re-resolve by re-POSTing the same field shape, because the error catalog entry names the cause but not the resolution path — and there is no error catalog in the product artifacts at all [Layer 2]**

**Pattern claim:** dev_k1l2 receives `requirements.errors=[verification_document_failed_greyscale]` (traces:117) and responds by uploading the document again with the same shape twice (traces:119, 134), at which point the integration stalls (traces:137, 138, 141, 145, 147) — annotated "cannot self-resolve document error." The trace cohort has no separate error catalog in the product artifacts; error codes appear inline in `docs/persons.md` with a one-line "Resolution" column but no actionable code paths. The integration's repeated re-upload is the natural fallback when the error message names a cause ("greyscale") but the resolution lives in a separate doc.

**Cohort prevalence:** 1 of 7 integrations exhibits this specific document-error pattern in full (dev_k1l2). It accounts for 11 of 150 cohort calls (~7%): traces:105–109, 112–113, 115–117, 119, 132, 134, 137–138, 141, 145, 147. The pattern is structurally distinct from Finding 1 (the integration *is* POSTing) and Finding 2 (the integration is not in pending_verification — it's in an error state with an actionable requirement). I include it as a third finding rather than collapse it because the proposed change is different (it's a product-artifact gap, not a docs-flow gap).

**Trace evidence:**
- `dev_k1l2` traces:117 first surfaces `requirements.errors=[verification_document_failed_greyscale]` after a document upload (traces:116). The integration re-uploads at traces:119, gets the same error at traces:132, re-uploads again at traces:134, and from traces:137 onward issues read-only GETs annotated "cannot self-resolve document error." The integration never reaches `charges_enabled=true`.
- For context, dev_g7h8 traces:54 returns `parameter_unknown` after a POST shaped as `additional_owners=[{first_name}]` (an Accounts v1 legacy shape). The integration recovers by switching to the Persons API shape at traces:56, but only after two failed POSTs (traces:54, 55). The error code by itself did not name the shape change required.

**Product evidence:**
- The artifact tree lists "errors / error catalog" as `[no error catalog found]` — there is no `errors.md` or equivalent. Error codes are catalogued inline in `docs/persons.md:281–290` (the upload error table), which lists `verification_document_failed_greyscale` alongside ~30 other codes and gives a single shared resolution row: "The upload failed because of a problem with the file. Ask your account user to provide a new file that meets these requirements: Color image (8,000 pixels by 8,000 pixels or smaller); 10 MB or less; ..." The resolution row is correct but it is shared across all upload errors, so the specific code does not point to the specific fix.
- `sdk/stripe/_account.py:856–957` enumerates all `code` enum values for `requirements.errors` (including `verification_document_failed_greyscale` at line 911) as a flat list. The SDK exposes the code as a string but provides no enum-to-resolution mapping, so an integrator inspecting the error in code has no programmatic way to distinguish "re-upload as color" from "re-upload as larger file" from "re-upload with both sides."
- `openapi:5938–6038` (the `account_requirements_error` schema) defines `code`, `reason`, and `requirement` fields. The `reason` field is described as "An informative message that indicates the error type and provides additional details about the error" — but the traces show dev_k1l2 retrying the same shape, suggesting the `reason` string at runtime does not include the resolution ("upload a color scan, not a greyscale scan") or the integration is not surfacing it.

**Proposed change:** Add a dedicated `errors.md` or `error_catalog.md` to the product artifacts that maps each `requirements.errors.code` value to (a) the specific cause, (b) the specific resolution (e.g. "re-upload the document in color, not greyscale; greyscale scans are rejected before review"), and (c) a flag indicating whether the resolution is the same as a previous attempt (so the integration knows that re-POSTing without a real change will produce the same error). Because this requires authoring new content per error code, I'm marking the structured edit as not applyable — it is a product-content change, not a single-file edit.

```json
{
  "applyable": false,
  "reason": "Requires authoring a new error catalog file mapping each requirements.errors.code value (the enum is defined at sdk/stripe/_account.py:856–957 and openapi:5942–6037) to a specific cause/resolution pair. This is per-code content authoring with Stripe risk/compliance sign-off, not a mechanical edit of an existing file. A short-term Layer 3 mitigation would be to add a 'Common document re-upload failures' subsection to docs/persons.md near the existing upload error table at lines 281–290 that calls out greyscale/blurry/wrong-side as the three most common causes and explicitly states that re-uploading the same file will produce the same error — but the full fix is a product-artifact gap."
}
```

**How to verify:** In a follow-up cohort, the count of integrations that produce two or more consecutive `POST /v1/accounts/{account}/persons` calls with `verification[document][front]=file_*` where the previous response surfaced a `verification_document_failed_*` error in `requirements.errors` should drop. The finding fails if integrations continue to re-upload the same shape after the error catalog is published — which would suggest the integration is not reading `requirements.errors` at all (a different finding, in Layer 4) rather than misinterpreting it.


## Findings unique to funnel-researcher (1)

### Finding H2 — Per-capability requirements are a separate, undocumented gate [Layer 2] _(from funnel-researcher)_

**Claim:** The 22% capability-coupling bucket — developers polling `GET /v1/accounts/{account}/capabilities/{capability}` and seeing `status=inactive/pending` with the capability's OWN `requirements.currently_due` populated, while never re-submitting — is a distinct mechanism from Hypothesis 1. The API exposes TWO requirements hashes (`Account.requirements` at openapi spec3.yaml:5842–5910 and `Capability.requirements` at openapi spec3.yaml:5665–5733), and the SDK `Capability` class (sdk/stripe/_capability.py:194–362) only enforces this via runtime exceptions on `Capability.modify` and `Capability.retrieve` that direct callers to `account.retrieve_capability(...)` (sdk/stripe/_capability.py:401–413). The capability's `requirements` hash is reachable but invisible from the natural workflow: a developer who has cleared `Account.requirements.currently_due` reasonably believes they are done, because nothing in the Account object surfaces "but capability `card_payments` still has requirements." The funnel definition itself encodes the developer's expectation — step 5's success criterion checks only `Account.requirements.currently_due == []` — which means the funnel and the developer share the same blind spot the API has.

**Evidence:**
- openapi spec3.yaml:5665–5733 (`account_capability_requirements`): the Capability object has its own `currently_due`, `errors`, `disabled_reason`, and `current_deadline`, structurally parallel to but distinct from the Account's.
- sdk/stripe/_capability.py:401–413: `Capability.modify` and `Capability.retrieve` both raise `NotImplementedError` and require routing through `account.modify_capability(...)` / `account.retrieve_capability(...)`. This forces developers through the account-scoped API but does NOT signal that capability requirements must be read on a per-capability loop.
- docs/capabilities.md:489–528: documents that capabilities have a `requirements` hash with `currently_due` and `disabled_reason`, but frames it as something you do BEFORE requesting a capability ("Preview information requirements"). There is no symmetric instruction to inspect each requested capability's requirements AFTER submission as part of the wait-loop.
- docs/capabilities.md:431–433: "Capabilities operate independently of each other. If a connected account has both `card_payments` and `transfers`, and the `status` of either one is `inactive`, then both capabilities are disabled." This is exactly the coupling that bites, but it is buried in a "Multiple capabilities" subsection, not at the decision point where developers are checking whether onboarding is complete.
- dropoff signal: 22% of dropoffs are capability-coupling stalls with median 4 polling calls — these developers ARE checking capability status, just not realizing they need to re-submit fields from the capability's own `requirements.currently_due`.

**Proposed change:** Add a callout at the top of the "Capabilities for existing connected accounts" section in `docs/capabilities.md` explaining that capability-level `requirements.currently_due` is a separate gate that must be polled per-capability after the account's own `requirements` are cleared, with a link to `Account.retrieve_capability`.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/capabilities.md",
      "action": "insert_after",
      "at_line": 485,
      "new_content": "> #### Capability requirements are a separate gate from Account requirements\n>\n> When you request a capability (e.g. `card_payments`, `transfers`), Stripe creates a `Capability` object with its OWN `requirements` hash, distinct from `Account.requirements`. After clearing `Account.requirements.currently_due`, a requested capability can still be `inactive` or `pending` because **its own** `requirements.currently_due` is non-empty. You must:\n>\n> 1. After every account update, iterate over each requested capability via `GET /v1/accounts/{account}/capabilities/{capability}`.\n> 2. If the capability's `status` is not `active`, inspect `capability.requirements.currently_due` and `capability.requirements.errors[]` — these list capability-specific fields (often risk or compliance fields) that are NOT mirrored into `Account.requirements`.\n> 3. Submit those fields via `POST /v1/accounts/{account}` as usual, then re-poll the capability.\n>\n> A polling loop that only watches `Account.requirements.currently_due` will appear to succeed (the account looks \"done\") but `charges_enabled` will never become `true` because the underlying capability is still gated."
    }
  ]
}
```

**How to verify:** The 22% capability-coupling bucket should shrink directly. Specifically: the count of developers polling `GET /v1/accounts/{account}/capabilities/{capability}` four or more times without submitting new fields should drop substantially. Target: the 22% bucket moves below 10%, and `requirements_collected → requirements_satisfied` improves by 5–8 percentage points independently of Hypothesis 1. If the funnel's measurement is also adjusted to check per-capability `currently_due`, expect the step counts at `requirements_satisfied` to drop slightly first (the funnel becomes stricter) before recovering as developers adopt the loop.

---


## Findings unique to integration-watcher (0)

_All of this tool's findings appear in the cross-tool section above._
