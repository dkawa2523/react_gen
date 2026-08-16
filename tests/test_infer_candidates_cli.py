from pathlib import Path

import pytest
import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.inference.candidate_writer import build_candidate_registry
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.interface.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_normal_help_hides_maintenance_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "generate" in help_text
    assert "infer-candidates" not in help_text
    assert "promote" not in help_text


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
    assert summary["schema_version"] == 2
    assert "registry_mutated" not in summary
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
        reaction["data_status"]["reaction"] != "inferred" for reaction in network["reactions"]
    )


def test_candidate_registry_builds_unique_reactions_without_mutating_source_registry():
    registry_root = ROOT / "registry"
    before = {path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")}
    candidates = build_candidate_registry(
        load_case_config(ROOT / "cases" / "ar_cf4" / "input.yaml", registry_root),
        FileRegistry(registry_root),
    )

    reactions = candidates["reactions"]
    reaction_ids = [reaction["id"] for reaction in reactions]
    assert len(reaction_ids) == len(set(reaction_ids))
    assert {reaction["pair"]["family"] for reaction in reactions} == {
        "electron",
        "ion_neutral",
    }
    assert all(reaction["status"] == "inferred" for reaction in reactions)
    assert {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    } == before
