# Stripe Connect onboarding example

This example runs the diagnostic methodology against Stripe Connect's
onboarding flow: the path from creating a connected account through reaching
`charges_enabled`. It lives here, alongside the `cross_pluma`
fixture, because the fixture validates the method and it's findings against production surfaces. 
The product suerface used here includes: the docs, the `stripe-python` SDK source, the error catalog, the
OpenAPI slice. The cohort and dropoff numbers are synthesized, grounded in observable public signal about where
developers actually get stuck.

The example has been run twice. The current output (`outputs/rerun_post_loader_fix.md`)
is the canonical run referenced throughout. The earlier run (Phase 3
artifacts in `outputs/`) is preserved as historical context as it surfaced a
loader bug in triage, which was fixed in `integration-watcher` and
`funnel-researcher` before the re-run.

## What's real and what's synthesized

The methodology operates on the actual **product surface**. The
cohort signal is the trigger that names *what to investigate* in that
surface; it is synthesized but constructed so the friction it encodes
matches documented public signal.

| Real | Synthesized |
|---|---|
| Stripe Connect docs: selected pages from `docs.stripe.com`, verbatim | The funnel definition: the six steps and the target dropoff step |
| `stripe-python` SDK source — verbatim from `stripe/stripe-python` | The cohort numbers: cohort size, per-step counts, pass rates |
| Stripe error catalog — distilled from public Stripe docs | The 7-integration developer cohort |
| Connect-relevant OpenAPI surface — extracted from Stripe's public spec | The 150-call trace stream |
| Public-signal grounding: GitHub issues, Stack Overflow, Stripe Support KB, Stripe changelog (sources in `inputs/PHASE_2_RESEARCH.md`) | |

The numbers do not represent a measured audit of the onboarding metrics but
maintains a valid/defensible shape: where the largest dropoff sits, which patterns dominate, 
and how the failure modes are distributed. Every synthesized number is traceable to a public signal or a
documented rationale (`inputs/PHASE_2_NOTES.md`). Endpoints and error codes
in the traces are real and were validated against the OpenAPI surface and
error catalog.

## The friction surface, in plain terms

Six recurring ways developers stall moving a connected account toward
`charges_enabled`. These are drawn from public signal in `stripe-python`
issues, Stack Overflow, Stripe's own Support KB and changelog. The full
source list with URLs is in `inputs/PHASE_2_RESEARCH.md`.

**The silent gate.** `POST /v1/accounts` returns `200` with a valid
`acct_…`, and the account still can't charge. The blocker is data on the
response object — `requirements.currently_due`, `requirements.disabled_reason`
— not an exception. No `try/except` ever fires. A `200` is not progress.

**Capability coupling.** Requesting a capability (`card_payments`,
`transfers`) silently expands the requirement set, and the capability stays
`inactive`/`pending` until those new requirements clear. The capability's
requirements live in a different place than the account's, so an account
that looks "done" can still be gated.

**Typed-model mismatches in the SDK.** The modern typed SDK promises
attributes the runtime object doesn't always carry, and input parameter
shapes don't always round-trip with output shapes. Gating logic written
against the typed model crashes on paths the type hints said were safe.

**Errors that name the prohibition, not the fix.** A failure tells you what
you can't do, not what to do next: a test-mode bank error blames the wrong
field; a generic `invalid_request_error` on account creation doesn't point
at the missing requirement; a rejected verification document reports
"greyscale" but the corrective action lives elsewhere.

**The account-link handoff loop.** The create-account → create-account_link
→ redirect → return → re-check-requirements sequence is the first place a
Connect integration leaves copy-paste example code. Integrations stall in
the handoff, tight-poll before the user has finished, or never establish a
re-check path.

**Account vs Customer vs Person confusion.** Developers can't tell whether
a signed-up seller is a `Customer`, a connected `Account`, or a `Person`
on an account, so the onboarding sequence is mis-rooted from the first call.

