# Integration findings report: stripe_connect_stall_before_charges_enabled

## Watch question

Connect platform integrations create a connected account successfully
(POST /v1/accounts returns 200) but a large fraction never reach
charges_enabled. Trace data shows the account is created, then a scatter
of GETs on the account / capabilities, partial POSTs back, and then
failures or silence — without an HTTP error in many cases. Where are
integrations getting stuck between first account creation and
charges_enabled, and what in the product surface (errors, SDK, docs,
call sequence) is producing the pattern?

## Cohort summary

- 7 developers, 150 total calls, 2026-04-15 → 2026-05-14.
- Only 1 of 7 integrations (dev_a1b2) is observed reaching `charges_enabled=true` (traces:29). The other 6 remain at `charges_enabled=false` through their entire observed window.
- Error volume is low (9 errors total across the cohort), concentrated in two developers (dev_g7h8: 4; dev_m3n4: 5). The dominant stall pattern is **success-coded silence**, not error retry: 78 of 150 calls are GET /v1/accounts/{account}, the bulk of which return `charges_enabled=false` unchanged.
- Two qualitatively distinct stall shapes appear in the traces:
  - **Pending-verification waits after requirements are cleared** (dev_a1b2 eventually flips; dev_g7h8, dev_m3n4 do not within the observed window). These poll GET /v1/accounts/{account} on multi-hour intervals.
  - **Submission never happens** — the integration creates the account, reads requirements once or twice, then polls forever without ever POSTing the requirements back (dev_c3d4, dev_e5f6, dev_i9j0). These account for the largest share of "silence without an HTTP error" in the watch question.

## Layer categorization

The dominant pattern (integration creates an account, polls, never submits requirements) sits in **Layer 4 — Integration sequence**: the API exposes `requirements.currently_due` immediately on the create response, but multiple integrations are reading it and not acting on it, then waiting for a state change that the API cannot deliver without their POST. The mechanism is reinforced by Layer 3 (the hosted-onboarding quickstart does not show the API onboarding sequence with a worked POST-requirements-back step; `docs/persons.md:22` only tells you to *listen* for events, not to act on the create response). A secondary, narrower pattern (long pending_verification waits with no fresh signal) is Layer 2/3 — the docs and SDK don't explain that `account.updated` is the only signal during pending_verification, so integrations build their own polling loops that hammer GET /v1/accounts/{account}.

## Findings

### Finding 1: Three of seven integrations create an account, read `requirements.currently_due`, and never POST any of the required fields back — they enter an indefinite GET-poll loop waiting for a state transition the API cannot make without their submission (Layer 4)

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

### Finding 2: Once `requirements.currently_due=[]` and `disabled_reason=requirements.pending_verification`, integrations have no documented signal channel and fall back to high-frequency `GET /v1/accounts/{account}` polling that returns success-coded "unchanged" responses for days (Layer 3)

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

### Finding 3: When `requirements.errors` reports a document-level failure (e.g. `verification_document_failed_greyscale`), integrations attempt to re-resolve by re-POSTing the same field shape, because the error catalog entry names the cause but not the resolution path — and there is no error catalog in the product artifacts at all (Layer 2)

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

## What this report is NOT

- These are findings, not verified product changes. Each requires applying the structured edit and re-observing traces over a follow-up cohort to confirm the pattern shifted.
- These are the strongest patterns the investigation surfaced. Other framings were considered and rejected — e.g. "developers don't know which capabilities to request" (rejected because the cohort's capability-request POSTs at traces:2, 34, 53, 105, 122 are all syntactically correct; the failure is downstream), and "rate-limiting is causing the stall" (rejected: only 1 rate_limit error in 150 calls, at traces:127, and that integration recovered immediately at traces:128).
- This report does not prescribe priority order. Finding 1 affects the largest share of the cohort (3 integrations, 38% of calls) and is the cheapest to fix; Finding 2 affects a similar number of integrations with a less clear-cut docs change; Finding 3 affects the smallest share but exposes a structural gap (no error catalog). Apply cost vs. expected lift is the operator's call.