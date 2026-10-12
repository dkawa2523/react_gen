"""State identity follows source science; acquisition context survives separately."""

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case
from reactgen.chemistry import parse_state_id
from reactgen.evidence import EvidenceCatalog, snapshot_reaction
from reactgen.pipeline import analyze
from reactgen.records import (
    normalized_dataset,
    normalized_state_record,
    scientific_record_key,
    scientific_state_content,
    state_record_payload,
)

SOURCE = {"provider": "laboratory", "collection": "levels", "release": "v1"}


def _record(identity: str = "source") -> dict:
    record = {
        "species": "Ar@ground",
        "phase": "gas",
        "existence": "confirmed",
        "status": "reviewed",
        "method": "measured",
        "properties": {"ionization_energy_eV": {"value": 15.76, "unit": "eV", "tier": "reviewed"}},
        "source_declaration": {"native_condition": {"pressure_Pa": 10}},
    }
    if identity == "source":
        record["source"] = {"record_id": "native-1"}
    elif identity == "top":
        record["record_id"] = "native-1"
    return record


def _normalized(record: dict, source: dict | None = None, *, preserved: bool = False):
    candidate = parse_state_id(record["species"])
    assert candidate is not None
    return normalized_state_record(
        record, candidate, source or SOURCE, preserved_record_id=preserved
    )


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(body), encoding="utf-8")
    return path


def _snapshot(path: Path, record: dict, index: int) -> Path:
    return _write(
        path,
        {
            "snapshot_version": 1,
            "kind": "state_property",
            "source": SOURCE
            | {
                "acquisition": {
                    "retrieved_at": f"2026-10-{index:02d}T00:00:00Z",
                    "requested_url": f"https://example.invalid/request/{index}",
                    "raw_path": f"directory-{index}/raw.txt",
                }
            },
            "records": [record],
        },
    )


@pytest.mark.parametrize("identity", ["source", "top", "anonymous"])
def test_state_reacquisition_shares_identity_without_losing_declarations(identity) -> None:
    first = _normalized(
        _record(identity), SOURCE | {"acquisition": {"retrieved_at": "first", "path": "a"}}
    )
    second = _normalized(
        _record(identity), SOURCE | {"acquisition": {"retrieved_at": "second", "path": "b"}}
    )
    before = deepcopy(first.source_declaration)
    assert first.record_id == second.record_id
    assert scientific_state_content(first) == scientific_state_content(second)
    assert first.source_declaration != second.source_declaration
    assert first.source_declaration == before


@pytest.mark.parametrize("identity", ["source", "top"])
@pytest.mark.parametrize("change", ["value", "method", "tier", "condition", "target"])
def test_native_state_id_detects_scientific_changes(identity, change) -> None:
    original = _record(identity)
    changed = deepcopy(original)
    if change == "value":
        changed["properties"]["ionization_energy_eV"]["value"] = 16
    elif change == "method":
        changed["method"] = "calculated"
    elif change == "tier":
        changed["status"] = "imported"
    elif change == "condition":
        changed["source_declaration"]["native_condition"]["pressure_Pa"] = 20
    else:
        changed["species"] = "Ne@ground"
    first, second = _normalized(original), _normalized(changed)
    assert first.record_id == second.record_id
    assert scientific_record_key(state_record_payload(first)) == scientific_record_key(
        state_record_payload(second)
    )
    assert scientific_state_content(first) != scientific_state_content(second)


@pytest.mark.parametrize("field", ["provider", "collection", "release", "source_id"])
def test_native_record_namespace_keeps_distinct_source_records(field) -> None:
    first = _normalized(_record())
    second = _normalized(_record(), SOURCE | {field: "different"})
    assert first.record_id != second.record_id
    assert scientific_record_key(state_record_payload(first)) != scientific_record_key(
        state_record_payload(second)
    )


@pytest.mark.parametrize("field", ["method", "conditions"])
def test_anonymous_state_identity_includes_scientific_header_context(field) -> None:
    record = _record("anonymous")
    record.pop("method")
    first_context = SOURCE | {"method": "measured", "conditions": {"pressure_Pa": 10}}
    second_context = deepcopy(first_context)
    second_context[field] = "calculated" if field == "method" else {"pressure_Pa": 20}
    first, second = _normalized(record, first_context), _normalized(record, second_context)
    assert first.record_id != second.record_id
    assert scientific_state_content(first) != scientific_state_content(second)


