from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from external_data_tools.cache import sha256_file
from external_data_tools.registry_admin import (
    build_registry_pack,
    import_lxcat_raw,
    import_property_snapshot,
    import_rate_snapshot,
)
from plasma_reactgen.infrastructure.registry_pack import select_registry_pack
from plasma_reactgen.interface.cli import main


def test_generate_auto_selects_pack_without_new_user_input(tmp_path, monkeypatch):
    _write_base_registry(tmp_path / "registry")
    _write_pack(tmp_path / "registry_packs")
    case = tmp_path / "case.yaml"
    _write_yaml(case, {"case": {"name": "pack_case"}, "gases": ["A"]})
    monkeypatch.chdir(tmp_path)

    assert main(["generate", str(case), "--output", "outputs"]) == 0

    summary = _read_yaml(tmp_path / "outputs" / "summary.json")
    reactions = _read_yaml(tmp_path / "outputs" / "network.reactions.yaml")["reactions"]
    assert summary["registry"]["pack"]["id"] == "a_pack"
    assert summary["registry"]["pack"]["version"] == "1.2.0"
    assert [reaction["id"] for reaction in reactions] == ["e_A_to_B"]


def test_explicit_registry_bypasses_pack_and_no_pack_falls_back(tmp_path, monkeypatch):
    registry = tmp_path / "registry"
    _write_base_registry(registry)
    _write_pack(tmp_path / "registry_packs")
    case = tmp_path / "case.yaml"
    _write_yaml(case, {"case": {"name": "fallback"}, "gases": ["A"]})
    monkeypatch.chdir(tmp_path)

    assert main(["generate", str(case), "--registry", str(registry), "--output", "explicit"]) == 0
    explicit = _read_yaml(tmp_path / "explicit" / "summary.json")
    assert explicit["registry"]["mode"] == "explicit_registry"
    assert explicit["registry"]["pack"] is None
    assert explicit["n_reactions"] == 0

    (tmp_path / "registry_packs" / "index.yaml").unlink()
    assert main(["generate", str(case), "--output", "fallback"]) == 0
    fallback = _read_yaml(tmp_path / "fallback" / "summary.json")
    missing = _read_yaml(tmp_path / "fallback" / "missing_data.yaml")["missing_data"]
    assert fallback["registry"]["coverage_gap"] is False
    assert all(item["field"] != "registry_pack.coverage" for item in missing)


def test_lxcat_exact_mapping_preserves_header_hash_and_deduplicates(tmp_path):
    registry = tmp_path / "registry"
    _write_base_registry(registry, include_reaction=True)
    raw = tmp_path / "lxcat.txt"
    raw.write_text(
        "DATABASE: TestDB\n"
        "CONTRIBUTOR: Jane Doe\n"
        "CITATION: Example 2026\n"
        "REACTION_ID: e_A_to_B\n"
        "PROCESS: e + A -> e + B\n"
        "Energy(eV) Cross section(m2)\n"
        "0 0\n"
        "1 1e-20\n",
        encoding="utf-8",
    )

    first = import_lxcat_raw(raw, registry_root=registry, report_dir=tmp_path / "reports")
    second = import_lxcat_raw(raw, registry_root=registry, report_dir=tmp_path / "reports")

    assert first["summary"]["n_applied"] == 1
    assert second["duplicate"] is True
    metadata = first["assets"][0]["metadata"]
    assert metadata["sha256"] == sha256_file(raw)
    assert metadata["database"] == "TestDB"
    assert "CONTRIBUTOR: Jane Doe" in metadata["source_header"]
    channel = _first_channel(registry)
    assert len(channel["data"]["datasets"]) == 1


def test_lxcat_ambiguous_equation_is_not_applied(tmp_path):
    registry = tmp_path / "registry"
    _write_base_registry(registry, include_reaction=True, duplicate_equation=True)
    raw = tmp_path / "ambiguous.txt"
    raw.write_text(
        "e + A -> e + B\n0 0\n1 1e-20\n",
        encoding="utf-8",
    )

    report_dir = tmp_path / "reports"
    report = import_lxcat_raw(raw, registry_root=registry, report_dir=report_dir)

    assert report["summary"]["n_applied"] == 0
    assert report["review"][0]["reason"] == "ambiguous_mapping"
    assert (report_dir / "lxcat_raw_import.yaml").is_file()
    assert all("datasets" not in channel.get("data", {}) for channel in _channels(registry))


