# Pluma cross-tool report

Generated: 2026-05-16T20:45:02+00:00

Tools run:
  - funnel-researcher
  - integration-watcher

## Correlation matrix

| Tool | Layer 3 | Total |
|---|---|---|
| funnel-researcher | 3 | 3 |
| integration-watcher | 3 | 3 |

## Cross-tool findings (6)

### Cross-match 1 — Mechanical match

**Reason:** both cite `docs/hosted_vs_custom.md:49-55`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H1: The hosted-onboarding quickstart treats API onboarding as a same-shape alternative, hiding the asynchronous-verification contract that distinguishes them [Layer 3]**

**Claim:** `docs/hosted_vs_custom.md` presents Stripe-hosted, Embedded, and API onboarding as three options differing in "integration effort" and "customization," but never tells an API-onboarding-bound reader that *they* are now responsible for the verification loop that hosted onboarding handles invisibly. A developer who picks API onboarding from this comparison table walks into the `POST /v1/accounts` flow believing the contract is request/response — submit fields, get 200, done. The 14% "200-without-progress" signal (median 5 retries — the highest in the data, indicating sustained confused retrying) and the 17% "never re-checks after `pending_verification`" signal are exactly what this misconception produces: developers retrying as if the 200 is the failure surface, and never wiring `account.updated` because they don't know they need to. The information needed to disabuse them *does* exist — but it lives in `docs/persons.md` (which they'd only find if they already knew to look for verification handling), not on the page where the choice between onboarding modes is actually made.

**Evidence:**
- `docs/hosted_vs_custom.md:15-23`: The comparison table contrasts the three options on "INTEGRATION EFFORT", "CUSTOMIZATION", "AUTOMATIC UPDATES FOR NEW COMPLIANCE REQUIREMENTS", "FLOW LOGIC" — but the row "AUTOMATIC UPDATES FOR NEW COMPLIANCE REQUIREMENTS" lists API onboarding as "Requires integration changes" without any link or callout to what specifically must be built.
- `docs/hosted_vs_custom.md:49-55`: The API onboarding section states "You use the Accounts API to build an onboarding flow and handle identity verification, localization, and error handling for each country" and "We don't recommend this option unless you're committed to the operational complexity required" — but the actual operational complexity (the async webhook loop, the 200-isn't-done semantics, the capability-level requirements coupling) is not enumerated here. A reader bounces to `api-onboarding.md` (not in this artifact set) without being warned.
- `docs/persons.md:20-25` (where the actual verification loop is correctly described): "Establish a Connect webhook URL... immediately after creating an account, check the Account object's `requirements.currently_due`... Continue watching for `account.updated` event notifications to see if the `requirements` hash changes." This is the right information — but it's gated behind "Handle verification with the API," which a developer doesn't navigate to until they're already confused.
- Dropoff signal: 14% of dropoffs are `POST .../accounts/{account}` 200 with unchanged `currently_due`, with **median 5 calls** before quit. The high call count means developers are actively retrying — i.e., behaving as if the API is the diagnostic surface. That's the behavior the missing context produces.
- Dropoff signal: 17% have `disabled_reason == requirements.pending_verification` and the integration "stops listening for account.updated and never re-checks" — i.e., the webhook leg of the loop was never wired at all.

**Proposed change:** Add a callout block to the API-onboarding row of the comparison table, and a "Before you start" prerequisites paragraph immediately above the `## API onboarding` section, naming the three things API-onboarding developers must build that hosted developers don't: (1) an `account.updated` webhook handler, (2) a post-update re-read of `requirements.currently_due` (since 200 doesn't mean cleared), (3) separate handling of capability-level `requirements`. Link directly to `docs/persons.md` for each.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 48,
      "new_content": "> #### Before you choose API onboarding\n>\n> Unlike Stripe-hosted and Embedded onboarding, with API onboarding **a successful `POST /v1/accounts/{account}` response does not mean the account is enabled**. You must build three things that the hosted flows handle for you:\n>\n> 1. **A webhook handler for `account.updated`.** Stripe verifies submitted information asynchronously. You learn the outcome via [account.updated](https://docs.stripe.com/connect/handling-api-verification.md), not the POST response. See [Verification process](https://docs.stripe.com/connect/handling-api-verification.md).\n> 2. **A re-read of `Account.requirements.currently_due` after every update.** A 200 response means Stripe accepted the request, not that the requirement cleared. If you submit under-specified or wrong-shape fields, `currently_due` is unchanged and no error is returned. Compare `currently_due` before and after.\n> 3. **Separate polling of capability-level requirements.** Capabilities have their own `requirements.currently_due` (see [Capabilities API](https://docs.stripe.com/connect/account-capabilities.md#understand-capability-requirements)). An account can have `requirements.currently_due == []` while a requested capability still has outstanding requirements, leaving the capability `inactive`.\n>\n> If you cannot commit to building all three, use Embedded or Stripe-hosted onboarding instead."
    }
  ]
}
```

**How to verify:** The 14% signal (200-without-progress, median 5 calls) should drop materially; the 17% signal (no `account.updated` listener) should drop. Expect `requirements_collected → requirements_satisfied` pass rate to move from 63.4% toward the funnel's other ~85-90% step rates. If the signals don't shift, the hypothesis is that the comparison-table page isn't where developers actually make this decision (i.e., wrong locus), and the next attempt should hit `docs/accounts_overview.md` or wherever the choice is first surfaced.

**integration-watcher — F1: Developers don't POST `requirements.currently_due` back, because the API-onboarding entry point doesn't name "submit currently_due" as the loop body [Layer 3]**

**Pattern claim:** Connected accounts that the developer has not yet routed through hosted onboarding receive a populated `requirements.currently_due` on the first GET after `POST /v1/accounts`, and a subset of the cohort never POSTs those fields back. They GET the account repeatedly, observe the same `currently_due`, and abandon. The product evidence shows the explanatory paragraph is in the *capabilities* doc, not in the API-onboarding entry point developers reach first, so a developer who lands on `docs/hosted_vs_custom.md` to read about "API onboarding" never encounters the rule "your loop is: read `requirements.currently_due`, collect from the user, POST back, repeat."

**Cohort prevalence:** 2 of 7 integrations (dev_c3d4, dev_e5f6) — accounting for 41/150 calls (27%). dev_c3d4 issues 14 GETs and 0 POSTs over 6 days against a `currently_due=[business_type, representative, tos_acceptance, external_account]` that never changes. dev_e5f6 issues 22 GETs/1 re-request POST (a no-op capability re-request) without ever submitting the named `currently_due` fields (`business_profile.mcc`, `business_profile.url`, `representative`, `external_account`, `company.tax_id`).

**Trace evidence:**
- dev_c3d4 at traces:17 creates the account, traces:18 reads `currently_due=[business_type,representative,tos_acceptance,external_account]`, then traces:19, 21, 22, 24, 26, 28, 38, 43, 48, 64, 76 are all GETs returning the same unchanged `currently_due`, never a POST. traces:82 is the final GET before abandonment.
- dev_e5f6 at traces:32 creates the account, traces:35 reads `requirements.currently_due=[business_profile.mcc,business_profile.url,representative,external_account,company.tax_id]` on the card_payments capability. traces:39, 40, 42, 44, 46, 47, 51, 52, 63, 65, 69, 73, 74, 79 all poll the same capability with status `inactive unchanged (polling, no requirements submitted)`. traces:77 is a `POST /v1/accounts/{account}/capabilities/{capability}` re-requesting the capability — but `requested=true` is already true; this is the developer's misreading of "request capability" as "advance verification." traces:84 is the abandonment.

**Product evidence:**
- `docs/hosted_vs_custom.md:49-55` is the only paragraph under "API onboarding" in the entry-point doc. It says "You use the Accounts API to build an onboarding flow and handle identity verification, localization, and error handling..." but does not name the actual loop: read `requirements.currently_due`, POST those fields back. The rule appears only buried in `docs/persons.md:21-24` ("Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute... Obtain any required information from the connected account and update the `Account`") — three docs away from where these developers entered.
- `docs/capabilities.md:481` says "the `requirements` hash specifies the required information" but doesn't connect the hash to a POST loop.
- The capability-level rule that explains dev_e5f6's specific misread is at `docs/capabilities.md:13`: "The capabilities you request for a connected account determine the information you're required to collect." This text is upstream of where dev_e5f6 is in their flow; nothing in the capability-retrieval response (`docs/capabilities.md:509-524`) tells the developer "the `currently_due` on this capability is your work item."

**Proposed change:** Insert an explicit "API onboarding loop" callout into `docs/hosted_vs_custom.md` immediately after the "API onboarding" paragraph, naming the four steps: (1) `POST /v1/accounts`; (2) `GET /v1/accounts/{account}` and read `requirements.currently_due`; (3) collect those fields from the user; (4) `POST /v1/accounts/{account}` with those fields, and repeat until `currently_due` is empty. Link to `docs/persons.md` verification section.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 55,
      "new_content": "\n### The API onboarding loop\n\nIf you choose API onboarding, your integration is responsible for the verification loop. After `POST /v1/accounts` returns, the new account's `requirements.currently_due` is populated with the fields Stripe needs before `charges_enabled` can become `true`. Submitting `POST /v1/accounts` and getting `200` does **not** mean the account is enabled. Your loop is:\n\n1. `POST /v1/accounts` to create the account.\n2. `GET /v1/accounts/{account}` and read `requirements.currently_due` and (per-capability) `GET /v1/accounts/{account}/capabilities/{capability}`'s `requirements.currently_due`.\n3. Collect those fields from the connected account through your own UI.\n4. `POST /v1/accounts/{account}` (or `POST /v1/accounts/{account}/persons` for person-level fields) submitting the collected values.\n5. Repeat from step 2 until `requirements.currently_due` is empty.\n\nUntil step 5 completes, polling the account will return the same `currently_due` — Stripe is waiting for you to submit those fields, not processing them. See [Handle verification with the API](handling-api-verification.md) for the full requirement schema."
    }
  ]
}
```

