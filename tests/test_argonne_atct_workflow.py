from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from external_data_tools.argonne_atct_snapshot_plan import build_argonne_atct_snapshot_plan
from external_data_tools.argonne_atct_snapshot_validate import validate_argonne_atct_snapshot
from plasma_reactgen.data_sources.argonne_atct_snapshot import ArgonneAtctSnapshotPropertyProvider
from plasma_reactgen.data_sources.registry import (
    get_providers,
    register_argonne_atct_snapshot_provider,
)
from plasma_reactgen.preparation.reaction_energetics import fill_reaction_energetics


def test_argonne_atct_planner_emits_required_species_for_missing_delta_e(tmp_path):
    outputs = tmp_path / "outputs"
    _write_yaml(
        outputs / "network.reactions.yaml",
        {
            "schema_version": 1,
            "reactions": [
                {
                    "id": "Arp_CF4_dct",
                    "family": "ion_neutral",
                    "type": "dissociative_charge_transfer",
                    "reactants": [{"species": "Ar+"}, {"species": "CF4"}],
                    "products": [
                        {"species": "Ar", "n": 1},
                        {"species": "CF3+", "n": 1},
                        {"species": "F", "n": 1},
                    ],
                    "deltaE_products_minus_reactants_eV": None,
                }
            ],
        },
    )

    plan = build_argonne_atct_snapshot_plan(outputs)

    by_species = {record["species"]: record for record in plan["required_records"]}
    assert by_species["CF3+"] == {
        "species": "CF3+",
        "properties": ["enthalpy_formation_eV"],
        "reason": ["needed_for_deltaE_products_minus_reactants_eV"],
    }
    assert set(by_species) == {"Ar+", "CF4", "Ar", "CF3+", "F"}


def test_argonne_atct_validator_accepts_valid_snapshot(tmp_path):
    snapshot = _write_snapshot(tmp_path / "thermo.yaml", [_record("CF4", -9.671936443224865)])

    report = validate_argonne_atct_snapshot(snapshot)

    assert report == {
        "schema_version": 1,
        "valid": True,
        "summary": {"records": 1, "errors": 0},
        "errors": [],
    }


def test_argonne_atct_validator_rejects_unsupported_unit(tmp_path):
    record = _record("CF4", -934.0)
    record["unit"] = "kJ/mol"
    snapshot = _write_snapshot(tmp_path / "thermo.yaml", [record])

    report = validate_argonne_atct_snapshot(snapshot)

    assert report["valid"] is False
    assert {
        "index": 0,
        "species": "CF4",
        "reason": "unsupported_unit",
        "message": "unsupported unit: kJ/mol",
        "field": "unit",
    } in report["errors"]


def test_argonne_atct_provider_returns_enthalpy_and_registers_name(tmp_path):
    snapshot = _write_snapshot(
        tmp_path / "thermo.yaml",
        [_record("CF4", -9.67, aliases=["tetrafluoromethane"])],
    )
    provider = ArgonneAtctSnapshotPropertyProvider(snapshot)

    candidates = provider.find_properties("tetrafluoromethane", ["enthalpy_formation_eV"])

    assert candidates[0]["species"] == "CF4"
    assert candidates[0]["property"] == "enthalpy_formation_eV"
    assert candidates[0]["value"] == -9.67
    assert candidates[0]["unit"] == "eV"

    register_argonne_atct_snapshot_provider(snapshot)
    registered = get_providers("properties", {"properties": ["argonne_atct_snapshot"]})[0]
    assert registered.find_properties("CF4", ["enthalpy_formation_eV"])[0]["value"] == -9.67


