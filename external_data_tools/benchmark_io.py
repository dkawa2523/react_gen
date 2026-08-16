from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

_REPOSITORY_RELATIVE_ROOTS = {
    "benchmarks",
    "cases",
    "external_data",
    "registry",
}


def resolve_path(value: Any, config_path: Path) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists() or (path.parts and path.parts[0] in _REPOSITORY_RELATIVE_ROOTS):
        return cwd_candidate
    return (config_path.parent / path).resolve()


def required_path(value: Any, config_path: Path, label: str) -> Path:
    path = resolve_path(value, config_path)
    if path is None:
        raise ValueError(f"benchmark entry missing {label}")
    return path


def clear_generated_path(path: Path, results_root: Path, label: str) -> None:
    ensure_under(path, results_root, label)
    if path.exists():
        shutil.rmtree(path)


def ensure_under(path: Path, root: Path, label: str) -> None:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"benchmark {label} must be under {resolved_root}: {path}") from exc


def read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return payload


def read_optional_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "clear_generated_path",
    "ensure_under",
    "now",
    "read_optional_yaml",
    "read_yaml",
    "required_path",
    "resolve_path",
    "write_yaml",
]
