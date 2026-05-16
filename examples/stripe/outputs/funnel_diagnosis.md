# Funnel diagnosis report: stripe_connect_onboarding / requirements_satisfied

## Dropoff summary

Step-to-step pass rates show a severe collapse at the target step:
- `requirements_collected → requirements_satisfied`: **63.4%** (612 → 388), the worst transition in the funnel by a wide margin (next-worst is 85%).
- 388 of 612 accounts that submitted `currently_due` data actually reach an empty `currently_due` + cleared `disabled_reason`.

Top failure signals at `requirements_satisfied`:
1. **34%** — `currently_due` non-empty 7+ days after last submit; silent abandonment after a median of 3 calls (P1: silent gate).
2. **22%** — capability stays `inactive`/`pending` with capability-level `currently_due` populated; developer polls capabilities endpoint without submitting new requirements; median 4 calls (P2: capability coupling).
3. **17%** — `disabled_reason == requirements.pending_verification`; integration stops listening to `account.updated`; median 2 calls.
4. **14%** — POST `/v1/accounts/{account}` returns 200 but `currently_due` is unchanged (under-specified/wrong fields); median 5 calls (P4 + P1).
5. **13%** — `requirements.errors[]` populated and unresolved.

Qualitative signal worth flagging: the highest-signal SO questions are conceptual ("Customers vs Accounts vs Persons"), and stripe-python issue #1227 (`AttributeError: service_agreement`) suggests typed-model gating logic crashes on optional fields — both consistent with the "gate is upstream of code" interpretation.

## Layer categorization

The dominant cause sits in **Layer 2 (API/SDK surface)**: the requirements contract is multi-layered (Account.requirements, Account.future_requirements, per-capability requirements, requirements.errors[]) and the SDK/API surface does not make it obvious that **a 200 on POST /v1/accounts is not evidence of progress** and that **capability-level requirements are a separate hash from account-level requirements**. The 34% + 14% + 22% signals (70% of dropoff) all flow from this: developers reasonably interpret a 200 response as "submitted, now wait," when in fact they must re-read `requirements.currently_due` after each write and separately poll each capability's `requirements` hash.

Secondary candidate: **Layer 3 (docs at decision time)** — `docs/persons.md` does describe the requirements lifecycle (lines 22–24, 491–492) and lists the `requirements` properties, but the critical loop ("POST → re-GET → diff currently_due → loop until empty; capability requirements live in a separate place") is not stated as a procedure, and there is no end-to-end example of the wait-loop or of capability requirement remediation. The 17% pending_verification signal (developers stop listening to `account.updated`) is a Layer 3 failure specifically: the webhook requirement is mentioned but is not co-located with the `requirements_satisfied` decision point.

I considered Layer 4 (workflow ordering) and rejected it: the funnel ordering is correct — capabilities-then-persons-then-requirements is the actual order Stripe requires, and reordering would not change the dropoff. I considered Layer 1 (funnel measurement) and rejected it: the success criterion `currently_due == [] and disabled_reason not in (...)` is exactly the right gate; the dropoff is real, not a measurement artifact.

## Hypotheses

### Hypothesis 1: SDK/API surface does not signal that POST /v1/accounts returning 200 is not progress (Layer 2)

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

### Hypothesis 2: Per-capability requirements are a separate, undocumented gate (Layer 2)

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

### Hypothesis 3: The async `pending_verification` transition has no surfaced "you must subscribe to webhooks" gate (Layer 3)

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

## What this report is NOT

- These are hypotheses, not verified fixes. Each requires re-measurement of the specific dropoff buckets cited above after the change ships.
- These three hypotheses are structurally distinct and target three different ~14–34% slices of the failure population. Apply order is the operator's call, but Hypothesis 1 has the largest addressable surface (~48% of dropoffs) and the smallest edit footprint.
- Other framings were considered and rejected: "rename `currently_due` to be more discoverable" (collapsed to forbidden "improve API naming" without grounded mechanism); "add a tutorial video on Connect onboarding" (forbidden generic content rec); "reorder funnel steps" (Layer 4, but the evidence does not support a reordering — the dropoff is about feedback at each step, not the order of steps).
- Hypothesis 2's edit is a docs change rather than an SDK change because the SDK already prevents the wrong call shape (sdk/stripe/_capability.py:401–413); the gap is conceptual ("two requirements hashes exist") rather than mechanical. A stronger Layer-2 version of this fix would add a `Capability` field to the `Account` object's serialized response that surfaces a synthesized `account.has_unsatisfied_capabilities` boolean, but that crosses the applyable threshold (it requires an API contract change), so it is not proposed here.