**How to verify:** After this edit, follow-up cohorts should show, for API-onboarding integrations, the ratio of `POST /v1/accounts/{account}` (or `/persons`) to `GET /v1/accounts/{account}` rise from the current ~0.05 (dev_c3d4: 0/14; dev_e5f6: 1/22) to at least 0.3 within the first week of account creation. The finding is wrong if integrations continue producing >10 consecutive GETs with no POSTs against an unchanged `currently_due` — that would imply the gap is elsewhere (e.g., the developer didn't build the form UI), not in the doc.

---


### Cross-match 2 — Mechanical match

**Reason:** both cite `docs/persons.md:20-25`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H1: The hosted-onboarding quickstart treats API onboarding as a same-shape alternative, hiding the asynchronous-verification contract that distinguishes them [Layer 3]**

**Claim:** `docs/hosted_vs_custom.md` presents Stripe-hosted, Embedded, and API onboarding as three options differing in "integration effort" and "customization," but never tells an API-onboarding-bound reader that *they* are now responsible for the verification loop that hosted onboarding handles invisibly. A developer who picks API onboarding from this comparison table walks into the `POST /v1/accounts` flow believing the contract is request/response — submit fields, get 200, done. The 14% "200-without-progress" signal (median 5 retries — the highest in the data, indicating sustained confused retrying) and the 17% "never re-checks after `pending_verification`" signal are exactly what this misconception produces: developers retrying as if the 200 is the failure surface, and never wiring `account.updated` because they don't know they need to. The information needed to disabuse them *does* exist — but it lives in `docs/persons.md` (which they'd only find if they already knew to look for verification handling), not on the page where the choice between onboarding modes is actually made.

