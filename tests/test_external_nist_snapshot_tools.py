from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.nist_snapshot_plan import build_nist_snapshot_plan, main as plan_main
from external_data_tools.nist_snapshot_validate import (
    main as validate_main,
    validate_nist_snapshot,
)


def test_nist_snapshot_request_generated_from_missing_data(tmp_path):
    missing_data = tmp_path / "outputs" / "missing_data.yaml"
    _write_yaml(
        missing_data,
        {
            "schema_version": 1,
            "missing_data": [
                {
                    "subject_kind": "species",
                    "subject_id": "CF4",
                    "field": "ionization_energy_eV",
                },
                {
                    "subject_kind": "species",
                    "subject_id": "CF4",
                    "field": "enthalpy_formation_eV",
                },
                {
                    "subject_kind": "dnt_task",
                    "subject_id": "Ar__CF4",
                    "target": "CF4",
                    "field": "target.polarizability_A3",
                },
                {
                    "subject_kind": "dnt_task",
                    "subject_id": "Ar__CF4",
                    "target": "CF4",
                    "field": "target.dipole_moment_D",
                },
                {
                    "subject_kind": "species",
                    "subject_id": "Ar",
                    "field": "ionization_energy_eV",
                },
            ],
        },
    )

    plan = build_nist_snapshot_plan(missing_data.parent)

    cf4 = _record(plan, "CF4")
    ar = _record(plan, "Ar")
    assert cf4["properties"] == [
        "ionization_energy_eV",
        "enthalpy_formation_eV",
        "polarizability_A3",
        "dipole_moment_D",
    ]
    assert cf4["suggested_sources"] == [
        "NIST Chemistry WebBook SRD 69",
        "NIST CCCBDB SRD 101",
    ]
    assert ar["properties"] == ["ionization_energy_eV"]
    assert ar["suggested_sources"] == ["NIST ASD"]
    assert plan["snapshot_request"]["name"] == "nist_required_properties"


def test_nist_snapshot_plan_cli_writes_output_from_prepare_report(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "external_data" / "snapshots" / "nist_required_properties.yaml"
    _write_yaml(
        workspace / "prepare_report.yaml",
        {
            "schema_version": 1,
            "unresolved": [
                {
                    "kind": "missing_property",
                    "species": "CF4",
                    "property": "electron_affinity_eV",
                }
            ],
        },
    )

    exit_code = plan_main([str(workspace), "--output", str(output)])

    assert exit_code == 0
    plan = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert plan["required_records"] == [
        {
            "species": "CF4",
            "properties": ["electron_affinity_eV"],
            "suggested_sources": ["NIST Chemistry WebBook SRD 69"],
        }
    ]


def test_nist_snapshot_validator_accepts_valid_record(tmp_path):
    snapshot = _write_yaml(
        tmp_path / "nist_species_properties.yaml",
        {"schema_version": 1, "records": [_valid_record()]},
    )

    report = validate_nist_snapshot(snapshot)

    assert report == {
        "schema_version": 1,
        "valid": True,
        "summary": {"records": 1, "errors": 0},
        "errors": [],
    }
    assert validate_main([str(snapshot)]) == 0


def test_nist_snapshot_validator_rejects_unsupported_unit(tmp_path):
    record = _valid_record()
    record["unit"] = "kJ/mol"
    snapshot = _write_yaml(
        tmp_path / "nist_species_properties.yaml",
        {"schema_version": 1, "records": [record]},
    )

    report = validate_nist_snapshot(snapshot)

    assert report["valid"] is False
    assert report["errors"] == [
        {
            "index": 0,
            "species": "CF4",
            "reason": "unsupported_unit",
            "message": "unsupported unit: kJ/mol",
            "field": "unit",
        }
    ]
    assert validate_main([str(snapshot)]) == 1


def test_collision_radius_is_not_assigned_to_nist_by_default(tmp_path):
    missing_data = tmp_path / "missing_data.yaml"
    _write_yaml(
        missing_data,
        {
            "schema_version": 1,
            "missing_data": [
                {
                    "subject_kind": "dnt_task",
                    "subject_id": "Ar__CF4",
                    "target": "CF4",
                    "field": "target.collision_radius_A",
                }
            ],
        },
    )

    plan = build_nist_snapshot_plan(missing_data)

    assert plan["required_records"] == []


def _record(plan: dict, species: str) -> dict:
    return next(record for record in plan["required_records"] if record["species"] == species)


def _valid_record() -> dict:
    return {
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
            "accessed_date": "2026-06-15",
        },
    }


def _write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path
