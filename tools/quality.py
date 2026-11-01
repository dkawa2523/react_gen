"""Small, reproducible quality entry points used by Make and Nox."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


class QualityFailure(RuntimeError):
    pass


def _run(command: Sequence[str], *, allowed: set[int] | None = None, capture: bool = False) -> None:
    print("+ " + " ".join(command))
    result = subprocess.run(list(command), cwd=ROOT, check=False, capture_output=capture, text=True)
    if result.returncode not in (allowed or {0}):
        if capture:
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
        raise QualityFailure(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def quality_smoke() -> None:
    """Exercise ordinary local IO during development, without a fixture count oracle."""
    from reactgen import export

    with TemporaryDirectory(prefix="reactgen-smoke-") as workspace:
        directory = Path(workspace)
        case = directory / "case.yaml"
        case.write_text("gases: [Ar]\n", encoding="utf-8")
        result = directory / "result"
        csv = directory / "csv"
        network = directory / "network"
        command = [sys.executable, "-m", "reactgen.cli"]
        _run([*command, "analyze", "--input", str(case), "--out", str(result)], capture=True)
        canonical = result / "result.yaml"
        original = canonical.read_bytes()
        _run([*command, "needs", str(result), "--data-missing"], capture=True)
        for kind, destination in (("csv", csv), ("network", network)):
            _run(
                [*command, "view", str(result), "--kind", kind, "--out", str(destination)],
                capture=True,
            )
        payload = export.read(result, verify_views=True)
        if export.stale_views(payload, csv):
            raise QualityFailure("regenerated CSV views differ from the saved canonical result")
        if canonical.read_bytes() != original:
            raise QualityFailure("saved-result inspection or display changed the canonical result")
        network_file = network / "network.html"
        if not network_file.is_file() or network_file.stat().st_size == 0:
            raise QualityFailure("network view did not produce a nonempty HTML file")
    print("Smoke passed: local analysis, saved inspection, CSV and HTML.")


def quality_fast() -> None:
    _run([sys.executable, "-m", "ruff", "format", "--check", "."])
    _run([sys.executable, "-m", "ruff", "check", "."])
    _run([sys.executable, "-m", "mypy", "src", "tools/quality.py", "noxfile.py"])
    _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])


def quality_pr() -> None:
    quality_fast()
    # Invoke the package's console entry point with the active Python. This
    # avoids depending on a generated launcher beside that interpreter.
    _run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            ".importlinter",
            "--no-cache",
        ]
    )


def quality_nightly() -> None:
    quality_pr()
    for case in sorted((ROOT / "cases").glob("*/case.yaml")):
        out = ROOT / "build" / "nightly" / case.parent.name
        _run(
            [
                sys.executable,
                "-m",
                "reactgen.cli",
                "analyze",
                "--input",
                str(case),
                "--evidence",
                str(ROOT / "registry"),
                "--out",
                str(out),
            ],
            allowed={0, 1},
        )


COMMANDS = {
    "quality-smoke": quality_smoke,
    "quality-fast": quality_fast,
    "quality-pr": quality_pr,
    "quality-nightly": quality_nightly,
}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in COMMANDS:
        print("usage: python tools/quality.py " + "|".join(COMMANDS), file=sys.stderr)
        return 2
    try:
        COMMANDS[arguments[0]]()
    except QualityFailure as error:
        print(f"QUALITY FAILURE: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
