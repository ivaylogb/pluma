# Phase 2 research — public signal on Stripe Connect onboarding friction

Internal documentation, not user-facing. Same status as `PHASE_1_NOTES.md`.
This is the observable public signal that *grounds* the synthesized funnel
(`dropoff_data.json`) and trace cohort (`traces.jsonl`). Every synthesized
number/pattern in Phase 2 traces back to an entry here.

- Research window: 2026-05-15. Active research time: ~0.5 hour (well under the
  3-hour soft cap; patterns converged fast and stopped emerging).
- Retrieval method: `$0` faithful — GitHub Search REST API + StackExchange
  API + Stripe `docs.stripe.com/*.md` via `curl`; one `WebSearch` to
  substitute for the defunct community-forum source. No diagnosis tools, no
  model API spend.
- Sources surveyed:
  - **A. stripe/stripe-python issues:** 57 unique issues pulled across 6
    search terms (`connect`, `capability`, `requirements`, `charges_enabled`,
    `person`, `account`); ~40 Connect-relevant; 4 deep-dived.
  - **B. Stack Overflow `stripe-connect`:** 76 tag questions (by votes) + 3
    targeted full-text queries.
  - **C. Community forum:** `stripe-archive/stripe-community` and
    `stripe/stripe-community` both return 404 — the GitHub-hosted Stripe
    community no longer exists. Substituted with a web search that surfaced
    Stripe's own Support KB (the closest current equivalent of "community
    pain that Stripe felt obliged to answer").
  - **D. Stripe changelog:** `docs.stripe.com/changelog.md` (2,263 lines)
    mined for Connect/requirements/capability entries.

---

## A. stripe-python GitHub issues

### `AttributeError: service_agreement` — #1227 (open, 20 comments)
https://github.com/stripe/stripe-python/issues/1227
- Friction observed: `Account.tos_acceptance` is typed `Optional[TosAcceptance]` and `TosAcceptance.service_agreement` is typed `Optional[str]`, but reading `account.tos_acceptance.service_agreement` on an account whose service agreement isn't `recipient` raises `AttributeError` instead of returning `None`. Highest-engagement onboarding issue in the repo and still open.
- Mechanism: the typed SDK model promises an attribute that the runtime object doesn't always carry. Developers writing onboarding gating logic (`if tos_acceptance.service_agreement == "recipient"`) crash on a path the type hints said was safe.
- Cited evidence: `inputs/product/sdk/stripe/_account.py` (the `Account.TosAcceptance` nested class and the inline `TypedDict` model — exactly the typed-bulk surface flagged in Phase 1 decision D-2).

### Can't update a French Connect Custom account's legal entity with a new account token — #417 (closed, 6 comments)
https://github.com/stripe/stripe-python/issues/417
- Friction observed: updating `legal_entity` on a `country='FR'` Custom account via an `account_token` works with raw `curl` but fails through the library.
- Mechanism: SDK behavior diverges from the underlying API for the account-token update path during Custom-account onboarding.
- Cited evidence: `inputs/product/sdk/stripe/_account.py` (`Account.modify`); `inputs/product/docs/hosted_vs_custom.md` (Custom account responsibilities).

### Strange behavior of `additional_owners` in Connect Custom accounts — #418 (closed, 5 comments)
https://github.com/stripe/stripe-python/issues/418
- Friction observed: `additional_owners` can't be passed as an array on create even though the API *returns* it as an array — the accepted input shape ≠ the returned output shape.
- Mechanism: asymmetric parameter shape on the onboarding write path; the object you read back doesn't round-trip as the object you write.
- Cited evidence: `inputs/product/sdk/stripe/_account.py`; `inputs/product/openapi.yaml` (`account` / `person_relationship` schemas).