One signal worth calling out because it is a *negative* one. Searching the
`stripe-python` issue tracker for `charges_enabled` returns nothing: the
"my account won't enable" problem produces almost no SDK bug reports. It
produces Stack Overflow questions, Support tickets, and conceptual
confusion instead. That absence is itself evidence — the dominant friction
is not a code defect developers can file against the library; it is a
mental-model gap upstream of the code. The findings below reflect that:
the largest one is about what a *successful* response fails to communicate,
not about an error.

## What the diagnostic run surfaced

Two lenses run against the same product surface. The funnel lens reads the
dropoff numbers and explains *why* developers fall off at the target step.
The trace lens reads the call sequences and explains *where* integrations
get stuck. Then the cross step reports where the two independently agree.

Findings carry a layer tag in parentheses — the surface the defect lives
in. The current run produced six findings, all in Layer 3 (the documented
surface available at decision time): citations point to docs and the error
catalog where the friction is missing or misplaced. Citations point into
`inputs/product/`.

### Funnel-side findings

**H1: Async-verification contract hidden at the mode-choice page (Layer 3).**
A 14% bucket of developers pick a hosted/API onboarding mode without
ever encountering the asynchronous verification contract — the docs at
`docs/hosted_vs_custom.md:15-23` and `docs/hosted_vs_custom.md:49-55`
present the two modes at the same shape, with no callout that the
"complete" signal arrives later via `account.updated` and not on the next
synchronous read. A 17% bucket inherits the same gap. Proposes an
applyable doc callout at the mode-choice page.

**H2: Capability requirement expansion documented forward-only (Layer 3).**
`docs/capabilities.md:487-528` documents what happens when a requested
capability adds requirements; it doesn't document the reverse path — given
a capability that won't activate, how to diagnose which requirements
expanded and where to read them. The SDK reflects this:
`sdk/stripe/_capability.py:391-413` raises `NotImplementedError` on the
diagnostic surface a developer would reach for. Proposes an applyable
bridging paragraph.

**H3: `errors.md` correctly names asynchronous verification, in the
wrong artifact (Layer 3).** The 34% silent-abandonment bucket — developers
who submit, see Stripe accept it, and quit fast — is grounded in
`errors.md:8-15` and `errors.md:186-187`. Those rows correctly state that
verification state is data, not an exception. The placement is the
problem: the rows live in the error catalog (a debug-time artifact),
while `docs/persons.md` is the entry-point doc and doesn't surface the
same content. Proposes an applyable docs/persons.md edit pulling the
verification-state language to the entry-point.

### Trace-side findings

**F1: Read `currently_due`, never POST it back (Layer 3).** Two of seven
integrations read `requirements.currently_due` once and then GET-poll
forever without ever POSTing the required fields back. 41 of 150 cohort
calls. The entry-point doc doesn't name the read-then-POST loop;
`docs/persons.md` is where the loop is mentioned but it isn't where a
developer following the quickstart lands. Proposes an applyable docs edit
naming the loop at the entry point.

**F2: Hour-scale polling treating `pending_verification` as an error
(Layer 3).** Integrations that submitted correctly then poll on
hour-scale intervals against an unchanging
`disabled_reason=requirements.pending_verification`. The error catalog at
`errors.md:120` correctly identifies `pending_verification` as a state,
but the row doesn't say "stop polling, wait for `account.updated`."
Proposes a surgical one-line catalog edit.

**F3: Re-upload the same greyscale document (Layer 3).** An integration
receives `requirements.errors=[verification_document_failed_greyscale]`
and responds by re-uploading the same document shape, then stalls. The
error catalog at `errors.md:173` names the code; the test-mode fix lives
separately at `docs/common_errors.md:87-89` (a row pointing at the
`file_identity_document_success` test token, which is the actual remedy
for reproducing this in test mode). The catalog row doesn't link to the
test-token fix. Proposes a surgical one-line catalog edit. The test
tokens and the error code were externally verified against Stripe's live
documentation.

