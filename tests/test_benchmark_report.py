from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.benchmark_report import generate_benchmark_report, main


def test_benchmark_report_generated_from_summary_fixture(tmp_path):
    summary = _write_summary_fixture(tmp_path)
    output = tmp_path / "semiconductor_benchmark_report.md"

    result = generate_benchmark_report(summary, output)
    text = output.read_text(encoding="utf-8")

    assert result["case_count"] == 3
    assert "# Semiconductor Low-Pressure Plasma Reaction-Network Benchmark" in text
    assert "Ar/O2 simple oxygen plasma" in text
    assert "Ar/CF4 fluorocarbon plasma" in text
    assert "Ar/SF6/O2 electronegative plasma" in text
    assert "YAML reports and metrics are the source of truth" in text
    assert "Markdown report is a point-in-time snapshot" in text


def test_benchmark_report_does_not_include_cl2_bcl3_as_default(tmp_path):
    output = tmp_path / "report.md"
    generate_benchmark_report(_write_summary_fixture(tmp_path), output)
    text = output.read_text(encoding="utf-8")

    assert "Cl2/BCl3" not in text
    assert "cl2_bcl3_halogen" not in text


def test_low_cross_section_coverage_generates_warning(tmp_path):
    output = tmp_path / "report.md"
    generate_benchmark_report(_write_summary_fixture(tmp_path), output)
    text = output.read_text(encoding="utf-8")

    assert "WARNING_DATA_GAPS" in text
    assert "Cross-section asset coverage is low" in text
    assert "Import reviewed LXCat/internal cross sections" in text


def test_validation_error_generates_failure(tmp_path):
    summary = _write_summary_fixture(tmp_path, validation_errors={"ar_o2_simple": 1})
    output = tmp_path / "report.md"
    result = generate_benchmark_report(summary, output)
    text = output.read_text(encoding="utf-8")

    assert result["statuses"]["failed"] >= 1
    assert "FAIL_VALIDATION" in text
    assert "Charge or element balance validation errors are present" in text


def test_structural_enrichment_error_prevents_workflow_pass(tmp_path):
    summary = _write_summary_fixture(
        tmp_path,
        structural_errors={"ar_o2_simple": 2},
    )
    output = tmp_path / "report.md"
    result = generate_benchmark_report(summary, output)
    text = output.read_text(encoding="utf-8")

    assert result["statuses"]["failed"] >= 1
    assert "FAIL_ENRICHMENT" in text
    assert "Structural enrichment or configured-source defects remain unresolved" in text


def test_truncated_generation_prevents_workflow_pass(tmp_path):
    summary = _write_summary_fixture(
        tmp_path,
        generation_complete={"ar_o2_simple": False},
    )
    output = tmp_path / "report.md"
    result = generate_benchmark_report(summary, output)
    text = output.read_text(encoding="utf-8")

    assert result["statuses"]["failed"] >= 1
    assert "FAIL_GENERATION" in text
    assert "Generation was truncated by a configured limit" in text


def test_benchmark_report_cli_prints_supported_statuses(tmp_path, capsys):
    output = tmp_path / "report.md"

    result = main([str(_write_summary_fixture(tmp_path)), "--output", str(output)])

    stdout = capsys.readouterr().out
    assert result == 0
    assert "passed:" in stdout
    assert "warnings:" in stdout
    assert "failed:" in stdout
    assert "skipped:" not in stdout


def _write_summary_fixture(
    tmp_path: Path,
    validation_errors: dict[str, int] | None = None,
    structural_errors: dict[str, int] | None = None,
    generation_complete: dict[str, bool] | None = None,
) -> Path:
    validation_errors = validation_errors or {}
    structural_errors = structural_errors or {}
    generation_complete = generation_complete or {}
    case_ids = ["ar_o2_simple", "ar_cf4_fluorocarbon", "sf6_o2_electronegative"]
    results = tmp_path / "results"
    summary_rows = []
    for case_id in case_ids:
        case_dir = results / case_id
        output_dir = case_dir / "outputs"
        work_dir = case_dir / "work"
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        metrics = _metrics(
            case_id,
            validation_errors.get(case_id, 0),
            structural_errors.get(case_id, 0),
            generation_complete.get(case_id, True),
        )
        report = {
            "schema_version": 1,
            "id": case_id,
            "source_profile": str(tmp_path / "fixtures" / case_id / "source_profile.yaml"),
            "output": str(output_dir),
            "missing_plan": str(work_dir / "missing_plan.yaml"),
            "metrics": metrics,
            "expectations": {
                "passed": validation_errors.get(case_id, 0) == 0,
                "score": metrics["expectation_score"],
                "missing_species": [],
                "missing_reaction_families": [],
            },
            "passed": (
                validation_errors.get(case_id, 0) == 0
                and structural_errors.get(case_id, 0) == 0
                and generation_complete.get(case_id, True)
            ),
        }
        _write_yaml(case_dir / "benchmark_metrics.yaml", metrics)
        _write_yaml(case_dir / "benchmark_report.yaml", report)
        _write_yaml(output_dir / "network.states.yaml", {"species": _states(case_id)})
        _write_yaml(output_dir / "network.reactions.yaml", {"reactions": _reactions(case_id)})
        _write_yaml(work_dir / "missing_plan.yaml", _missing_plan(case_id))
        summary_rows.append(
            {
                "id": case_id,
                "passed": report["passed"],
                "score": metrics["expectation_score"],
                "report": str(case_dir / "benchmark_report.yaml"),
                "metrics": str(case_dir / "benchmark_metrics.yaml"),
            }
        )
    setup_report = results / "setup_report.yaml"
    _write_yaml(setup_report, {"summary": {"required_data_ready": True}})
    summary = {
        "schema_version": 1,
        "generated_at": "2026-06-15T00:00:00+00:00",
        "summary": {"n_benchmarks": 3, "n_passed": 3, "n_failed": 0},
        "benchmarks": summary_rows,
        "setup": {
            "report": str(setup_report),
            "required_data_ready": True,
        },
    }
    path = results / "summary.yaml"
    _write_yaml(path, summary)
    return path


