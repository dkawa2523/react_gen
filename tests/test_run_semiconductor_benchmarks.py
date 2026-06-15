from __future__ import annotations

from pathlib import Path
import socket

import yaml

from external_data_tools.run_semiconductor_benchmarks import main, run_semiconductor_benchmarks


CASE_IDS = [
    "ar_o2_simple",
    "ar_cf4_fluorocarbon",
    "sf6_o2_electronegative",
]


def test_default_workflow_run_includes_three_cases_and_excludes_cl2(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    config = _write_config(tmp_path, Path(__file__).resolve().parents[1])

    result = run_semiconductor_benchmarks(config)

    assert result["return_code"] == 0
    assert result["cases"] == CASE_IDS
    assert "cl2_bcl3_halogen" not in yaml.safe_dump(result, sort_keys=True)
    assert Path(result["summary"]).exists()
    assert Path(result["semiconductor_report"]).exists()
    for case_id in CASE_IDS:
        assert case_id in result["case_reports"]
        assert case_id in result["missing_plans"]
        assert case_id in result["manual_inputs"]
        assert case_id in result["plots"]


def test_only_ar_o2_simple_works(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    config = _write_config(tmp_path, Path(__file__).resolve().parents[1])

    result = run_semiconductor_benchmarks(config, only="ar_o2_simple")

    assert result["return_code"] == 0
    assert result["cases"] == ["ar_o2_simple"]
    assert list(result["case_reports"]) == ["ar_o2_simple"]


def test_cli_prints_skipped_solver_message(tmp_path, monkeypatch, capsys):
    _block_network(monkeypatch)
    config = _write_config(tmp_path, Path(__file__).resolve().parents[1])

    rc = main(["--config", str(config), "--only", "ar_o2_simple"])
    captured = capsys.readouterr()

    assert rc == 0
    assert "ar_o2_simple" in captured.out
    assert "External solvers skipped because no executable paths are configured" in captured.out
    assert "cl2_bcl3_halogen" not in captured.out


def test_strict_mode_fails_on_low_expectation_fixture(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    repo_root = Path(__file__).resolve().parents[1]
    bad_expectation = tmp_path / "bad_expectation.yaml"
    bad_expectation.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "required_species": [
                    "Ar",
                    "O2",
                    "definitely_missing_species_1",
                    "definitely_missing_species_2",
                    "definitely_missing_species_3",
                ],
                "required_reaction_families": ["electron", "ion_neutral"],
                "required_outputs": ["network.reactions.yaml", "missing_data.yaml"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = _write_config(tmp_path, repo_root, expectation_overrides={"ar_o2_simple": bad_expectation})

    result = run_semiconductor_benchmarks(config, only="ar_o2_simple", strict=True)

    assert result["return_code"] == 1
    assert result["error"] in {"strict benchmark checks failed", "benchmark runner reported failed cases"}


def test_strict_mode_does_not_fail_for_missing_optional_solver(tmp_path, monkeypatch):
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

    result = run_semiconductor_benchmarks(config, only="ar_o2_simple", strict=True)

    assert result["return_code"] == 0
    assert result["solver_skipped"] is True


def test_required_fixture_missing_fails_setup(tmp_path):
    data_requirements = tmp_path / "data_requirements.yaml"
    data_requirements.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "required_for_registry_benchmark": [
                    {
                        "id": "missing_required_fixture",
                        "kind": "internal_file_db",
                        "path": str(tmp_path / "missing_fixture"),
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
                "policies": {"fail_if_required_data_missing": True, "fail_if_required_solver_missing": False},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = tmp_path / "benchmark_config.yaml"
    config.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "setup": {"config": str(setup_config), "require_success": True}, "benchmarks": []},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_semiconductor_benchmarks(config)

    assert result["return_code"] == 1
    assert result["error"] == "required benchmark setup check failed"
    assert Path(result["setup_report"]).exists()


def _write_config(
    tmp_path: Path,
    repo_root: Path,
    *,
    external_solvers: Path | None = None,
    expectation_overrides: dict[str, Path] | None = None,
) -> Path:
    config_path = tmp_path / "benchmarks" / "benchmark_config_semiconductor.yaml"
    solver_config = external_solvers or repo_root / "benchmarks" / "external_solvers.example.yaml"
    expectation_overrides = expectation_overrides or {}
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
                expectation_overrides.get(case_id),
            )
            for case_id in CASE_IDS
        ],
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return config_path


def _benchmark_payload(
    case_id: str,
    repo_root: Path,
    result_dir: Path,
    solver_config: Path,
    expectation_override: Path | None,
) -> dict:
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
        "expectation": str(expectation_override or repo_root / "benchmarks" / "expectations" / f"{case_id}.yaml"),
        "external_solvers": str(solver_config),
        "cross_section_imports": imports[case_id],
        "cross_section_mapping": str(fixture / "cross_section_mapping.yaml"),
    }


def _block_network(monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("semiconductor benchmark workflow must not access network")

    monkeypatch.setattr(socket, "socket", fail_socket)