def test_fill_reaction_energetics_computes_delta_e_when_all_enthalpies_exist(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    _write_species(prepared_registry, "Ar+", 15.759)
    _write_species(prepared_registry, "CF4", -9.671936443224865)
    snapshot = _write_snapshot(
        tmp_path / "external_data" / "argonne_atct" / "thermo.yaml",
        [
            _record("Ar", 0.0),
            _record("CF3+", 5.0),
            _record("F", 0.8),
        ],
    )
    _write_reaction(prepared_registry, delta_e=None)
    provider = ArgonneAtctSnapshotPropertyProvider(snapshot)

    report = fill_reaction_energetics(
        prepared_registry,
        [provider],
        {"name": "argonne_test"},
    )

    payload = _read_yaml(prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml")
    channel = payload["channels"][0]
    expected = pytest.approx(0.0 + 5.0 + 0.8 - 15.759 - (-9.671936443224865))

    assert report["summary"]["n_energetics_filled"] == 1
    assert channel["deltaE_products_minus_reactants_eV"] == expected
    assert channel["data"]["energetics"]["status"] == "computed_from_snapshot"
    assert channel["data"]["energetics"]["method"] == "products_minus_reactants_enthalpy_formation"
    assert len(channel["data"]["energetics"]["source_records"]) == 5


def test_fill_reaction_energetics_does_not_overwrite_existing_delta_e(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    _write_species(prepared_registry, "Ar+", 15.759)
    _write_species(prepared_registry, "CF4", -9.67)
    _write_reaction(prepared_registry, delta_e=1.23)

    report = fill_reaction_energetics(prepared_registry, [], {"name": "test"})
    channel = _read_yaml(prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml")["channels"][0]

    assert report["summary"]["n_energetics_filled"] == 0
    assert report["skipped"][0]["reason"] == "deltaE_already_present"
    assert channel["deltaE_products_minus_reactants_eV"] == 1.23


def test_fill_reaction_energetics_reports_missing_enthalpy_and_registry_unchanged(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    registry_root = tmp_path / "registry"
    _write_species(prepared_registry, "Ar+", 15.759)
    _write_species(prepared_registry, "CF4", -9.67)
    _write_reaction(prepared_registry, delta_e=None)
    _write_yaml(registry_root / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml", {"channels": [{"id": "curated"}]})
    original_registry = {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")}

    report = fill_reaction_energetics(prepared_registry, [], {"name": "test"})
    channel = _read_yaml(prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml")["channels"][0]

    assert report["summary"]["n_unresolved"] == 1
    assert report["unresolved"][0]["reason"] == "missing_enthalpy_formation_eV"
    assert set(report["unresolved"][0]["species"]) == {"Ar", "CF3+", "F"}
    assert channel["deltaE_products_minus_reactants_eV"] is None
    assert {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")} == original_registry


def _record(species: str, value: float, aliases: list[str] | None = None) -> dict:
    return {
        "species": species,
        "aliases": aliases or [],
        "property": "enthalpy_formation_eV",
        "value": value,
        "unit": "eV",
        "temperature_K": 298.15,
        "status": "literature_supported",
        "uncertainty_eV": None,
        "source_record": {
            "source_type": "local_snapshot",
            "database": "Argonne_ATcT_or_internal_thermochemistry",
            "source_id": f"atct_like:{species}:delta_f_H_298",
            "citation": "local approved thermochemistry snapshot",
        },
    }


def _write_snapshot(path: Path, records: list[dict]) -> Path:
    return _write_yaml(
        path,
        {
            "schema_version": 1,
            "source": {
                "source_type": "local_snapshot",
                "database": "Argonne_ATcT_or_internal_thermochemistry",
                "version": "2026-06",
                "citation": "local approved thermochemistry snapshot",
                "license_note": "User must ensure this local snapshot is permitted for internal use.",
            },
            "records": records,
        },
    )


def _write_species(prepared_registry: Path, species: str, enthalpy: float) -> None:
    _write_yaml(
        prepared_registry / "species" / f"{species.replace('+', '_p').replace('-', '_m')}.yaml",
        {
            "schema_version": 1,
            "id": species,
            "properties": {
                "enthalpy_formation_eV": {
                    "value": enthalpy,
                    "unit": "eV",
                    "source_record": {
                        "source_type": "local_snapshot",
                        "database": "Argonne_ATcT_or_internal_thermochemistry",
                        "source_id": f"prepared:{species}:hf",
                    },
                }
            },
        },
    )


def _write_reaction(prepared_registry: Path, delta_e: float | None) -> None:
    _write_yaml(
        prepared_registry / "reactions" / "ion_neutral" / "Ar_p__CF4.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "ion_neutral", "projectile": "Ar+", "target": "CF4"},
            "channels": [
                {
                    "id": "Arp_CF4_dct",
                    "type": "dissociative_charge_transfer",
                    "products": [
                        {"species": "Ar", "n": 1},
                        {"species": "CF3+", "n": 1},
                        {"species": "F", "n": 1},
                    ],
                    "deltaE_products_minus_reactants_eV": delta_e,
                    "data": {},
                }
            ],
        },
    )


def _write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
