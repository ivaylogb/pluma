# Stripe Connect onboarding — a worked example

This example runs the diagnostic methodology against Stripe Connect's
onboarding flow: the path from creating a connected account through reaching
`charges_enabled`. It is here, alongside the fictional `cross_pluma` fixture,
because the fixture proves the method runs and this proves it produces real
findings against a real production surface. The product surface — the docs,
the `stripe-python` SDK source, the error catalog, the OpenAPI slice — is
real Stripe. The cohort and dropoff numbers are synthesized, but grounded in
observable public signal about where developers actually get stuck. What
follows is what the run found, what holds up, and the one finding triage
flagged — including a defect it caught in the diagnostic harness itself.

## What's real and what's synthesized

The methodology operates on the **product surface**, which is real. The
cohort signal is the trigger that names *what to investigate* in that
surface; it is synthesized but constructed so the friction it encodes
matches documented public signal.

| Real | Synthesized |
|---|---|
| Stripe Connect docs — selected pages from `docs.stripe.com`, verbatim | The funnel definition: the six steps and the target dropoff step |
| `stripe-python` SDK source — verbatim from `stripe/stripe-python` | The cohort numbers: cohort size, per-step counts, pass rates |
| Stripe error catalog — distilled from public Stripe docs | The 7-integration developer cohort |
| Connect-relevant OpenAPI surface — extracted from Stripe's public spec | The 150-call trace stream |
| Public-signal grounding — GitHub issues, Stack Overflow, Stripe Support KB, Stripe changelog (sources in `inputs/PHASE_2_RESEARCH.md`) | |

The numbers are illustrative — they are not a measured audit of any real
platform's onboarding metrics. What is defensible is their *shape*: where
the largest dropoff sits, which patterns dominate, and how the failure
modes are distributed. Every synthesized number is traceable to a public
signal or a documented rationale (`inputs/PHASE_2_NOTES.md`). Endpoints and
error codes in the traces are real and were validated against the OpenAPI
surface and error catalog.

## The friction surface, in plain terms

Six recurring ways developers stall moving a connected account toward
`charges_enabled`. These are drawn from public signal — stripe-python
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
attributes the runtime object doesn't always carry (e.g. accessing
`tos_acceptance.service_agreement` on an account whose agreement isn't
`recipient` raises `AttributeError`), and input parameter shapes don't
always round-trip with output shapes. Gating logic written against the
typed model crashes on paths the type hints said were safe.

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
a signed-up seller is a `Customer`, a connected `Account`, or a `Person` on
an account, so the onboarding sequence is mis-rooted from the first call.

One signal worth calling out because it is a *negative* one. Searching the
`stripe-python` issue tracker for `charges_enabled` returns nothing: the
"my account won't enable" problem produces almost no SDK bug reports. It
produces Stack Overflow questions, Support tickets, and conceptual
confusion instead. That absence is itself evidence — the dominant friction
is not a code defect developers can file against the library; it is a
mental-model gap upstream of the code. A diagnosis that located this in the
SDK's exception surface would be looking in the wrong place, and the
findings below reflect that: the largest one is about what a *successful*
response fails to communicate, not about an error.

## What the diagnostic run surfaced

Two lenses run against the same product surface. The funnel lens reads the
dropoff numbers and explains *why* developers fall off at the target step.
The trace lens reads the call sequences and explains *where* integrations
get stuck. Then the cross step reports where the two independently agree.

Findings carry a layer tag in parentheses — the surface the defect lives in
(2 = API/SDK, 3 = docs-at-decision-time, 4 = integration call sequence).
Citations point into `inputs/product/`.

### Funnel-side findings

**H1 — A `200` from `POST /v1/accounts` is not progress (Layer 2).**
The largest dropoff bucket is developers who submit the fields named in
`requirements.currently_due`, get a `200` back with the updated `Account`,
and treat that as "submitted, awaiting Stripe." Nothing in the SDK signals
that the caller must re-read `requirements.currently_due` (and
`requirements.errors[]`) on the returned object, and that an unchanged
`currently_due` after a `200` is the actual failure signal.
`sdk/stripe/_account.py:1155` declares `Requirements.currently_due` as
`Optional[List[str]]`, documented (the following lines) only as "Fields
that need to be resolved to keep the account enabled" — with no indication
that it is the post-write verification surface a caller must diff after
every successful write. Surfaces: the silent gate. Proposes an applyable SDK
docstring/comment documenting the required post-write protocol.

**H2 — Per-capability requirements is a separate, undocumented gate
(Layer 2).** Developers who clear `Account.requirements.currently_due`
reasonably believe they're done — but a requested capability has its *own*
`requirements` hash that is not mirrored onto the account.
`docs/capabilities.md:431` states "If a connected account has both
`card_payments` and `transfers`, and the `status` of either one is
`inactive`, then both capabilities are disabled" — the exact coupling that
bites, buried in a "Multiple capabilities" subsection rather than at the
point where developers check whether onboarding is complete. The funnel's
own success criterion only checks the account-level hash, so the funnel
shares the developer's blind spot. Surfaces: capability coupling.