def test_property_and_rate_snapshots_normalize_and_exact_match(tmp_path):
    registry = tmp_path / "registry"
    _write_base_registry(registry, include_reaction=True)
    properties = tmp_path / "properties.csv"
    properties.write_text(
        "species_id,property,value,unit,quality,source,citation\n"
        "A,polarizability,1.2,A3,experimental,local_lab,Paper A\n",
        encoding="utf-8",
    )
    rates = tmp_path / "rates.yaml"
    _write_yaml(
        rates,
        {
            "records": [
                {
                    "reaction": "e + A -> e + B",
                    "representation": "arrhenius",
                    "parameters": {"A": 1.0e-15, "n": 0.5},
                    "temperature_min_K": 200,
                    "temperature_max_K": 1000,
                    "unit": "m3/s",
                    "source": "rate_snapshot",
                    "citation": "Paper B",
                }
            ]
        },
    )

    property_report = import_property_snapshot(properties, registry_root=registry)
    rate_report = import_rate_snapshot(rates, registry_root=registry)

    assert property_report["summary"]["n_applied"] == 1
    species = _read_yaml(next((registry / "species").glob("A.yaml")))
    prop = species["properties"]["polarizability_A3"]
    assert prop["quality"] == "experimental"
    assert prop["source_record"]["sha256"] == sha256_file(properties)
    assert rate_report["summary"]["n_applied"] == 1
    dataset = _first_channel(registry)["data"]["datasets"][0]
    assert dataset["representation"] == "arrhenius"
    assert dataset["validity"] == {"unit": "K", "minimum": 200.0, "maximum": 1000.0}


def test_property_snapshot_reports_invalid_records_and_expands_flat_payload(tmp_path):
    registry = tmp_path / "registry"
    _write_base_registry(registry)
    snapshot = tmp_path / "properties.yaml"
    _write_yaml(
        snapshot,
        [
            {"species_id": "A", "mass": 2.0, "mass_unit": "amu"},
            {"species_id": "A", "property": "unknown", "value": 1},
            {"species_id": "missing", "property": "mass", "value": 1},
            {"species_id": "A", "property": "mass", "value": "invalid"},
            {
                "species_id": "A",
                "property": "mass",
                "value": 1,
                "quality": "unreviewed",
            },
        ],
    )

    report = import_property_snapshot(snapshot, registry_root=registry)
    duplicate = import_property_snapshot(snapshot, registry_root=registry)

    assert report["summary"] == {"n_applied": 1, "n_review": 4}
    assert {item["reason"] for item in report["review"]} == {
        "unsupported_property_or_species",
        "species_id_not_found",
        "non_numeric_value",
        "unsupported_quality",
    }
    assert duplicate["duplicate"] is True


def test_rate_snapshot_handles_constant_table_and_review_paths(tmp_path):
    registry = tmp_path / "registry"
    _write_base_registry(registry, include_reaction=True)
    snapshot = tmp_path / "rates.yaml"
    _write_yaml(
        snapshot,
        {
            "rates": [
                {
                    "reaction_id": "e_A_to_B",
                    "representation": "constant",
                    "constant": 2.5,
                    "unit": "m3/s",
                },
                {
                    "reaction_id": "e_A_to_B",
                    "representation": "table",
                    "table": [{"temperature_K": 300, "rate": 1.0e-15}],
                    "unit": "m3/s",
                },
                {"reaction_id": "e_A_to_B", "representation": "unsupported"},
                {
                    "reaction_id": "e_A_to_B",
                    "representation": "table",
                    "path": "missing.csv",
                },
                {"reaction_id": "unknown", "representation": "constant", "value": 1},
            ]
        },
    )

    report = import_rate_snapshot(snapshot, registry_root=registry)

    assert report["summary"] == {"n_applied": 2, "n_review": 3}
    assert {item["reason"] for item in report["review"]} == {
        "unsupported_representation",
        "rate_table_data_missing",
        "no_exact_mapping",
    }
    datasets = _first_channel(registry)["data"]["datasets"]
    assert datasets[0]["parameters"]["value"] == 2.5
    assert (registry / datasets[1]["path"]).is_file()


