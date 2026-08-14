from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.identifiers import to_file_key

_ASSET_FIELDS = {"path", "format", "checksum", "sha256"}
_SOURCE_FIELDS = {
    "source_type",
    "type",
    "source",
    "source_id",
    "id",
    "citation",
    "url",
    "accessed_date",
    "retrieved_at",
    "license",
    "license_note",
}
_VALIDITY_FIELDS = {"minimum", "maximum", "min", "max", "unit"}


def normalized_datasets_from_channel(channel: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize explicit datasets and the legacy ``data.cross_section`` entry."""

    reaction_id = str(channel.get("id") or "unknown_reaction")
    data = _mapping_or_empty(channel.get("data"))
    raw_datasets = channel.get("datasets", data.get("datasets", []))
    datasets = _explicit_datasets(raw_datasets, reaction_id)

    legacy = data.get("cross_section")
    if isinstance(legacy, dict) and not _contains_legacy_cross_section(datasets, legacy):
        datasets.append(_legacy_cross_section_dataset(reaction_id, legacy, len(datasets) + 1))
    return datasets


def _explicit_datasets(value: Any, reaction_id: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        _dataset_from_mapping(payload, reaction_id, index)
        for index, payload in enumerate(value, start=1)
        if isinstance(payload, dict)
    ]


def _dataset_from_mapping(
    payload: dict[str, Any],
    reaction_id: str,
    index: int,
) -> dict[str, Any]:
    kind = str(payload.get("kind") or "cross_section")
    asset = _asset_from(payload.get("asset"), payload)
    return {
        "id": str(payload.get("id") or _generated_id(reaction_id, kind, index)),
        "reaction_id": str(payload.get("reaction_id") or reaction_id),
        "kind": kind,
        "representation": str(payload.get("representation") or _representation_for(asset)),
        "independent_variable": payload.get("independent_variable"),
        "dependent_variable": payload.get("dependent_variable"),
        "unit": payload.get("unit"),
        "parameters": _mapping_or_empty(payload.get("parameters")),
        "asset": asset,
        "validity": _validity_from(_first_truthy(payload, "validity", "validity_range")),
        "source": _source_from(_first_truthy(payload, "source_record", "provenance", "source")),
        "status": str(payload.get("status") or "draft"),
        "preferred": bool(payload.get("preferred", False)),
        "notes": _notes_from(payload.get("notes")),
    }


def _legacy_cross_section_dataset(
    reaction_id: str,
    payload: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    asset = _asset_from(payload, payload)
    return {
        "id": _generated_id(reaction_id, "cross_section", index),
        "reaction_id": reaction_id,
        "kind": "cross_section",
        "representation": _representation_for(asset),
        "independent_variable": payload.get("independent_variable", "energy"),
        "dependent_variable": payload.get("dependent_variable", "cross_section"),
        "unit": payload.get("unit") or payload.get("cross_section_unit"),
        "parameters": {},
        "asset": asset,
        "validity": _validity_from(_first_truthy(payload, "validity", "validity_range")),
        "source": _source_from(_first_truthy(payload, "source_record", "source")),
        "status": str(payload.get("status") or "reference_only_needs_import"),
        "preferred": bool(payload.get("preferred", True)),
        "notes": _notes_from(payload.get("notes")),
    }


def _asset_from(value: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"path": value, "format": None, "checksum": None, "metadata": {}}
    if isinstance(value, dict):
        return {
            "path": value.get("path"),
            "format": value.get("format"),
            "checksum": value.get("checksum") or value.get("sha256"),
            "metadata": _without_fields(value, _ASSET_FIELDS),
        }

    path = payload.get("asset_path") or payload.get("path")
    if path is None:
        return None
    return {
        "path": str(path),
        "format": payload.get("format"),
        "checksum": payload.get("checksum") or payload.get("sha256"),
        "metadata": {},
    }


def _validity_from(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "minimum": _as_float(value.get("minimum", value.get("min"))),
        "maximum": _as_float(value.get("maximum", value.get("max"))),
        "unit": value.get("unit"),
        "conditions": _without_fields(value, _VALIDITY_FIELDS),
    }


def _source_from(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {
            "source_type": value,
            "source_id": None,
            "citation": None,
            "url": None,
            "accessed_date": None,
            "license": None,
            "metadata": {},
        }
    if not isinstance(value, dict):
        return None
    return {
        "source_type": value.get("source_type") or value.get("type") or value.get("source"),
        "source_id": value.get("source_id") or value.get("id"),
        "citation": value.get("citation"),
        "url": value.get("url"),
        "accessed_date": value.get("accessed_date") or value.get("retrieved_at"),
        "license": value.get("license") or value.get("license_note"),
        "metadata": _without_fields(value, _SOURCE_FIELDS),
    }


def _contains_legacy_cross_section(
    datasets: list[dict[str, Any]],
    legacy: dict[str, Any],
) -> bool:
    legacy_path = legacy.get("path")
    return any(
        dataset["kind"] == "cross_section"
        and dataset["asset"] is not None
        and dataset["asset"]["path"] == legacy_path
        for dataset in datasets
    )


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _first_truthy(payload: dict[str, Any], *field_names: str) -> Any:
    return next((payload[name] for name in field_names if payload.get(name)), None)


def _without_fields(payload: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in excluded}


def _notes_from(value: Any) -> list[str]:
    return [str(note) for note in value] if isinstance(value, list) else []


def _representation_for(asset: dict[str, Any] | None) -> str:
    return "table" if asset and asset["path"] else "reference_only"


def _generated_id(reaction_id: str, kind: str, index: int) -> str:
    return f"ds_{to_file_key(reaction_id)}_{to_file_key(kind)}_{index:03d}"


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
