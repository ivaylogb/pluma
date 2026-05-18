"""Internal self-consistency of src/pluma/api/openapi.yaml.

The v0.1 HTTP API spec is intentionally a *subset* of agent-diagnosis-spec
v0.2 (rich schema, honest v0.1 population — see the spec's "API v0.1
capability vs schema" table), so we do NOT assert cross-spec equivalence
with agent-diagnosis-spec here. We assert the spec is consistent with
itself and with the Pydantic models that implement it:

  1. every example value matches its own schema's pattern;
  2. every required field on the core schemas exists on the matching
     Pydantic model in pluma.api.models;
  3. every $ref in the document resolves (no dangling references).

If the spec file is unreachable the test FAILS with a clear message — it
does not skip or silently pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import pluma.api.models as models

SPEC_PATH = Path(models.__file__).parent / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict:
    if not SPEC_PATH.is_file():
        pytest.fail(
            f"Canonical OpenAPI spec not found at {SPEC_PATH}. The API "
            "package must ship openapi.yaml (see pyproject package-data)."
        )
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert text.lstrip().startswith("#"), "missing canonical top comment"
    return yaml.safe_load(text)


def _resolve(doc: dict, ref: str):
    assert ref.startswith("#/"), f"unsupported $ref: {ref}"
    node = doc
    for part in ref[2:].split("/"):
        assert isinstance(node, dict) and part in node, f"dangling $ref: {ref}"
        node = node[part]
    return node


def _walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for v in node.values():
            _walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn)


# ---- 1. examples match their schema's pattern ----------------------------


def test_scalar_examples_match_their_patterns(spec):
    schemas = spec["components"]["schemas"]

    job_pat = schemas["JobId"]["pattern"]
    assert re.match(job_pat, schemas["JobId"]["example"])

    req_hdr = spec["components"]["headers"]["RequestId"]["schema"]
    assert re.match(req_hdr["pattern"], req_hdr["example"])

    idem = spec["components"]["parameters"]["IdempotencyKey"]["schema"]
    assert re.match(idem["pattern"], idem["example"])
    assert idem["minLength"] <= len(idem["example"]) <= idem["maxLength"]

    err_rid = schemas["Error"]["properties"]["request_id"]
    assert re.match(err_rid["pattern"], err_rid["example"])


def test_embedded_example_ids_match_canonical_patterns(spec):
    job_pat = spec["components"]["schemas"]["JobId"]["pattern"]
    req_pat = spec["components"]["schemas"]["Error"]["properties"][
        "request_id"
    ]["pattern"]

    seen = {"job_id": 0, "request_id": 0}

    def check(node: dict):
        for key, pat, label in (
            ("job_id", job_pat, "job_id"),
            ("request_id", req_pat, "request_id"),
        ):
            if key in node and isinstance(node[key], str) and node[
                key
            ].startswith(("job_", "req_")):
                assert re.match(pat, node[key]), f"{label}={node[key]!r}"
                seen[label] += 1

    _walk(spec["paths"], check)
    # Sanity: the spec really does carry embedded examples we validated.
    assert seen["job_id"] > 0 and seen["request_id"] > 0


# ---- 2. required spec fields exist on the implementing models ------------

# Spec schema name → implementing Pydantic model.
_SCHEMA_TO_MODEL = {
    "CreateJobRequest": models.CreateJobRequest,
    "BraintrustSource": models.BraintrustSource,
    "LangSmithSource": models.LangSmithSource,
    "PostHogSource": models.PostHogSource,
    "Job": models.Job,
    "JobFindings": models.JobFindings,
    "FailingEvalContainer": models.FailingEvalContainer,
    "FailingEval": models.FailingEval,
    "Citation": models.Citation,
    "Edit": models.Edit,
    "Error": models.Error,
}

# Models whose spec-required fields are client-supplied inputs and so must
# be *required* (no default) on the model, not merely present.
_INPUT_MODELS = {
    "CreateJobRequest",
    "BraintrustSource",
    "LangSmithSource",
    "PostHogSource",
    "Citation",
    "Edit",
}


def test_required_fields_present_on_models(spec):
    schemas = spec["components"]["schemas"]
    for name, model in _SCHEMA_TO_MODEL.items():
        required = schemas[name].get("required", [])
        fields = model.model_fields
        for field in required:
            assert field in fields, (
                f"{name}.{field} required by spec but missing from "
                f"{model.__name__}"
            )
            if name in _INPUT_MODELS:
                assert fields[field].is_required(), (
                    f"{name}.{field} is spec-required input but optional "
                    f"on {model.__name__}"
                )


def test_jobstatus_enum_matches_spec(spec):
    spec_values = spec["components"]["schemas"]["JobStatus"]["enum"]
    model_values = [s.value for s in models.JobStatus]
    assert sorted(spec_values) == sorted(model_values)


def test_failingeval_category_enum_matches_model(spec):
    spec_cat = spec["components"]["schemas"]["FailingEval"]["properties"][
        "category"
    ]["enum"]
    # The Literal on FailingEval.category, in declaration order.
    model_cat = list(
        models.FailingEval.model_fields["category"].annotation.__args__
    )
    assert sorted(spec_cat) == sorted(model_cat)


# ---- 3. every $ref resolves ----------------------------------------------


def test_all_refs_resolve(spec):
    refs: list[str] = []

    def collect(node: dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            refs.append(node["$ref"])

    _walk(spec, collect)
    assert refs, "spec has no $refs — unexpected"
    for ref in refs:
        _resolve(spec, ref)  # asserts on dangling


def test_every_endpoint_response_schema_is_reachable(spec):
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method == "parameters":
                continue
            for code, resp in op.get("responses", {}).items():
                resp_node = resp
                if "$ref" in resp_node:
                    resp_node = _resolve(spec, resp_node["$ref"])
                content = resp_node.get("content", {})
                for media in content.values():
                    schema = media.get("schema", {})
                    if "$ref" in schema:
                        _resolve(spec, schema["$ref"])