def _metrics(
    case_id: str,
    validation_error_count: int,
    structural_enrichment_unresolved_count: int,
    generation_complete: bool,
) -> dict:
    counts = {
        "ar_o2_simple": (6, 11, 7, 4),
        "ar_cf4_fluorocarbon": (12, 43, 17, 26),
        "sf6_o2_electronegative": (12, 20, 12, 8),
    }[case_id]
    return {
        "schema_version": 1,
        "n_species": counts[0],
        "n_reactions": counts[1],
        "n_electron_reactions": counts[2],
        "n_ion_neutral_reactions": counts[3],
        "max_depth_reached": 2,
        "n_pairs_found": 4,
        "n_pairs_missing": 3,
        "n_missing_data_items": 5,
        "generation_complete": generation_complete,
        "n_generation_truncations": 0 if generation_complete else 1,
        "n_missing_plan_actions": 2,
        "n_dnt_tasks": 2,
        "n_dnt_property_ready_pairs": 1,
        "n_dnt_pairs_with_missing_properties": 1,
        "n_cross_section_assets": 1,
        "n_reactions_with_cross_section_asset": 1,
        "cross_section_asset_coverage_fraction": 0.1,
        "n_reactions_with_provenance": 1,
        "provenance_coverage_fraction": 0.1,
        "n_inferred_reactions": 0,
        "n_imported_reactions": 2,
        "n_literature_supported_reactions": 0,
        "inferred_reaction_fraction": 0.0,
        "imported_or_literature_supported_fraction": 0.2,
        "validation_error_count": validation_error_count,
        "structural_enrichment_unresolved_count": structural_enrichment_unresolved_count,
        "expectation_score": 1.0,
    }


def _states(case_id: str) -> list[dict]:
    base = {
        "ar_o2_simple": ["Ar", "O2", "Ar+", "O2+", "O", "O-"],
        "ar_cf4_fluorocarbon": ["Ar", "CF4", "Ar+", "CF4+", "CF3", "F", "F-", "CF3+"],
        "sf6_o2_electronegative": ["Ar", "SF6", "O2", "Ar+", "SF5", "F", "F-", "O", "O-"],
    }[case_id]
    return [{"id": item} for item in base]


def _reactions(case_id: str) -> list[dict]:
    if case_id == "ar_o2_simple":
        return [
            {
                "id": "e_O2_elastic",
                "family": "electron",
                "type": "elastic",
                "equation": "e + O2 -> e + O2",
                "validation": {"charge_balance": "ok", "element_balance": "ok"},
            },
            {
                "id": "e_O2_ionization",
                "family": "electron",
                "type": "ionization",
                "equation": "e + O2 -> 2e + O2+",
                "validation": {"charge_balance": "ok", "element_balance": "ok"},
            },
            {
                "id": "e_O2_dissociation_O_O",
                "family": "electron",
                "type": "dissociation",
                "equation": "e + O2 -> e + O + O",
                "validation": {"charge_balance": "ok", "element_balance": "ok"},
            },
            {
                "id": "e_O2_attachment_Om_O",
                "family": "electron",
                "type": "attachment",
                "equation": "e + O2 -> O- + O",
                "validation": {"charge_balance": "ok", "element_balance": "ok"},
            },
            {
                "id": "Arp_O2_elastic",
                "family": "ion_neutral",
                "type": "elastic",
                "equation": "Ar+ + O2 -> Ar+ + O2",
                "validation": {"charge_balance": "ok", "element_balance": "ok"},
            },
        ]
    target = "CF4" if case_id == "ar_cf4_fluorocarbon" else "SF6"
    return [
        {
            "id": f"e_{target}_elastic",
            "family": "electron",
            "type": "elastic",
            "equation": f"e + {target} -> e + {target}",
            "validation": {"charge_balance": "ok", "element_balance": "ok"},
        },
        {
            "id": f"Arp_{target}_elastic",
            "family": "ion_neutral",
            "type": "elastic",
            "equation": f"Ar+ + {target} -> Ar+ + {target}",
            "validation": {"charge_balance": "ok", "element_balance": "ok"},
        },
    ]


def _missing_plan(case_id: str) -> dict:
    return {
        "schema_version": 1,
        "actions": [
            {"action": "import_cross_sections", "subjects": [case_id], "priority": "high"},
            {"action": "review_reaction_energetics", "subjects": [case_id], "priority": "medium"},
        ],
    }


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