**H3 — `pending_verification` resolution isn't surfaced where developers
look (Layer 3).** A distinct bucket: developers who did submit, saw Stripe
accept it, watched the account move into asynchronous verification, and
quit fast (the lowest call-count-before-quit of any bucket). The
`account.updated` webhook is mentioned once at `docs/persons.md:22` as item
one of a three-item list, not co-located with the troubleshooting tables a
developer lands on when an account appears stuck. Surfaces: the silent
gate (asynchronous tail).

### Trace-side findings

**F1 — Read `currently_due`, never POST it back (Layer 4).** Three of seven
integrations create an account, read the requirements once, then issue only
GET requests forever — waiting for a state transition the API cannot make
without their submission. 57 of 150 cohort calls. The hosted-onboarding
worked example at `docs/hosted_vs_custom.md:88` ends at the account-creation
curl with no follow-up POST shown; the only place the post-create loop is
named (`docs/persons.md:21`) is buried in the API-verification guide a
developer following the quickstart never reaches. Surfaces: the silent
gate; the account-link handoff loop. Proposes an applyable docs edit.

**F2 — Indefinite `pending_verification` polling (Layer 3).** Integrations
that did submit correctly then poll `GET /v1/accounts/{account}` on
multi-hour intervals against an unchanging
`disabled_reason=requirements.pending_verification`, with no fresh signal,
because the docs and SDK don't establish that `account.updated` is the
channel during asynchronous review. The trace-side image of H3. Surfaces:
the silent gate (asynchronous tail).

**F3 — Re-POST the same rejected document (Layer 2).** An integration
receives `requirements.errors=[verification_document_failed_greyscale]` and
responds by re-uploading the same document shape, then stalls — it has the
error code but not the corrective action. The friction is real. The
finding's load-bearing claim about *why* — "there is no error catalog in
the product artifacts at all" — is not. See **What triage caught**, below.

### The applyable edits

Four of the six findings carry an applyable structured edit (one-file,
mechanical); two are marked not-applyable with a reason. The two that
target the convergence defect, in plain form:

**H1** inserts a comment block above `Account.modify` /
`modify_async` in `sdk/stripe/_account.py` stating that a `200` does not
mean `currently_due` is cleared, and naming the required post-write
protocol: re-read `requirements.currently_due`; read
`requirements.errors[]` for per-field validation failures; separately read
each requested capability's own `requirements` hash; subscribe to
`account.updated` for the asynchronous transitions.

**F1** inserts a "What to do with the create response" subsection into
`docs/hosted_vs_custom.md` immediately after the account-creation example,
stating that `requirements.currently_due` is the integration's worklist —
not a status display — and that the account does not progress until those
fields are POSTed back via `/v1/accounts/{account}` or
`/v1/accounts/{account}/persons`, with polling explicitly called out as
insufficient.

Both edits say the same thing in two places — the SDK call site and the
onboarding doc — because the defect shows up in both. F3's edit is marked
not-applyable; its stated reason ("requires authoring a new error catalog")
is itself the false premise triage caught.

### Cross-tool findings

| Tool | Layer 2 | Layer 3 | Layer 4 | Total |
|---|---|---|---|---|
| funnel lens | 2 | 1 | 0 | 3 |
| trace lens | 1 | 1 | 1 | 3 |

Five cross-tool matches, one unique finding (H2, funnel-only), none unique
to the trace lens. The cross step preserved H2 rather than dropping it: the
trace cohort encoded capability coupling in a single integration that the
trace lens folded into F1, so only the funnel lens kept it as a distinct
finding. Keeping a real single-lens finding instead of discarding it is
exactly what the cross step is for.

## Cross-tool convergence as the credibility result

The point of running two lenses is not redundancy. It is that two disjoint
data sources, given no shared inputs, land on the same defect when the
defect is real.

The funnel lens sees only numbers: a collapse from `requirements_collected`
to `requirements_satisfied` (a 63.4% pass rate, the worst transition in the
funnel by a wide margin — the next-worst is 85%), with the dropoff
concentrated in two buckets that share one mechanism — 34% "submitted,
nothing changed, abandoned" plus 14% "POST returned 200 but `currently_due`
unchanged," about half the dropoff at the step. From that alone it
concludes: a `200` is not progress; the gate is data the developer must
re-read (H1).

The trace lens sees only call sequences: three of seven integrations that
create an account, read requirements once, and then GET-poll forever
without ever POSTing the fields back — 57 of 150 cohort calls (F1). From
that alone it concludes the same thing — the integrations are waiting for a
transition the API cannot make without a submission they never send.

Neither lens was given the other's input. They converge because the
underlying defect — the surface does not make "a `200` is not progress"
legible at the call site — is real, and it shows up as both a dropoff shape
and a trace shape. That convergence is the credibility result. The fixture
example shows the cross machinery works; this shows it converges on a real
production defect.

The cohort includes one integration that reaches `charges_enabled` cleanly
— it reads `currently_due`, POSTs the fields back, polls correctly, and
flips. That contrast matters: without a success path in the data, a
diagnosis of the failures would be unfalsifiable. The findings describe how
the seven diverge from the one, not a uniform population that fails for
unstated reasons.