def test_build_pack_excludes_site_local_numeric_assets(tmp_path):
    registry = tmp_path / "registry"
    _write_base_registry(registry, include_reaction=True, include_dataset=True)

    result = build_registry_pack(
        pack_id="a_pack",
        version="2.0.0",
        seed_gases=["A"],
        max_depth=2,
        registry_root=registry,
        packs_root=tmp_path / "registry_packs",
        redistribution_status="site-local",
    )

    assert result["built"] is True
    pack_root = Path(result["pack_root"])
    manifest = _read_yaml(pack_root / "pack.yaml")
    assert manifest["version"] == "2.0.0"
    assert manifest["excluded_numeric_assets"][0]["redistribution_status"] == "site-local"
    assert not (pack_root / "assets" / "cross_sections" / "a.csv").exists()
    index = _read_yaml(tmp_path / "registry_packs" / "index.yaml")
    assert index["packs"][0]["id"] == "a_pack"


def test_build_pack_keeps_versions_in_distinct_directories(tmp_path):
    registry = tmp_path / "registry"
    packs = tmp_path / "registry_packs"
    _write_base_registry(registry, include_reaction=True)

    first = build_registry_pack(
        pack_id="a_pack",
        version="1.0.0",
        seed_gases=["A"],
        max_depth=1,
        registry_root=registry,
        packs_root=packs,
    )
    second = build_registry_pack(
        pack_id="a_pack",
        version="2.0.0",
        seed_gases=["A"],
        max_depth=2,
        registry_root=registry,
        packs_root=packs,
    )

    first_root = Path(first["pack_root"])
    second_root = Path(second["pack_root"])
    assert first_root != second_root
    assert _read_yaml(first_root / "pack.yaml")["version"] == "1.0.0"
    assert _read_yaml(second_root / "pack.yaml")["version"] == "2.0.0"
    index = _read_yaml(packs / "index.yaml")
    assert {(item["version"], item["path"]) for item in index["packs"]} == {
        ("1.0.0", "a_pack/1.0.0"),
        ("2.0.0", "a_pack/2.0.0"),
    }
    assert select_registry_pack(["A"], packs).version == "2.0.0"


def test_pack_selection_prefers_exact_gas_coverage_over_newer_superset(tmp_path):
    packs = tmp_path / "registry_packs"
    _write_selectable_pack(packs, "exact", "1.0.0", ["A"])
    _write_selectable_pack(packs, "superset", "99.0.0", ["A", "B"])
    _write_yaml(
        packs / "index.yaml",
        {
            "packs": [
                {"id": "superset", "path": "superset"},
                {"id": "exact", "path": "exact"},
            ]
        },
    )

    selected = select_registry_pack(["A"], packs)

    assert selected is not None
    assert selected.id == "exact"
    assert selected.version == "1.0.0"
    assert selected.recommended_max_depth is None
    assert selected.redistribution_status == "site-local"


def test_pack_selection_ignores_invalid_entries_and_missing_manifests(tmp_path):
    packs = tmp_path / "registry_packs"
    _write_yaml(
        packs / "index.yaml",
        {
            "packs": [
                "not-a-mapping",
                {},
                {"id": "missing-manifest", "path": "missing"},
            ]
        },
    )

    assert select_registry_pack(["A"], packs) is None


def test_pack_selection_rejects_manifest_path_outside_pack_root(tmp_path):
    packs = tmp_path / "registry_packs"
    _write_selectable_pack(tmp_path, "outside", "1.0.0", ["A"])
    _write_yaml(
        packs / "index.yaml",
        {"packs": [{"id": "outside", "path": "../outside"}]},
    )

    assert select_registry_pack(["A"], packs) is None


def test_build_pack_copies_permitted_asset_and_replaces_same_version(tmp_path):
    registry = tmp_path / "registry"
    packs = tmp_path / "registry_packs"
    _write_base_registry(registry, include_reaction=True, include_dataset=True)
    reaction_path = next((registry / "reactions").glob("*/*.yaml"))
    reaction = _read_yaml(reaction_path)
    reaction["channels"][0]["data"]["datasets"][0]["source_record"]["redistribution_status"] = (
        "permitted"
    )
    _write_yaml(reaction_path, reaction)

    first = build_registry_pack(
        pack_id="a_pack",
        version="1.0.0",
        seed_gases=["A"],
        max_depth=1,
        registry_root=registry,
        packs_root=packs,
        redistribution_status="permitted",
    )
    second = build_registry_pack(
        pack_id="a_pack",
        version="1.0.0",
        seed_gases=["A"],
        max_depth=1,
        registry_root=registry,
        packs_root=packs,
        redistribution_status="permitted",
    )

    assert first["built"] is True
    assert second["built"] is True
    assert (Path(second["pack_root"]) / "assets" / "cross_sections" / "a.csv").is_file()


