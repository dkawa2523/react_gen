from pathlib import Path

import yaml

from plasma_reactgen.data_sources.nist_snapshot import NistSnapshotPropertyProvider
from plasma_reactgen.data_sources.registry import get_providers, register_nist_snapshot_provider
from plasma_reactgen.preparation import prepare_case


def test_nist_snapshot_returns_cf4_ie_and_enthalpy_candidates(tmp_path):
    nist_root = _make_nist_snapshot(tmp_path / "external_data" / "nist")
    provider = NistSnapshotPropertyProvider(nist_root)

    candidates = provider.find_properties(
        "CF4",
        ["ionization_energy_eV", "enthalpy_formation_eV"],
    )

    assert [candidate["property"] for candidate in candidates] == [
        "ionization_energy_eV",
        "enthalpy_formation_eV",
    ]
    assert candidates[0]["value"] == 14.7
    assert candidates[0]["unit"] == "eV"
    assert candidates[0]["source_record"] == {
        "source_type": "public_database_snapshot",
        "database": "NIST Chemistry WebBook SRD 69",
        "source_id": "nist_webbook:CF4:ionization_energy",
        "citation": "NIST Chemistry WebBook SRD 69",
    }


def test_nist_snapshot_alias_lookup_works(tmp_path):
    nist_root = _make_nist_snapshot(tmp_path / "external_data" / "nist")
    provider = NistSnapshotPropertyProvider(nist_root)

    candidates = provider.find_properties("tetrafluoromethane", ["ionization_energy_eV"])

    assert len(candidates) == 1
    assert candidates[0]["species"] == "CF4"
    assert candidates[0]["property"] == "ionization_energy_eV"


def test_nist_snapshot_skips_unsupported_units_with_unresolved_warning(tmp_path):
    nist_root = _make_nist_snapshot(tmp_path / "external_data" / "nist")
    provider = NistSnapshotPropertyProvider(nist_root)

    candidates = provider.find_properties("Ar", ["enthalpy_formation_eV"])

    assert candidates == []
    assert provider.status()["unresolved"] == [
        {
            "species": "Ar",
            "property": "enthalpy_formation_eV",
            "unit": "kJ/mol",
            "reason": "unsupported_unit",
        }
    ]


def test_register_nist_snapshot_provider_makes_profile_entry_functional(tmp_path):
    nist_root = _make_nist_snapshot(tmp_path / "external_data" / "nist")
    register_nist_snapshot_provider(nist_root)

    provider = get_providers("properties", {"properties": ["nist_snapshot"]})[0]

    assert provider.find_properties("CF4", ["ionization_energy_eV"])[0]["value"] == 14.7


def test_prepare_case_uses_nist_snapshot_without_mutating_registry(tmp_path):
    registry_root = _make_registry_with_missing_cf4_properties(tmp_path / "registry")
    nist_root = _make_nist_snapshot(tmp_path / "external_data" / "nist")
    input_path = tmp_path / "case.yaml"
    output_dir = tmp_path / "prepared_registry"
    input_path.write_text(
        yaml.safe_dump(
            {
                "case": {"name": "nist-snapshot-test"},
                "gases": ["CF4"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    original_registry = {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    }

    report = prepare_case(
        input_path=input_path,
        registry_root=registry_root,
        source_profile={
            "name": "nist_snapshot_test",
            "properties": ["local_registry", "nist_snapshot"],
            "nist_snapshot": {"root": str(nist_root)},
        },
        output_dir=output_dir,
    )

    prepared_cf4 = yaml.safe_load((output_dir / "species" / "CF4.yaml").read_text(encoding="utf-8"))
    report_payload = yaml.safe_load(
        (output_dir / "prepare_report.yaml").read_text(encoding="utf-8")
    )

    assert prepared_cf4["properties"]["ionization_energy_eV"]["value"] == 14.7
    assert prepared_cf4["properties"]["enthalpy_formation_eV"]["value"] == -9.6719
    assert (
        prepared_cf4["properties"]["ionization_energy_eV"]["source_record"]["source_type"]
        == "public_database_snapshot"
    )
    assert report["schema_version"] == 2
    assert report_payload["summary"]["n_properties_filled"] == 2
    assert {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    } == original_registry


def _make_nist_snapshot(root: Path) -> Path:
    _write_yaml(
        root / "species_properties.yaml",
        [
            {
                "species": "CF4",
                "aliases": ["tetrafluoromethane"],
                "property": "ionization_energy_eV",
                "value": 14.7,
                "unit": "eV",
                "status": "literature_supported",
                "evidence_type": "evaluated",
                "source_record": {
                    "source_type": "public_database_snapshot",
                    "database": "NIST Chemistry WebBook SRD 69",
                    "source_id": "nist_webbook:CF4:ionization_energy",
                    "citation": "NIST Chemistry WebBook SRD 69",
                },
            },
            {
                "species": "CF4",
                "aliases": ["tetrafluoromethane"],
                "property": "enthalpy_formation_eV",
                "value": -9.6719,
                "unit": "eV",
                "status": "literature_supported",
                "evidence_type": "evaluated",
                "source_record": {
                    "source_type": "public_database_snapshot",
                    "database": "NIST Chemistry WebBook SRD 69",
                    "source_id": "nist_webbook:CF4:enthalpy_formation",
                    "citation": "NIST Chemistry WebBook SRD 69",
                },
            },
            {
                "species": "Ar",
                "property": "enthalpy_formation_eV",
                "value": 0.0,
                "unit": "kJ/mol",
                "status": "literature_supported",
                "evidence_type": "evaluated",
                "source_record": {
                    "source_type": "public_database_snapshot",
                    "database": "NIST Chemistry WebBook SRD 69",
                    "source_id": "nist_webbook:Ar:enthalpy_formation",
                },
            },
        ],
    )
    _write_yaml(
        root / "atomic_properties.yaml",
        [
            {
                "species": "Ar",
                "property": "ionization_energy_eV",
                "value": 15.75961,
                "unit": "eV",
                "status": "literature_supported",
                "evidence_type": "evaluated",
                "source_record": {
                    "source_type": "public_database_snapshot",
                    "database": "NIST ASD",
                    "source_id": "nist_asd:Ar:ionization_energy",
                },
            }
        ],
    )
    (root / "README.md").write_text(
        "Local test snapshot. No online access.\n",
        encoding="utf-8",
    )
    return root


def _make_registry_with_missing_cf4_properties(root: Path) -> Path:
    _write_yaml(
        root / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "display_name": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "classes": ["neutral", "molecule"],
            "state": {"kind": "ground", "label": "X", "excitation_energy_eV": 0.0},
            "properties": {
                "ionization_energy_eV": {"value": None, "unit": "eV", "source": None},
                "enthalpy_formation_eV": {"value": None, "unit": "eV", "source": None},
            },
            "metadata": {"status": "curated", "notes": []},
        },
    )
    return root


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