**Evidence:**
- `docs/hosted_vs_custom.md:15-23`: The comparison table contrasts the three options on "INTEGRATION EFFORT", "CUSTOMIZATION", "AUTOMATIC UPDATES FOR NEW COMPLIANCE REQUIREMENTS", "FLOW LOGIC" — but the row "AUTOMATIC UPDATES FOR NEW COMPLIANCE REQUIREMENTS" lists API onboarding as "Requires integration changes" without any link or callout to what specifically must be built.
- `docs/hosted_vs_custom.md:49-55`: The API onboarding section states "You use the Accounts API to build an onboarding flow and handle identity verification, localization, and error handling for each country" and "We don't recommend this option unless you're committed to the operational complexity required" — but the actual operational complexity (the async webhook loop, the 200-isn't-done semantics, the capability-level requirements coupling) is not enumerated here. A reader bounces to `api-onboarding.md` (not in this artifact set) without being warned.
- `docs/persons.md:20-25` (where the actual verification loop is correctly described): "Establish a Connect webhook URL... immediately after creating an account, check the Account object's `requirements.currently_due`... Continue watching for `account.updated` event notifications to see if the `requirements` hash changes." This is the right information — but it's gated behind "Handle verification with the API," which a developer doesn't navigate to until they're already confused.
- Dropoff signal: 14% of dropoffs are `POST .../accounts/{account}` 200 with unchanged `currently_due`, with **median 5 calls** before quit. The high call count means developers are actively retrying — i.e., behaving as if the API is the diagnostic surface. That's the behavior the missing context produces.
- Dropoff signal: 17% have `disabled_reason == requirements.pending_verification` and the integration "stops listening for account.updated and never re-checks" — i.e., the webhook leg of the loop was never wired at all.

**Proposed change:** Add a callout block to the API-onboarding row of the comparison table, and a "Before you start" prerequisites paragraph immediately above the `## API onboarding` section, naming the three things API-onboarding developers must build that hosted developers don't: (1) an `account.updated` webhook handler, (2) a post-update re-read of `requirements.currently_due` (since 200 doesn't mean cleared), (3) separate handling of capability-level `requirements`. Link directly to `docs/persons.md` for each.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 48,
      "new_content": "> #### Before you choose API onboarding\n>\n> Unlike Stripe-hosted and Embedded onboarding, with API onboarding **a successful `POST /v1/accounts/{account}` response does not mean the account is enabled**. You must build three things that the hosted flows handle for you:\n>\n> 1. **A webhook handler for `account.updated`.** Stripe verifies submitted information asynchronously. You learn the outcome via [account.updated](https://docs.stripe.com/connect/handling-api-verification.md), not the POST response. See [Verification process](https://docs.stripe.com/connect/handling-api-verification.md).\n> 2. **A re-read of `Account.requirements.currently_due` after every update.** A 200 response means Stripe accepted the request, not that the requirement cleared. If you submit under-specified or wrong-shape fields, `currently_due` is unchanged and no error is returned. Compare `currently_due` before and after.\n> 3. **Separate polling of capability-level requirements.** Capabilities have their own `requirements.currently_due` (see [Capabilities API](https://docs.stripe.com/connect/account-capabilities.md#understand-capability-requirements)). An account can have `requirements.currently_due == []` while a requested capability still has outstanding requirements, leaving the capability `inactive`.\n>\n> If you cannot commit to building all three, use Embedded or Stripe-hosted onboarding instead."
    }
  ]
}
```

**How to verify:** The 14% signal (200-without-progress, median 5 calls) should drop materially; the 17% signal (no `account.updated` listener) should drop. Expect `requirements_collected → requirements_satisfied` pass rate to move from 63.4% toward the funnel's other ~85-90% step rates. If the signals don't shift, the hypothesis is that the comparison-table page isn't where developers actually make this decision (i.e., wrong locus), and the next attempt should hit `docs/accounts_overview.md` or wherever the choice is first surfaced.

**integration-watcher — F2: Developers poll on hour-scale cadences and treat `disabled_reason=requirements.pending_verification` as an unresolved error, because the docs name `account.updated` only in passing and the catalog entry for `requirements.pending_verification` doesn't say "stop polling; wait for the webhook" [Layer 3]**

**Pattern claim:** Once `requirements.currently_due` becomes empty and `disabled_reason` transitions to `requirements.pending_verification`, integrations should stop synchronously polling and subscribe to `account.updated`. Instead, three integrations in the cohort enter long-running polling loops on hour-to-day cadences, treating `pending_verification` as a problem to debug rather than an async state to wait on. The mechanism: the error catalog at `errors.md:120` describes `pending_verification` as a state but doesn't tell developers what to do, and the only `account.updated` mention they could have reached (`docs/persons.md:22`) is buried in the verification doc, not in the catalog entry or in the hosted_vs_custom entry point.

**Cohort prevalence:** 3 of 7 integrations (dev_a1b2, dev_g7h8, dev_m3n4) — accounting for the post-cleared-requirements polling portion of their traces, ~35/150 calls (23%). All three eventually-or-never reach `charges_enabled`: dev_a1b2 does (line 29), dev_g7h8 and dev_m3n4 do not within the window.

**Trace evidence:**
- dev_a1b2 at traces:10 reaches `currently_due=[] disabled_reason=requirements.pending_verification` and then issues 7 GETs annotated "account.updated webhook poll" at 2h/3h/4h/5h/6h/7h/3h intervals (traces:11–16, 23, 25) before finally observing `charges_enabled=true` at traces:29 — 60 hours later. The "webhook poll" annotation reveals the developer believes they are emulating a webhook with GETs rather than receiving one.
- dev_g7h8 at traces:68 reaches `currently_due=[] disabled_reason=requirements.pending_verification`, then issues 10 GETs (traces:72, 75, 78, 81, 83, 85, 95, 98, 100, 110) over 6 days, never observing the state change.
- dev_m3n4 at traces:131 reaches `currently_due=[] disabled_reason=requirements.pending_verification`, then issues 9 GETs (traces:133, 135, 139, 140, 143, 144, 146, 148, 150) over 7 days, eventually abandoning monitoring at traces:150.

**Product evidence:**
- `errors.md:120` describes the value: "Stripe is currently verifying submitted information. No action required. Inspect the `requirements.pending_verification` array to see the information being verified." This is the closest thing to guidance the developer encounters when they look up what `requirements.pending_verification` means, and it doesn't tell them how to find out when verification completes.
- `docs/persons.md:22` introduces the affordance: "Establish a [Connect webhook](https://docs.stripe.com/connect/webhooks.md) URL... to watch for activity, especially `account.updated` events." But this is a sub-bullet inside the verification-process section, not in the "I just got `pending_verification`, what now?" path.
- `docs/hosted_vs_custom.md:355` does say "listen to the `account.updated` event sent to your webhook endpoint" — but in the *hosted* onboarding context, paragraph 8 of a long doc, not the API-onboarding section.
- `sdk/stripe/_account.py:1503` exposes the `requirements: Optional[Requirements]` field but the SDK signature doesn't surface that this is an async-changing field; the developer has no programmatic signal that "poll" is the wrong primitive.

**Proposed change:** Update the `requirements.pending_verification` row in `errors.md` to explicitly direct developers to the `account.updated` webhook and discourage synchronous polling. Make the change in the layer-3a catalog because that's where developers go when they want to understand what they're seeing.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "errors.md",
      "action": "replace",
      "from_line_start": 120,
      "from_line_end": 120,
      "expected_content": "| `requirements.pending_verification` | Stripe is currently verifying submitted information. No action required. | Inspect `requirements.pending_verification`; wait for `account.updated`. | https://docs.stripe.com/connect/handling-api-verification.md |",
      "new_content": "| `requirements.pending_verification` | Stripe is currently verifying submitted information. The `Account` is in a terminal-for-your-integration state: there is no further request you can issue that will advance verification. Verification typically completes within minutes but can take several business days. | Subscribe to the `account.updated` webhook (see [webhooks](https://docs.stripe.com/connect/webhooks.md)) and respond when `charges_enabled` flips to `true`. Do **not** poll `GET /v1/accounts/{account}` on a tight loop — polling does not advance verification and produces no new information. Inspect `requirements.pending_verification` only to learn which fields Stripe is currently checking. | https://docs.stripe.com/connect/handling-api-verification.md |"
    }
  ]
}
```

**How to verify:** After this edit, follow-up cohorts in the same `pending_verification` state should issue at most 2 GETs on `/v1/accounts/{account}` before the next `account.updated`-driven event (vs. the current 7–10 GETs/integration). The finding is wrong about the mechanism if developers continue polling >5 times against `pending_verification` after the edit — that would suggest they don't have webhook infrastructure available and the real fix is in setup tooling, not catalog wording.

---


### Cross-match 3 — Mechanical match

**Reason:** both cite `docs/capabilities.md:487-528`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H2: `docs/capabilities.md` documents the capability→requirements expansion forward-only, leaving developers unable to diagnose a capability stuck `inactive` after `Account.requirements.currently_due == []` [Layer 3]**

**Claim:** The 22% signal (capability remains `inactive`/`pending` with its *own* `requirements.currently_due` populated, developer polls but never submits the new requirements) corresponds exactly to a documentation gap: `docs/capabilities.md` thoroughly explains that requesting a capability *expands* the requirement set, but it does not document the reverse diagnostic — "if your account-level requirements are clear and the capability is still inactive, the missing fields live on the capability object, not the account object." The dropoff data shows median 4 calls to `GET .../capabilities/{capability}` before quit, which means these developers found the capability endpoint and looked at it — but the schema response they see (`requirements.currently_due: [...]`) does not, in the docs, get connected to a corresponding action ("submit these via `POST /v1/accounts/{account}`"). The two endpoints (read capability requirements, write to account) are documented but never bridged at the moment a developer is staring at the GET response.

