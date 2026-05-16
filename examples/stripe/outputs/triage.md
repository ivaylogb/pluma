# Phase 3 triage — Stripe Connect diagnosis run

Honest triage of every finding produced by `funnel_diagnosis.md`,
`integration_findings.md`, and `cross.md`. Each finding is classified
**REAL** / **BORDERLINE** / **SPURIOUS** against the public signal recorded
in `inputs/PHASE_2_RESEARCH.md` (patterns P1–P6) and the actual Phase-1
product surface in `inputs/product/`.

- REAL — surfaces actual Stripe Connect friction observable in the public
  signal; evidence and proposed change hold up.
- BORDERLINE — the friction it points at is real, but a load-bearing claim
  or the proposed remedy is wrong/unsupported.
- SPURIOUS — model speculation about a non-issue, or contradicted by signal.

## Finding inventory

| ID | Tool | Layer | One line | Cross-status |
|---|---|---|---|---|
| H1 | funnel-researcher | 2 | `POST` 200 ≠ progress; must re-read `currently_due`/`errors[]` | matched (CM1, CM2) |
| H2 | funnel-researcher | 2 | Per-capability `requirements` is a separate, undocumented gate | **unique** |
| H3 | funnel-researcher | 3 | `pending_verification` resolves out-of-band; not co-located at decision point | matched (CM3–CM5) |
| F1 | integration-watcher | 4 | 3/7 integrations read `currently_due`, never POST it back | matched (CM1, CM3) |
| F2 | integration-watcher | 3 | Long `pending_verification` polling loops; no fresh signal | matched (CM4) |
| F3 | integration-watcher | 2 | Re-POST same doc on `verification_document_failed_*`; "no error catalog" | matched (CM2, CM5) |

6 distinct findings. cross produced **5 cross-tool matches, 1 unique**
(H2), 0 unique to integration-watcher.

---

## H1 — `POST` returning 200 is not progress (funnel, Layer 2) → **REAL**

**Patterns:** P1 (silent `requirements.currently_due` gate) + P4 (200-without-progress).

**Why REAL.** This is the dominant pattern P1 in `PHASE_2_RESEARCH.md`. Direct
support: the dedicated Stripe Support KB article *"payouts or charges not
enabled for connected accounts with platform-gathered verification
requirements"* [research §C], the changelog *future requirements field*
breaking change [§D], and the **negative signal** that `charges_enabled`
produces zero stripe-python issues — the friction is a mental-model gap, not
an SDK bug [§A], which is exactly what a "the 200 misleads you" finding
predicts. The 14% "200 but `currently_due` unchanged" sub-claim maps to the
P4 row in `errors.md` and the dropoff signal we grounded at 0.14. The
qualitative use of stripe-python #1227 (typed gating logic) is faithful to
the issue we recorded. Evidence cites real surface (`sdk/stripe/_account.py`,
`docs/persons.md:23-24`, openapi `currently_due` schema). Verdict: REAL.

**Caveat (not disqualifying):** the cross-match-1 SDK edit inserts a comment
at `sdk/stripe/_account.py:1982`; the exact insertion line is the model's
best guess at the `modify` boundary and would need a human to confirm the
anchor before apply. The *finding* stands regardless of the edit anchor.

## H2 — Per-capability requirements is a separate gate (funnel, Layer 2) → **REAL** *(the unique finding)*

**Pattern:** P2 (capabilities ↔ requirements coupling).

