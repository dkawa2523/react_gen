from __future__ import annotations

from pathlib import Path
import socket

import pytest
import yaml

from external_data_tools.benchmark_runner import run_benchmarks


CASE_IDS = [
    "ar_o2_simple",
    "ar_cf4_fluorocarbon",
    "sf6_o2_electronegative",
]


def test_runner_executes_ar_o2_simple(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    config = _write_config(tmp_path, repo_root)

    summary = run_benchmarks(config, only="ar_o2_simple")
    result_dir = config.parent / "results" / "ar_o2_simple"
    report = _read_yaml(result_dir / "benchmark_report.yaml")
    metrics = _read_yaml(result_dir / "benchmark_metrics.yaml")

    assert summary["summary"]["n_passed"] == 1
    assert report["passed"] is True
    assert (result_dir / "work" / "missing_plan.yaml").exists()
    assert (result_dir / "work" / "manual_inputs" / "cross_section_mapping.yaml").exists()
    assert metrics["n_missing_plan_actions"] > 0
    assert metrics["expectation_score"] == 1.0
    assert metrics["solver_status_summary"]["disabled"] >= 1


def test_runner_executes_all_three_benchmarks(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    config = _write_config(tmp_path, repo_root)

    summary = run_benchmarks(config)
    summary_file = _read_yaml(config.parent / "results" / "summary.yaml")
    ids = [item["id"] for item in summary_file["benchmarks"]]

    assert summary["summary"]["n_benchmarks"] == 3
    assert summary["summary"]["n_failed"] == 0
    assert ids == CASE_IDS
    assert "cl2_bcl3_halogen" not in yaml.safe_dump(summary_file, sort_keys=True)
    for case_id in CASE_IDS:
        assert (config.parent / "results" / case_id / "benchmark_report.yaml").exists()


def test_required_fixture_missing_causes_setup_failure(tmp_path):
    data_requirements = tmp_path / "missing_data_requirements.yaml"
    data_requirements.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "required_for_registry_benchmark": [
                    {
                        "id": "missing_required_fixture",
                        "kind": "internal_file_db",
                        "path": str(tmp_path / "does_not_exist"),
                        "required": True,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    solver_config = tmp_path / "solvers.yaml"
    solver_config.write_text("schema_version: 1\nsolvers: {}\n", encoding="utf-8")
    setup_config = tmp_path / "benchmark_setup.yaml"
    setup_config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "external_solvers": {"config": str(solver_config)},
                "data_requirements": {"config": str(data_requirements)},
                "policies": {
                    "allow_network_downloads": False,
                    "fail_if_required_data_missing": True,
                    "fail_if_required_solver_missing": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = tmp_path / "benchmark_config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "setup": {"config": str(setup_config), "require_success": True},
                "benchmarks": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="benchmark setup check failed"):
        run_benchmarks(config)

    report = _read_yaml(tmp_path / "results" / "setup_report.yaml")
    assert report["summary"]["required_data_ready"] is False


def test_optional_missing_solver_is_skipped_not_failed(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    solver_config = tmp_path / "external_solvers.yaml"
    solver_config.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "solvers": {
                    "ngspice": {
                        "enabled": True,
                        "executable": str(tmp_path / "missing_ngspice"),
                        "adapter": "ngspice_basic",
                        "install": {"mode": "package_manager_or_user_path"},
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = _write_config(tmp_path, repo_root, external_solvers=solver_config)

    summary = run_benchmarks(config, only="ar_o2_simple")
    report = _read_yaml(config.parent / "results" / "ar_o2_simple" / "benchmark_report.yaml")
    metrics = _read_yaml(config.parent / "results" / "ar_o2_simple" / "benchmark_metrics.yaml")

    assert summary["summary"]["n_failed"] == 0
    assert report["passed"] is True
    assert metrics["solver_status_summary"]["skipped_missing_executable"] == 1


def test_cross_section_import_and_mapping_happen_before_generate(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    config = _write_config(tmp_path, repo_root)
    run_benchmarks(config, only="ar_o2_simple")

    result_dir = config.parent / "results" / "ar_o2_simple"
    report = _read_yaml(result_dir / "benchmark_report.yaml")
    commands = [step["command"] for step in report["steps"]]

    import_index = _index_containing(commands, "import-cross-sections")
    mapping_index = _index_containing(commands, "apply-cross-section-mapping")
    generate_index = _index_containing(commands, "generate")
    assert import_index < generate_index
    assert mapping_index < generate_index

    reactions = _read_yaml(result_dir / "outputs" / "network.reactions.yaml")["reactions"]
    elastic = next(reaction for reaction in reactions if reaction["id"] == "e_O2_elastic")
    assert elastic["data"]["cross_section"]["path"].endswith(".csv")


def _write_config(tmp_path: Path, repo_root: Path, *, external_solvers: Path | None = None) -> Path:
    config_path = tmp_path / "benchmarks" / "benchmark_config.yaml"
    solver_config = external_solvers or repo_root / "benchmarks" / "external_solvers.example.yaml"
    payload = {
        "schema_version": 1,
        "setup": {
            "config": str(repo_root / "benchmarks" / "benchmark_setup.yaml"),
            "require_success": True,
        },
        "benchmarks": [
            _benchmark_payload(
                case_id,
                repo_root,
                config_path.parent / "results" / case_id,
                solver_config,
            )
            for case_id in CASE_IDS
        ],
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config_path


def _benchmark_payload(case_id: str, repo_root: Path, result_dir: Path, solver_config: Path) -> dict:
    fixture = repo_root / "benchmarks" / "fixtures" / case_id
    imports = {
        "ar_o2_simple": [
            {
                "file": str(fixture / "cross_sections" / "e_O2_elastic.csv"),
                "source": "local_file",
                "reaction_id": "e_O2_elastic",
                "target": "O2",
                "license_note": "synthetic benchmark fixture",
            }
        ],
        "ar_cf4_fluorocarbon": [
            {
                "file": str(fixture / "cross_sections" / "e_CF4_elastic.csv"),
                "source": "local_file",
                "reaction_id": "e_CF4_elastic",
                "target": "CF4",
                "license_note": "synthetic benchmark fixture",
            }
        ],
        "sf6_o2_electronegative": [
            {
                "file": str(fixture / "cross_sections" / "e_SF6_elastic.csv"),
                "source": "local_file",
                "reaction_id": "e_SF6_elastic",
                "target": "SF6",
                "license_note": "synthetic benchmark fixture",
            },
            {
                "file": str(fixture / "cross_sections" / "e_O2_elastic.csv"),
                "source": "local_file",
                "reaction_id": "e_O2_elastic",
                "target": "O2",
                "license_note": "synthetic benchmark fixture",
            },
        ],
    }
    return {
        "id": case_id,
        "case": str(repo_root / "benchmarks" / "cases" / case_id / "input.yaml"),
        "registry": str(repo_root / "registry"),
        "source_profile": str(fixture / "source_profile.yaml"),
        "workspace": str(result_dir / "work"),
        "output": str(result_dir / "outputs"),
        "expectation": str(repo_root / "benchmarks" / "expectations" / f"{case_id}.yaml"),
        "external_solvers": str(solver_config),
        "cross_section_imports": imports[case_id],
        "cross_section_mapping": str(fixture / "cross_section_mapping.yaml"),
    }


def _block_network(monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("semiconductor benchmark runner must not access network")

    monkeypatch.setattr(socket, "socket", fail_socket)


def _index_containing(commands: list[str], text: str) -> int:
    for index, command in enumerate(commands):
        if text in command:
            return index
    raise AssertionError(f"command not found: {text}")


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
