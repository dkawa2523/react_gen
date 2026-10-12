"""Independent scientific declarations survive each explicit input/persistence route."""

from dataclasses import asdict
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case
from reactgen.chemistry import parse_state_id
from reactgen.evidence import EvidenceCatalog, registry_reaction_candidate
from reactgen.pipeline import analyze
from reactgen.records import normalized_dataset, normalized_property, normalized_thermo
from reactgen.registry import Registry


def write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


def registry(tmp_path: Path) -> Path:
    root = tmp_path / "registry"
    write(
        root / "species" / "Ar.yaml",
        {
            "id": "Ar",
            "composition": {"Ar": 1},
            "phase": "gas",
            "state": {"kind": "ground"},
        },
    )
    return root


def declaration(record_id: str, provider: str, value: float) -> dict:
    return {
        "species": "Ar@ground",
        "record_id": record_id,
        "phase": "gas",
        "properties": {
            "enthalpy_formation_eV": {
                "value": value,
                "unit": "eV",
                "source": "original table",
                "method": "evaluated",
                "tier": "imported",
                "reference_temperature_K": 298.15,
            }
        },
        "thermo": {
            "low": [1, 0, 0, 0, 0, value, 1],
            "high": [1, 0, 0, 0, 0, value, 1],
            "t_min": 200,
            "t_mid": 1000,
            "t_max": 2000,
            "phase": "gas",
            "standard_pressure_Pa": 100000,
            "source": "original NASA fit",
            "method": "calculated",
            "tier": "imported",
        },
        "source": {
            "provider": provider,
            "collection": "collection",
            "release": "v1",
            "record_id": record_id,
            "url": "https://example.invalid/record",
            "citation": "synthetic source",
            "query_url": "original query",
            "native_notes": {"marker": "[interpolated]"},
        },
        "source_levels": [{"level": "1", "annotation": "[]"}],
        "source_response": "original bytes represented as text",
        "status": "imported",
        "review_scope": [],
    }


def test_property_model_and_raw_source_survive_snapshot_ingest_adopt(tmp_path) -> None:
    root = registry(tmp_path)
    source = write(
        tmp_path / "snapshot.yaml",
        {
            "snapshot_version": 1,
            "kind": "state_property",
            "source": {"provider": "transport", "download": {"hash": "raw-hash"}},
            "records": [declaration("a", "original", 2.0)],
        },
    )
    direct = EvidenceCatalog.load(None, known=(source,)).state_records[0]
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(source, tmp_path / "bundle", overlay).accepted == 1
    via_ingest = EvidenceCatalog.load(None, overlay).state_records[0]
    assert via_ingest.provenance == direct.provenance
    assert via_ingest.source_declaration == direct.source_declaration
    assert via_ingest.properties == direct.properties
    assert via_ingest.thermo == direct.thermo
    assert via_ingest.record_id == direct.record_id
    assert direct.provenance.record_id == "a"
    assert direct.record_id.startswith("source-state:")
    assert via_ingest.id == "Ar@ground"
    assert via_ingest.existence == "unknown"
    assert direct.source_declaration["source_levels"][0]["annotation"] == "[]"
    assert direct.source_declaration["source"]["native_notes"] == {"marker": "[interpolated]"}
    assert direct.source_declaration["snapshot_source"]["download"]["hash"] == "raw-hash"

    assert adopt.adopt(overlay, root).values == 1
    saved = next(
        item
        for item in EvidenceCatalog.load(root).state_records
        if item.record_id == direct.record_id
    )
    assert saved.provenance == direct.provenance
    assert saved.source_declaration == direct.source_declaration
    assert saved.properties == direct.properties
    assert saved.thermo == direct.thermo
    assert saved.existence == "unknown"
    assert adopt.adopt(overlay, root).values == 0


def test_two_sources_and_models_are_retained_without_permanent_selection(tmp_path) -> None:
    root = registry(tmp_path)
    overlay = write(
        tmp_path / "overlay.yaml",
        {"state_records": {"Ar@ground": [declaration("a", "one", 1), declaration("b", "two", 2)]}},
    )
    assert adopt.adopt(overlay, root).values == 2
    catalog = EvidenceCatalog.load(root)
    candidate = parse_state_id("Ar@ground")
    assert candidate is not None
    evidence = catalog.state(candidate)
    assert evidence.match == "exact"
    independent = [record for record in evidence.records if record.record_id is not None]
    assert {record.record_id for record in independent} == {"a", "b"}
    assert {record.provenance.provider for record in independent} == {"one", "two"}
    assert {record.properties["enthalpy_formation_eV"].value for record in independent} == {1, 2}
    assert len({record.thermo.low for record in independent}) == 2
    persisted = yamlio.load((root / "species" / "Ar.yaml").read_text(encoding="utf-8"))
    assert "thermo" not in persisted
    assert "properties" not in persisted


