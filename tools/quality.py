"""Small, reproducible quality entry points used by Make and Nox."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QualityFailure(RuntimeError):
    pass


def _run(command: Sequence[str], *, allowed: set[int] | None = None) -> None:
    print("+ " + " ".join(command))
    result = subprocess.run(list(command), cwd=ROOT, check=False)
    if result.returncode not in (allowed or {0}):
        raise QualityFailure(
            f"command failed with exit code {result.returncode}: {' '.join(command)}"
        )


def quality_fast() -> None:
    _run([sys.executable, "-m", "ruff", "format", "--check", "."])
    _run([sys.executable, "-m", "ruff", "check", "."])
    _run([sys.executable, "-m", "mypy", "src", "tools/quality.py", "noxfile.py"])
    _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])


def quality_pr() -> None:
    quality_fast()
    executable = Path(sys.executable).with_name(
        "lint-imports.exe" if sys.platform == "win32" else "lint-imports"
    )
    _run([str(executable), "--config", ".importlinter", "--no-cache"])


def quality_nightly() -> None:
    quality_pr()
    for case in sorted((ROOT / "cases").glob("*/case.yaml")):
        out = ROOT / "build" / "nightly" / case.parent.name
        _run(
            [
                sys.executable,
                "-m",
                "reactgen.cli",
                "generate",
                str(case),
                "--out",
                str(out),
            ],
            allowed={0, 1},
        )


COMMANDS = {
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
