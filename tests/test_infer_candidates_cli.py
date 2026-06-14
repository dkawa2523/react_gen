from pathlib import Path

import yaml
import pytest

from plasma_reactgen.interface.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_infer_candidates_help_is_available():
    with pytest.raises(SystemExit) as exc:
        main(["infer-candidates", "--help"])
    assert exc.value.code == 0


def test_infer_candidates_writes_candidate_registry_only(tmp_path):
    output_dir = tmp_path / "candidate_registry"

    rc = main(
        [
            "infer-candidates",
            str(ROOT / "cases" / "ar_cf4" / "input.yaml"),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / "species").is_dir()
    assert (output_dir / "reactions").is_dir()
    assert (output_dir / "summary.yaml").exists()
    assert not (output_dir / "network.reactions.yaml").exists()
    assert not (output_dir / "dnt_tasks.yaml").exists()
    assert not (output_dir / "species" / "Ar_p.yaml").exists()

    summary = yaml.safe_load((output_dir / "summary.yaml").read_text(encoding="utf-8"))
    assert summary["registry_mutated"] is False
    assert summary["summary"]["n_species_candidates"] > 0
    assert summary["summary"]["n_reaction_candidates"] > 0

    species_payload = yaml.safe_load(
        next((output_dir / "species").glob("*.yaml")).read_text(encoding="utf-8")
    )
    reaction_payload = yaml.safe_load(
        next((output_dir / "reactions").glob("*.yaml")).read_text(encoding="utf-8")
    )
    assert species_payload["kind"] in {"species_candidate", "fragment_set_candidate"}
    assert reaction_payload["kind"] == "reaction_channel_candidate"


def test_generate_does_not_write_candidate_registry_by_default(tmp_path):
    output_dir = tmp_path / "outputs"

    rc = main(
        [
            "generate",
            str(ROOT / "cases" / "ar_cf4" / "input.yaml"),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert not (output_dir / "candidate_registry").exists()
    network = yaml.safe_load((output_dir / "network.reactions.yaml").read_text(encoding="utf-8"))
    assert all(
        reaction["data_status"]["reaction"] != "inferred"
        for reaction in network["reactions"]
    )