**Evidence:**
- `docs/capabilities.md:487-528`: The "Understand capability requirements" and "Preview information requirements" sections show the GET response with `requirements.currently_due: ["company.tax_id", ...]` but do not state what endpoint a developer calls to *submit* those fields. The reader is left to infer that capability requirements are cleared by `POST /v1/accounts/{account}` (the same endpoint as account-level requirements), which is not obvious from the response shape.
- `docs/capabilities.md:530-545`: The "Request and unrequest capabilities" section follows immediately and only describes setting `requested=true/false` — reinforcing the (wrong) inference that the capability endpoint is where capability requirements are also submitted.
- `sdk/stripe/_capability.py:391-413`: The SDK explicitly raises `NotImplementedError` when developers try to modify a capability directly: `"Can't update a capability without an account ID. Update a capability using account.modify_capability('acct_123', 'acap_123', params)"`. But `modify_capability` only updates `requested` — it doesn't accept the requirement fields. A developer following the error message lands on a method that can't satisfy what they're trying to do.
- Dropoff signal: 22% of dropoffs with `capability.requirements.currently_due` populated, developer polling GET on the capability without submitting — median 4 calls. The polling behavior is diagnostic: they know where to *look*, they don't know where to *write*.
- Qualitative: changelog signal — "risk requirements added to the Capabilities API" — confirms this surface is recently expanded, increasing the likelihood the docs lag the behavior.

**Proposed change:** Add a bridging paragraph in the capabilities doc that, immediately after the GET response example, explicitly tells the developer "submit these fields via `POST /v1/accounts/{account}` with the field names from `currently_due`; capability requirements clear when the underlying account fields are accepted and verified."

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/capabilities.md",
      "action": "insert_after",
      "at_line": 528,
      "new_content": "> #### How to clear capability requirements\n>\n> The fields listed in a capability's `requirements.currently_due` are submitted via [`POST /v1/accounts/{account}`](https://docs.stripe.com/api/accounts/update.md) — **not** by writing to the capability endpoint. The capability object is read-only for requirements; only the account-level update endpoint accepts field values.\n>\n> For example, if `card_payments.requirements.currently_due` contains `[\"company.tax_id\"]`, you clear it by:\n>\n> ```curl\n> curl https://api.stripe.com/v1/accounts/{{CONNECTED_ACCOUNT_ID}} \\\n>   -u \"<<YOUR_SECRET_KEY>>:\" \\\n>   -d \"company[tax_id]=000000000\"\n> ```\n>\n> After the POST returns 200, the capability requirement is **not** immediately cleared — Stripe verifies asynchronously. Listen for `account.updated`, then re-fetch the capability to confirm `currently_due` is empty and `status` has moved to `active`. Note that `Account.requirements.currently_due` can be `[]` while a requested capability still has its own outstanding requirements; check both."
    }
  ]
}
```

**How to verify:** The 22% capability-stuck signal should drop. The downstream `requirements_satisfied → charges_enabled` pass rate (already 85%) should also tick up slightly, since some capability-inactive accounts currently making it past `requirements_satisfied` (account-level cleared, capability not) stall at `charges_enabled`. If the signal doesn't move, the next hypothesis is that developers aren't reading `docs/capabilities.md` at all when stuck, and the bridging copy needs to live on the error/response surface itself (which would be a Layer 2 fix, not Layer 3).

**integration-watcher — F1: Developers don't POST `requirements.currently_due` back, because the API-onboarding entry point doesn't name "submit currently_due" as the loop body [Layer 3]**

**Pattern claim:** Connected accounts that the developer has not yet routed through hosted onboarding receive a populated `requirements.currently_due` on the first GET after `POST /v1/accounts`, and a subset of the cohort never POSTs those fields back. They GET the account repeatedly, observe the same `currently_due`, and abandon. The product evidence shows the explanatory paragraph is in the *capabilities* doc, not in the API-onboarding entry point developers reach first, so a developer who lands on `docs/hosted_vs_custom.md` to read about "API onboarding" never encounters the rule "your loop is: read `requirements.currently_due`, collect from the user, POST back, repeat."

**Cohort prevalence:** 2 of 7 integrations (dev_c3d4, dev_e5f6) — accounting for 41/150 calls (27%). dev_c3d4 issues 14 GETs and 0 POSTs over 6 days against a `currently_due=[business_type, representative, tos_acceptance, external_account]` that never changes. dev_e5f6 issues 22 GETs/1 re-request POST (a no-op capability re-request) without ever submitting the named `currently_due` fields (`business_profile.mcc`, `business_profile.url`, `representative`, `external_account`, `company.tax_id`).

**Trace evidence:**
- dev_c3d4 at traces:17 creates the account, traces:18 reads `currently_due=[business_type,representative,tos_acceptance,external_account]`, then traces:19, 21, 22, 24, 26, 28, 38, 43, 48, 64, 76 are all GETs returning the same unchanged `currently_due`, never a POST. traces:82 is the final GET before abandonment.
- dev_e5f6 at traces:32 creates the account, traces:35 reads `requirements.currently_due=[business_profile.mcc,business_profile.url,representative,external_account,company.tax_id]` on the card_payments capability. traces:39, 40, 42, 44, 46, 47, 51, 52, 63, 65, 69, 73, 74, 79 all poll the same capability with status `inactive unchanged (polling, no requirements submitted)`. traces:77 is a `POST /v1/accounts/{account}/capabilities/{capability}` re-requesting the capability — but `requested=true` is already true; this is the developer's misreading of "request capability" as "advance verification." traces:84 is the abandonment.

**Product evidence:**
- `docs/hosted_vs_custom.md:49-55` is the only paragraph under "API onboarding" in the entry-point doc. It says "You use the Accounts API to build an onboarding flow and handle identity verification, localization, and error handling..." but does not name the actual loop: read `requirements.currently_due`, POST those fields back. The rule appears only buried in `docs/persons.md:21-24` ("Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute... Obtain any required information from the connected account and update the `Account`") — three docs away from where these developers entered.
- `docs/capabilities.md:481` says "the `requirements` hash specifies the required information" but doesn't connect the hash to a POST loop.
- The capability-level rule that explains dev_e5f6's specific misread is at `docs/capabilities.md:13`: "The capabilities you request for a connected account determine the information you're required to collect." This text is upstream of where dev_e5f6 is in their flow; nothing in the capability-retrieval response (`docs/capabilities.md:509-524`) tells the developer "the `currently_due` on this capability is your work item."

**Proposed change:** Insert an explicit "API onboarding loop" callout into `docs/hosted_vs_custom.md` immediately after the "API onboarding" paragraph, naming the four steps: (1) `POST /v1/accounts`; (2) `GET /v1/accounts/{account}` and read `requirements.currently_due`; (3) collect those fields from the user; (4) `POST /v1/accounts/{account}` with those fields, and repeat until `currently_due` is empty. Link to `docs/persons.md` verification section.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 55,
      "new_content": "\n### The API onboarding loop\n\nIf you choose API onboarding, your integration is responsible for the verification loop. After `POST /v1/accounts` returns, the new account's `requirements.currently_due` is populated with the fields Stripe needs before `charges_enabled` can become `true`. Submitting `POST /v1/accounts` and getting `200` does **not** mean the account is enabled. Your loop is:\n\n1. `POST /v1/accounts` to create the account.\n2. `GET /v1/accounts/{account}` and read `requirements.currently_due` and (per-capability) `GET /v1/accounts/{account}/capabilities/{capability}`'s `requirements.currently_due`.\n3. Collect those fields from the connected account through your own UI.\n4. `POST /v1/accounts/{account}` (or `POST /v1/accounts/{account}/persons` for person-level fields) submitting the collected values.\n5. Repeat from step 2 until `requirements.currently_due` is empty.\n\nUntil step 5 completes, polling the account will return the same `currently_due` — Stripe is waiting for you to submit those fields, not processing them. See [Handle verification with the API](handling-api-verification.md) for the full requirement schema."
    }
  ]
}
```

