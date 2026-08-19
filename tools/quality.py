from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = ROOT / "quality" / "baseline.json"
REPORT_DIR = ROOT / "build" / "quality"
PYTHON_TARGETS = ("src", "tests", "tools", "noxfile.py")
PRODUCTION_TARGETS = ("src/reactgen", "src/acquire")
MYPY_TARGETS = (*PRODUCTION_TARGETS, "tools/quality.py", "noxfile.py")
COMPLEXITY_LIMIT = 10
DIFF_COVERAGE_MINIMUM = 90.0


class QualityFailure(RuntimeError):
    """Raised when a quality gate cannot complete or detects a regression."""


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        suffix = ".exe" if os.name == "nt" else ""
        sibling = Path(sys.executable).parent / f"{name}{suffix}"
        executable = str(sibling) if sibling.is_file() else None
    if executable is None:
        raise QualityFailure(
            f"Required quality tool '{name}' is unavailable. Install with: "
            "python -m pip install -e .[quality]"
        )
    return executable


def _run(
    command: Sequence[str],
    *,
    allowed: set[int] | None = None,
    echo: bool = False,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    env = os.environ.copy()
    if environment:
        env.update(environment)
    result = subprocess.run(
        list(command),
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if echo or result.returncode not in (allowed or {0}):
        if result.stdout:
            _safe_output(result.stdout, sys.stdout)
        if result.stderr:
            _safe_output(result.stderr, sys.stderr)
    if result.returncode not in (allowed or {0}):
        raise QualityFailure(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}"
        )
    return result


def _safe_output(value: str, stream: Any) -> None:
    encoding = stream.encoding or "utf-8"
    safe_value = value.encode(encoding, errors="backslashreplace").decode(encoding)
    print(safe_value, end="", file=stream)


def _normalized_path(value: str) -> str:
    path = value.replace("\\", "/")
    root = ROOT.as_posix().rstrip("/") + "/"
    if path.startswith(root):
        path = path[len(root) :]
    return path.removeprefix("./")


def _counter_payload(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _collect_unformatted(paths: Sequence[str]) -> list[str]:
    result = _run([_tool("ruff"), "format", "--check", *paths], allowed={0, 1})
    output = result.stdout + result.stderr
    prefix = "Would reformat: "
    files = [
        _normalized_path(line[len(prefix) :].strip())
        for line in output.splitlines()
        if line.startswith(prefix)
    ]
    return sorted(files)


def _collect_ruff(paths: Sequence[str]) -> Counter[str]:
    result = _run(
        [_tool("ruff"), "check", *paths, "--output-format", "json"],
        allowed={0, 1},
    )
    records = json.loads(result.stdout or "[]")
    return Counter(f"{_normalized_path(str(item['filename']))}::{item['code']}" for item in records)


def _collect_mypy(paths: Sequence[str], *, changed_only: bool = False) -> Counter[str]:
    command = [_tool("mypy"), *paths]
    if changed_only:
        command.extend(["--follow-imports", "silent"])
    result = _run(command, allowed={0, 1})
    pattern = re.compile(r"^(.*?):\d+(?::\d+)?: error: .* \[([^]]+)]$")
    issues: Counter[str] = Counter()
    for line in (result.stdout + result.stderr).splitlines():
        match = pattern.match(line)
        if match:
            issues[f"{_normalized_path(match.group(1))}::{match.group(2)}"] += 1
    return issues


def _complexity_blocks(payload: Mapping[str, Any]) -> dict[str, int]:
    values: dict[str, int] = {}
    for filename, blocks in payload.items():
        for block in blocks:
            _record_complexity(values, _normalized_path(filename), block)
    return dict(sorted(values.items()))


def _record_complexity(values: dict[str, int], filename: str, block: Mapping[str, Any]) -> None:
    name = str(block.get("name", "<unknown>"))
    key = f"{filename}::{name}"
    values[key] = max(values.get(key, 0), int(block.get("complexity", 0)))
    for method in block.get("methods", []):
        method_name = f"{name}.{method.get('name', '<unknown>')}"
        method_key = f"{filename}::{method_name}"
        values[method_key] = max(values.get(method_key, 0), int(method.get("complexity", 0)))


def _collect_complexity() -> dict[str, int]:
    result = _run([_tool("radon"), "cc", *PRODUCTION_TARGETS, "-j"])
    return _complexity_blocks(json.loads(result.stdout))


def _collect_bandit() -> Counter[str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / "bandit.json"
    _run(
        [
            _tool("bandit"),
            "-r",
            *PRODUCTION_TARGETS,
            "-f",
            "json",
            "-o",
            str(report),
            "--exit-zero",
        ],
    )
    records = json.loads(report.read_text(encoding="utf-8")).get("results", [])
    return Counter(
        f"{_normalized_path(str(item['filename']))}::{item['test_id']}" for item in records
    )


def _collect_vulture() -> Counter[str]:
    result = _run(
        [_tool("vulture"), *PRODUCTION_TARGETS, "--min-confidence", "60"],
        allowed={0, 3},
    )
    pattern = re.compile(r"^(.*?):\d+: (.+) \(\d+% confidence\)$")
    candidates: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        match = pattern.match(line)
        if match:
            candidates[f"{_normalized_path(match.group(1))}::{match.group(2)}"] += 1
    return candidates


def _secret_exclusion() -> str:
    directories = (
        r"\.git|\.venv|build|dist|\.mypy_cache|\.pytest_cache|\.ruff_cache|\.import_linter_cache"
    )
    generated = r"benchmarks[\\/]results"
    return rf"(?i)(^|[\\/])(?:{directories}|{generated})(?:[\\/]|$)|(^|[\\/])\.coverage(?:\..*)?$"


def _collect_secrets() -> Counter[str]:
    result = _run(
        [
            sys.executable,
            "-m",
            "detect_secrets",
            "scan",
            "--all-files",
            "--exclude-files",
            _secret_exclusion(),
        ]
    )
    payload = json.loads(result.stdout)
    findings: Counter[str] = Counter()
    for filename, records in payload.get("results", {}).items():
        for item in records:
            key = f"{_normalized_path(filename)}::{item['type']}::{item['hashed_secret']}"
            findings[key] += 1
    return findings


def _collect_pip_audit() -> Counter[str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / "pip-audit.json"
    result = _run(
        [_tool("pip-audit"), "--local", "--format", "json", "--output", str(report)],
        allowed={0, 1},
        environment={"PIP_AUDIT_CACHE_DIR": str(REPORT_DIR / "pip-audit-cache")},
    )
    if result.returncode not in {0, 1} or not report.is_file():
        raise QualityFailure("pip-audit did not produce its JSON report")
    payload = json.loads(report.read_text(encoding="utf-8"))
    findings: Counter[str] = Counter()
    for dependency in payload.get("dependencies", []):
        for vulnerability in dependency.get("vulns", []):
            findings[f"{dependency['name']}::{vulnerability['id']}"] += 1
    return findings


def _coverage_paths() -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return REPORT_DIR / "coverage.json", REPORT_DIR / "coverage.xml"


def _run_tests_with_coverage() -> float:
    json_report, xml_report = _coverage_paths()
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--cov=reactgen",
        "--cov=acquire",
        "--cov-branch",
        f"--cov-report=json:{json_report}",
        f"--cov-report=xml:{xml_report}",
        "--cov-report=term:skip-covered",
    ]
    _run(command, echo=True)
    payload = json.loads(json_report.read_text(encoding="utf-8"))
    return float(payload["totals"]["percent_covered"])


def _snapshot(*, include_coverage: bool, include_audit: bool) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "ruff": {
            "unformatted_files": _collect_unformatted(PYTHON_TARGETS),
            "issues": _counter_payload(_collect_ruff(PYTHON_TARGETS)),
        },
        "mypy": {"issues": _counter_payload(_collect_mypy(MYPY_TARGETS))},
        "complexity": {"functions": _collect_complexity()},
        "bandit": {"issues": _counter_payload(_collect_bandit())},
        "vulture": {"candidates": _counter_payload(_collect_vulture())},
        "secrets": {"findings": _counter_payload(_collect_secrets())},
    }
    if include_audit:
        snapshot["pip_audit"] = {"vulnerabilities": _counter_payload(_collect_pip_audit())}
    if include_coverage:
        snapshot["coverage"] = {"branch_percent": _run_tests_with_coverage()}
    return snapshot


def _load_baseline() -> dict[str, Any]:
    if not BASELINE_PATH.is_file():
        raise QualityFailure(
            "Quality baseline is missing. Create it explicitly with quality-baseline."
        )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _compare_counter(
    label: str,
    current: Mapping[str, int],
    baseline: Mapping[str, int],
) -> list[str]:
    regressions = []
    for key, count in current.items():
        previous = int(baseline.get(key, 0))
        if count > previous:
            regressions.append(f"{label}: {key}: {previous} -> {count}")
    return regressions


def _compare_snapshot(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    regressions: list[str] = []
    for tool, field in (
        ("ruff", "issues"),
        ("mypy", "issues"),
        ("bandit", "issues"),
        ("vulture", "candidates"),
        ("secrets", "findings"),
        ("pip_audit", "vulnerabilities"),
    ):
        regressions.extend(
            _compare_counter(
                tool,
                current.get(tool, {}).get(field, {}),
                baseline.get(tool, {}).get(field, {}),
            )
        )
    regressions.extend(_compare_format(current, baseline))
    regressions.extend(_compare_complexity(current, baseline))
    return regressions


def _compare_format(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    old = set(baseline.get("ruff", {}).get("unformatted_files", []))
    new = set(current.get("ruff", {}).get("unformatted_files", [])) - old
    return [f"ruff-format: newly unformatted file: {path}" for path in sorted(new)]


def _compare_complexity(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    old = baseline.get("complexity", {}).get("functions", {})
    regressions = []
    for key, value in current.get("complexity", {}).get("functions", {}).items():
        previous = int(old.get(key, COMPLEXITY_LIMIT))
        if int(value) > COMPLEXITY_LIMIT and int(value) > previous:
            regressions.append(f"complexity: {key}: {previous} -> {value}")
    return regressions


def _git_lines(command: Sequence[str]) -> set[str]:
    result = _run(["git", *command])
    return {_normalized_path(line.strip()) for line in result.stdout.splitlines() if line.strip()}


def _resolve_base_ref() -> str | None:
    configured = os.environ.get("QUALITY_BASE_REF")
    if configured:
        return configured
    result = _run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        allowed={0, 128},
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _changed_files() -> tuple[list[str], str | None]:
    base_ref = _resolve_base_ref()
    files: set[str] = set()
    if base_ref:
        files.update(_git_lines(["diff", "--name-only", "--diff-filter=ACMR", base_ref]))
    files.update(_git_lines(["diff", "--name-only", "--diff-filter=ACMR"]))
    files.update(_git_lines(["diff", "--cached", "--name-only", "--diff-filter=ACMR"]))
    files.update(_git_lines(["ls-files", "--others", "--exclude-standard"]))
    existing = sorted(path for path in files if (ROOT / path).is_file())
    return existing, base_ref


def _changed_python_files() -> tuple[list[str], str | None]:
    files, base_ref = _changed_files()
    return [path for path in files if path.endswith(".py")], base_ref


def _strict_changed_files() -> tuple[list[str], str | None]:
    changed, base_ref = _changed_python_files()
    checked = [path for path in changed if path.startswith(PYTHON_TARGETS)]
    if not checked:
        print("No changed Python files require strict format/lint checks.")
        return changed, base_ref
    failures = _changed_file_failures(checked)
    if failures:
        raise QualityFailure("Changed-file quality failures:\n" + "\n".join(failures))
    return changed, base_ref


def _changed_file_failures(checked: Sequence[str]) -> list[str]:
    unformatted = _collect_unformatted(checked)
    lint = _collect_ruff(checked)
    typed = [path for path in checked if path.startswith(MYPY_TARGETS)]
    typing = _collect_mypy(typed, changed_only=True) if typed else Counter()
    failures = [*(f"ruff-format: {path}" for path in unformatted)]
    failures.extend(f"ruff: {key} ({count})" for key, count in lint.items())
    failures.extend(f"mypy: {key} ({count})" for key, count in typing.items())
    return failures


def _run_architecture() -> None:
    _run([_tool("lint-imports"), "--config", ".importlinter", "--no-cache"], echo=True)


def _check_coverage(current: float, baseline: Mapping[str, Any]) -> None:
    minimum = float(baseline["coverage"]["branch_percent"])
    print(f"Branch coverage: current={current:.2f}% baseline={minimum:.2f}%")
    if current + 1e-9 < minimum:
        raise QualityFailure(f"Branch coverage regressed: {minimum:.2f}% -> {current:.2f}%")


def _check_diff_coverage(changed: Iterable[str], base_ref: str | None) -> None:
    changed_source = [
        path for path in changed if path.endswith(".py") and path.startswith(PRODUCTION_TARGETS)
    ]
    _check_untracked_coverage(changed_source)
    if not changed_source or not base_ref:
        print("Diff coverage skipped: no changed production Python or no base ref.")
        return
    _, xml_report = _coverage_paths()
    _run(
        [
            _tool("diff-cover"),
            str(xml_report),
            "--compare-branch",
            base_ref,
            "--fail-under",
            str(DIFF_COVERAGE_MINIMUM),
        ],
        echo=True,
    )


def _check_untracked_coverage(changed_source: Sequence[str]) -> None:
    """Cover new local files that are not visible to ``git diff`` yet."""

    untracked = _git_lines(["ls-files", "--others", "--exclude-standard"])
    checked = set(changed_source).intersection(untracked)
    if not checked:
        return
    json_report, _ = _coverage_paths()
    payload = json.loads(json_report.read_text(encoding="utf-8"))
    reports = {_normalized_path(path): data for path, data in payload.get("files", {}).items()}
    covered = 0
    statements = 0
    missing_reports: list[str] = []
    for path in sorted(checked):
        report = reports.get(path)
        if report is None:
            missing_reports.append(path)
            continue
        summary = report["summary"]
        covered += int(summary["covered_lines"])
        statements += int(summary["num_statements"])
    if missing_reports:
        raise QualityFailure(
            "Coverage report is missing new production files:\n" + "\n".join(missing_reports)
        )
    percent = 100.0 if statements == 0 else covered / statements * 100.0
    print(f"Untracked-file coverage: {percent:.2f}% ({covered}/{statements})")
    if percent + 1e-9 < DIFF_COVERAGE_MINIMUM:
        raise QualityFailure(
            f"Untracked-file coverage is {percent:.2f}%; minimum is {DIFF_COVERAGE_MINIMUM:.2f}%"
        )


def quality_baseline() -> None:
    print("Updating the quality baseline explicitly.")
    snapshot = _snapshot(include_coverage=True, include_audit=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": {
            "complexity_limit": COMPLEXITY_LIMIT,
            "diff_coverage_minimum": DIFF_COVERAGE_MINIMUM,
        },
        **snapshot,
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote baseline: {BASELINE_PATH.relative_to(ROOT)}")


def quality_fast() -> None:
    _strict_changed_files()
    _run(
        [sys.executable, "-m", "pytest", "-q", "-m", "not integration and not e2e"],
        echo=True,
    )


def quality_pr() -> None:
    changed, base_ref = _strict_changed_files()
    baseline = _load_baseline()
    current = _snapshot(include_coverage=False, include_audit=True)
    regressions = _compare_snapshot(current, baseline)
    if regressions:
        raise QualityFailure("Quality baseline regressions:\n" + "\n".join(regressions))
    _run_architecture()
    coverage = _run_tests_with_coverage()
    _check_coverage(coverage, baseline)
    _check_diff_coverage(changed, base_ref)


def _run_multiple_hypothesis_seeds() -> None:
    for seed in (117, 20260813, 4294967291):
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-m",
                "property",
                f"--hypothesis-seed={seed}",
            ],
            echo=True,
        )


def quality_nightly() -> None:
    quality_pr()
    _run_multiple_hypothesis_seeds()
    _generate_every_case()


def _generate_every_case() -> None:
    """Every case in the repository must generate a bundle without a blocking gap."""

    for case in sorted(Path("cases").glob("*/case.yaml")):
        _run(
            [sys.executable, "-m", "reactgen.cli", "generate", str(case), "--out", "build/nightly"],
            echo=True,
        )


COMMANDS = {
    "quality-fast": quality_fast,
    "quality-pr": quality_pr,
    "quality-nightly": quality_nightly,
    "quality-baseline": quality_baseline,
}


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in COMMANDS:
        print("usage: python tools/quality.py " + "|".join(COMMANDS), file=sys.stderr)
        return 2
    try:
        COMMANDS[arguments[0]]()
    except QualityFailure as exc:
        print(f"QUALITY FAILURE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