def test_build_pack_rejects_unknown_redistribution_status(tmp_path):
    with pytest.raises(ValueError, match="unsupported redistribution status"):
        build_registry_pack(
            pack_id="a_pack",
            version="1.0.0",
            seed_gases=["A"],
            max_depth=1,
            registry_root=tmp_path / "registry",
            packs_root=tmp_path / "registry_packs",
            redistribution_status="unknown",
        )


def _write_base_registry(
    root: Path,
    *,
    include_reaction: bool = False,
    duplicate_equation: bool = False,
    include_dataset: bool = False,
) -> None:
    for species_id in ("A", "B"):
        _write_yaml(
            root / "species" / f"{species_id}.yaml",
            {
                "id": species_id,
                "composition": {"X": 1},
                "charge": 0,
                "classes": ["neutral", "radical"],
                "properties": {},
            },
        )
    _write_yaml(
        root / "rules" / "reaction_type_catalog.yaml",
        {"electron": {"dissociation": {"expands_species": True}}},
    )
    _write_yaml(root / "rules" / "role_required_properties.yaml", {"roles": {}})
    if not include_reaction:
        return
    datasets = []
    if include_dataset:
        asset = root / "assets" / "cross_sections" / "a.csv"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("energy_eV,cross_section_m2\n0,0\n1,1e-20\n", encoding="utf-8")
        datasets.append(
            {
                "id": "ds_a",
                "kind": "cross_section",
                "representation": "table",
                "unit": "m2",
                "path": "assets/cross_sections/a.csv",
                "source_record": {
                    "source_type": "local",
                    "redistribution_status": "site-local",
                },
                "status": "imported",
            }
        )
    channels = [
        {
            "id": "e_A_to_B",
            "type": "dissociation",
            "products": [{"species": "e"}, {"species": "B"}],
            "status": "curated",
            "data": {"datasets": datasets} if datasets else {},
            "source_record": {"source_type": "fixture", "source_id": "r1"},
        }
    ]
    if duplicate_equation:
        channels.append({**channels[0], "id": "e_A_to_B_second"})
    _write_yaml(
        root / "reactions" / "electron" / "e_A.yaml",
        {
            "pair": {"family": "electron", "projectile": "e", "target": "A"},
            "channels": channels,
        },
    )


def _write_pack(packs_root: Path) -> None:
    pack = packs_root / "a_pack"
    _write_yaml(
        packs_root / "index.yaml",
        {"schema_version": 1, "packs": [{"id": "a_pack", "path": "a_pack"}]},
    )
    _write_yaml(
        pack / "pack.yaml",
        {
            "id": "a_pack",
            "version": "1.2.0",
            "seed_gases": ["A"],
            "supported_species": ["A", "B"],
            "recommended_max_depth": 2,
            "source_manifest": [],
            "data_coverage_summary": {"n_reactions": 1},
            "redistribution_status": "site-local",
        },
    )
    _write_yaml(
        pack / "species" / "B.yaml",
        {"id": "B", "composition": {"X": 1}, "charge": 0, "classes": ["neutral", "radical"]},
    )
    _write_yaml(
        pack / "reactions" / "electron" / "e_A.yaml",
        {
            "pair": {"family": "electron", "projectile": "e", "target": "A"},
            "channels": [
                {
                    "id": "e_A_to_B",
                    "type": "dissociation",
                    "products": [{"species": "e"}, {"species": "B"}],
                    "status": "curated",
                }
            ],
        },
    )


def _write_selectable_pack(
    packs_root: Path,
    pack_id: str,
    version: str,
    seed_gases: list[str],
) -> None:
    _write_yaml(
        packs_root / pack_id / "pack.yaml",
        {
            "id": pack_id,
            "version": version,
            "seed_gases": seed_gases,
        },
    )


def _first_channel(registry: Path) -> dict:
    return _channels(registry)[0]


def _channels(registry: Path) -> list[dict]:
    return _read_yaml(next((registry / "reactions").glob("*/*.yaml")))["channels"]


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