**How to verify:** After this edit, follow-up cohorts should show, for API-onboarding integrations, the ratio of `POST /v1/accounts/{account}` (or `/persons`) to `GET /v1/accounts/{account}` rise from the current ~0.05 (dev_c3d4: 0/14; dev_e5f6: 1/22) to at least 0.3 within the first week of account creation. The finding is wrong if integrations continue producing >10 consecutive GETs with no POSTs against an unchanged `currently_due` — that would imply the gap is elsewhere (e.g., the developer didn't build the form UI), not in the doc.

---


### Cross-match 4 — Mechanical match

**Reason:** both cite `docs/persons.md:22-24`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: The error catalog's Layer 3a/3b structure correctly documents that verification state is data-on-the-object, but no surface tells the developer this *at the moment they expect an exception*, producing the 34% silent-abandonment signal [Layer 3]**

**Claim:** `errors.md` does an unusually good job of explaining that Layer 3 verification state is **not** an SDK exception — it's lines 186-187 say "Layer 3 verification state is **not** an exception — it's data on a successfully returned object, so `try/except` never fires for it. This is a primary onboarding confusion." Stripe's own catalog identifies this exact confusion. But the artifact this warning lives in — a flat error catalog — is the one a developer reads only after they suspect an error. The 34% silent-abandonment signal (median 3 calls before quitting; `currently_due` non-empty 7+ days after last POST, no further API calls) is the behavioral fingerprint of a developer who *doesn't suspect an error*: they got a 200, they're done from their perspective, and they walk away. The warning is correctly placed for someone debugging; it is misplaced for someone succeeding-on-paper. The fix is to surface the same warning where the developer first executes the POST — `docs/hosted_vs_custom.md` (covered by Hypothesis 1) and `docs/persons.md` near the response-handling guidance.

**Evidence:**
- `errors.md:8-15`: The error catalog opens by saying "Layer 3 is the one most developers don't anticipate: the API returns `200`, the `Account` object exists, and `charges_enabled` is still `false`." This is Stripe's own diagnosis.
- `errors.md:186-187` (in the SDK exception classes section): "Note: Layer 3 verification state is **not** an exception — it's data on a successfully returned object, so `try/except` never fires for it. This is a primary onboarding confusion."
- `docs/persons.md:22-24`: The correct loop *is* documented here — "Establish a Connect webhook URL... Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute for additional requirements... Continue watching for `account.updated` event notifications" — but a developer who got a 200 on `POST /v1/accounts/{account}` has no reason to navigate to a doc titled "Handle verification with the API."
- Dropoff signal: 34% of all dropoffs at this step, median 3 calls, **no further API activity** — the developer believes they are done. This is not retry-confusion (that's the 14% signal); this is "I shipped it, why isn't it working in a week."
- The signal is the largest single contributor to dropoff (34% × 36.6% step failure = ~12% of the cohort), making this the highest-leverage fix.

**Proposed change:** Add a "After POST: confirm the requirement actually cleared" subsection at the top of the verification-process section in `docs/persons.md`, restating in positive form what `errors.md` says in diagnostic form: that 200 is acceptance-of-request, not confirmation-of-clearance, and giving the developer the exact code-shape to re-read after every POST.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/persons.md",
      "action": "insert_after",
      "at_line": 11,
      "new_content": "> #### A 200 from `POST /v1/accounts/{account}` does not mean the account is verified\n>\n> The most common cause of a Connect integration that \"looks done\" but never produces `charges_enabled = true` is treating the 200 response from `POST /v1/accounts/{account}` as the success signal. It is not. The 200 means Stripe accepted your request shape. Verification runs asynchronously after the response returns.\n>\n> After **every** `POST /v1/accounts/{account}`, you must:\n>\n> 1. Re-fetch the account: `GET /v1/accounts/{account}`.\n> 2. Check whether `requirements.currently_due` is empty. If it is unchanged from before the POST, the fields you submitted did not match what Stripe needed — inspect `requirements.errors[]` for the specific reason.\n> 3. Check `requirements.disabled_reason`. If it is `requirements.pending_verification`, Stripe is still verifying; you will receive an `account.updated` webhook with the outcome. **Do not poll** — wire the webhook.\n> 4. For each requested capability, also `GET /v1/accounts/{account}/capabilities/{capability}` and check **its** `requirements.currently_due` separately. A capability can have outstanding requirements even when the account does not.\n>\n> If `requirements.currently_due` is non-empty 24 hours after your last update and `requirements.errors[]` is empty, your integration is not progressing — it is silently stalled, not waiting on Stripe. Re-inspect the fields you submitted against `requirements.currently_due` exactly."
    }
  ]
}
```

**How to verify:** The 34% silent-abandonment signal should drop substantially. Specifically, the `median_developer_calls_before_quit` for that signal should rise (currently 3) — developers who used to quit silently should instead either call more (because they now know to GET-after-POST) or progress. If the median calls rises but the abandonment percentage stays high, the copy is being read but not understood — that would suggest a Layer 2 change is needed (e.g., a `requirements_changed` flag in the POST response itself), which is out of scope for an applyable doc edit.

**integration-watcher — F1: Developers don't POST `requirements.currently_due` back, because the API-onboarding entry point doesn't name "submit currently_due" as the loop body [Layer 3]**

**Pattern claim:** Connected accounts that the developer has not yet routed through hosted onboarding receive a populated `requirements.currently_due` on the first GET after `POST /v1/accounts`, and a subset of the cohort never POSTs those fields back. They GET the account repeatedly, observe the same `currently_due`, and abandon. The product evidence shows the explanatory paragraph is in the *capabilities* doc, not in the API-onboarding entry point developers reach first, so a developer who lands on `docs/hosted_vs_custom.md` to read about "API onboarding" never encounters the rule "your loop is: read `requirements.currently_due`, collect from the user, POST back, repeat."

**Cohort prevalence:** 2 of 7 integrations (dev_c3d4, dev_e5f6) — accounting for 41/150 calls (27%). dev_c3d4 issues 14 GETs and 0 POSTs over 6 days against a `currently_due=[business_type, representative, tos_acceptance, external_account]` that never changes. dev_e5f6 issues 22 GETs/1 re-request POST (a no-op capability re-request) without ever submitting the named `currently_due` fields (`business_profile.mcc`, `business_profile.url`, `representative`, `external_account`, `company.tax_id`).

**Trace evidence:**
- dev_c3d4 at traces:17 creates the account, traces:18 reads `currently_due=[business_type,representative,tos_acceptance,external_account]`, then traces:19, 21, 22, 24, 26, 28, 38, 43, 48, 64, 76 are all GETs returning the same unchanged `currently_due`, never a POST. traces:82 is the final GET before abandonment.
- dev_e5f6 at traces:32 creates the account, traces:35 reads `requirements.currently_due=[business_profile.mcc,business_profile.url,representative,external_account,company.tax_id]` on the card_payments capability. traces:39, 40, 42, 44, 46, 47, 51, 52, 63, 65, 69, 73, 74, 79 all poll the same capability with status `inactive unchanged (polling, no requirements submitted)`. traces:77 is a `POST /v1/accounts/{account}/capabilities/{capability}` re-requesting the capability — but `requested=true` is already true; this is the developer's misreading of "request capability" as "advance verification." traces:84 is the abandonment.

**Product evidence:**
- `docs/hosted_vs_custom.md:49-55` is the only paragraph under "API onboarding" in the entry-point doc. It says "You use the Accounts API to build an onboarding flow and handle identity verification, localization, and error handling..." but does not name the actual loop: read `requirements.currently_due`, POST those fields back. The rule appears only buried in `docs/persons.md:21-24` ("Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute... Obtain any required information from the connected account and update the `Account`") — three docs away from where these developers entered.
- `docs/capabilities.md:481` says "the `requirements` hash specifies the required information" but doesn't connect the hash to a POST loop.
- The capability-level rule that explains dev_e5f6's specific misread is at `docs/capabilities.md:13`: "The capabilities you request for a connected account determine the information you're required to collect." This text is upstream of where dev_e5f6 is in their flow; nothing in the capability-retrieval response (`docs/capabilities.md:509-524`) tells the developer "the `currently_due` on this capability is your work item."

**Proposed change:** Insert an explicit "API onboarding loop" callout into `docs/hosted_vs_custom.md` immediately after the "API onboarding" paragraph, naming the four steps: (1) `POST /v1/accounts`; (2) `GET /v1/accounts/{account}` and read `requirements.currently_due`; (3) collect those fields from the user; (4) `POST /v1/accounts/{account}` with those fields, and repeat until `currently_due` is empty. Link to `docs/persons.md` verification section.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/hosted_vs_custom.md",
      "action": "insert_after",
      "at_line": 55,
      "new_content": "\n### The API onboarding loop\n\nIf you choose API onboarding, your integration is responsible for the verification loop. After `POST /v1/accounts` returns, the new account's `requirements.currently_due` is populated with the fields Stripe needs before `charges_enabled` can become `true`. Submitting `POST /v1/accounts` and getting `200` does **not** mean the account is enabled. Your loop is:\n\n1. `POST /v1/accounts` to create the account.\n2. `GET /v1/accounts/{account}` and read `requirements.currently_due` and (per-capability) `GET /v1/accounts/{account}/capabilities/{capability}`'s `requirements.currently_due`.\n3. Collect those fields from the connected account through your own UI.\n4. `POST /v1/accounts/{account}` (or `POST /v1/accounts/{account}/persons` for person-level fields) submitting the collected values.\n5. Repeat from step 2 until `requirements.currently_due` is empty.\n\nUntil step 5 completes, polling the account will return the same `currently_due` — Stripe is waiting for you to submit those fields, not processing them. See [Handle verification with the API](handling-api-verification.md) for the full requirement schema."
    }
  ]
}
```

