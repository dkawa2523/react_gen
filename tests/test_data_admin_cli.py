from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from external_data_tools import data_admin


def test_plan_command_writes_full_plan_and_prints_summary(tmp_path, monkeypatch, capsys):
    captured: dict[str, Any] = {}

    def plan_registry_pack(**kwargs):
        captured.update(kwargs)
        return {"summary": {"species": 3}, "details": ["A", "B", "e"]}

    monkeypatch.setattr(data_admin, "plan_registry_pack", plan_registry_pack)
    output = tmp_path / "plan.yaml"

    exit_code = data_admin.main(
        [
            "plan_registry_pack",
            "--seed-gases",
            "A",
            "B",
            "--max-depth",
            "4",
            "--registry",
            str(tmp_path / "registry"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "seed_gases": ["A", "B"],
        "max_depth": 4,
        "registry_root": tmp_path / "registry",
    }
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["details"] == ["A", "B", "e"]
    assert yaml.safe_load(capsys.readouterr().out) == {"species": 3}


def test_data_acquisition_command_forwards_arbitrary_gases(tmp_path, monkeypatch, capsys):
    captured: dict[str, Any] = {}

    def plan_data_acquisition(**kwargs):
        captured.update(kwargs)
        return {"summary": {"n_electron_datasets": 2}, "built": True}

    monkeypatch.setattr(data_admin, "plan_data_acquisition", plan_data_acquisition)
    output_dir = tmp_path / "acquisition"

    exit_code = data_admin.main(
        [
            "plan_data_acquisition",
            "--seed-gases",
            "Ar",
            "O2",
            "--registry",
            str(tmp_path / "registry"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "seed_gases": ["Ar", "O2"],
        "max_depth": None,
        "registry_root": tmp_path / "registry",
        "output_dir": output_dir,
        "vamdc_endpoint": None,
    }
    assert yaml.safe_load(capsys.readouterr().out) == {"n_electron_datasets": 2}


def test_import_commands_forward_shared_paths(tmp_path, monkeypatch):
    calls: list[tuple[str, Path, dict[str, Any]]] = []

    def record_import(name: str):
        def run(path: Path, **kwargs):
            calls.append((name, path, kwargs))
            return {"summary": {"n_applied": 1}}

        return run

    monkeypatch.setattr(data_admin, "import_lxcat_raw", record_import("lxcat"))
    monkeypatch.setattr(data_admin, "import_property_snapshot", record_import("property"))
    monkeypatch.setattr(data_admin, "import_rate_snapshot", record_import("rate"))
    registry = tmp_path / "registry"
    reports = tmp_path / "reports"

    assert (
        data_admin.main(
            [
                "import_lxcat_raw",
                str(tmp_path / "lxcat.txt"),
                "--registry",
                str(registry),
                "--report-dir",
                str(reports),
                "--redistribution-status",
                "internal",
            ]
        )
        == 0
    )
    assert (
        data_admin.main(
            [
                "import_property_snapshot",
                str(tmp_path / "properties.yaml"),
                "--registry",
                str(registry),
                "--report-dir",
                str(reports),
            ]
        )
        == 0
    )
    assert (
        data_admin.main(
            [
                "import_rate_snapshot",
                str(tmp_path / "rates.yaml"),
                "--registry",
                str(registry),
                "--report-dir",
                str(reports),
            ]
        )
        == 0
    )

    assert calls == [
        (
            "lxcat",
            tmp_path / "lxcat.txt",
            {
                "registry_root": registry,
                "report_dir": reports,
                "redistribution_status": "internal",
            },
        ),
        (
            "property",
            tmp_path / "properties.yaml",
            {"registry_root": registry, "report_dir": reports},
        ),
        (
            "rate",
            tmp_path / "rates.yaml",
            {"registry_root": registry, "report_dir": reports},
        ),
    ]


def test_nist_beb_command_forwards_targets_to_site_local_registry(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}

    def import_nist_beb(targets, **kwargs):
        captured["targets"] = targets
        captured.update(kwargs)
        return {"summary": {"n_applied": 3}}

    monkeypatch.setattr(data_admin, "import_nist_beb", import_nist_beb)
    registry = tmp_path / "prepared_registry"
    reports = tmp_path / "reports"

    assert (
        data_admin.main(
            [
                "import_nist_beb",
                "--targets",
                "O2",
                "SF5",
                "SF6",
                "--registry",
                str(registry),
                "--report-dir",
                str(reports),
            ]
        )
        == 0
    )
    assert captured == {
        "targets": ["O2", "SF5", "SF6"],
        "registry_root": registry,
        "report_dir": reports,
        "redistribution_status": "site-local",
    }


def test_oxygen_command_uses_explicit_site_local_import(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}

    def import_oxygen_cross_sections(**kwargs):
        captured.update(kwargs)
        return {"summary": {"n_applied": 7}}

    monkeypatch.setattr(
        data_admin,
        "import_oxygen_cross_sections",
        import_oxygen_cross_sections,
    )
    registry = tmp_path / "prepared_registry"
    reports = tmp_path / "reports"

    assert (
        data_admin.main(
            [
                "import_oxygen_cross_sections",
                "--registry",
                str(registry),
                "--report-dir",
                str(reports),
            ]
        )
        == 0
    )
    assert captured == {
        "registry_root": registry,
        "report_dir": reports,
        "redistribution_status": "site-local",
    }


def test_build_command_returns_failure_when_pack_is_not_built(tmp_path, monkeypatch, capsys):
    captured: dict[str, Any] = {}

    def build_registry_pack(**kwargs):
        captured.update(kwargs)
        return {"built": False, "summary": {"reason": "coverage gap"}}

    monkeypatch.setattr(data_admin, "build_registry_pack", build_registry_pack)

    exit_code = data_admin.main(
        [
            "build_registry_pack",
            "--id",
            "test-pack",
            "--version",
            "1.0.0",
            "--seed-gases",
            "A",
            "--registry",
            str(tmp_path / "registry"),
            "--packs-root",
            str(tmp_path / "packs"),
        ]
    )

    assert exit_code == 1
    assert captured["pack_id"] == "test-pack"
    assert captured["version"] == "1.0.0"
    assert captured["seed_gases"] == ["A"]
    assert captured["max_depth"] == 2
    assert captured["redistribution_status"] == "site-local"
    assert yaml.safe_load(capsys.readouterr().out) == {"reason": "coverage gap"}
