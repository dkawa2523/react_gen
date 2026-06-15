from __future__ import annotations

from pathlib import Path
import socket

import yaml

from external_data_tools.benchmark_metrics import collect_metrics, evaluate_expectations
from external_data_tools.benchmark_runner import run_benchmarks


def test_benchmark_runner_works_on_ar_cf4_db_smoke(tmp_path, monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("benchmark runner must not access the network")

    monkeypatch.setattr(socket, "socket", fail_socket)

    repo_root = Path(__file__).resolve().parents[1]
    config = _write_benchmark_config(tmp_path / "benchmarks" / "benchmark_config.yaml", repo_root)
    original_registry = _snapshot_yaml(repo_root / "registry")

    summary = run_benchmarks(config, only="ar_cf4_db_smoke")

    result_dir = config.parent / "results" / "ar_cf4_db_smoke"
    report = _read_yaml(result_dir / "benchmark_report.yaml")
    metrics = _read_yaml(result_dir / "benchmark_metrics.yaml")
    summary_file = _read_yaml(config.parent / "results" / "summary.yaml")

    assert summary["summary"]["n_benchmarks"] == 1
    assert summary["summary"]["n_passed"] == 1
    assert summary_file["benchmarks"][0]["id"] == "ar_cf4_db_smoke"
    assert report["passed"] is True
    assert report["expectations"]["passed"] is True
    assert report["expectations"]["score"] == 1.0
    assert metrics["n_species"] >= 2
    assert metrics["n_reactions"] > 0
    assert metrics["n_electron_reactions"] > 0
    assert metrics["n_ion_neutral_reactions"] > 0
    assert metrics["n_dnt_tasks"] > 0
    assert (result_dir / "outputs" / "network.reactions.yaml").exists()
    assert (result_dir / "outputs" / "dnt_tasks.yaml").exists()
    assert _snapshot_yaml(repo_root / "registry") == original_registry


def test_metrics_and_expectations_can_be_collected_from_benchmark_outputs(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config = _write_benchmark_config(tmp_path / "benchmarks" / "benchmark_config.yaml", repo_root)
    run_benchmarks(config, only="ar_cf4_db_smoke")

    result_dir = config.parent / "results" / "ar_cf4_db_smoke"
    output = result_dir / "outputs"
    prepared_registry = result_dir / "work" / "prepared_registry"
    expectation = repo_root / "benchmarks" / "expectations" / "ar_cf4_expectations.yaml"

    metrics = collect_metrics(output, prepared_registry)
    evaluation = evaluate_expectations(output, expectation)

    assert metrics["validation_error_count"] == 0
    assert metrics["imported_or_literature_supported_fraction"] >= 0
    assert evaluation["passed"] is True
    assert evaluation["missing_species"] == []
    assert evaluation["missing_reaction_families"] == []
    assert evaluation["missing_outputs"] == []


def _write_benchmark_config(path: Path, repo_root: Path) -> Path:
    payload = {
        "schema_version": 1,
        "benchmarks": [
            {
                "id": "ar_cf4_db_smoke",
                "case": str(repo_root / "cases" / "ar_cf4_db_smoke" / "input.yaml"),
                "registry": str(repo_root / "registry"),
                "source_profile": str(repo_root / "cases" / "ar_cf4_db_smoke" / "source_profile.yaml"),
                "workspace": str(path.parent / "results" / "ar_cf4_db_smoke" / "work"),
                "output": str(path.parent / "results" / "ar_cf4_db_smoke" / "outputs"),
                "expectation": str(repo_root / "benchmarks" / "expectations" / "ar_cf4_expectations.yaml"),
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _snapshot_yaml(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.yaml"))
    }


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
