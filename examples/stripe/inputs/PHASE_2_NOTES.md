# Phase 2 notes — synthesis rationale

Internal documentation, not user-facing. Same status as `PHASE_1_NOTES.md`.
This file makes the Phase 2 synthesis defensible: every synthesized number
and trace pattern traces back to a public-signal entry in
`PHASE_2_RESEARCH.md` or to a documented rationale here.

Companion files:
- `PHASE_2_RESEARCH.md` — the public signal (GitHub, Stack Overflow, Support
  KB, changelog) and the six friction patterns (P1–P6) derived from it.
- `funnel.yaml`, `dropoff_data.json` — funnel-researcher inputs.
- `integration_cohort.yaml`, `traces.jsonl` — integration-watcher inputs.

## 0. Schema decision (read this first)

The Phase 2 spec sketched illustrative shapes (`product` / `activation_goal`;
`steps[].entered/completed/dropoff_pct`; `method`/`path`/`params`). The
**actual schemas the tools consume** are the sister-repo canonical shapes:
`funnel-researcher/examples/api_activation/{funnel.yaml,dropoff_data.json}`
and `integration-watcher/examples/agent_platform/{integration_cohort.yaml,
traces.jsonl}`. Phase 3 runs the real tools against these files, so all four
inputs follow the **canonical** shapes, not the illustrative sketches:

- `funnel.yaml`: `name` / `metric` / `target_dropoff_step` / `steps[]`
  (`id`, `name`, `success_criterion`, `typical_duration`). `description` is
  added per step as an extra informational key (auditability; tools ignore
  unknown keys).
- `dropoff_data.json`: `cohort_name` / `cohort_size` /
  `measurement_window_days` / `step_counts` / `step_pass_rates` /
  `target_step_failure_signals[]` / `qualitative_signals[]`. A
  `_synthesis_note` key and per-signal `grounded_in` keys are added for
  auditability.
- `integration_cohort.yaml`: `cohort_name` / `date_range` /
  `developer_count` / `api_product` / `watch_question` / `scope` /
  `product_artifact_dir` / `notes`.
- `traces.jsonl`: `timestamp`, `developer_id`, `endpoint` ("METHOD /path"),
  `request_summary`, `response_status`, `error_code`, `latency_ms`.

## 1. Friction patterns adopted

From `PHASE_2_RESEARCH.md` — six patterns, four-layer labels in parens:

- **P1 — silent `requirements.currently_due` gate** (measurement + context):
  `POST /v1/accounts` returns 200; `charges_enabled` stays false; the gate
  is data on the object, never an exception. *Dominant funnel driver.*
- **P2 — capabilities↔requirements coupling** (context + sequence):
  requesting a capability silently expands the requirement set; capability
  stays `inactive`/`pending`. *Dominant funnel driver.*
- **P3 — SDK typed-model vs runtime mismatch** (interface): typed attrs
  raise `AttributeError`; input shape ≠ output shape.
- **P4 — error messages don't name the corrective action** (interface):
  prohibition stated, fix not; 200-without-progress.
- **P5 — account-link / hosted-onboarding handoff** (sequence): the
  create→link→redirect→re-poll loop is where copy-paste examples end.
- **P6 — Account vs Customer vs Person object confusion** (context):
  upstream mental-model error mis-roots the sequence.

P1 and P2 are encoded as the funnel's dominant dropoff. P3/P4 are encoded as
trace-visible error clusters and retry loops. P5/P6 are encoded as
wrong-order / wrong-object trace sequences.

## 2. Funnel design rationale

Six steps, terminal = `charges_enabled` (the locked Phase 1 activation
goal). Sequence follows the documented v1 onboarding path in
`inputs/product/docs/` (accounts_overview → capabilities → persons /
handling-api-verification → requirements → charges):

1. `account_created` — `POST /v1/accounts` 200. Near-universal success; the
   200 here is the *start of the P1 trap*, not a milestone.
2. `capabilities_requested` — capabilities requested. P2's origin point.
3. `persons_added` — representative/owners submitted. P3/P6 bite (typed
   model, object confusion).
4. `requirements_collected` — `currently_due` fields submitted back. P4
   bites (confusing errors, 200-without-progress).
5. `requirements_satisfied` — `currently_due` empty, `disabled_reason`
   cleared. **`target_dropoff_step`** — P1 and P2 converge here; this is
   the "200 but not enabled" wall.
6. `charges_enabled` — terminal. Residual stalls on async
   `pending_verification` / risk `disabled_reason`.

