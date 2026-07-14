from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

from external_data_tools.benchmark_setup import main, run_setup
from external_data_tools.benchmark_data_requirements import check_data_requirements


def test_missing_required_data_causes_failed_status_and_nonzero(tmp_path):
    setup = _write_setup_config(
        tmp_path,
        data_records=[
            {
                "id": "missing_required",
                "kind": "internal_file_db",
                "path": "missing/internal_data",
                "required": True,
            }
        ],
    )

    report, exit_code = run_setup(setup, check=True)

    assert exit_code == 1
    assert report["summary"]["required_data_ready"] is False
    assert report["data_status"][0]["status"] == "required_missing"


def test_install_python_deps_is_not_run_unless_flag_is_passed(tmp_path, monkeypatch):
    requirement = tmp_path / "requirements.txt"
    requirement.write_text("# empty\n", encoding="utf-8")
    setup = _write_setup_config(
        tmp_path,
        data_records=[],
        requirements=[str(requirement)],
        policies={"fail_if_required_data_missing": False},
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("external_data_tools.benchmark_setup.subprocess.run", fake_run)

    run_setup(setup, check=True, install_python_deps=False)
    assert calls == []

    report, exit_code = run_setup(setup, install_python_deps=True)
    assert exit_code == 0
    assert len(calls) == 1
    assert "-m" in calls[0] and "pip" in calls[0]
    assert report["summary"]["python_optional_dependencies_installed"] is True


def test_download_explicit_data_requires_flag_and_policy(tmp_path, monkeypatch):
    manifest = tmp_path / "downloads.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "downloads": [
                    {
                        "id": "example",
                        "url": "file:///example.txt",
                        "output": "example.txt",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    setup = _write_setup_config(
        tmp_path,
        data_records=[],
        download_manifest=str(manifest),
        policies={"fail_if_required_data_missing": False, "allow_network_downloads": True},
    )
    calls = []

    def fake_download_many(payload, output_root, dry_run=False):
        calls.append((payload, output_root, dry_run))
        return {
            "schema_version": 1,
            "summary": {"total": 1, "planned": 0, "downloaded": 1, "failed": 0},
            "records": [{"id": "example"}],
        }

    monkeypatch.setattr("external_data_tools.benchmark_setup.download_many", fake_download_many)

    report, exit_code = run_setup(setup, check=True, download_explicit_data=False)
    assert exit_code == 0
    assert calls == []
    assert report["downloads"]["ran"] is False

    report, exit_code = run_setup(setup, download_explicit_data=True)
    assert exit_code == 0
    assert len(calls) == 1
    assert report["downloads"]["ran"] is True

    blocked = _write_setup_config(
        tmp_path / "blocked",
        data_records=[],
        download_manifest=str(manifest),
        policies={"fail_if_required_data_missing": False, "allow_network_downloads": False},
    )
    report, exit_code = run_setup(blocked, download_explicit_data=True)
    assert exit_code == 1
    assert report["downloads"]["ran"] is False
    assert "disabled by policy" in report["downloads"]["error"]


def test_setup_report_is_written(tmp_path):
    setup = _write_setup_config(
        tmp_path,
        data_records=[],
        policies={"fail_if_required_data_missing": False},
    )
    report_path = tmp_path / "setup_report.yaml"

    rc = main(["--config", str(setup), "--check", "--write-report", str(report_path)])

    assert rc == 0
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert "summary" in report


def test_check_data_requirements_records_file_sha256(tmp_path):
    data_file = tmp_path / "table.csv"
    data_file.write_text("energy_eV,cross_section_m2\n1,1e-20\n", encoding="utf-8")
    requirements = tmp_path / "requirements.yaml"
    requirements.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "required_for_registry_benchmark": [
                    {
                        "id": "xsec",
                        "kind": "cross_section_csv",
                        "path": str(data_file),
                        "required": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = check_data_requirements(requirements)

    assert report["summary"]["required_data_ready"] is True
    assert report["data_status"][0]["status"] == "ready"
    assert len(report["data_status"][0]["sha256"]) == 64


def _write_setup_config(
    root: Path,
    *,
    data_records: list[dict],
    requirements: list[str] | None = None,
    download_manifest: str | None = None,
    policies: dict | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    data_config = root / "data_requirements.yaml"
    data_config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "required_for_registry_benchmark": data_records,
                "optional_for_registry_benchmark": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    setup = root / "benchmark_setup.yaml"
    setup.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "python": {
                    "install_optional_dependencies": False,
                    "requirements": requirements or [],
                },
                "data_requirements": {"config": str(data_config)},
                "downloads": {"manifest": download_manifest or str(root / "downloads.yaml")},
                "policies": {
                    "allow_network_downloads": False,
                    "allow_system_package_install": False,
                    "fail_if_required_data_missing": True,
                    **(policies or {}),
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return setup