def test_saved_canonical_state_id_is_preserved_and_old_native_identity_can_match() -> None:
    original = _record("top")
    original.pop("source_declaration")
    fresh = _normalized(original)
    saved = state_record_payload(fresh)
    legacy = deepcopy(saved)
    legacy["record_id"] = "native-1"
    legacy["provenance"]["record_id"] = None
    restored = _normalized(legacy, {}, preserved=True)
    assert restored.record_id == "native-1"
    assert scientific_record_key(legacy) == scientific_record_key(saved)
    assert scientific_state_content(restored) == scientific_state_content(fresh)
    assert _normalized(saved, {}, preserved=True).record_id == fresh.record_id


def test_saved_anonymous_id_is_not_regenerated() -> None:
    saved = state_record_payload(_normalized(_record("anonymous")))
    saved["record_id"] = "local-state:legacy-preserved-content-id"
    restored = _normalized(saved, {}, preserved=True)
    assert restored.record_id == saved["record_id"]


def _thermal_record() -> dict:
    return _record() | {
        "thermo": {
            "low": [2.5, 0, 0, 0, 0, 0, 0],
            "high": [2.5, 0, 0, 0, 0, 0, 0],
            "t_min": 200,
            "t_mid": 1000,
            "t_max": 2000,
            "phase": "gas",
            "standard_pressure_Pa": 100000,
            "tier": "reviewed",
            "original_model_note": {"pressure_reference": "declared standard pressure"},
        }
    }


def test_older_property_and_thermo_payloads_share_default_status_without_losing_raw() -> None:
    fresh = state_record_payload(_normalized(_thermal_record()))
    old = deepcopy(fresh)
    old["record_id"] = "native-1"
    for prop in old["properties"].values():
        prop.pop("status")
    old["thermo"].pop("status")
    before = deepcopy(old)
    assert scientific_state_content(old) == scientific_state_content(fresh)
    assert old == before
    assert old["thermo"]["source_declaration"]["original_model_note"] == {
        "pressure_reference": "declared standard pressure"
    }
    restored = _normalized(old, {}, preserved=True)
    assert restored.properties == _normalized(_thermal_record()).properties
    assert restored.thermo == _normalized(_thermal_record()).thermo
    assert restored.source_declaration == fresh["source_declaration"]
    changed = deepcopy(old)
    changed["thermo"]["source_declaration"]["original_model_note"]["pressure_reference"] = (
        "changed reference"
    )
    assert scientific_state_content(changed) != scientific_state_content(old)
    changed = deepcopy(old)
    changed["properties"]["ionization_energy_eV"]["future_condition"] = {"population": "A"}
    assert scientific_state_content(changed) != scientific_state_content(old)


def test_older_payload_reacquisition_keeps_its_id_and_original_declarations(tmp_path) -> None:
    root = tmp_path / "registry"
    first = _snapshot(tmp_path / "first.yaml", _thermal_record(), 1)
    direct = EvidenceCatalog.load(None, known=(first,)).state_records[0]
    old = state_record_payload(direct)
    old["record_id"] = "native-1"
    for prop in old["properties"].values():
        prop.pop("status")
    old["thermo"].pop("status")
    species_path = _write(
        root / "species" / "Ar.yaml",
        {
            "id": "Ar",
            "composition": {"Ar": 1},
            "phase": "gas",
            "state": {"kind": "ground"},
            "records": [old],
        },
    )
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    second = _snapshot(tmp_path / "second.yaml", _thermal_record(), 2)
    overlay = _write(tmp_path / "overlay.yaml", {"state_records": {"Ar@ground": [old]}})
    assert ingest.ingest(second, tmp_path / "bundle", overlay).accepted == 1
    overlay_records = yamlio.load(overlay.read_text(encoding="utf-8"))["state_records"]["Ar@ground"]
    assert len(overlay_records) == 2
    assert {item["record_id"] for item in overlay_records} == {"native-1"}
    assert overlay_records[0] == old
    report = adopt.adopt(overlay, root)
    assert report.values == 1
    assert report.written == {"Ar@ground": ["native-1"]}
    persisted = yamlio.load(species_path.read_text(encoding="utf-8"))["records"]
    assert len(persisted) == 2
    assert persisted[0] == old
    assert {item["record_id"] for item in persisted} == {"native-1"}
    assert adopt.adopt(overlay, root).values == 0


def test_conflicting_native_identity_declarations_are_rejected() -> None:
    record = _record("top") | {"source": {"record_id": "another"}}
    with pytest.raises(ValueError, match="contradicts"):
        _normalized(record)


