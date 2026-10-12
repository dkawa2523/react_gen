"""Source-local native IDs cannot collide with unrelated numerical records."""

from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import data_use
from reactgen.pipeline import analyze
from reactgen.records import normalized_dataset, scientific_record_id
from reactgen.registry import Registry
from reactgen.selection import DataSelection

REACTION = ReactionCandidate(
    "test",
    (Term("Ar@ground", 2),),
    (Term("Ar@ground", 2),),
    "neutral",
    "elastic",
    "test",
    "test",
    0,
)
SOURCE = {"provider": "database-a", "collection": "rates", "release": "v1"}


def _record(value: float = 1e-15) -> dict:
    return {
        "reaction": "Ar + Ar -> Ar + Ar",
        "type": "elastic",
        "status": "reviewed",
        "method": "measured",
        "form": "constant",
        "unit": "m3/s",
        "reaction_order": 2,
        "parameters": {"value": value},
        "independent_variable": "gas_temperature",
        "validity": {
            "quantity": "gas_temperature",
            "minimum": 300,
            "maximum": 1000,
            "unit": "K",
        },
        "source": {"record_id": "1"},
    }


def _write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


def _snapshot(path: Path, source: dict, record: dict | None = None) -> Path:
    return _write(
        path,
        {
            "snapshot_version": 1,
            "kind": "rate_coefficient",
            "source": source,
            "records": [_record() if record is None else record],
        },
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"provider": "database-b"},
        {"collection": "other-rates"},
        {"release": "v2"},
        {"source_id": "different-source-document"},
    ],
)
def test_native_ids_are_scoped_by_stated_source_identifiers(changed) -> None:
    first = normalized_dataset(_record(), default_source=SOURCE)
    second = normalized_dataset(_record(), default_source=SOURCE | changed)
    assert first.provenance.record_id == second.provenance.record_id == "1"
    assert first.id != second.id
    assert first.id.startswith("source-dataset:")


def test_top_level_native_record_id_is_not_a_canonical_dataset_id() -> None:
    nested = normalized_dataset(_record(), default_source=SOURCE)
    top_level = normalized_dataset(
        _record() | {"source": {}, "record_id": "1"}, default_source=SOURCE
    )
    assert nested.id == top_level.id
    assert top_level.id != "1"
    assert scientific_record_id({"record_id": "state-native-id"}) == "state-native-id"


def test_explicit_canonical_dataset_ids_are_preserved() -> None:
    first = normalized_dataset(_record() | {"id": "canonical"}, default_source=SOURCE)
    second = normalized_dataset(
        _record() | {"id": "canonical"}, default_source=SOURCE | {"provider": "database-b"}
    )
    assert first.id == second.id == "canonical"


@pytest.mark.parametrize("identifier", ["", " ", True, 1])
def test_malformed_explicit_dataset_ids_fail_at_the_boundary(identifier) -> None:
    with pytest.raises(ValueError, match="dataset.id"):
        normalized_dataset(_record() | {"id": identifier}, default_source=SOURCE)


def test_content_ids_include_default_source_when_a_native_id_is_absent() -> None:
    record = _record() | {"source": {}}
    first = normalized_dataset(record, default_source=SOURCE)
    second = normalized_dataset(record, default_source=SOURCE | {"provider": "database-b"})
    assert first.id != second.id
    assert first.id.startswith("local-dataset:")
    assert first.id == normalized_dataset(record, default_source=SOURCE).id


def test_distinct_snapshot_sources_remain_selectable_with_matching_native_ids(tmp_path) -> None:
    first = _snapshot(tmp_path / "one.yaml", SOURCE)
    second = _snapshot(tmp_path / "two.yaml", SOURCE | {"provider": "database-b"})
    copied = _snapshot(tmp_path / "moved" / "renamed.yaml", SOURCE)
    first_data = EvidenceCatalog.load_paths((first,)).reaction(REACTION).datasets[0]
    assert first_data.id == EvidenceCatalog.load_paths((copied,)).reaction(REACTION).datasets[0].id
    combined = EvidenceCatalog.load_paths((first, second))
    request = DataSelection.from_document(
        {"quantities": {"rate_coefficient": {"mode": "only", "providers": ["database-a"]}}}
    )
    use = data_use(
        REACTION,
        combined.reaction(REACTION),
        Conditions(gas_temperature_K=350),
        request,
    )
    assert use.status == "coefficient"
    assert use.dataset_id == first_data.id
    assert len(use.datasets) == 2
    assert all(item.status == "valid" for item in use.datasets)


def test_changed_content_with_one_native_identity_stays_a_conflict(tmp_path) -> None:
    first = _snapshot(tmp_path / "one.yaml", SOURCE)
    changed = _snapshot(tmp_path / "two.yaml", SOURCE, _record(2e-15))
    first_data = EvidenceCatalog.load_paths((first,)).reaction(REACTION).datasets[0]
    changed_data = EvidenceCatalog.load_paths((changed,)).reaction(REACTION).datasets[0]
    assert first_data.id == changed_data.id
    use = data_use(
        REACTION,
        EvidenceCatalog.load_paths((first, changed)).reaction(REACTION),
        Conditions(gas_temperature_K=350),
    )
    assert use.status == "conflict"
    assert use.disagreements == (first_data.id,)
    assert use.datasets[0].reason == "same ID has different content"


def test_native_identity_survives_snapshot_ingest_adoption_and_repeat_reads(tmp_path) -> None:
    root = tmp_path / "registry"
    _write(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "phase": "gas", "state": {"kind": "ground"}},
    )
    _write(
        root / "reactions" / "neutral" / "pair.yaml",
        {
            "pair": {"family": "neutral", "projectile": "Ar", "target": "Ar"},
            "channels": [
                {"id": "elastic", "type": "elastic", "products": [{"species": "Ar", "n": 2}]}
            ],
        },
    )
    case = Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=350))
    export.write(tmp_path / "bundle", analyze(case, EvidenceCatalog.load(root)))
    snapshot = _snapshot(tmp_path / "source.yaml", SOURCE)
    direct = EvidenceCatalog.load_paths((snapshot,)).reaction(REACTION).datasets[0]
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(snapshot, tmp_path / "bundle", overlay).accepted == 1
    via_ingest = next(iter(EvidenceCatalog.load(None, overlay).overlay_datasets.values()))[0]
    assert via_ingest == direct
    assert adopt.adopt(overlay, root).values == 2
    adopted = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets[0]
    assert adopted == direct
    assert adopt.adopt(overlay, root).values == 0


def test_legacy_anonymous_registry_container_ids_are_retained() -> None:
    record = _record() | {"source": {}}
    assert normalized_dataset(record, default_id="legacy-container").id == "legacy-container"
    identified = normalized_dataset(record, default_id="legacy-container", default_source=SOURCE)
    assert identified.id != "legacy-container"
