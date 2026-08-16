from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from plasma_reactgen.interface.cli import main


def test_ar_cf4_db_smoke_workflow_runs_end_to_end(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    registry = repo_root / "registry"
    fixture_case = repo_root / "cases" / "ar_cf4_db_smoke"
    case_dir = tmp_path / "ar_cf4_db_smoke"
    shutil.copytree(fixture_case, case_dir)
    _rewrite_source_profile_roots(case_dir / "source_profile.yaml", case_dir / "internal_data", registry)

    original_registry = _snapshot_yaml(registry)
    workspace = case_dir / "work"
    outputs = case_dir / "outputs"
    visualizations = case_dir / "visualizations"

    assert main(
        [
            "enrich",
            str(case_dir / "input.yaml"),
            "--registry",
            str(registry),
            "--workspace",
            str(workspace),
            "--source-profile",
            str(case_dir / "source_profile.yaml"),
        ]
    ) == 0

    assert main(
        [
            "import-cross-sections",
            str(case_dir / "cross_sections" / "e_CF4_elastic.csv"),
            "--workspace",
            str(workspace),
            "--source",
            "local_file",
            "--reaction-id",
            "e_CF4_elastic",
            "--target",
            "CF4",
            "--license-note",
            "synthetic test fixture",
        ]
    ) == 0

    assert main(
        [
            "apply-cross-section-mapping",
            str(case_dir / "cross_section_mapping.yaml"),
            "--workspace",
            str(workspace),
        ]
    ) == 0

    assert main(
        [
            "generate",
            str(case_dir / "input.yaml"),
            "--registry",
            str(workspace / "prepared_registry"),
            "--output",
            str(outputs),
        ]
    ) == 0

    assert main(
        [
            "plan-missing",
            str(outputs),
            "--output",
            str(workspace / "missing_plan.yaml"),
        ]
    ) == 0

    assert main(
        [
            "visualize",
            str(outputs),
            "--output",
            str(visualizations),
            "--formats",
            "svg,png",
        ]
    ) == 0

    prepared_registry = workspace / "prepared_registry"
    assert prepared_registry.exists()
    assert (workspace / "enrichment_report.yaml").exists()
    assert (outputs / "network.reactions.yaml").exists()
    assert (outputs / "network.states.yaml").exists()
    assert (outputs / "dnt_tasks.yaml").exists()
    assert (outputs / "dnt_manifest.yaml").exists()
    assert (outputs / "missing_data.yaml").exists()
    assert (workspace / "missing_plan.yaml").exists()

    reactions = _read_yaml(outputs / "network.reactions.yaml")["reactions"]
    assert any(reaction["family"] == "electron" for reaction in reactions)
    assert any(reaction["family"] == "ion_neutral" for reaction in reactions)

    prepared_cf4 = _read_yaml(prepared_registry / "reactions" / "electron" / "e__CF4.yaml")
    elastic = next(channel for channel in prepared_cf4["channels"] if channel["id"] == "e_CF4_elastic")
    cross_section = elastic["data"]["cross_section"]
    assert cross_section["status"] == "local_file_registered"
    assert cross_section["path"] == "assets/cross_sections/e_CF4_elastic_ad89a4ea17.csv"
    assert (prepared_registry / cross_section["path"]).exists()

    manifest = json.loads((visualizations / "manifest.json").read_text(encoding="utf-8"))
    assert Path(manifest["network"]["dot"]).exists()
    assert Path(manifest["lineage"]["dot"]).exists()
    if manifest["network"]["graphviz_dot_available"]:
        assert manifest["network"]["rendered"]
        assert all(Path(path).exists() for path in manifest["network"]["rendered"])

    assert _snapshot_yaml(registry) == original_registry


def _rewrite_source_profile_roots(profile_path: Path, internal_root: Path, registry_root: Path) -> None:
    profile = _read_yaml(profile_path)
    profile.setdefault("internal_file", {})["root"] = str(internal_root)
    profile.setdefault("local_registry", {})["root"] = str(registry_root)
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _snapshot_yaml(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.yaml"))
    }


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
