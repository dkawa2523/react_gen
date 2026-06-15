from pathlib import Path

import pytest
import yaml

from plasma_reactgen.interface.cli import main
from plasma_reactgen.preparation.input_templates import generate_missing_input_templates


def test_templates_generated_from_missing_data(tmp_path):
    outputs = tmp_path / "outputs"
    _write_missing_data(
        outputs / "missing_data.yaml",
        [
            _missing("dnt_task", "Ar+__CF4", "target.collision_radius_A", "dnt_plus", "missing radius"),
            _missing("reaction", "e_CF4_elastic", "data.cross_section.path", "electron_collision", "missing xsec"),
            _missing(
                "reaction",
                "Arp_CF4_dct_CF3p",
                "deltaE_products_minus_reactants_eV",
                "dnt_task",
                "missing deltaE",
            ),
            _missing("reaction", "mystery", "unmapped.field", "diagnostic", "unknown"),
        ],
    )

    report = generate_missing_input_templates(outputs, tmp_path / "manual_inputs")

    out = tmp_path / "manual_inputs"
    assert (out / "species_properties.yaml").exists()
    assert (out / "reaction_channels.yaml").exists()
    assert (out / "cross_section_mapping.yaml").exists()
    assert (out / "reaction_energetics.yaml").exists()
    assert (out / "manual_review.yaml").exists()
    assert (out / "README.md").exists()
    assert report["summary"]["n_missing_items"] == 4


def test_templates_include_units_and_no_fake_values(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [
            _missing("dnt_task", "Ar+__CF4", "target.collision_radius_A", "dnt_plus", "missing radius"),
            _missing("species", "CF4", "polarizability_A3", "dnt_plus", "missing polarizability"),
        ],
    )

    generate_missing_input_templates(missing_file, tmp_path / "manual_inputs")

    species_properties = _read_yaml(tmp_path / "manual_inputs" / "species_properties.yaml")
    records = species_properties["records"]
    radius = next(record for record in records if record["property"] == "collision_radius_A")
    polarizability = next(record for record in records if record["property"] == "polarizability_A3")

    assert radius["species"] == "CF4"
    assert radius["value"] is None
    assert radius["unit"] == "A"
    assert polarizability["value"] is None
    assert polarizability["unit"] == "A3"
    assert radius["source_record"]["source_type"] == "manual_review"


def test_cross_section_and_energetics_templates_have_blank_values(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [
            _missing("reaction", "e_CF4_elastic", "data.cross_section", "electron_collision", "missing xsec"),
            _missing("reaction", "Arp_CF4_dct_CF3p", "deltaE_products_minus_reactants_eV", "dnt", "missing energy"),
        ],
    )

    generate_missing_input_templates(missing_file, tmp_path / "manual_inputs")

    mapping = _read_yaml(tmp_path / "manual_inputs" / "cross_section_mapping.yaml")
    energetics = _read_yaml(tmp_path / "manual_inputs" / "reaction_energetics.yaml")

    assert mapping["mappings"][0]["reaction_id"] == "e_CF4_elastic"
    assert mapping["mappings"][0]["asset_path"] is None
    assert mapping["mappings"][0]["mapping_status"] == "manual_review_required"
    assert energetics["records"][0]["deltaE_products_minus_reactants_eV"] is None
    assert energetics["records"][0]["unit"] == "eV"


def test_threshold_energy_template_has_blank_threshold(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [_missing("reaction", "e_O2_ionization", "threshold_eV", "electron_collision", "missing threshold")],
    )

    generate_missing_input_templates(missing_file, tmp_path / "manual_inputs")

    energetics = _read_yaml(tmp_path / "manual_inputs" / "reaction_energetics.yaml")
    assert energetics["records"][0]["reaction_id"] == "e_O2_ionization"
    assert energetics["records"][0]["threshold_eV"] is None
    assert energetics["records"][0]["unit"] == "eV"


def test_missing_pair_coverage_generates_reaction_channel_template(tmp_path):
    outputs = tmp_path / "outputs"
    _write_missing_data(outputs / "missing_data.yaml", [])
    _write_yaml(
        outputs / "coverage_report.yaml",
        {
            "schema_version": 1,
            "pairs": {
                "missing": [
                    {
                        "pair_key": "ion_neutral|Ar+|O2",
                        "pair_label": "Ar+ + O2",
                        "family": "ion_neutral",
                        "depth": 1,
                        "reason": "No registered reaction file",
                    }
                ]
            },
        },
    )

    report = generate_missing_input_templates(outputs, tmp_path / "manual_inputs")
    channels = _read_yaml(tmp_path / "manual_inputs" / "reaction_channels.yaml")

    assert report["summary"]["n_reaction_channel_records"] == 1
    assert channels["records"][0]["pair"] == {
        "family": "ion_neutral",
        "projectile": "Ar+",
        "target": "O2",
    }
    assert channels["records"][0]["placeholder_channels"][0]["id"] is None
    assert channels["records"][0]["placeholder_channels"][0]["products"] == []


def test_unknown_fields_go_to_manual_review(tmp_path):
    missing_file = _write_missing_data(
        tmp_path / "missing_data.yaml",
        [_missing("reaction", "mystery", "unmapped.field", "diagnostic", "unknown")],
    )

    generate_missing_input_templates(missing_file, tmp_path / "manual_inputs")

    manual = _read_yaml(tmp_path / "manual_inputs" / "manual_review.yaml")
    assert manual["items"][0]["subject_id"] == "mystery"
    assert manual["items"][0]["field"] == "unmapped.field"
    assert manual["items"][0]["action"] == "manual_review"


def test_templates_generated_from_all_semiconductor_benchmark_outputs_if_available(tmp_path):
    case_ids = ["ar_o2_simple", "ar_cf4_fluorocarbon", "sf6_o2_electronegative"]
    output_roots = [Path("benchmarks/results") / case_id / "outputs" for case_id in case_ids]
    if not all((root / "missing_data.yaml").exists() for root in output_roots):
        pytest.skip("benchmark outputs are not available in this checkout")

    for case_id, output_root in zip(case_ids, output_roots):
        destination = tmp_path / case_id
        report = generate_missing_input_templates(output_root, destination)
        assert (destination / "README.md").exists()
        assert (destination / "species_properties.yaml").exists()
        assert (destination / "reaction_energetics.yaml").exists()
        assert (destination / "reaction_channels.yaml").exists()
        assert (destination / "cross_section_mapping.yaml").exists()
        assert "cl2_bcl3" not in yaml.safe_dump(_read_yaml(destination / "cross_section_mapping.yaml")).lower()
        assert "Cl2/BCl3" not in (destination / "README.md").read_text(encoding="utf-8")
        assert report["summary"]["n_missing_items"] >= 0


def test_template_missing_cli_writes_templates(tmp_path):
    outputs = tmp_path / "outputs"
    _write_missing_data(
        outputs / "missing_data.yaml",
        [_missing("reaction", "e_CF4_elastic", "data.cross_section.path", "electron_collision", "missing xsec")],
    )
    output_dir = tmp_path / "manual_inputs"

    rc = main(["template-missing", str(outputs), "--output-dir", str(output_dir)])

    assert rc == 0
    assert _read_yaml(output_dir / "cross_section_mapping.yaml")["mappings"][0]["reaction_id"] == "e_CF4_elastic"


def _missing(kind: str, subject: str, field: str, required_by: str, message: str) -> dict:
    return {
        "subject_kind": kind,
        "subject_id": subject,
        "field": field,
        "required_by": required_by,
        "severity": "warning",
        "message": message,
    }


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


def _write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
