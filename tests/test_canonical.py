"""Canonical JSON conformance tests.

The expected ``canonical`` strings in ``spec/canonical-vectors.json`` are
written *by hand* from the rules in ``spec/FORMAT.md`` — they are not generated
by this implementation. Passing therefore means agreeing with the spec, not
with ourselves.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ailog.bridge.localchain import _leaf_hash, _stable_json, interaction_record
from ailog.core.canonical import (
    MAX_SAFE_INTEGER,
    CanonicalJSONError,
    canonical_json,
    canonical_sha256,
    loads_strict,
)
from ailog.core.models import ContentType, Interaction, Message, Role

VECTORS_PATH = Path(__file__).resolve().parents[1] / "spec" / "canonical-vectors.json"
_DOC = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
VECTORS = _DOC["vectors"]
VALID = [v for v in VECTORS if not v.get("invalid")]
INVALID = [v for v in VECTORS if v.get("invalid")]

VALID_IDS = [v["id"] for v in VALID]
INVALID_IDS = [v["id"] for v in INVALID]


def test_vectors_file_is_well_formed():
    assert _DOC["spec_version"] == "0.1"
    assert len(VECTORS) >= 10
    assert VALID and INVALID
    for vector in VECTORS:
        assert vector["id"] and vector["why"]
        assert ("canonical" in vector) != bool(vector.get("invalid"))


@pytest.mark.parametrize("vector", VALID, ids=VALID_IDS)
def test_canonical_json_matches_vector(vector):
    assert canonical_json(vector["input"]) == vector["canonical"]


@pytest.mark.parametrize("vector", VALID, ids=VALID_IDS)
def test_vector_hash_is_self_consistent(vector):
    """Guards against a typo in the vectors file itself."""
    digest = hashlib.sha256(vector["canonical"].encode("utf-8")).hexdigest()
    assert digest == vector["sha256"]


@pytest.mark.parametrize("vector", VALID, ids=VALID_IDS)
def test_canonical_sha256_matches_vector(vector):
    assert canonical_sha256(vector["input"]) == vector["sha256"]


@pytest.mark.parametrize("vector", INVALID, ids=INVALID_IDS)
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(CanonicalJSONError):
        canonical_json(vector["input"])


# --------------------------------------------------------------------------
# rules that no JSON literal can express, so they need code-level tests
# --------------------------------------------------------------------------


def test_duplicate_keys_are_rejected_by_loads_strict():
    with pytest.raises(CanonicalJSONError):
        loads_strict('{"a":1,"a":2}')


def test_loads_strict_accepts_a_clean_document():
    assert loads_strict('{"a":1,"b":[2,3]}') == {"a": 1, "b": [2, 3]}


@pytest.mark.parametrize(
    "value",
    [
        {"a": {"b": [1, 2.0]}},          # nested float
        {"a": float("nan")},
        {"a": float("inf")},
        {"a": 9007199254740992},          # 2**53, one past the safe ceiling
        {"a": -9007199254740992},
        {1: "non-string key"},            # C2
        {"a": object()},                  # unsupported type
    ],
    ids=["nested-float", "nan", "inf", "int-too-big", "int-too-small", "int-key", "object"],
)
def test_hashing_domain_rejects_bad_values(value):
    with pytest.raises(CanonicalJSONError):
        canonical_json(value)


def test_safe_integer_boundary_is_accepted():
    assert canonical_json({"n": MAX_SAFE_INTEGER}) == '{"n":9007199254740991}'
    assert canonical_json({"n": -MAX_SAFE_INTEGER}) == '{"n":-9007199254740991}'


def test_absent_optional_fields_are_omitted_not_nulled():
    assert canonical_json({"a": 1, "b": None}) == '{"a":1,"b":null}'
    # C6 is about *absent* fields; an explicit null is preserved on purpose.
    assert canonical_json({"a": 1}) == '{"a":1}'


# --------------------------------------------------------------------------
# the bridge must route through Canonical JSON, not its own serializer
# --------------------------------------------------------------------------


def _record():
    interaction = Interaction(
        id="ix_01",
        timestamp="2026-06-18T00:00:01Z",
        session_id="s1",
        turn_index=0,
        messages=[
            Message(role=Role.USER, content_type=ContentType.TEXT, content="hi"),
            Message(role=Role.ASSISTANT, content_type=ContentType.TEXT, content="hello"),
        ],
    )
    return interaction_record(interaction, "0.1")


def test_bridge_stable_json_delegates_to_canonical_json():
    record = _record()
    assert _stable_json(record) == canonical_json(record)


def test_bridge_leaf_hash_is_canonical_sha256():
    record = _record()
    assert _leaf_hash(record) == canonical_sha256(record)


def test_leaf_hash_is_key_order_independent():
    """The whole point of the spec: same record, different key order, same hash."""
    a = {"type": "ailog.interaction", "id": "ix_01", "turn_index": 0}
    b = {"turn_index": 0, "id": "ix_01", "type": "ailog.interaction"}
    assert canonical_sha256(a) == canonical_sha256(b)

# --------------------------------------------------------------------------
# the spec document and the vectors must not drift apart
# --------------------------------------------------------------------------


def test_spec_documents_all_canonical_rules():
    spec_path = VECTORS_PATH.parent / "FORMAT.md"
    spec = spec_path.read_text(encoding="utf-8")
    assert "## Canonical JSON" in spec, "spec lost its Canonical JSON section"
    for rule in ("C1", "C2", "C3", "C4", "C5", "C6", "C7"):
        assert f"**{rule}**" in spec, f"rule {rule} is not documented"
    assert "spec/canonical-vectors.json" in spec, "spec does not point at the vectors"
