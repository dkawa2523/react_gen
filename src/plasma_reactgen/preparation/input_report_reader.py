"""Read and normalize missing-data reports used to create manual inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MissingInputContext:
    missing_path: Path
    prepare_report_path: Path | None
    coverage_report_path: Path | None
    case_name: str | None
    items: list[dict[str, Any]]


def load_missing_input_context(source: str | Path) -> MissingInputContext:
    original = Path(source)
    missing_path, missing_payload, missing_items = load_missing_data(original)
    prepare_path = _find_report(original, missing_path, "prepare_report.yaml")
    coverage_path = _find_report(original, missing_path, "coverage_report.yaml")
    items = _unique_items([*missing_items, *_coverage_report_items(coverage_path)])
    return MissingInputContext(
        missing_path=missing_path,
        prepare_report_path=prepare_path,
        coverage_report_path=coverage_path,
        case_name=_case_name(missing_payload),
        items=items,
    )


def load_missing_data(source: str | Path) -> tuple[Path, Any, list[dict[str, Any]]]:
    path = resolve_missing_data_path(source)
    payload = _read_yaml(path, label="missing-data YAML")
    return path, payload, _missing_items(payload)


def resolve_missing_data_path(source: str | Path) -> Path:
    path = Path(source)
    if path.is_dir():
        path = path / "missing_data.yaml"
    if not path.exists():
        raise FileNotFoundError(f"missing_data.yaml not found: {path}")
    return path


def _read_yaml(path: Path, *, label: str = "YAML") -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed {label}: {path}") from exc


def _missing_items(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("missing_data", [])
    else:
        raise ValueError("missing-data payload must be a mapping or a list")
    if not isinstance(items, list):
        raise ValueError("missing_data must be a list")
    return [item for item in items if isinstance(item, dict)]


def _find_report(original: Path, missing_path: Path, filename: str) -> Path | None:
    candidates = [missing_path.parent / filename, missing_path.parent.parent / filename]
    if original.is_dir():
        candidates.insert(0, original / filename)
    return next((path for path in candidates if path.exists()), None)


def _coverage_report_items(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = _read_yaml(path)
    if not isinstance(payload, dict):
        return []
    pairs = payload.get("pairs", {})
    if not isinstance(pairs, dict):
        return []
    return [_coverage_item(pair) for pair in _mapping_items(pairs.get("missing"))]


def _coverage_item(pair: dict[str, Any]) -> dict[str, Any]:
    pair_key = str(pair.get("pair_key") or "")
    family, projectile, target = split_pair_key(pair_key)
    return {
        "subject_kind": "collision_pair",
        "subject_id": pair_key or pair.get("pair_label") or "unknown",
        "field": "reaction_pair_coverage",
        "required_by": "coverage_report",
        "severity": "warning",
        "message": pair.get("reason") or "No registered reaction file for this collision pair.",
        "pair": {
            "family": pair.get("family") or family,
            "projectile": projectile,
            "target": target,
            "label": pair.get("pair_label"),
            "depth": pair.get("depth"),
        },
    }


def _unique_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, Any, Any]] = set()
    unique = []
    for item in items:
        key = (item.get("subject_kind"), item.get("subject_id"), item.get("field"))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def split_pair_key(pair_key: str) -> tuple[str | None, str | None, str | None]:
    parts = pair_key.split("|")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return None, None, None


def _case_name(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    case = payload.get("case")
    if isinstance(case, dict) and case.get("name"):
        return str(case["name"])
    return None


__all__ = ["MissingInputContext", "load_missing_data", "load_missing_input_context"]