**How to verify:** After this edit, follow-up cohorts should show, for API-onboarding integrations, the ratio of `POST /v1/accounts/{account}` (or `/persons`) to `GET /v1/accounts/{account}` rise from the current ~0.05 (dev_c3d4: 0/14; dev_e5f6: 1/22) to at least 0.3 within the first week of account creation. The finding is wrong if integrations continue producing >10 consecutive GETs with no POSTs against an unchanged `currently_due` — that would imply the gap is elsewhere (e.g., the developer didn't build the form UI), not in the doc.

---


### Cross-match 5 — Mechanical match

**Reason:** both cite `docs/persons.md:22-24`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: The error catalog's Layer 3a/3b structure correctly documents that verification state is data-on-the-object, but no surface tells the developer this *at the moment they expect an exception*, producing the 34% silent-abandonment signal [Layer 3]**

**Claim:** `errors.md` does an unusually good job of explaining that Layer 3 verification state is **not** an SDK exception — it's lines 186-187 say "Layer 3 verification state is **not** an exception — it's data on a successfully returned object, so `try/except` never fires for it. This is a primary onboarding confusion." Stripe's own catalog identifies this exact confusion. But the artifact this warning lives in — a flat error catalog — is the one a developer reads only after they suspect an error. The 34% silent-abandonment signal (median 3 calls before quitting; `currently_due` non-empty 7+ days after last POST, no further API calls) is the behavioral fingerprint of a developer who *doesn't suspect an error*: they got a 200, they're done from their perspective, and they walk away. The warning is correctly placed for someone debugging; it is misplaced for someone succeeding-on-paper. The fix is to surface the same warning where the developer first executes the POST — `docs/hosted_vs_custom.md` (covered by Hypothesis 1) and `docs/persons.md` near the response-handling guidance.

**Evidence:**
- `errors.md:8-15`: The error catalog opens by saying "Layer 3 is the one most developers don't anticipate: the API returns `200`, the `Account` object exists, and `charges_enabled` is still `false`." This is Stripe's own diagnosis.
- `errors.md:186-187` (in the SDK exception classes section): "Note: Layer 3 verification state is **not** an exception — it's data on a successfully returned object, so `try/except` never fires for it. This is a primary onboarding confusion."
- `docs/persons.md:22-24`: The correct loop *is* documented here — "Establish a Connect webhook URL... Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute for additional requirements... Continue watching for `account.updated` event notifications" — but a developer who got a 200 on `POST /v1/accounts/{account}` has no reason to navigate to a doc titled "Handle verification with the API."
- Dropoff signal: 34% of all dropoffs at this step, median 3 calls, **no further API activity** — the developer believes they are done. This is not retry-confusion (that's the 14% signal); this is "I shipped it, why isn't it working in a week."
- The signal is the largest single contributor to dropoff (34% × 36.6% step failure = ~12% of the cohort), making this the highest-leverage fix.

**Proposed change:** Add a "After POST: confirm the requirement actually cleared" subsection at the top of the verification-process section in `docs/persons.md`, restating in positive form what `errors.md` says in diagnostic form: that 200 is acceptance-of-request, not confirmation-of-clearance, and giving the developer the exact code-shape to re-read after every POST.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/persons.md",
      "action": "insert_after",
      "at_line": 11,
      "new_content": "> #### A 200 from `POST /v1/accounts/{account}` does not mean the account is verified\n>\n> The most common cause of a Connect integration that \"looks done\" but never produces `charges_enabled = true` is treating the 200 response from `POST /v1/accounts/{account}` as the success signal. It is not. The 200 means Stripe accepted your request shape. Verification runs asynchronously after the response returns.\n>\n> After **every** `POST /v1/accounts/{account}`, you must:\n>\n> 1. Re-fetch the account: `GET /v1/accounts/{account}`.\n> 2. Check whether `requirements.currently_due` is empty. If it is unchanged from before the POST, the fields you submitted did not match what Stripe needed — inspect `requirements.errors[]` for the specific reason.\n> 3. Check `requirements.disabled_reason`. If it is `requirements.pending_verification`, Stripe is still verifying; you will receive an `account.updated` webhook with the outcome. **Do not poll** — wire the webhook.\n> 4. For each requested capability, also `GET /v1/accounts/{account}/capabilities/{capability}` and check **its** `requirements.currently_due` separately. A capability can have outstanding requirements even when the account does not.\n>\n> If `requirements.currently_due` is non-empty 24 hours after your last update and `requirements.errors[]` is empty, your integration is not progressing — it is silently stalled, not waiting on Stripe. Re-inspect the fields you submitted against `requirements.currently_due` exactly."
    }
  ]
}
```

**How to verify:** The 34% silent-abandonment signal should drop substantially. Specifically, the `median_developer_calls_before_quit` for that signal should rise (currently 3) — developers who used to quit silently should instead either call more (because they now know to GET-after-POST) or progress. If the median calls rises but the abandonment percentage stays high, the copy is being read but not understood — that would suggest a Layer 2 change is needed (e.g., a `requirements_changed` flag in the POST response itself), which is out of scope for an applyable doc edit.

**integration-watcher — F2: Developers poll on hour-scale cadences and treat `disabled_reason=requirements.pending_verification` as an unresolved error, because the docs name `account.updated` only in passing and the catalog entry for `requirements.pending_verification` doesn't say "stop polling; wait for the webhook" [Layer 3]**

**Pattern claim:** Once `requirements.currently_due` becomes empty and `disabled_reason` transitions to `requirements.pending_verification`, integrations should stop synchronously polling and subscribe to `account.updated`. Instead, three integrations in the cohort enter long-running polling loops on hour-to-day cadences, treating `pending_verification` as a problem to debug rather than an async state to wait on. The mechanism: the error catalog at `errors.md:120` describes `pending_verification` as a state but doesn't tell developers what to do, and the only `account.updated` mention they could have reached (`docs/persons.md:22`) is buried in the verification doc, not in the catalog entry or in the hosted_vs_custom entry point.

**Cohort prevalence:** 3 of 7 integrations (dev_a1b2, dev_g7h8, dev_m3n4) — accounting for the post-cleared-requirements polling portion of their traces, ~35/150 calls (23%). All three eventually-or-never reach `charges_enabled`: dev_a1b2 does (line 29), dev_g7h8 and dev_m3n4 do not within the window.

**Trace evidence:**
- dev_a1b2 at traces:10 reaches `currently_due=[] disabled_reason=requirements.pending_verification` and then issues 7 GETs annotated "account.updated webhook poll" at 2h/3h/4h/5h/6h/7h/3h intervals (traces:11–16, 23, 25) before finally observing `charges_enabled=true` at traces:29 — 60 hours later. The "webhook poll" annotation reveals the developer believes they are emulating a webhook with GETs rather than receiving one.
- dev_g7h8 at traces:68 reaches `currently_due=[] disabled_reason=requirements.pending_verification`, then issues 10 GETs (traces:72, 75, 78, 81, 83, 85, 95, 98, 100, 110) over 6 days, never observing the state change.
- dev_m3n4 at traces:131 reaches `currently_due=[] disabled_reason=requirements.pending_verification`, then issues 9 GETs (traces:133, 135, 139, 140, 143, 144, 146, 148, 150) over 7 days, eventually abandoning monitoring at traces:150.

**Product evidence:**
- `errors.md:120` describes the value: "Stripe is currently verifying submitted information. No action required. Inspect the `requirements.pending_verification` array to see the information being verified." This is the closest thing to guidance the developer encounters when they look up what `requirements.pending_verification` means, and it doesn't tell them how to find out when verification completes.
- `docs/persons.md:22` introduces the affordance: "Establish a [Connect webhook](https://docs.stripe.com/connect/webhooks.md) URL... to watch for activity, especially `account.updated` events." But this is a sub-bullet inside the verification-process section, not in the "I just got `pending_verification`, what now?" path.
- `docs/hosted_vs_custom.md:355` does say "listen to the `account.updated` event sent to your webhook endpoint" — but in the *hosted* onboarding context, paragraph 8 of a long doc, not the API-onboarding section.
- `sdk/stripe/_account.py:1503` exposes the `requirements: Optional[Requirements]` field but the SDK signature doesn't surface that this is an async-changing field; the developer has no programmatic signal that "poll" is the wrong primitive.

**Proposed change:** Update the `requirements.pending_verification` row in `errors.md` to explicitly direct developers to the `account.updated` webhook and discourage synchronous polling. Make the change in the layer-3a catalog because that's where developers go when they want to understand what they're seeing.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "errors.md",
      "action": "replace",
      "from_line_start": 120,
      "from_line_end": 120,
      "expected_content": "| `requirements.pending_verification` | Stripe is currently verifying submitted information. No action required. | Inspect `requirements.pending_verification`; wait for `account.updated`. | https://docs.stripe.com/connect/handling-api-verification.md |",
      "new_content": "| `requirements.pending_verification` | Stripe is currently verifying submitted information. The `Account` is in a terminal-for-your-integration state: there is no further request you can issue that will advance verification. Verification typically completes within minutes but can take several business days. | Subscribe to the `account.updated` webhook (see [webhooks](https://docs.stripe.com/connect/webhooks.md)) and respond when `charges_enabled` flips to `true`. Do **not** poll `GET /v1/accounts/{account}` on a tight loop — polling does not advance verification and produces no new information. Inspect `requirements.pending_verification` only to learn which fields Stripe is currently checking. | https://docs.stripe.com/connect/handling-api-verification.md |"
    }
  ]
}
```

