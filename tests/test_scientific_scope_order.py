"""Review is an unordered claim set; original declarations keep their order."""

from copy import deepcopy
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog, snapshot_reaction, snapshot_state
from reactgen.pipeline import analyze
from reactgen.records import (
    normalized_dataset,
    scientific_dataset_content,
    scientific_reaction_content,
    scientific_state_content,
)

SOURCE = {"provider": "laboratory", "collection": "observations", "release": "v1"}
SCOPES = ["state_existence", "channel_assertion", "rate_coefficient"]


def _record(kind: str, *, native: bool) -> dict:
    common = {
        "source": SOURCE | ({"record_id": "native-1"} if native else {}),
        "review_scope": SCOPES,
        "status": "reviewed",
        "source_declaration": {"review_scope": SCOPES, "state_sequence": ["lower", "upper"]},
    }
    if kind == "state":
        return common | {"species": "Ar@ground", "phase": "gas", "existence": "confirmed"}
    common |= {"reaction": "Ar + Ar -> Ar + Ar", "type": "elastic"}
    if kind == "numeric":
        common |= {"form": "constant", "unit": "m3/s", "parameters": {"value": 1e-15}}
    return common


def _normalize(kind: str, entry: dict):
    if kind == "state":
        record = snapshot_state(entry, {})
        assert record is not None
        return record.record_id, scientific_state_content(record), record.source_declaration
    if kind == "numeric":
        record = normalized_dataset(entry)
        return record.id, scientific_dataset_content(record), record.source_declaration
    record = snapshot_reaction(entry, datasets=())
    assert record is not None
    return record.id, scientific_reaction_content(record), record.source_declaration


@pytest.mark.parametrize("kind", ["state", "numeric", "reaction"])
@pytest.mark.parametrize("native", [True, False])
def test_scope_order_does_not_change_identity_or_scientific_comparison(kind, native) -> None:
    original = _record(kind, native=native)
    changed = deepcopy(original)
    changed["review_scope"] = list(reversed(SCOPES))
    changed["source_declaration"]["review_scope"] = list(reversed(SCOPES))
    before = deepcopy(original)
    left_id, left_content, left_raw = _normalize(kind, original)
    right_id, right_content, right_raw = _normalize(kind, changed)
    assert left_id == right_id
    assert left_content == right_content
    assert left_raw != right_raw
    assert original == before
    assert left_raw["review_scope"] == SCOPES
    assert right_raw["review_scope"] == list(reversed(SCOPES))
    # Unknown sequence semantics must not be erased by blanket list sorting.
    changed["source_declaration"]["state_sequence"].reverse()
    assert _normalize(kind, changed)[1] != left_content
    if not native:
        assert _normalize(kind, changed)[0] != left_id


def _write(path: Path, content: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(content), encoding="utf-8")
    return path


@pytest.mark.parametrize("kind", ["state", "numeric", "reaction"])
def test_scope_order_reacquisition_preserves_both_original_declarations(tmp_path, kind) -> None:
    root = tmp_path / "registry"
    species_path = _write(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "phase": "gas", "state": {"kind": "ground"}},
    )
    channel_path = _write(
        root / "reactions" / "neutral" / "pair.yaml",
        {
            "pair": {"family": "neutral", "projectile": "Ar", "target": "Ar"},
            "channels": [
                {"id": "elastic", "type": "elastic", "products": [{"species": "Ar", "n": 2}]}
            ],
        },
    )
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    original = _record(kind, native=True)
    changed = deepcopy(original)
    changed["review_scope"] = list(reversed(SCOPES))
    changed["source_declaration"]["review_scope"] = list(reversed(SCOPES))
    paths = (
        _write(tmp_path / "first.yaml", {"records": [original]}),
        _write(tmp_path / "second.yaml", {"records": [changed]}),
    )
    overlay = tmp_path / "overlay.yaml"
    for path in (*paths, paths[1]):
        report = ingest.ingest(path, tmp_path / "bundle", overlay)
        assert report.accepted == 1
        assert not report.review
    assert adopt.adopt(overlay, root).values == (4 if kind == "numeric" else 2)
    assert adopt.adopt(overlay, root).values == 0
    if kind == "state":
        records = yamlio.load(species_path.read_text(encoding="utf-8"))["records"]
    else:
        channel = yamlio.load(channel_path.read_text(encoding="utf-8"))["channels"][0]
        records = channel["data"]["datasets"] if kind == "numeric" else channel["records"]
    assert len(records) == 2
    assert {tuple(record["source_declaration"]["review_scope"]) for record in records} == {
        tuple(SCOPES),
        tuple(reversed(SCOPES)),
    }
