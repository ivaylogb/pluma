# Phase 1 notes — Stripe Connect onboarding worked example

Internal documentation, not user-facing. Exists so Phase 1 input assembly is
auditable: if a Phase 3 finding cites `inputs/product/<file>:<line>`, a reader
can trace back to the exact upstream source URL + commit that produced it.

## Retrieval provenance

| Item | Value |
|---|---|
| Retrieval timestamp (UTC) | `2026-05-15T20:15:51Z` |
| Retrieval date | 2026-05-15 |
| stripe-python version | `15.1.0` |
| stripe-python commit SHA | `41a2ece934c8d365b9fc88253bc3c4675913d09e` (default branch, shallow clone) |
| stripe/openapi commit SHA | `c8dcae494153b25b43015b896dc3831fde2de228` (default branch, shallow clone) |
| Stripe OpenAPI `info.version` | `2026-04-22.dahlia` |
| Docs source | `https://docs.stripe.com/<path>.md` (Stripe's own faithful Markdown rendering of each docs page) |
| Method | `curl` for raw bytes (SDK, OpenAPI, docs `.md`); PyYAML 6.0.3 for the OpenAPI structural extraction. No model calls. $0 API spend. |

The docs `.md` endpoint is Stripe's official Markdown serialization of each
documentation page (discovered via `https://docs.stripe.com/llms.txt`). It is
not a summary — it is the page content verbatim, which is why it is suitable
for `file:line` citation. Spot-checked: no HTML/JS wrappers, no truncation, no
404/redirect bodies.

## Docs (`inputs/product/docs/`) — 4,827 lines, 7 files

Each file begins with a `<!-- source: ... | retrieved: ... -->` header. The
two multi-source files repeat that header before each concatenated source,
delimited by a `---` rule, so a cited line traces to the right upstream page.

| File | Lines | Source(s) | Covers |
|---|---|---|---|
| `accounts_overview.md` | 519 | `connect/how-connect-works.md` + `connect/accounts.md` | Connect overview (onboarding/management/payments/payouts components, fund flows) and the connected-account model: the `Account` object, account configurations, account creation. Two sources joined to satisfy both "overview" and "Account object/creation". |
| `persons.md` | 613 | `connect/handling-api-verification.md` | The `Person` object and the API verification flow: `requirements.currently_due` / `eventually_due` / `past_due` / `pending_verification`, `charges_enabled` / `payouts_enabled`, the `requirements.errors[]` array, `disabled_reason`. The single richest onboarding-friction doc. |
| `capabilities.md` | 610 | `connect/account-capabilities.md` | How capabilities work, how requested capabilities drive verification requirements, capability `status` and `requirements`, what a connected account can do. |
| `requirements.md` | 1,810 | `connect/required-verification-information.md` | Required + future verification information by country, business type, and capability. Kept **complete** (see decision D-1). |
| `hosted_vs_custom.md` | 484 | `connect/onboarding.md` + `connect/hosted-onboarding.md` + `connect/custom-accounts.md` | The onboarding-method decision developers face: choosing an onboarding configuration, Stripe-hosted onboarding flow + Account Links, and the legacy custom-account (full API responsibility) path. Three sources joined (decision page is only ~50 lines on its own). |
| `charges_transfers.md` | 166 | `connect/charges.md` | The activation goal: charge types (direct / destination / separate charges and transfers), how funds move once `charges_enabled` is true. |
| `common_errors.md` | 625 | `connect/testing.md` | Testing Connect onboarding: test-mode triggers for forcing specific verification/requirement states, OOB verification simulation, simulating rejected/restricted accounts — i.e. how onboarding error states are reproduced. |

## SDK (`inputs/product/sdk/stripe/`) — 4,332 lines, 6 files

Real production stripe-python source, copied **verbatim** (byte-for-byte body
diff against the cloned source is empty). Each file has a 3-line header
prepended:

```
# source: https://github.com/stripe/stripe-python/blob/41a2ece934c8d365b9fc88253bc3c4675913d09e/stripe/<file>
# retrieved: 2026-05-15T20:15:51Z
<blank line>
```

**Line-number offset:** the prepended header is 3 lines. A citation of
`sdk/stripe/_account.py:N` corresponds to upstream GitHub line `N - 3`. This
offset is constant and applies to all 6 SDK files.

| Bundled file | Bundled lines | Source lines (GitHub) | Relevance |
|---|---|---|---|
| `_account.py` | 2,612 | 2,609 | The `Account` resource: nested `Capabilities`, `Requirements`, `FutureRequirements`, `Company`, `Controller`, `TosAcceptance`, `Settings` object shapes + `create` / `retrieve` / `modify` / `persons` / `*_capability` / `*_person` methods. This is the core onboarding-friction surface. |
| `_person.py` | 798 | 795 | The `Person` resource incl. its own `Requirements` / `FutureRequirements` / `Verification` nested shapes. |
| `_capability.py` | 418 | 415 | The `Capability` resource: `status`, `requirements`, `future_requirements`. |
| `_account_link.py` | 72 | 69 | The `AccountLink` resource — the hosted-onboarding entrypoint. |
| `_error.py` | 198 | 195 | The exception class hierarchy actually raised by stripe-python. Cited by `errors.md`. |
| `_api_resource.py` | 234 | 231 | Base API-resource request/instance-URL handling underneath every call above. |

Path structure mirrors the **current** stripe-python layout (flat
`stripe/_account.py`), not the older `stripe/api_resources/account.py` layout
referenced illustratively in the Phase 1 spec. stripe-python 15.x flattened
its module layout; we preserve what the SHA above actually ships so citations
match the real source.

## `inputs/product/errors.md` — 201 lines, 91 catalog entries

A **distilled** flat catalog (this artifact is explicitly a distillation, not
a verbatim copy). Every entry carries a per-row source URL for verification.
Grounded in three real Stripe sources + the SDK:

- `https://docs.stripe.com/api/errors.md` — error `type` enum + HTTP status table
- `https://docs.stripe.com/error-codes.md` — specific `code` strings
- `https://docs.stripe.com/connect/handling-api-verification.md` — `requirements.disabled_reason` values and `requirements.errors[].code` values
- `stripe/_error.py` @ SHA above — exception class hierarchy

Organised by the three onboarding failure layers (transport/auth → request
shape → verification state) so it doubles as a map of *where* in the funnel a
developer is stuck. Card-decline / Terminal / Issuing / Tax-only / Financial
Connections codes excluded except where they intersect the onboarding path.

## `inputs/product/openapi.yaml` — 6,785 lines, 10 paths, 29 schemas

Extracted from `openapi/spec3.yaml` (the public, non-SDK-annotated spec) via
PyYAML — a **structural** selection, so it is valid OpenAPI 3.0.0 and
re-parses cleanly; no arbitrary line cuts. Header comment + `info.x-selection`
record provenance and the selection rule in-band.

- **Paths (10):** `/v1/account`, `/v1/account_links`, `/v1/account_sessions`, `/v1/accounts`, `/v1/accounts/{account}`, `/v1/accounts/{account}/capabilities`, `/v1/accounts/{account}/capabilities/{capability}`, `/v1/accounts/{account}/persons`, `/v1/accounts/{account}/persons/{person}`, `/v1/accounts/{account}/reject` (17 operations).
- **Schemas (29):** the explicit onboarding object schemas (`account`, `person`, `capability`, `account_link`, `external_account`, `error`, `deleted_*`, `legal_entity_person_verification*`, business profile / settings / tos) plus the full `account_requirements*` / `account_capabilit*` / `account_future*` / `capability*` / `person_*` requirements-and-capability cluster — that cluster *is* the friction surface.
- Deeper nested `$ref`s (`legal_entity_company`, `address_*`, `document_*`, …) are intentionally left unresolved. This file is the API surface Phase 2 traces reference, not a runnable spec.

## Total product surface

| Category | Lines |
|---|---|
| docs | 4,827 |
| sdk | 4,332 |
| errors | 201 |
| openapi | 6,785 |
| **Total `inputs/product/`** | **16,145** |

## Selection decisions / judgment calls

**D-1 — `requirements.md` kept complete (1,810 lines).** The Phase 1 guardrail
allows section-selecting an oversized page. The source
(`required-verification-information.md`) is a per-country / per-capability
requirement matrix — that matrix *is* the onboarding friction surface ("what's
missing for activation"). Dropping countries would weaken exactly the evidence
the example exists to produce, and any section cut would desync `file:line`
from the upstream page. Decision: keep it verbatim and complete. It is the
single largest doc but the most diagnostically load-bearing one.

**D-2 — SDK total (4,332 lines) exceeds the ~1,000–3,000 soft target.** Driven
almost entirely by `_account.py` (2,612 lines), which is large because modern
stripe-python embeds typed parameter `TypedDict`s inline in the resource
module. Splicing `_account.py` to hit the target would (a) break `file:line`
citation against the real source and (b) cut the `Requirements` /
`Capabilities` object definitions that are the whole point. Decision:
faithfulness + citation integrity over the soft size target; keep all 6 files
verbatim and complete. Flagged here and in the Phase 1 report rather than
silently truncated.

**D-3 — Docs total (4,827) slightly under the 5,000–15,000 soft target.** All
7 sources were kept verbatim and complete; nothing was padded to hit a number.
4,827 lines of faithful, citable surface is preferable to inflated content.
Within the spirit of "enough surface for real diagnosis, not so much it
overwhelms."

**D-4 — v1 Accounts API surface, deliberately.** Stripe's docs now steer new
integrations to the Accounts v2 API (`POST /v2/core/accounts`). Locked
decision D1 targets the flow to `charges_enabled` via the `Account` / `Person`
/ `Capabilities` / `Requirements` model — those are v1 Account-object concepts,
and they are exactly what `stripe-python`'s `_account.py` / `_person.py` /
`_capability.py` implement (D2). The v1 surface is the one that maps to the
chosen SDK and to the documented friction. The v1↔v2 split is itself a real,
publicly-discussed onboarding friction signal; Phase 1 only records the
surface and does not editorialize on it.

**D-5 — Accounts path tree narrowed.** From the full `/v1/accounts/*` tree we
excluded `/bank_accounts`, `/bank_accounts/{id}`, `/external_accounts`,
`/external_accounts/{id}`, `/login_links`, and the legacy `/people` +
`/people/{person}` endpoints. Rationale: external/bank accounts and login
links are downstream of activation (payout setup, Express dashboard); `/people`
is a legacy alias of `/persons`. Keeping both would add noise without adding
onboarding-friction surface. Recorded in `openapi.yaml`'s `x-selection` too.

**D-6 — Doc topic → file mapping.** The Phase 1 spec lists 8 doc topics but
the expected output names 7 files. Resolved by joining closely-related sources
into single files where it preserves clean per-source citation
(`accounts_overview.md` = overview + accounts; `hosted_vs_custom.md` =
onboarding decision + hosted + custom). Each joined source keeps its own
`<!-- source -->` header, so citations stay traceable.

**D-7 — `common_errors.md` source choice.** The Phase 1 spec's
`common_errors.md` doc page is distinct from the distilled `errors.md`
catalog. The general API error reference + Connect error codes went into the
`errors.md` catalog (Step 1.3). For the `common_errors.md` *doc page* the
best-fit live Connect page is `connect/testing.md` — it documents how
onboarding error / requirement / rejection states are deliberately triggered
and observed, which is the "common errors during onboarding" surface a
developer actually reads. Noted as a judgment call.