**How to verify:** After this edit, follow-up cohorts in the same `pending_verification` state should issue at most 2 GETs on `/v1/accounts/{account}` before the next `account.updated`-driven event (vs. the current 7–10 GETs/integration). The finding is wrong about the mechanism if developers continue polling >5 times against `pending_verification` after the edit — that would suggest they don't have webhook infrastructure available and the real fix is in setup tooling, not catalog wording.

---


### Cross-match 6 — Categorical match

**Reason:** same Layer 3, shared surface `errors.md`

**Tools:** funnel-researcher, integration-watcher

**funnel-researcher — H3: The error catalog's Layer 3a/3b structure correctly documents that verification state is data-on-the-object, but no surface tells the developer this *at the moment they expect an exception*, producing the 34% silent-abandonment signal [Layer 3]**

**Claim:** `errors.md` does an unusually good job of explaining that Layer 3 verification state is **not** an SDK exception — it's lines 186-187 say "Layer 3 verification state is **not** an exception — it's data on a successfully returned object, so `try/except` never fires for it. This is a primary onboarding confusion." Stripe's own catalog identifies this exact confusion. But the artifact this warning lives in — a flat error catalog — is the one a developer reads only after they suspect an error. The 34% silent-abandonment signal (median 3 calls before quitting; `currently_due` non-empty 7+ days after last POST, no further API calls) is the behavioral fingerprint of a developer who *doesn't suspect an error*: they got a 200, they're done from their perspective, and they walk away. The warning is correctly placed for someone debugging; it is misplaced for someone succeeding-on-paper. The fix is to surface the same warning where the developer first executes the POST — `docs/hosted_vs_custom.md` (covered by Hypothesis 1) and `docs/persons.md` near the response-handling guidance.