def test_reaction_numeric_method_and_original_claims_survive_all_routes(tmp_path) -> None:
    root = registry(tmp_path)
    write(
        root / "reactions" / "neutral" / "pair.yaml",
        {
            "pair": {"family": "neutral", "projectile": "Ar", "target": "Ar"},
            "channels": [
                {"id": "elastic", "type": "elastic", "products": [{"species": "Ar", "n": 2}]}
            ],
        },
    )
    acquired = {
        "id": "native-numerical-row",
        "reaction": "Ar + Ar -> Ar + Ar",
        "type": "elastic",
        "form": "constant",
        "unit": "m3/s",
        "parameters": {"value": 1e-16},
        "reaction_order": 2,
        "threshold_eV": 0.0,
        "notes": "original process qualification",
        "review_scope": ["coefficient"],
        "source": {
            "provider": "original",
            "collection": "rates",
            "record_id": "1",
            "method": "measured",
            "query_url": "exact original query",
        },
    }
    source = write(
        tmp_path / "source.yaml",
        {
            "snapshot_version": 1,
            "kind": "rate_coefficient",
            "source": {"release": "v1"},
            "records": [acquired],
        },
    )
    direct = EvidenceCatalog.load(None, known=(source,)).reaction_records[0].datasets[0]
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(source, tmp_path / "bundle", overlay).accepted == 1
    loaded = Registry.load(root)
    channel = loaded.channels[("neutral", "Ar", "Ar")][0]
    candidate = registry_reaction_candidate(channel, loaded.species)
    assert candidate is not None
    placed = EvidenceCatalog.load(None, overlay).overlay_datasets[candidate.id][0]
    assert placed == direct
    assert placed.method == "measured"
    assert placed.tier == "imported"
    assert placed.review_scope == ("coefficient",)
    assert placed.source_declaration["threshold_eV"] == 0.0
    assert placed.source_declaration["notes"] == acquired["notes"]
    # The independent reaction declaration and numerical record are both persisted.
    assert adopt.adopt(overlay, root).values == 2
    saved = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets[0]
    assert saved == direct
    assert adopt.adopt(overlay, root).values == 0


def test_state_record_id_conflict_queues_the_entire_incoming_declaration(tmp_path) -> None:
    root = registry(tmp_path)
    export.write(tmp_path / "bundle", analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    initial = declaration("same-native-row", "one", 1)
    source = write(tmp_path / "source.yaml", {"records": [initial]})
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(source, tmp_path / "bundle", overlay).accepted == 1
    before = overlay.read_bytes()
    replacement = declaration("same-native-row", "one", 2)
    write(source, {"records": [replacement]})
    report = ingest.ingest(source, tmp_path / "bundle", overlay)
    assert report.accepted == 0
    assert report.review[0]["original_record"] == replacement
    assert overlay.read_bytes() == before


def test_native_state_ids_in_different_provider_namespaces_both_survive(tmp_path) -> None:
    root = registry(tmp_path)
    overlay = write(
        tmp_path / "overlay.yaml",
        {
            "state_records": {
                "Ar@ground": [declaration("row", "one", 1), declaration("row", "two", 2)]
            },
        },
    )
    assert adopt.adopt(overlay, root).values == 2
    assert len(Registry.load(root).species["Ar"].records) == 2


def test_record_state_kind_cannot_override_its_target_at_direct_or_array_inputs(tmp_path) -> None:
    contradicted = declaration("row", "one", 1) | {"state": {"kind": "electronic"}}
    snapshot = write(tmp_path / "source.yaml", {"records": [contradicted]})
    overlay = write(tmp_path / "overlay.yaml", {"state_records": {"Ar@ground": [contradicted]}})
    for load in (
        lambda: EvidenceCatalog.load(None, known=(snapshot,)),
        lambda: EvidenceCatalog.load(None, overlay),
    ):
        with pytest.raises(ValueError, match="physical target"):
            load()


def test_source_reference_never_infers_provider_or_review_from_legacy_text() -> None:
    value = normalized_property({"value": 1, "unit": "eV", "source": "famous database"})
    assert value.source == value.provenance.citation == "famous database"
    assert value.provenance.provider is None
    assert value.method == "unknown"
    assert value.tier == "imported"
    assert value.source_declaration["source"] == "famous database"
    assert normalized_property(asdict(value)) == value


@pytest.mark.parametrize("source_type", ["famous", "estimated_fit", "derived_model"])
def test_source_names_and_method_never_upgrade_a_numeric_qualification(source_type) -> None:
    result = normalized_dataset(
        {
            "form": "constant",
            "parameters": {"value": 1},
            "source": {"source_type": source_type, "method": "estimated"},
        }
    )
    assert result.tier == "imported"
    assert result.method == "estimated"
    assert result.review_scope == ()


@pytest.mark.parametrize("kind", ["property", "thermo", "dataset"])
def test_explicit_raw_source_is_not_reinterpreted_as_approval(kind) -> None:
    raw = {"method": "measured", "unknown_fields": {"original": [1, 2]}}
    entry = {"source": "display", "source_declaration": raw, "method": "calculated"}
    if kind == "property":
        result = normalized_property(entry | {"value": 1, "unit": "eV"})
    elif kind == "thermo":
        result = normalized_thermo(
            entry
            | {
                "low": [1] * 7,
                "high": [1] * 7,
                "t_min": 200,
                "t_mid": 1000,
                "t_max": 2000,
            }
        )
    else:
        result = normalized_dataset(entry | {"form": "constant", "parameters": {"value": 1}})
    assert result is not None
    assert result.source_declaration == raw
    assert result.method == "calculated"
    assert result.tier == "imported"
    assert result.provenance.provider is None
    raw["unknown_fields"]["original"].append(3)
    assert result.source_declaration["unknown_fields"]["original"] == [1, 2]


@pytest.mark.parametrize("version", [2, "1", None, True])
def test_unknown_snapshot_versions_fail_before_any_ingest_write(tmp_path, version) -> None:
    source = write(tmp_path / "source.yaml", {"snapshot_version": version, "records": []})
    with pytest.raises(ValueError, match="snapshot_version"):
        EvidenceCatalog.load(None, known=(source,))
    with pytest.raises(ValueError, match="snapshot_version"):
        ingest.ingest(source, tmp_path / "unused-bundle", tmp_path / "overlay.yaml")
    assert not (tmp_path / "overlay.yaml").exists()