@pytest.mark.parametrize("kind", ["state", "numeric", "reaction"])
def test_null_top_native_id_falls_back_to_source_and_blank_id_remains_invalid(kind) -> None:
    if kind == "state":
        entry = _record()

        def identifier(record):
            return _normalized(record).record_id

        changed = deepcopy(entry)
        changed["properties"]["ionization_energy_eV"]["value"] = 16
    else:
        entry = {
            "reaction": "Ar + Ar -> Ar + Ar",
            "type": "elastic",
            "source": {"record_id": "native-1"},
            "status": "reviewed",
        }
        if kind == "numeric":
            entry.update(form="constant", unit="m3/s", parameters={"value": 1e-15})

            def identifier(record):
                return normalized_dataset(record, default_source=SOURCE).id

            changed = deepcopy(entry)
            changed["parameters"]["value"] = 2e-15
        else:

            def identifier(record):
                normalized = snapshot_reaction(record, SOURCE, datasets=())
                assert normalized is not None
                return normalized.id

            changed = entry | {"threshold_eV": 1}
    expected = identifier(entry)
    assert identifier(entry | {"record_id": None}) == expected
    assert identifier(changed | {"record_id": None}) == expected
    with pytest.raises(ValueError, match="nonempty text"):
        identifier(entry | {"record_id": ""})


@pytest.mark.parametrize("identity", ["source", "top", "anonymous"])
def test_reacquisition_roundtrip_keeps_all_originals_and_rejects_scientific_change(
    tmp_path, identity
) -> None:
    root = tmp_path / "registry"
    _write(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "phase": "gas", "state": {"kind": "ground"}},
    )
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    paths = (
        _snapshot(tmp_path / "first.yaml", _record(identity), 1),
        _snapshot(tmp_path / "second.yaml", _record(identity), 2),
    )
    overlay = tmp_path / "overlay.yaml"
    for path in (*paths, paths[1]):
        report = ingest.ingest(path, tmp_path / "bundle", overlay)
        assert report.accepted == 1
        assert not report.review
    records = EvidenceCatalog.load(None, overlay).state_records
    assert len(records) == 2
    assert len({record.record_id for record in records}) == 1
    assert adopt.adopt(overlay, root).values == 2
    assert adopt.adopt(overlay, root).values == 0
    saved = [record for record in EvidenceCatalog.load(root).state_records if record.record_id]
    assert len(saved) == 2
    assert {
        record.source_declaration["snapshot_source"]["acquisition"]["retrieved_at"]
        for record in saved
    } == {"2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"}
    assert {asdict(record.provenance)["provider"] for record in saved} == {"laboratory"}

    invalid_overlay = deepcopy(yamlio.load(overlay.read_text(encoding="utf-8")))
    invalid_overlay["state_records"]["Ar@ground"][0]["properties"]["ionization_energy_eV"][
        "value"
    ] = 16
    invalid_path = _write(tmp_path / "invalid-overlay.yaml", invalid_overlay)
    registry_before = (root / "species" / "Ar.yaml").read_bytes()
    with pytest.raises(ValueError, match="different content"):
        adopt.adopt(invalid_path, root)
    assert (root / "species" / "Ar.yaml").read_bytes() == registry_before

    changed = _record(identity)
    changed["properties"]["ionization_energy_eV"]["value"] = 16
    bad = _snapshot(tmp_path / "changed.yaml", changed, 3)
    before = overlay.read_bytes()
    incoming = ingest.ingest(bad, tmp_path / "bundle", overlay)
    if identity == "anonymous":
        assert incoming.accepted == 1
        assert len(EvidenceCatalog.load(None, overlay).state_records) == 3
    else:
        assert incoming.accepted == 0
        assert (
            incoming.review[0]["original_record"]["properties"]["ionization_energy_eV"]["value"]
            == 16
        )
        assert overlay.read_bytes() == before


def test_adoption_preserves_a_legacy_canonical_id_for_new_acquisition(tmp_path) -> None:
    root = tmp_path / "registry"
    first = _snapshot(tmp_path / "first.yaml", _record(), 1)
    original = EvidenceCatalog.load(None, known=(first,)).state_records[0]
    saved = state_record_payload(original)
    saved["record_id"] = "native-1"
    species_path = _write(
        root / "species" / "Ar.yaml",
        {
            "id": "Ar",
            "composition": {"Ar": 1},
            "phase": "gas",
            "state": {"kind": "ground"},
            "records": [saved],
        },
    )
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    second = _snapshot(tmp_path / "second.yaml", _record(), 2)
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(second, tmp_path / "bundle", overlay).accepted == 1
    assert adopt.adopt(overlay, root).values == 1
    records = yamlio.load(species_path.read_text(encoding="utf-8"))["records"]
    assert len(records) == 2
    assert {record["record_id"] for record in records} == {"native-1"}
    assert (
        len(
            {
                record["source_declaration"]["snapshot_source"]["acquisition"]["retrieved_at"]
                for record in records
            }
        )
        == 2
    )