### Test-mode external bank account: wrong/misleading error message — #347 (closed, 5 comments)
https://github.com/stripe/stripe-python/issues/347
- Friction observed: adding an external bank account to an already-created Connect `Account` in test mode returns `InvalidRequestError: You cannot use a live bank account number when making transfers or debits in test mode` — the message blames the wrong thing; the real issue is the test-mode bank-number requirement.
- Mechanism: the error string doesn't name the corrective action; the developer is told what they *can't* do, not what to do.
- Cited evidence: `inputs/product/errors.md` (Layer-2 `account_number_invalid` / `bank_account_unusable` rows, and the catalog's stated "error → next-action gap" framing).

### Context issues (not deep-dived, corroborating)
- #482 *Add support for the Person resource* (PR, closed): the Persons API was historically absent from the SDK — signals Persons as a late-arriving, under-modeled onboarding surface.
- #292 *Transfer split into Transfer/Payout/RecipientTransfer for Connect*: fund-flow object identity churn.
- #817 *expired checkout session for connect account drops `stripe_account`*; #664 *beta header breaks with two accounts*: `stripe_account` / multi-account header propagation friction.

---

## B. Stack Overflow (`stripe-connect`)

The `stripe-connect` tag corpus is dominated by generic Stripe/webhook/SSL
questions (the tag is broadly applied). The genuinely onboarding-relevant,
highest-signal questions:

### Stripe Connect: difference between Customers and Accounts? — score 31, answered
https://stackoverflow.com/questions/40228547/stripe-connect-whats-the-difference-between-customers-and-accounts
- The confusion: developer can't tell whether to model a signed-up seller as a `Customer` or a connected `Account`; both can hold a card. Root-cause answer: they're different objects for different fund-flow roles.
- Mechanism: object-model ambiguity *before any code is written* — developers create the wrong object and the onboarding sequence never starts correctly.
- Cited evidence: `inputs/product/docs/accounts_overview.md` (connected-account model vs customer).

### "Top-level await" while following `collect-then-transfer#create-an-account-link` — score 104, answered
https://stackoverflow.com/questions/66486903/top-level-await-expressions-are-only-allowed-when-the-module-option-is-set-t
- The confusion: developer stalls *at the account-link creation step* of the Connect onboarding guide. (The proximate error is JS/tooling, but the corpus position — highest-voted `stripe-connect` question — is itself signal that the account-link step is where people are when they get stuck.)
- Mechanism: the create-account → create-account_link → redirect handoff is the first place a Connect integration must leave "happy path" example code.
- Cited evidence: `inputs/product/docs/hosted_vs_custom.md`; `inputs/product/sdk/stripe/_account_link.py`.

### 'No such token' on Connect login/account-id/token flow — score 56, answered
https://stackoverflow.com/questions/33137053/no-such-token-error-upon-submitting-payment-request-to-stripe
- The confusion: token created in one context, used against the wrong account → `resource_missing`-class failure.
- Mechanism: token / `stripe_account` scoping during onboarding.
- Cited evidence: `inputs/product/errors.md` (`resource_missing`, `account_invalid`).

---

## C. Community forum

`stripe-archive/stripe-community` → 404. `stripe/stripe-community` → 404. The
GitHub-hosted Stripe community is defunct; Stripe consolidated to Discord +
the Support knowledge base. Closest current public equivalent (Stripe Support
articles that exist *because* enough developers hit the problem):

- *"Payouts or charges not enabled for connected accounts with platform-gathered verification requirements"* — https://support.stripe.com/questions/payouts-or-charges-not-enabled-for-connected-accounts-with-platform-gathered-verification-requirements
  - A dedicated Stripe Support article whose entire existence is a confession: developers complete API onboarding, get a `200`, and `charges_enabled` stays `false` because `requirements.currently_due` isn't empty.
- *"Connect platforms: Manage onboarding and risk requirements for connected accounts"* — https://support.stripe.com/questions/connect-platforms-manage-onboarding-and-risk-requirements-for-connected-accounts
  - Stripe Support documenting that requested capabilities expand the requirement set and that risk review adds requirements you can't satisfy via the API.

---

## D. Stripe-acknowledged changelog items

From `docs.stripe.com/changelog.md`. These are changes Stripe shipped to
*reduce onboarding friction* — i.e. Stripe naming things it knew were hard:

- *Adds risk requirements to the Capabilities API* (2026-03-25, **Breaking**) — https://docs.stripe.com/changelog/dahlia/2026-03-25/capabilities-api-risk-requirements.md — capability status was opaque about *why* it stayed inactive; Stripe had to surface risk requirements on it.
- *Adds future requirements field* (2025-11-17, **Breaking**) — developers couldn't see what would *become* required, only what was currently due, so onboarding was a moving target. (`account_future_requirements` / `FutureRequirements` are in the Phase 1 surface.)
- *Updates requirements collection parameters* (2025-11-17, **Breaking**) — the requirements-collection contract was changed.
- *Accounts now support digital attestation for proof of registration and beneficial ownership verification* (2025-12-15) and *Adds the ability to attest to an Account's authorized company representative* (2025-10-29) — representative/owner verification was a friction point Stripe added attestation flows for.
- The broad 2025–2026 push to **Accounts v2** is itself the largest confession: the v1 `Account`/`Person`/`Capabilities`/`Requirements` model (this example's locked target, Phase 1 D-4) was hard enough that Stripe rebuilt it. Phase 2 records the v1 friction; it does not editorialize on the migration.

---

## Friction patterns observed

Six distinct patterns. Layer labels use the four-layer model
(measurement / interface / context / sequence) so Phase 3 can correlate
them with what the diagnostic tools surface.

### P1 — The silent `requirements.currently_due` gate (the "200 but not enabled" trap)
- Source count: 4 independent (Support KB ×2 [C], changelog future_requirements [D], SO Account-vs-Account confusion [B], and the *negative* signal that `charges_enabled` yields **0** stripe-python issues [A]).
- Mechanism: `POST /v1/accounts` returns `200` with a valid `acct_…`; developers expect to charge; `charges_enabled` is `false` and the gate is *data on the returned object* (`requirements.currently_due`, `disabled_reason`), never an exception. No `try/except` ever fires.
- Layer: **measurement** (the success state isn't where developers look) with a **context** component (the causal model isn't taught at the call site).

### P2 — Capabilities ↔ Requirements coupling is non-obvious
- Source count: 3 (account-capabilities doc + Support KB [C], changelog "risk requirements added to Capabilities API" [D], WebSearch corroboration that one inactive capability disables both).
- Mechanism: requesting a capability (`card_payments`, `transfers`) silently expands the requirement set; the capability stays `inactive`/`pending` until those clear. Developers request capabilities and don't connect that to the new `currently_due` entries.
- Layer: **context** (cause→effect not surfaced) with a **sequence** component (request-capability-then-satisfy ordering).

### P3 — SDK typed model vs runtime mismatch on the Account/Person object
- Source count: 3 (#1227 [A, 20 comments, open], #418 [A], #417 [A]).
- Mechanism: typed attributes the model promises (`tos_acceptance.service_agreement`) raise `AttributeError`; input param shapes ≠ output shapes (`additional_owners`); library diverges from `curl`. The modern typed SDK introduced an interface-friction class the dynamic-attribute era didn't have.
- Layer: **interface** (SDK signature/behavior contradicts the object).

### P4 — Onboarding error messages don't name the corrective action
- Source count: 2 (#347 [A], the structure of `errors.md` itself [Phase 1]).
- Mechanism: errors describe the prohibition, not the fix (test-mode bank message [#347]); generic `invalid_request_error` / `parameter_unknown` on account/person create doesn't point at the missing requirement or the v1/v2 field mix.
- Layer: **interface** (error → next-action gap).

### P5 — Account-link / hosted-onboarding handoff sequence
- Source count: 2 (SO s=104 create-an-account-link [B], hosted_vs_custom doc + `_account_link.py` [Phase 1]).
- Mechanism: the create-account → create-account_link → redirect → return → re-poll-requirements loop is the first place a Connect integration leaves copy-paste example code; developers stall or skip the re-poll.
- Layer: **sequence**.

### P6 — Object-model confusion: Account vs Customer vs Person
- Source count: 2 (SO s=31 [B], #482 Person-resource history [A]; changelog representative/owner attestation [D] corroborates).
- Mechanism: developers create the wrong object or conflate platform account / connected account / person, so the onboarding sequence is mis-rooted from call #1.
- Layer: **context** (upstream mental model).

**Dominant funnel-dropoff drivers:** P1 and P2 (they gate `charges_enabled`
and produce the largest stalls). **Trace-visible interface friction:** P3, P4
(error clusters, retry loops on real endpoints). **Sequence/context framing:**
P5, P6 (visible as wrong-order or wrong-object call sequences).