### Cross-tool agreement

| Tool | Layer 3 | Total |
|---|---|---|
| funnel lens | 3 | 3 |
| trace lens | 3 | 3 |


6 findings in cross-tool matches. No unique findings in the current run. The
funnel lens and the trace lens, reading disjoint inputs, land on the same
six defects.

The cross step is the convergence check. When the funnel lens (reading
only step-by-step dropoff numbers) and the trace lens (reading only
individual call sequences) cite the same `file:line` as the source of a
defect, that is independent corroboration of the gap on the surface. 
The current run produces full overlap because the documented surface 
(now including `errors.md`) gives both lenses the same citable evidence for each
pattern.

One honest caveat. Most of the cross-matches resolve to the same handful
of files: `docs/persons.md`, `docs/hosted_vs_custom.md`, `errors.md`. The
documented surface where Connect onboarding friction concentrates its
citable evidence is small, so both lenses cite the same locations.
Convergence on the *diagnosis* is independent (different data, same
conclusion); the file clustering itself is a property of where Stripe's
documentation is structured to live.

The cohort includes one integration that reaches `charges_enabled`
cleanly. It reads `currently_due`, POSTs the fields back, polls correctly
on `account.updated`, and flips. That contrast is in the data
deliberately: a diagnosis of failures against a cohort with no success
path would be unfalsifiable. The findings describe how the seven diverge
from the one.

## How the loader bug was caught

The original run produced one BORDERLINE finding under triage — F3 in the
original output (`outputs/triage.md`). The friction pattern (developers
re-uploading rejected documents) was real and grounded in public signal.
The proposed fix wasn't: the finding claimed "there is no error catalog
in the product artifacts at all," but `errors.md` was right there in the
product surface, with the relevant row at line 173.

Triage cross-references each finding's claims against external signal. The
pattern claim matched the public signal. The proposed-fix claim didn't:
`errors.md` clearly existed. The mismatch traced to the product loader —
it had been ingesting `docs/`, `sdk/`, the OpenAPI surface, and a
specific error-catalog candidate list, but a top-level `errors.md` matched
none of those branches.

The loader is duplicated byte-for-byte between `integration-watcher` and
`funnel-researcher`. The fix landed in both (`integration-watcher` commit,
`funnel-researcher` commit) — a generic top-level scan by file extension,
so any reasonably-named root file is picked up. After the fix:
`iw.read_product` and `fr.read_product` against this example both return
`errors.md` (22693 bytes, content intact).

