from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.db_cleanup_plan import build_cleanup_report


def test_db_cleanup_dry_run_does_not_mutate_files(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    decision = _write_decisions(
        repo / "cleanup.yaml",
        [{"target": "chemicals_optional", "action": "disable", "reason": "test"}],
    )
    profile = repo / "registry" / "rules" / "source_profiles" / "experimental_first.yaml"
    before = profile.read_text(encoding="utf-8")

    report = build_cleanup_report(
        repo / "docs" / "db_provider_audit.md",
        decision_path=decision,
        repo_root=repo,
        apply=False,
    )

    assert report["mode"] == "dry_run"
    assert report["summary"]["repository_mutated"] is False
    assert profile.read_text(encoding="utf-8") == before
    assert "registry/rules/source_profiles/experimental_first.yaml" in report["decisions"][0]["files_to_modify"]


def test_db_cleanup_disable_updates_source_profile_fixture(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    decision = _write_decisions(
        repo / "cleanup.yaml",
        [{"target": "chemicals_optional", "action": "disable", "reason": "test"}],
    )

    report = build_cleanup_report(
        repo / "docs" / "db_provider_audit.md",
        decision_path=decision,
        repo_root=repo,
        apply=True,
    )

    profile = _read_yaml(repo / "registry" / "rules" / "source_profiles" / "experimental_first.yaml")
    assert report["summary"]["repository_mutated"] is True
    assert "chemicals_optional" not in profile["properties"]
    assert (repo / "docs" / "db_cleanup_decisions.md").exists()


def test_db_cleanup_remove_refuses_if_active_import_remains(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _write_text(repo / "external_data_tools" / "vamdc_query.py", "def run_vamdc_queries():\n    pass\n")
    _write_text(repo / "src" / "uses_vamdc.py", "from external_data_tools.vamdc_query import run_vamdc_queries\n")
    decision = _write_decisions(
        repo / "cleanup.yaml",
        [{"target": "vamdc_external_tools", "action": "remove", "reason": "test", "remove_tests": True}],
    )

    report = build_cleanup_report(
        repo / "docs" / "db_provider_audit.md",
        decision_path=decision,
        repo_root=repo,
        apply=True,
    )

    item = report["decisions"][0]
    assert item["blocked"] is True
    assert item["block_reason"] == "active imports remain"
    assert item["applied"] is False
    assert (repo / "external_data_tools" / "vamdc_query.py").exists()


def test_db_cleanup_unknown_target_reports_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    decision = _write_decisions(
        repo / "cleanup.yaml",
        [{"target": "unknown_db", "action": "remove", "reason": "test"}],
    )

    report = build_cleanup_report(
        repo / "docs" / "db_provider_audit.md",
        decision_path=decision,
        repo_root=repo,
        apply=False,
    )

    assert report["summary"]["n_errors"] == 1
    assert report["errors"] == ["unknown cleanup target: unknown_db"]


def _make_repo(root: Path) -> Path:
    _write_text(root / "docs" / "db_provider_audit.md", "# audit\n")
    _write_yaml(
        root / "registry" / "rules" / "source_profiles" / "experimental_first.yaml",
        {
            "schema_version": 1,
            "name": "experimental_first",
            "species_identity": ["local_registry"],
            "properties": ["local_registry", "chemicals_optional"],
            "electron_cross_sections": ["local_assets"],
            "ion_neutral_reactions": ["local_registry"],
        },
    )
    _write_text(root / "external_data_tools" / "__init__.py", "")
    _write_text(root / "tests" / "test_placeholder.py", "def test_ok():\n    assert True\n")
    return root


def _write_decisions(path: Path, decisions: list[dict]) -> Path:
    return _write_yaml(path, {"schema_version": 1, "decisions": decisions})


def _write_yaml(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
