from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "importers" / "import_lxcat_placeholder.py"


def test_lxcat_placeholder_help_exits_successfully():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--input" in result.stdout
    assert "--registry" in result.stdout
    assert "--output-dir" in result.stdout


def test_lxcat_placeholder_reports_not_implemented_without_writes():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "not implemented" in result.stdout
    assert "registry/assets/external_sources/lxcat" in result.stdout
    assert "No network access" in result.stdout