**Why REAL.** P2 is independently grounded in the changelog **breaking**
change *"Adds risk requirements to the Capabilities API"* [§D], the
`account-capabilities.md` content (the finding cites lines 431–433: *"if the
status of either … is inactive, then both capabilities are disabled"*), and
the WebSearch corroboration in §C. The finding also makes a sharp,
defensible methodological point: the funnel's own step-5 success criterion
only checks `Account.requirements.currently_due == []`, so *the funnel shares
the developer's blind spot* — a genuinely insightful, signal-grounded
observation, not speculation. This is the **only finding unique to one tool**
and it is real: the trace cohort encoded P2 in just one integration
(`dev_e5f6`), which integration-watcher folded into F1, so the trace lens
under-weighted it while the funnel lens kept it. That is precisely the
cross-tool value proposition working as intended. Verdict: REAL.

## H3 — `pending_verification` resolution not surfaced at the decision point (funnel, Layer 3) → **REAL** *(with a wording caveat)*

**Pattern:** P1 async tail (the 0.17 `disabled_reason = requirements.pending_verification` signal).

**Why REAL.** The friction is grounded: `errors.md` Layer-3a documents
`requirements.pending_verification` as a `disabled_reason`; `persons.md`
(= handling-api-verification.md, Phase-1 D-6) puts the `account.updated`
webhook in a preamble list, not at the troubleshooting decision point; we
explicitly synthesized the "stops polling `account.updated`, median 2 calls"
dropoff bucket from this signal. The finding correctly isolates it from
H1/H2 by the distinctively low call count. Verdict: REAL.

**Caveat.** The proposed edit text asserts the resolution is delivered
**"only"** via webhook and that "polling will return the same state until
verification completes." Stripe's real surface does *recommend* webhooks but
the API state does eventually reflect the result on poll — so the edit's
"webhook ONLY / polling never reflects it" phrasing slightly overstates the
source. The *finding and its layer attribution are real*; the *fix prose
needs softening* before it could ship. Flagged, not downgraded — triage
classifies the finding, and the friction is real and in-signal.

## F1 — Integrations read `currently_due` and never POST it back (integration, Layer 4) → **REAL**

**Patterns:** P1 (silent gate, developer-side) + P5 (account-link handoff, via `dev_i9j0`).

**Why REAL.** This is the trace-side image of P1, and it correctly recovers
the three integrations we designed to encode it (`dev_c3d4` = pure P1,
`dev_e5f6` = P2-flavoured, `dev_i9j0` = P5 account-link). Prevalence math
(3/7 integrations, 57/150 calls = 38%) is correct against the actual
`traces.jsonl`. Product evidence cites real lines in
`docs/hosted_vs_custom.md` and `docs/persons.md:21-24`. The Layer-4
attribution (missing submission step, not an error) matches the
"success-coded silence" we deliberately built (the 6% HTTP-error design
decision in `PHASE_2_NOTES.md §5`). Verdict: REAL.

## F2 — Long `pending_verification` polling loops (integration, Layer 3) → **REAL**

**Pattern:** P1 async tail (trace-side mirror of H3).

**Why REAL.** Grounded in the same signal as H3, observed from the
independent trace lens: `dev_a1b2` (transiently, before it flips),
`dev_g7h8`, `dev_m3n4` poll `GET /v1/accounts/{account}` on multi-hour
intervals against an unchanging `disabled_reason=requirements.pending_verification`
state — exactly the journeys we authored for those IDs
(`PHASE_2_NOTES.md §4`). Real surface, real pattern. Verdict: REAL.

## F3 — Re-POST same document on `verification_document_failed_*`; "no error catalog" (integration, Layer 2) → **BORDERLINE**

**Pattern:** P4 (errors don't name the corrective action).

**The real part.** The behavioural friction is genuinely P4 and well
grounded: stripe-python #347 (test-mode bank message blames the wrong thing)
[§A], the `errors.md` Layer-3b `verification_document_failed_greyscale` row,
and the `dev_k1l2` journey we built precisely to encode "re-upload the same
shape, can't self-resolve." The trace evidence (traces:117 → re-upload →
same error → stall) is accurate against `traces.jsonl`.

**Why only BORDERLINE.** The finding's load-bearing product-evidence claim is
**factually false**: *"there is no error catalog in the product artifacts at
all … `[no error catalog found]`"*, and its primary proposed change is
"author a new `errors.md`." But `inputs/product/errors.md` **exists** — it is
a Phase-1 artifact, 201 lines / 91 entries, and it explicitly contains the
`verification_document_failed_greyscale` row with cause and resolution. The
tool did not ingest it (see "Surprising" below). So:
- the *pattern* it surfaces (P4) is REAL, but
- its central evidence claim is refuted by the actual artifact set, and its
  headline remedy (create the file) is **moot** — the file is already there.
A finding whose proposed fix is "build something that already exists,
because I couldn't see it" cannot be called REAL. It is not SPURIOUS either —
the friction is real and in-signal. BORDERLINE is the honest call, and the
root cause is a tool-ingestion gap, not a Stripe-surface gap.

---

## Triage breakdown

| Verdict | Count | Findings |
|---|---|---|
| REAL | 5 | H1, H2, H3, F1, F2 |
| BORDERLINE | 1 | F3 |
| SPURIOUS | 0 | — |

**No SPURIOUS findings.** Every finding maps to a documented public-signal
pattern (P1, P2, P4, P5). The one weak finding (F3) is weak because of a
**tool-ingestion defect**, not because the model speculated about a
non-issue. For a methodology-credibility example, "0 spurious, 1 borderline,
and the borderline is a harness bug we can name precisely" is a strong,
honest result.

## Surprising / unexpected

1. **The tools did not ingest `inputs/product/errors.md`.** integration-watcher
   explicitly reports `[no error catalog found]`; funnel-researcher never
   cites `errors.md` either (it reaches the same codes via the
   `sdk/stripe/_account.py` enum and the openapi schema). Phase-1 created a
   201-line distilled catalog at the product root and Phase-2 grounded the
   traces in it, but pluma's product loader appears to surface `docs/`,
   `sdk/`, and `openapi*` and to miss a bare top-level `errors.md`. This
   single gap produced F3's false premise and moot remedy. **This is the
   most important Phase-3 result** and must be disclosed in the Phase-4
   README — and is itself a real finding *about the methodology/harness*.
2. **Strong cross-tool convergence on P1 from independent inputs.** The funnel
   lens (dropoff numbers) and the trace lens (call sequences) independently
   land on the same root mechanism — "a 200 is not progress; the gate is
   data you must re-read." That agreement, reached from disjoint inputs, is
   the credibility payoff of the cross design.
3. **The only unique finding is real (H2, P2).** cross kept a true finding
   (per-capability requirements) that the trace lens collapsed into F1; 0
   findings were unique to integration-watcher. The cross report did exactly
   what it is for: preserve a real single-lens finding rather than drop it.
4. **4 of 5 cross-matches are mechanical on `docs/persons.md`** (lines 22,
   23-24, 264-290). This is a downstream consequence of Phase-1 decision D-6
   (mapping `persons.md` ← the richest friction doc,
   handling-api-verification.md): citable evidence concentrated there, so the
   tools cite it in common. Predictable in hindsight; worth stating plainly
   so the matches aren't over-read as independent corroboration when they are
   partly an artifact of where the evidence was put.
5. **`cross` repeats full finding bodies per match** (H1 and H3 each appear
   in multiple match blocks verbatim), so `cross.md` is long (399 lines) for
   6 underlying findings. Not a defect — the matcher is pairwise, as the
   cross_pluma README documents — but the Phase-4 README should set that
   expectation.

## What this triage is NOT

- Not a verified-fix claim. Every REAL finding is a grounded hypothesis;
  confirming it requires applying the structured edit and re-measuring, which
  is out of Phase-3 scope.
- The product surface is real Stripe; the funnel/cohort is synthesized
  (Phase-2). These findings demonstrate the methodology produces
  signal-grounded results against a real surface — they are not a measured
  audit of any real platform's onboarding metrics.
- The errors.md ingestion gap means this run did **not** exercise the full
  Phase-1 surface. A re-run after fixing the loader (or relocating
  `errors.md` into a directory the loader globs) would be needed before
  claiming the methodology consumed the entire real surface.
