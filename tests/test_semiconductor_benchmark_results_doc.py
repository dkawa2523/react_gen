from pathlib import Path


REPORT = Path("docs/semiconductor_benchmark_results.md")


def _report_text() -> str:
    assert REPORT.exists(), "docs/semiconductor_benchmark_results.md should exist"
    return REPORT.read_text(encoding="utf-8")


def test_report_includes_correct_semiconductor_cases() -> None:
    text = _report_text()

    assert "Ar/O2 simple oxygen plasma" in text
    assert "Ar/CF4 fluorocarbon plasma" in text
    assert "Ar/SF6/O2 electronegative plasma" in text


def test_report_excludes_non_default_halogen_case() -> None:
    text = _report_text()

    assert "Cl2/BCl3" not in text
    assert "cl2_bcl3" not in text.lower()


def test_report_has_ar_o2_evaluation_and_fixture_warning() -> None:
    text = _report_text()

    assert "## Ar/O2 Specific Evaluation" in text
    assert "O2 electron elastic reaction exists" in text
    assert "O2 electron ionization reaction exists" in text
    assert "O2 electron dissociation reaction exists" in text
    assert "O2 electron attachment reaction exists" in text
    assert "synthetic fixture warning" in text


def test_report_interprets_solver_skip_status_as_non_failure() -> None:
    text = _report_text()

    assert "## Live Solver Status" in text
    assert "| BOLSIG+ | false | null | export_only | disabled |" in text
    assert "registry-level benchmark can complete without live solvers" in text
    assert "not registry benchmark failures" in text