**Evidence:**
- `errors.md:8-15`: The error catalog opens by saying "Layer 3 is the one most developers don't anticipate: the API returns `200`, the `Account` object exists, and `charges_enabled` is still `false`." This is Stripe's own diagnosis.
- `errors.md:186-187` (in the SDK exception classes section): "Note: Layer 3 verification state is **not** an exception — it's data on a successfully returned object, so `try/except` never fires for it. This is a primary onboarding confusion."
- `docs/persons.md:22-24`: The correct loop *is* documented here — "Establish a Connect webhook URL... Immediately after creating an account, check the `Account` object's `requirements.currently_due` attribute for additional requirements... Continue watching for `account.updated` event notifications" — but a developer who got a 200 on `POST /v1/accounts/{account}` has no reason to navigate to a doc titled "Handle verification with the API."
- Dropoff signal: 34% of all dropoffs at this step, median 3 calls, **no further API activity** — the developer believes they are done. This is not retry-confusion (that's the 14% signal); this is "I shipped it, why isn't it working in a week."
- The signal is the largest single contributor to dropoff (34% × 36.6% step failure = ~12% of the cohort), making this the highest-leverage fix.

**Proposed change:** Add a "After POST: confirm the requirement actually cleared" subsection at the top of the verification-process section in `docs/persons.md`, restating in positive form what `errors.md` says in diagnostic form: that 200 is acceptance-of-request, not confirmation-of-clearance, and giving the developer the exact code-shape to re-read after every POST.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/persons.md",
      "action": "insert_after",
      "at_line": 11,
      "new_content": "> #### A 200 from `POST /v1/accounts/{account}` does not mean the account is verified\n>\n> The most common cause of a Connect integration that \"looks done\" but never produces `charges_enabled = true` is treating the 200 response from `POST /v1/accounts/{account}` as the success signal. It is not. The 200 means Stripe accepted your request shape. Verification runs asynchronously after the response returns.\n>\n> After **every** `POST /v1/accounts/{account}`, you must:\n>\n> 1. Re-fetch the account: `GET /v1/accounts/{account}`.\n> 2. Check whether `requirements.currently_due` is empty. If it is unchanged from before the POST, the fields you submitted did not match what Stripe needed — inspect `requirements.errors[]` for the specific reason.\n> 3. Check `requirements.disabled_reason`. If it is `requirements.pending_verification`, Stripe is still verifying; you will receive an `account.updated` webhook with the outcome. **Do not poll** — wire the webhook.\n> 4. For each requested capability, also `GET /v1/accounts/{account}/capabilities/{capability}` and check **its** `requirements.currently_due` separately. A capability can have outstanding requirements even when the account does not.\n>\n> If `requirements.currently_due` is non-empty 24 hours after your last update and `requirements.errors[]` is empty, your integration is not progressing — it is silently stalled, not waiting on Stripe. Re-inspect the fields you submitted against `requirements.currently_due` exactly."
    }
  ]
}
```

**How to verify:** The 34% silent-abandonment signal should drop substantially. Specifically, the `median_developer_calls_before_quit` for that signal should rise (currently 3) — developers who used to quit silently should instead either call more (because they now know to GET-after-POST) or progress. If the median calls rises but the abandonment percentage stays high, the copy is being read but not understood — that would suggest a Layer 2 change is needed (e.g., a `requirements_changed` flag in the POST response itself), which is out of scope for an applyable doc edit.

**integration-watcher — F3: Developers re-upload the same failing identity document because the error catalog and SDK names `verification_document_failed_greyscale` but doesn't link the test-mode fix tokens [Layer 3]**

**Pattern claim:** When a `requirements.errors[]` entry surfaces `verification_document_failed_greyscale`, the developer's natural response is to ask the user to re-upload — but in test mode the failing file is a Stripe test token, and re-uploading the same token reproduces the same failure. The catalog and SDK list the code but don't reference the working test tokens (`file_identity_document_success`) that exist exactly for this case, so developers retry the same broken file shape indefinitely.

**Cohort prevalence:** 1 of 7 integrations (dev_k1l2) — but this developer's last 5 successful days are 100% blocked on this single recoverable error. 6/18 of their calls (33%) are re-uploads of greyscale documents that the catalog could have steered to the success token.

**Trace evidence:**
- dev_k1l2 at traces:116 uploads `verification[document][front]=file_xxx (greyscale scan)`. At traces:117 the response surfaces `requirements.errors=[verification_document_failed_greyscale]`.
- traces:119 re-uploads `file_yyy (re-upload, still greyscale)` — same failure mode.
- traces:134 re-uploads `file_zzz (re-upload, still greyscale)` — same failure mode.
- traces:132, 137, 138, 141, 145, 147 are all GETs annotated "unchanged (cannot self-resolve document error)". The developer's loop is sound (read errors, ask for re-upload, POST back); the failure is that they cannot diagnose that the file token itself is the test fixture for the failure case.

**Product evidence:**
- `errors.md:173` names the code: "`verification_document_failed_greyscale` | Submitted ID document is greyscale. | Re-collect a color document scan/photo." The "Re-collect" guidance is the trap: in test mode, "re-collecting" means switching to a different test token, not asking the end user.
- `docs/common_errors.md:87-89` lists the actual fix: "`file_identity_document_success` | Uses the verified image and marks that document requirement as satisfied." But this is in the testing guide, not in the catalog the developer reaches when handling the production-shaped error.
- `sdk/stripe/_person.py:617` types the SDK field `details_code: Optional[str]` with the documented values including `document_failed_greyscale` but provides no inline guidance.

**Proposed change:** Update the catalog row for `verification_document_failed_greyscale` to link the test-mode success token, since the same error name is what test-mode and live-mode developers both look up.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "errors.md",
      "action": "replace",
      "from_line_start": 173,
      "from_line_end": 173,
      "expected_content": "| `verification_document_failed_greyscale` | Submitted ID document is greyscale. | Re-collect a color document scan/photo. | https://docs.stripe.com/connect/handling-api-verification.md |",
      "new_content": "| `verification_document_failed_greyscale` | Submitted ID document is greyscale. | In live mode, re-collect a color document scan/photo from the user. In test mode, the failing token is a Stripe test fixture for this exact error — replace it with `file_identity_document_success` (see [testing identity verification](https://docs.stripe.com/connect/testing.md#test-file-tokens)) to exercise the success path. Re-uploading another greyscale or unverified-image test token reproduces this error. | https://docs.stripe.com/connect/handling-api-verification.md |"
    }
  ]
}
```

**How to verify:** After this edit, traces should show at most one `verification_document_failed_greyscale` per integration in test mode before the developer switches to `file_identity_document_success`. The finding is wrong if developers continue producing 3+ consecutive greyscale re-uploads — that would suggest they aren't reaching the catalog at all and the fix needs to be in the SDK exception path or the developer dashboard's account-detail page instead.


## Findings unique to funnel-researcher (0)

_All of this tool's findings appear in the cross-tool section above._

## Findings unique to integration-watcher (0)

_All of this tool's findings appear in the cross-tool section above._