One honest caveat about the matches. Four of the five cross-matches resolve
to the same file, `docs/persons.md` (Stripe's "Handle verification with the
API" guide). That is where the Connect onboarding friction surface
concentrates its citable evidence, so both lenses cite it in common. The
convergence on the *diagnosis* is independent; the *file clustering* of the
matches is not. It does not weaken the H1/F1 agreement — they reach the
same conclusion from different data — but the five matches should be read
as one strong convergence plus file-clustered restatements, not five
independent corroborations.

## What triage caught

Of six findings, five hold up against the public signal. One —  F3 — is
borderline, and it is the most instructive result in the run.

F3 surfaces a real friction pattern: developers re-POST a rejected
verification document without enough information to fix it (errors that
name the prohibition, not the fix). That pattern is grounded in the public
signal and the error catalog.

But F3's load-bearing explanation is false. It claims "there is no error
catalog in the product artifacts at all" and proposes, as its primary fix,
authoring a new `errors.md`. There already is one:
`inputs/product/errors.md` is part of the product surface, 201 lines, 91
entries — and it contains the exact row in question:

```
inputs/product/errors.md:173
| `verification_document_failed_greyscale` | Submitted ID document is
greyscale. | Re-collect a color document scan/photo. | https://docs.stripe.com/connect/handling-api-verification.md |
```

Three things this surfaces, named cleanly:

1. **The friction is real.** Errors that name the prohibition rather than
   the corrective action is a documented pattern in the public signal.
   That part of F3 stands.
2. **The proposed fix is moot.** "Author a new `errors.md`" addresses a
   file that already exists with the needed content. Applying it would
   build something already present.
3. **The harness has a real loader gap.** The diagnostic product loader
   ingested `docs/`, `sdk/`, and the OpenAPI surface but did not pick up a
   top-level `errors.md`. The trace lens reports `[no error catalog found]`;
   the funnel lens never cites `errors.md` either. This is a finding about
   the diagnostic harness, not about Stripe.

This is shipped as-is, with the gap unfixed, on purpose. Triage caught the
false premise before the finding propagated: the REAL/BORDERLINE/SPURIOUS
check — "does this match the public signal and the actual surface" —
rejected F3's explanation and its proposed fix automatically, and the same
check located the harness defect that produced the false premise. The
discipline caught its own harness bug. That is the methodology working as
designed, and it is more useful preserved than papered over.

The loader gap will be fixed in Pluma separately. This run is kept as the
canonical evidence of the methodology catching a harness defect through
ordinary triage. The practical consequence for reading this example: the
run did not exercise the full product surface — `errors.md` was present but
not ingested — so a re-run after the loader fix would be needed before
claiming the methodology consumed the entire real surface.

## How to reproduce this run

From this directory (`pluma/examples/stripe/`). `inputs/product/` is the
real Stripe surface; `inputs/funnel.yaml`, `inputs/dropoff_data.json`,
`inputs/integration_cohort.yaml`, and `inputs/traces.jsonl` are the
synthesized cohort signal (rationale in `inputs/PHASE_2_NOTES.md`).

```bash
# Funnel lens — why developers drop at the target step
pluma diagnose-funnel \
  --product  inputs/product/ \
  --funnel   inputs/funnel.yaml \
  --dropoff  inputs/dropoff_data.json \
  --output-file outputs/funnel_diagnosis.md

# Trace lens — where the 7-integration cohort gets stuck
pluma watch \
  --product  inputs/product/ \
  --traces   inputs/traces.jsonl \
  --cohort   inputs/integration_cohort.yaml \
  --output-file outputs/integration_findings.md

# Cross — where the two lenses independently agree
pluma cross \
  --product  inputs/product/ \
  --funnel   inputs/funnel.yaml \
  --dropoff  inputs/dropoff_data.json \
  --traces   inputs/traces.jsonl \
  --cohort   inputs/integration_cohort.yaml \
  --output-file outputs/cross.md
```

The two lens runs are live model calls (≈$4–8 total on Opus 4.7; the
harness records no token telemetry, so treat that as an estimate, not a
meter reading). Each takes a couple of minutes — roughly five minutes wall
time for both. `cross` is free: both lens legs hit
`~/.pluma/cache/` on identical inputs, so only normalization and the
cross-match run, in well under a second. Re-running the exact commands
re-emits the same reports from cache at zero spend.

The outputs in `outputs/` are the actual reports from this run, not
regenerated samples.

## Inputs and audit trail

The product surface and the synthesized cohort each have an internal record
of what was selected and why. These are the audit trail; they are not
required reading to use the example.

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
- `outputs/triage.md` — the per-finding REAL / BORDERLINE / SPURIOUS
  analysis, including the full account of the F3 borderline and the loader
  gap.
- `outputs/funnel_diagnosis.md`, `outputs/integration_findings.md`,
  `outputs/cross.md` — the run outputs cited throughout this document.

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
- Because of the loader gap, this run did not consume the entire product
  surface. The convergence result (H1/F1) does not depend on the missing
  file; the F3 borderline is a direct consequence of it.
