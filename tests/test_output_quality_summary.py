import json
from pathlib import Path

import yaml

from plasma_reactgen.application.config import case_config_from_dict
from plasma_reactgen.domain.models import ReactionNetwork
from plasma_reactgen.infrastructure.yaml_writer import write_yaml_outputs
from plasma_reactgen.interface.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_generate_summary_json_has_quality_fields(tmp_path, capsys):
    output = tmp_path / "outputs"

    rc = main(
        [
            "generate",
            str(ROOT / "cases" / "ar_cf4" / "input.yaml"),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(output),
        ]
    )

    console = capsys.readouterr().out
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    quality = _read_yaml(output / "quality_summary.yaml")

    assert rc == 0
    for field in (
        "n_species",
        "n_reactions",
        "n_electron_reactions",
        "n_ion_neutral_reactions",
        "n_pairs_found",
        "n_pairs_missing",
        "n_missing_data_items",
        "n_dnt_tasks",
        "n_reactions_with_cross_section_asset",
        "n_reactions_missing_cross_section",
        "n_reactions_with_provenance",
        "n_inferred_reactions",
        "n_imported_reactions",
        "n_literature_supported_reactions",
        "by_depth",
    ):
        assert field in summary
    assert isinstance(summary["by_depth"], dict)
    assert "readiness" in quality
    assert "top_missing_actions" in quality
    assert "warnings" in quality
    assert "quality_summary:" in console
    assert "dnt_ready_pairs:" in console


def test_quality_summary_generated_for_sparse_data(tmp_path):
    config = case_config_from_dict({"case": {"name": "sparse"}, "gases": ["Ar"]})
    network = ReactionNetwork(species={}, species_nodes={}, reactions=[], coverage=[], missing_data=[])

    write_yaml_outputs(
        output_dir=tmp_path,
        case_config=config,
        network=network,
        states=[],
        dnt_tasks=[],
        missing_data=[],
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    quality = _read_yaml(tmp_path / "quality_summary.yaml")

    assert summary["n_reactions"] == 0
    assert summary["n_reactions_with_cross_section_asset"] == 0
    assert summary["by_depth"] == {}
    assert quality["readiness"]["mechanism_ready_for_review"] is False
    assert quality["readiness"]["cross_section_asset_coverage_fraction"] == 0.0
    assert quality["readiness"]["provenance_coverage_fraction"] == 0.0
    assert quality["top_missing_actions"] == []


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