`target_dropoff_step: requirements_satisfied` because the research shows the
dominant friction (P1) bites moving *into* that step, and it is the step
immediately before the activation goal — the canonical "I created the
account, why can't it charge" wall. (Mirrors api_activation targeting a
mid/late funnel step, not the terminal one.)

## 3. Dropoff numbers rationale

`cohort_size: 840` connected-account integrations; 30-day window. Counts are
monotone; `step_pass_rates` are exactly `count[next]/count[step]` (validated
arithmetic). Numbers are **illustrative, not measured.**

| Transition | Pass rate | Why this number (grounded pattern) |
|---|---|---|
| account_created → capabilities_requested | 0.967 | Account creation rarely fails at HTTP; tiny drop = accounts created without requesting capabilities (P6 confusion). |
| capabilities_requested → persons_added | 0.850 | First real friction: submitting persons. P3 (typed-model/param-shape, GitHub #418/#1227) + P6. |
| persons_added → requirements_collected | 0.887 | Most who got persons in figure out the `currently_due` read; moderate drop from P4 confusing errors. |
| **requirements_collected → requirements_satisfied** | **0.634** | **Worst pass rate, the target.** P1 (silent gate, abandon without submitting) + P2 (capability coupling unrecognized). Largest single dropoff (224 of 612). |
| requirements_satisfied → charges_enabled | 0.853 | Residual loss to async `pending_verification` / risk `disabled_reason` after a correct submission. |

`target_step_failure_signals` (fractions of the 224 target-step dropoffs,
sum = 1.0; each carries a `grounded_in` field in the JSON):

- 0.34 — `currently_due` non-empty 7+ days, silent abandonment → **P1**.
- 0.22 — capability stuck `inactive`/`pending`, requirements never
  submitted → **P2**.
- 0.17 — `disabled_reason = requirements.pending_verification`, stops
  polling → **P1** (async tail).
- 0.14 — `POST` returns 200 but `currently_due` unchanged → **P4 + P1**.
- 0.13 — `requirements.errors[]` populated and unresolved → **P4**.

Relative ordering (P1 largest, then P2) mirrors the research weighting: P1
has the most independent sources incl. the dedicated Stripe Support KB and
the *negative* signal that `charges_enabled` produces zero stripe-python
issues; P2 is second (changelog breaking changes + Support KB).

## 4. Cohort design

7 synthetic integrations (`integration_cohort.yaml` `developer_count: 7`),
window 2026-04-15 → 2026-05-14 (aligned with the dropoff cohort). Profile
distribution deliberately spans the pattern space, with one success as the
methodology's required contrast:

| Dev | Outcome | Primary pattern(s) | Role in the cohort |
|---|---|---|---|
| `dev_a1b2` | **Reaches `charges_enabled`** | — (clean) | Success contrast: instruments webhooks, submits requirements, polls correctly. |
| `dev_c3d4` | Abandons | **P1** | Pure silent-gate: creates account, polls, never POSTs `currently_due`, goes silent. |
| `dev_e5f6` | Abandons | **P2** | Requests capabilities, poll-loops the inactive capability, never submits the expanded requirements. |
| `dev_g7h8` | Stalls (pending) | **P3 + P4** | Param-shape/typed-model retries (`additional_owners`, `tax_id`), recovers, ends in `pending_verification`. |
| `dev_i9j0` | Abandons | **P5** | Account-link handoff: regenerates links, tight-polls before user finishes, no re-poll discipline. |
| `dev_k1l2` | Stalls (errors) | **P4** | `requirements.errors[]` it can't self-resolve (address combo, then greyscale document). |
| `dev_m3n4` | Stalls (pending) | **Layer-1 → P1** | Auth/mode false start (`secret_key_required`, `livemode_mismatch`, `account_invalid`), recovers, ends in `pending_verification`. |

1 success / 3 abandon / 3 stall. Coverage validated against the surface:
≥1 reaches `charges_enabled` (a1b2); ≥2 hit capabilities friction (e5f6,
c3d4); ≥2 hit requirements stalls (c3d4, g7h8, k1l2, m3n4).

## 5. Trace generation logic

- 150 calls total (lower end of the 150–300 target), 15–29 per integration —
  long enough per the integration-watcher guidance to expose each call
  pattern.
- Deterministically generated (fixed-seed Python), timestamps strictly
  increasing per developer, latencies in plausible ranges (auth/validation
  fast ~70–150 ms; creates/updates ~350–620 ms; GET polls ~105–127 ms).
- **Endpoints**: only the 10 real Stripe paths present in
  `inputs/product/openapi.yaml` (validated — zero unknown paths). `endpoint`
  uses the literal templated path (`/v1/accounts/{account}`) so it matches
  the OpenAPI path keys verbatim; the synthetic `acct_…` id appears in
  `request_summary`.
- **Error codes**: only real codes present verbatim in
  `inputs/product/errors.md` (validated — `secret_key_required`,
  `livemode_mismatch`, `account_invalid`, `parameter_unknown`,
  `parameter_invalid_empty`, `tax_id_invalid`, `account_number_invalid`,
  `url_invalid`, `rate_limit`).
- **Layer-3 is modelled as 200, not as an error.** The defining feature of
  P1/P2 is that the failure is *data on a successful response*. So the
  stalls appear as `response_status: 200, error_code: null` with the gate
  state in `request_summary` (`charges_enabled=false`,
  `requirements.currently_due=[…]`, `disabled_reason=requirements.pending_verification`,
  `requirements.errors=[invalid_address_city_state_postal_code]`,
  `verification_document_failed_greyscale`). Every such state string is
  faithful to `inputs/product/errors.md` (Layer 3a/3b). The 6 % HTTP-error
  rate is intentional: real Connect onboarding friction is overwhelmingly
  the silent 200 gate, not 4xx — encoding a high error rate would
  misrepresent the surface.
- Abandonment is encoded as a developer's trace simply ending (no
  terminal-event marker), matching how a trace cohort actually shows
  drop-off.