The current run uses the fixed loader. F3 in the re-run cites
`errors.md:173` directly, identifies the genuine residual gap (the catalog
row doesn't link to the test-mode fix token), and proposes a surgical
applyable edit. Triage marks it REAL.

## Differences from the original run

The original run is preserved at `outputs/cross.md`,
`outputs/funnel_diagnosis.md`, `outputs/integration_findings.md`, and
`outputs/triage.md`. The current run is `outputs/rerun_post_loader_fix.md`.

Three substantive differences in the re-run beyond F3:

The original run spanned Layers 2, 3, and 4 in its findings (SDK comment
fixes, doc fixes, call-sequence fixes). The current run is entirely Layer
3. Both lenses, with the richer surface available, anchored on the
documentation layer — the surface where the fixes the model proposes
actually need to land. The friction patterns are the same; the proposed
fixes shifted from SDK-level edits to doc/catalog edits.

The original run had one unique finding (funnel H2, no integration
counterpart). The current run has zero — every finding cross-matches.
`errors.md` is now a shared citable surface for both lenses, so claims
that previously appeared in only the funnel lens now appear in both.
Cross-match count went from five to six.

The original F1 was Layer 4 (call sequence) with three of seven
integrations, 57 of 150 calls. The current F1 is Layer 3 (entry-point
docs) with two of seven, 41 of 150. The dropped integration matched a
pattern (P5 in `inputs/PHASE_2_RESEARCH.md`) that the current F1 doesn't
fold in.

## How to reproduce this run

From this directory (`pluma/examples/stripe/`). `inputs/product/` is the
real Stripe surface; `inputs/funnel.yaml`, `inputs/dropoff_data.json`,
`inputs/integration_cohort.yaml`, and `inputs/traces.jsonl` are the
synthesized cohort signal (rationale in `inputs/PHASE_2_NOTES.md`).

```bash
pluma cross \
  --product       inputs/product/ \
  --funnel        inputs/funnel.yaml \
  --dropoff       inputs/dropoff_data.json \
  --traces        inputs/traces.jsonl \
  --cohort        inputs/integration_cohort.yaml \
  --force \
  --output-file   outputs/rerun_post_loader_fix.md
```

The `--force` flag is required. `pluma cross` caches results keyed on
input file content hashes. A loader code change in `integration-watcher`
or `funnel-researcher` doesn't invalidate this cache, so running the
command without `--force` returns the original pre-fix output from cache
at zero spend. With `--force`, both lenses run live.

Both lens runs are live model calls (≈$5–9 total on Opus 4.7; the harness
records no token telemetry, so treat that as an estimate, not a meter
reading). Wall time roughly four minutes for both. Without `--force` on
unchanged inputs, the cached output returns in under a second.

The individual lens runs and the original (pre-fix) cross output are also
in `outputs/`. They are the actual reports from those runs, not
regenerated samples.

## Inputs and audit trail

The product surface and the synthesized cohort each have an internal
record of what was selected and why. These are the audit trail; they are
not required reading to use the example.

- `inputs/PHASE_1_NOTES.md` — what was selected for the product surface,
  with source URLs, commit SHAs, line counts, and the selection decisions
  (why the SDK is verbatim and complete, why the v1 Accounts surface, why
  the requirements doc is kept whole).
- `inputs/PHASE_2_RESEARCH.md` — the public-signal sources behind the six
  friction patterns: GitHub `stripe-python` issues, Stack Overflow
  `stripe-connect`, Stripe Support KB, Stripe changelog, with URLs.
- `inputs/PHASE_2_NOTES.md` — the per-number synthesis rationale: why the
  funnel has these steps, why the dropoff sits where it does, how the
  7-integration cohort and the 150-call trace stream were constructed, and
  what is real versus synthesized.
- `outputs/rerun_post_loader_fix.md` — the current run cited throughout
  this document.
- `outputs/cross.md`, `outputs/funnel_diagnosis.md`,
  `outputs/integration_findings.md`, `outputs/triage.md` — the original
  run, including the triage step that flagged F3 as BORDERLINE.

## Known limitations

Two follow-ups identified during this work, neither addressed in the
current commits:

`product_reader.py` is byte-for-byte duplicated between
`integration-watcher` and `funnel-researcher`. The loader bug had to be
patched in lockstep across both. Consolidating into a shared module is a
separate effort.

Pluma's `cross` cache keys on input file content, not on loader/tool code.
Upstream code changes that affect what the loader produces don't
invalidate the cache. Anyone re-running this example after a loader update
must use `--force`, or the cached pre-fix output returns at zero spend
with no signal the new code didn't run. Making the cache key incorporate
tool version is a separate effort.

## What this example does not claim

- The findings are grounded hypotheses, not verified fixes. Confirming any
  of them means applying the structured edit and re-measuring the specific
  dropoff or trace pattern it targets — out of scope here.
- The product surface is real Stripe; the funnel and cohort are
  synthesized. This demonstrates the methodology produces signal-grounded
  findings against a real surface. It is not a measurement of any real
  platform's Connect onboarding.
- Single lens runs are subject to model variance, and the cross report
  inherits it — it correlates whatever the two legs produced; it does not
  stabilize them.
