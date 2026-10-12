"""Reacquisition preserves numerical meaning and every original declaration."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from acquire import snapshot
from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import data_use
from reactgen.pipeline import analyze
from reactgen.records import (
    normalized_dataset,
    scientific_dataset_content,
    scientific_record_id,
)
from reactgen.registry import Registry

SOURCE = {"provider": "laboratory", "collection": "rates", "release": "v1"}
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


def _record(*, native: bool = True) -> dict:
    return {
        "reaction": "Ar + Ar -> Ar + Ar",
        "type": "elastic",
        "form": "constant",
        "unit": "m3/s",
        "reaction_order": 2,
        "parameters": {"value": 1e-15},
        "independent_variable": "gas_temperature",
        "validity": {"quantity": "gas_temperature", "minimum": 300, "maximum": 500, "unit": "K"},
        "status": "reviewed",
        "method": "measured",
        "source": {"record_id": "native-1"} if native else {},
        "source_declaration": {"native_condition": {"pressure_Pa": 10}},
    }


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(body), encoding="utf-8")
    return path


def _acquired_snapshot(directory: Path, index: int, record: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / f"input-{index}.txt"
    raw.write_bytes(b"identical original source bytes")
    _write(
        directory / "acquisition.yaml",
        SOURCE
        | {
            "file": raw.name,
            "sha256": sha256(raw.read_bytes()).hexdigest(),
            "requested_url": f"https://example.invalid/request/{index}",
            "final_url": f"https://example.invalid/response/{index}",
            "retrieved_at": f"2026-10-1{index}T00:00:00Z",
            "original_access_note": f"operation {index}",
        },
    )
    return snapshot.write(
        directory / "converted", "rate_coefficient", SOURCE, [record], input_path=raw
    )


def _use(catalog: EvidenceCatalog):
    return data_use(REACTION, catalog.reaction(REACTION), Conditions(gas_temperature_K=350))


@pytest.mark.parametrize("identity", ["native", "anonymous", "canonical"])
def test_reacquisition_keeps_one_number_and_all_context_in_public_output(
    tmp_path, identity
) -> None:
    record = _record(native=identity == "native")
    if identity == "canonical":
        record["id"] = "canonical-global-id"
    first = _acquired_snapshot(tmp_path / "first", 1, record)
    second = _acquired_snapshot(tmp_path / "renamed-copy", 2, record)
    catalog = EvidenceCatalog.load_paths((first, second))
    datasets = catalog.reaction(REACTION).datasets
    assert len(datasets) == 2
    assert datasets[0].id == datasets[1].id
    assert datasets[0].source_declaration != datasets[1].source_declaration
    use = _use(catalog)
    assert use.status == "coefficient"
    assert use.value == pytest.approx(1e-15)
    assert len(use.datasets) == 1
    assert not use.disagreements

    result = analyze(Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=350)), catalog)
    export.write(tmp_path / "public", result)
    document = export.read(tmp_path / "public", verify_views=True)
    selected = next(item for item in document["reactions"] if item["data_use"]["dataset_id"])
    assert selected["data_use"]["value"] == pytest.approx(1e-15)
    saved = [item for row in selected["evidence"]["records"] for item in row["datasets"]]
    assert {
        item["source_declaration"]["snapshot_source"]["acquisition"]["input_name"] for item in saved
    } == {"input-1.txt", "input-2.txt"}
    assert all(
        item["source_declaration"]["native_condition"] == {"pressure_Pa": 10} for item in saved
    )


@pytest.mark.parametrize("change", ["quantity", "method", "tier", "unknown-condition"])
def test_scientific_changes_to_one_native_record_are_still_conflicts(tmp_path, change) -> None:
    original = _record()
    changed = deepcopy(original)
    if change == "quantity":
        changed["parameters"]["value"] = 2e-15
    elif change == "method":
        changed["method"] = "calculated"
    elif change == "tier":
        changed["status"] = "imported"
    else:
        changed["source_declaration"]["native_condition"]["pressure_Pa"] = 20
    paths = (
        _acquired_snapshot(tmp_path / "first", 1, original),
        _acquired_snapshot(tmp_path / "second", 2, changed),
    )
    use = _use(EvidenceCatalog.load_paths(paths))
    assert use.status == "conflict"
    assert use.datasets[0].reason == "same ID has different content"


def test_reserved_acquisition_paths_are_ignored_without_mutating_declarations() -> None:
    first = _record(native=False)
    first["acquisition"] = {"raw_path": "old.txt"}
    first["source"]["acquisition"] = {"retrieved_at": "old-time"}
    first["source_declaration"]["acquisition"] = deepcopy(first["acquisition"])
    second = deepcopy(first)
    second["acquisition"] = {"raw_path": "renamed.txt"}
    second["source"]["acquisition"] = {"retrieved_at": "new-time"}
    second["source_declaration"]["acquisition"] = deepcopy(second["acquisition"])
    left = normalized_dataset(first, default_source=SOURCE)
    right = normalized_dataset(second, default_source=SOURCE)
    before = deepcopy(left.source_declaration)
    assert left.id == right.id
    assert scientific_dataset_content(left) == scientific_dataset_content(right)
    assert left.source_declaration == before
    assert left.source_declaration["acquisition"]["raw_path"] == "old.txt"


def test_state_record_hash_remains_distinct_from_numerical_acquisition_identity() -> None:
    first = {"species": "Ar@ground", "acquisition": {"raw_path": "first.txt"}}
    second = {"species": "Ar@ground", "acquisition": {"raw_path": "second.txt"}}
    assert scientific_record_id(first) != scientific_record_id(second)
    assert scientific_record_id(first | {"record_id": "state-id"}) == scientific_record_id(
        second | {"record_id": "state-id"}
    )


@pytest.mark.parametrize("changed", ["method", "unknown-condition"])
def test_anonymous_identity_includes_scientific_snapshot_header_context(changed) -> None:
    record = _record(native=False)
    record.pop("method")
    original = SOURCE | {"method": "measured", "conditions": {"pressure_Pa": 10}}
    altered = deepcopy(original)
    if changed == "method":
        altered["method"] = "calculated"
    else:
        altered["conditions"]["pressure_Pa"] = 20
    first = normalized_dataset(record, default_source=original)
    second = normalized_dataset(record, default_source=altered)
    assert first.id != second.id
    assert scientific_dataset_content(first) != scientific_dataset_content(second)
    assert first.source_declaration["snapshot_source"]["conditions"] == {"pressure_Pa": 10}
    assert first.source_declaration["native_condition"] == {"pressure_Pa": 10}
    if changed == "method":
        assert first.method == "measured"
        assert second.method == "calculated"


def test_explicit_original_context_is_supplemented_without_overwriting() -> None:
    record = _record()
    record["source_declaration"]["snapshot_source"] = {
        "provider": "original-provider",
        "original_condition": {"pressure_Pa": 12},
    }
    original = deepcopy(record["source_declaration"])
    context = SOURCE | {"method": "measured", "additional_condition": {"temperature_K": 350}}
    dataset = normalized_dataset(record, default_source=context)
    saved = dataset.source_declaration["snapshot_source"]
    assert saved["provider"] == "original-provider"
    assert saved["original_condition"] == {"pressure_Pa": 12}
    assert saved["additional_condition"] == {"temperature_K": 350}
    assert saved["method"] == "measured"
    assert dataset.source_declaration["native_condition"] == original["native_condition"]
    assert record["source_declaration"] == original


def test_only_matching_snapshot_source_identifiers_are_redundant() -> None:
    record = _record() | {"source": SOURCE | {"record_id": "native-1"}}
    original = normalized_dataset(record)
    matching = replace(
        original,
        source_declaration=original.source_declaration | {"snapshot_source": SOURCE},
    )
    conflicting = replace(
        original,
        source_declaration=original.source_declaration
        | {"snapshot_source": SOURCE | {"provider": "another-laboratory"}},
    )
    assert scientific_dataset_content(original) == scientific_dataset_content(matching)
    assert scientific_dataset_content(original) != scientific_dataset_content(conflicting)


def test_local_asset_resolution_is_operational_context_in_saved_evidence(tmp_path) -> None:
    paths = []
    for index in (1, 2):
        directory = tmp_path / str(index)
        record = _record()
        record.update(
            form="table",
            parameters={},
            independent_variable="gas_temperature",
            asset="assets/curve.csv",
            validity={"quantity": "gas_temperature", "minimum": 300, "maximum": 500, "unit": "K"},
        )
        snapshot.write_table(
            directory / "converted", "curve", [(300, 1e-15), (500, 2e-15)], "temperature_K,k_m3_s"
        )
        paths.append(_acquired_snapshot(directory, index, record))
    catalog = EvidenceCatalog.load_paths(tuple(paths))
    datasets = catalog.reaction(REACTION).datasets
    assert datasets[0].asset.local_path != datasets[1].asset.local_path
    assert _use(catalog).status == "coefficient"
    result = analyze(Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=350)), catalog)
    export.write(tmp_path / "public", result)
    read = export.read(tmp_path / "public", verify_views=True)
    selected = next(item for item in read["reactions"] if item["data_use"]["dataset_id"])
    assert selected["data_use"]["value"] == pytest.approx(1.25e-15)


def test_ingest_and_adoption_keep_distinct_acquisitions_without_silent_replacement(
    tmp_path,
) -> None:
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
    result = analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root))
    export.write(tmp_path / "bundle", result)
    paths = (
        _acquired_snapshot(tmp_path / "first", 1, _record()),
        _acquired_snapshot(tmp_path / "second", 2, _record()),
    )
    overlay = tmp_path / "overlay.yaml"
    for path in (*paths, paths[1]):
        assert ingest.ingest(path, tmp_path / "bundle", overlay).accepted == 1
    records = next(iter(EvidenceCatalog.load(None, overlay).overlay_datasets.values()))
    assert len(records) == 2
    assert adopt.adopt(overlay, root).values == 4
    repeated = adopt.adopt(overlay, root)
    assert repeated.values == 0
    assert repeated.held == 4
    saved = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets
    assert len(saved) == 2
    assert {
        item.source_declaration["snapshot_source"]["acquisition"]["input_name"] for item in saved
    } == {"input-1.txt", "input-2.txt"}
    assert (
        data_use(
            REACTION,
            ReactionEvidence(overlay_datasets=tuple(saved)),
            Conditions(gas_temperature_K=350),
        ).status
        == "coefficient"
    )

    changed = _record()
    changed["source_declaration"]["native_condition"]["pressure_Pa"] = 99
    bad = _acquired_snapshot(tmp_path / "bad", 3, changed)
    before = overlay.read_bytes()
    report = ingest.ingest(bad, tmp_path / "bundle", overlay)
    assert report.accepted == 0
    assert report.review[0]["original_record"]["source_declaration"]["native_condition"] == {
        "pressure_Pa": 99
    }
    assert overlay.read_bytes() == before
    offered = deepcopy(yamlio.load(overlay.read_text(encoding="utf-8")))
    offered["datasets"][next(iter(offered["datasets"]))][0]["source_declaration"][
        "native_condition"
    ]["pressure_Pa"] = 99
    invalid = _write(tmp_path / "invalid-overlay.yaml", offered)
    registry_before = (root / "reactions" / "neutral" / "pair.yaml").read_bytes()
    with pytest.raises(ValueError, match="different content"):
        adopt.adopt(invalid, root)
    assert (root / "reactions" / "neutral" / "pair.yaml").read_bytes() == registry_before