## 6. Sources cited per friction pattern

Cross-reference to `PHASE_2_RESEARCH.md` (URLs there):

- **P1**: Stripe Support KB *payouts-or-charges-not-enabled* + *manage
  onboarding and risk requirements* [C]; changelog *future requirements
  field* [D]; `handling-api-verification.md` `disabled_reason` table
  [Phase 1]; *negative signal* — `charges_enabled` → 0 stripe-python issues
  [A].
- **P2**: changelog *Adds risk requirements to the Capabilities API*
  (Breaking) [D]; `account-capabilities.md` + Support KB [C]; WebSearch
  corroboration (one inactive capability disables both).
- **P3**: stripe-python #1227 (open, 20 comments), #418, #417 [A].
- **P4**: stripe-python #347 [A]; structure of `errors.md` [Phase 1].
- **P5**: Stack Overflow s=104 *create-an-account-link* [B];
  `hosted_vs_custom.md` + `_account_link.py` [Phase 1].
- **P6**: Stack Overflow s=31 *Customers vs Accounts* [B]; #482 Person
  resource history [A]; changelog representative/owner attestation [D].

## 7. Honest disclosures

**Real (Phase 1, unchanged):** the entire product surface in
`inputs/product/` — Stripe's own docs `.md`, verbatim stripe-python source,
the distilled error catalog, the selected OpenAPI. Endpoints and error codes
used in Phase 2 are real and were validated against those files.

**Real (Phase 2):** the public signal in `PHASE_2_RESEARCH.md` — actual
GitHub issue numbers/URLs/comment counts, actual Stack Overflow questions/
scores, actual Stripe Support KB articles, actual changelog entries. These
were retrieved at $0 (GitHub/StackExchange APIs, `docs.stripe.com/*.md`, one
WebSearch). No diagnosis tools were run; no model API spend.

**Synthesized:** the cohort and the numbers. `funnel.yaml` step definitions,
all counts/pass-rates in `dropoff_data.json`, the 7 integrations, and all
150 trace lines are authored, not measured. They are constructed so that the
friction *shape* matches the public signal — not to report any real
platform's metrics. The numbers are illustrative; their relative structure
(where the big dropoff is, which patterns dominate) is what's defensible,
not their absolute values.

**Known limitations:** (a) Stack Overflow's `stripe-connect` tag is noisy;
real onboarding Q&A there is sparse and skews conceptual — Phase 2 leans
more on GitHub + Support KB + changelog than on SO. (b) The community-forum
source (C) is defunct (GitHub repo 404); the Support KB is a reasonable but
not identical substitute. (c) The v1 surface is deliberate (Phase 1 D-4);
the broader v1→v2 migration is itself a friction signal Phase 2 records but
does not encode as a funnel step, to keep the example scoped to the locked
decision. (d) Single-cohort synthetic data inherits no model variance yet —
that enters in Phase 3 when the tools actually run.
