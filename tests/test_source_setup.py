from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from external_data_tools.source_setup import main, run_source_setup, validate_access_profile


def test_default_source_setup_profile_checks_and_writes_report(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report_path = tmp_path / "source_setup_report.yaml"

    report, exit_code = run_source_setup(
        repo_root / "external_data" / "source_access_profiles.yaml",
        check=True,
        write_report=report_path,
    )

    assert exit_code == 0
    assert report["schema_version"] == 2
    assert report["summary"]["valid"] is True
    assert report["summary"]["n_sources"] >= 5
    assert report["summary"]["downloads_ran"] is False
    assert "downloads_requested" not in report["summary"]
    assert "chemicals_install_requested" not in report["summary"]
    assert report_path.exists()


def test_chemicals_install_is_not_run_unless_flag_is_passed(tmp_path: Path, monkeypatch) -> None:
    requirements = tmp_path / "requirements-chemicals.txt"
    requirements.write_text("chemicals>=1.5\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        optional_python_dependencies={"chemicals": {"requirements": str(requirements)}},
        sources=[
            _source("chemicals_optional", enabled=True, access_mode="optional_python_package")
        ],
    )
    calls = []

    def fake_run(command):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "external_data_tools.source_setup_actions.run_install_command",
        fake_run,
    )
    monkeypatch.setattr(
        "external_data_tools.source_setup_actions.importlib.util.find_spec",
        lambda name: None,
    )

    report, exit_code = run_source_setup(config, check=True, install_chemicals=False)
    assert exit_code == 0
    assert calls == []
    assert report["chemicals"]["install_requested"] is False

    report, exit_code = run_source_setup(config, install_chemicals=True)
    assert exit_code == 0
    assert len(calls) == 1
    assert "-m" in calls[0]
    assert "pip" in calls[0]
    assert report["chemicals"]["installed"] is True


def test_explicit_downloads_require_flag_and_policy(tmp_path: Path, monkeypatch) -> None:
    manifest = tmp_path / "downloads.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "downloads": [
                    {
                        "id": "example",
                        "url": "https://example.invalid/file.yaml",
                        "output": "source/file.yaml",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = _write_config(
        tmp_path,
        policies={"allow_network_downloads": True},
        sources=[
            _source(
                "nist_snapshot",
                enabled=True,
                access_mode="manual_snapshot_or_explicit_url",
                download_manifest=str(manifest),
                download_output_root=str(tmp_path / "raw"),
            )
        ],
    )
    calls = []

    def fake_download_many(payload, output_root, dry_run=False):
        calls.append((payload, output_root, dry_run))
        return {
            "schema_version": 1,
            "summary": {"total": 1, "planned": 0, "downloaded": 1, "failed": 0},
            "records": [{"id": "example"}],
        }

    monkeypatch.setattr(
        "external_data_tools.source_setup_actions.download_many",
        fake_download_many,
    )

    report, exit_code = run_source_setup(config, check=True, download_explicit_data=False)
    assert exit_code == 0
    assert calls == []
    assert report["downloads"]["ran"] is False

    report, exit_code = run_source_setup(config, download_explicit_data=True)
    assert exit_code == 0
    assert len(calls) == 1
    assert report["downloads"]["ran"] is True


def test_explicit_downloads_are_blocked_when_policy_disallows_network(tmp_path: Path) -> None:
    manifest = tmp_path / "downloads.yaml"
    manifest.write_text("schema_version: 1\ndownloads: []\n", encoding="utf-8")
    config = _write_config(
        tmp_path,
        policies={"allow_network_downloads": False},
        sources=[
            _source(
                "pubchem",
                enabled=True,
                access_mode="public_api_explicit_cli",
                download_manifest=str(manifest),
            )
        ],
    )

    report, exit_code = run_source_setup(config, download_explicit_data=True)

    assert exit_code == 1
    assert report["downloads"]["ran"] is False
    assert "disabled by policy" in report["downloads"]["error"]


def test_access_profile_rejects_core_generate_and_scraping() -> None:
    payload = {
        "schema_version": 1,
        "sources": [
            _source(
                "bad_public_api",
                enabled=True,
                access_mode="public_api",
                automation_level="scraping",
                allowed_in_core_generate=True,
            )
        ],
    }

    report = validate_access_profile(payload)

    assert not report["valid"]
    assert any("core generate" in error for error in report["errors"])
    assert any("unsupported automation_level" in error for error in report["errors"])


def test_access_profile_reports_shape_duplicates_and_actionable_warnings(
    tmp_path: Path,
) -> None:
    source = _source(
        "duplicate",
        enabled=True,
        access_mode="public_api",
        download_manifest="missing-downloads.yaml",
    )
    source.update(
        {
            "requires_license_review": True,
            "license_note": "",
            "requires_api_key": True,
            "api_key_env": "",
        }
    )
    payload = {
        "schema_version": 1,
        "sources": [source, {"source_id": "duplicate"}, "not-a-record"],
    }

    report = validate_access_profile(
        payload,
        config_path=tmp_path / "source_access_profiles.yaml",
    )

    assert report["summary"] == {"n_errors": 5, "n_warnings": 3}
    assert "duplicate: duplicate source_id" in report["errors"]
    assert "sources[2] must be a mapping" in report["errors"]
    assert any("license_note" in warning for warning in report["warnings"])
    assert any("api_key_env" in warning for warning in report["warnings"])
    assert any("download manifest not found" in warning for warning in report["warnings"])


def test_chemicals_install_requires_existing_requirements_file(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        optional_python_dependencies={"chemicals": {"requirements": str(tmp_path / "missing.txt")}},
    )

    report, exit_code = run_source_setup(config, install_chemicals=True)

    assert exit_code == 1
    assert report["chemicals"]["installed"] is False
    assert report["chemicals"]["error"] == "requirements file not found"


def test_source_setup_cli_prints_summary_and_writes_report(tmp_path: Path, capsys) -> None:
    config = _write_config(tmp_path)
    report_path = tmp_path / "cli-report.yaml"

    exit_code = main(
        [
            "--config",
            str(config),
            "--check",
            "--write-report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    assert report_path.exists()
    assert "enabled_sources: 0/0" in capsys.readouterr().out


def _write_config(
    root: Path,
    *,
    policies: dict | None = None,
    sources: list[dict] | None = None,
    optional_python_dependencies: dict | None = None,
) -> Path:
    config = root / "source_access_profiles.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "policies": {
                    "allow_network_downloads": False,
                    "report_path": str(root / "source_setup_report.yaml"),
                    **(policies or {}),
                },
                "optional_python_dependencies": optional_python_dependencies or {},
                "sources": sources or [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config


def _source(
    source_id: str,
    *,
    enabled: bool,
    access_mode: str,
    automation_level: str = "explicit_user_url_only",
    download_manifest: str | None = None,
    download_output_root: str | None = None,
    allowed_in_core_generate: bool = False,
) -> dict:
    source = {
        "source_id": source_id,
        "enabled": enabled,
        "access_mode": access_mode,
        "automation_level": automation_level,
        "requires_registration": False,
        "requires_license_review": True,
        "requires_api_key": False,
        "license_note": "test license review",
        "allowed_in_core_generate": allowed_in_core_generate,
    }
    if download_manifest is not None:
        source["download_manifest"] = download_manifest
    if download_output_root is not None:
        source["download_output_root"] = download_output_root
    return source
