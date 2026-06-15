from __future__ import annotations

import ast
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = ROOT / "src" / "plasma_reactgen"
DISALLOWED_NETWORK_IMPORTS = {
    "requests",
    "httpx",
    "urllib.request",
    "urllib3",
    "aiohttp",
}
ALLOWED_CORE_DEPENDENCIES = {"pyyaml>=6.0"}


def test_core_package_does_not_import_external_data_tools():
    violations = [
        violation
        for violation in _iter_imports(CORE_ROOT)
        if violation.import_name == "external_data_tools"
        or violation.import_name.startswith("external_data_tools.")
    ]

    assert not violations, _format_violations(
        "Core package must not import external_data_tools. "
        "Move external acquisition/download logic outside src/plasma_reactgen.",
        violations,
    )


def test_core_package_does_not_import_network_libraries():
    violations = []
    for item in _iter_imports(CORE_ROOT):
        for disallowed in DISALLOWED_NETWORK_IMPORTS:
            if item.import_name == disallowed or item.import_name.startswith(disallowed + "."):
                violations.append(item)
                break

    assert not violations, _format_violations(
        "Core package must remain local-only and must not import network/download libraries.",
        violations,
    )


def test_reactgen_cli_does_not_import_external_tools():
    cli_path = CORE_ROOT / "interface" / "cli.py"
    violations = [
        item
        for item in _imports_from_file(cli_path)
        if item.import_name == "external_data_tools"
        or item.import_name.startswith("external_data_tools.")
    ]

    assert not violations, _format_violations(
        "reactgen CLI must not import external_data_tools; run external tools with "
        "`python -m external_data_tools...` instead.",
        violations,
    )


def test_core_dependencies_stay_minimal():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = set(pyproject.get("project", {}).get("dependencies", []))
    unexpected = sorted(dependencies - ALLOWED_CORE_DEPENDENCIES)
    missing = sorted(ALLOWED_CORE_DEPENDENCIES - dependencies)

    assert not unexpected and not missing, (
        "Core dependencies changed. Current policy allows only "
        f"{sorted(ALLOWED_CORE_DEPENDENCIES)}. "
        f"Unexpected: {unexpected}; missing: {missing}. "
        "Put optional DB/API/download dependencies in external tooling or optional extras after policy review."
    )


class ImportViolation:
    def __init__(self, path: Path, line: int, import_name: str):
        self.path = path
        self.line = line
        self.import_name = import_name


def _iter_imports(root: Path) -> list[ImportViolation]:
    imports: list[ImportViolation] = []
    for path in sorted(root.rglob("*.py")):
        imports.extend(_imports_from_file(path))
    return imports


def _imports_from_file(path: Path) -> list[ImportViolation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[ImportViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(ImportViolation(path, node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(ImportViolation(path, node.lineno, node.module))
    return imports


def _format_violations(message: str, violations: list[ImportViolation]) -> str:
    details = "\n".join(
        f"- {item.path.relative_to(ROOT)}:{item.line} imports {item.import_name}"
        for item in violations
    )
    return f"{message}\n{details}"
