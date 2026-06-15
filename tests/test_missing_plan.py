from pathlib import Path

import yaml

from plasma_reactgen.interface.cli import main
from plasma_reactgen.preparation.missing_plan import build_missing_plan, write_missing_plan


def test_electron_cross_section_missing_maps_to_import_cross_sections(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [
            {
                "subject_kind": "reaction",
                "subject_id": "e_CF4_dissociation_CF3_F",
                "field": "data.cross_section",
                "required_by": "electron_collision",
                "severity": "warning",
                "message": "missing cross section",
            },
            {
                "subject_kind": "asset",
                "subject_id": "e_CF4_elastic",
                "field": "data.cross_section.path",
                "required_by": "electron_collision",
                "severity": "warning",
                "message": "missing cross-section path",
            },
        ],
    )

    plan = build_missing_plan(missing_file)
    action = _action(plan, "import_cross_sections")

    assert action["priority"] == "high"
    assert action["subjects"] == ["e_CF4_dissociation_CF3_F", "e_CF4_elastic"]
    assert "reactgen import-cross-sections" in action["command_hint"]


def test_dnt_property_missing_maps_to_enrich_properties(tmp_path):
    outputs = tmp_path / "outputs"
    _write_missing_data(
        outputs / "missing_data.yaml",
        [
            {
                "subject_kind": "dnt_task",
                "subject_id": "CF3+__CF2",
                "field": "target.collision_radius_A",
                "required_by": "dnt_plus_dm",
                "severity": "required",
                "message": "missing collision radius",
            },
            {
                "subject_kind": "species",
                "subject_id": "CF2",
                "field": "enthalpy_formation_eV",
                "required_by": "state_role",
                "severity": "required",
                "message": "missing enthalpy",
            },
        ],
    )

    plan = build_missing_plan(outputs)
    action = _action(plan, "enrich_properties")

    assert action["priority"] == "high"
    assert action["subjects"] == ["CF3+__CF2", "CF2"]


def test_delta_e_missing_maps_to_review_reaction_energetics(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [
            {
                "subject_kind": "reaction",
                "subject_id": "Arp_CF4_charge_transfer",
                "field": "deltaE_products_minus_reactants_eV",
                "required_by": "dnt_task",
                "severity": "warning",
                "message": "missing reaction energy",
            }
        ],
    )

    plan = build_missing_plan(missing_file)
    action = _action(plan, "review_reaction_energetics")

    assert action["priority"] == "medium"
    assert action["subjects"] == ["Arp_CF4_charge_transfer"]


def test_output_summary_is_correct_and_unknown_fields_are_manual_review(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [
            {
                "subject_kind": "species",
                "subject_id": "CF3",
                "field": "registry/species",
                "required_by": "reaction_product",
                "severity": "required",
                "message": "missing species",
            },
            {
                "subject_kind": "reaction",
                "subject_id": "mystery",
                "field": "unmapped.field",
                "required_by": "diagnostic",
                "severity": "warning",
                "message": "unknown field",
            },
            {
                "subject_kind": "reaction",
                "subject_id": "e_CF4_elastic",
                "field": "data.cross_section.path",
                "required_by": "electron_collision",
                "severity": "warning",
                "message": "missing cross-section path",
            },
        ],
    )

    plan = build_missing_plan(missing_file)

    assert plan["summary"] == {"total_missing_items": 3, "suggested_actions": 3}
    assert _action(plan, "seed_species")["subjects"] == ["CF3"]
    assert _action(plan, "manual_review")["subjects"] == ["mystery"]


def test_write_missing_plan_and_cli_write_yaml(tmp_path):
    outputs = tmp_path / "outputs"
    output = tmp_path / "missing_plan.yaml"
    _write_missing_data(
        outputs / "missing_data.yaml",
        [
            {
                "subject_kind": "reaction",
                "subject_id": "e_CF4_elastic",
                "field": "data.cross_section.path",
                "required_by": "electron_collision",
                "severity": "warning",
                "message": "missing cross-section path",
            }
        ],
    )

    plan = write_missing_plan(outputs, output)
    assert output.exists()
    assert yaml.safe_load(output.read_text(encoding="utf-8")) == plan

    cli_output = tmp_path / "cli_missing_plan.yaml"
    rc = main(["plan-missing", str(outputs), "--output", str(cli_output)])

    assert rc == 0
    assert yaml.safe_load(cli_output.read_text(encoding="utf-8"))["summary"] == {
        "total_missing_items": 1,
        "suggested_actions": 1,
    }


def _action(plan: dict, action_name: str) -> dict:
    return next(action for action in plan["actions"] if action["action"] == action_name)


def _write_missing_data(path: Path, items: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "case": {"name": "test"}, "missing_data": items},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path
