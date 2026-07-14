from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from plasma_reactgen.domain.identifiers import to_file_key


@dataclass
class DatasetSource:
    source_type: str | None = None
    source_id: str | None = None
    citation: str | None = None
    url: str | None = None
    accessed_date: str | None = None
    license: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetValidity:
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetAsset:
    path: str | None = None
    format: str | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReactionDataset:
    id: str
    reaction_id: str
    kind: str
    representation: str = "reference_only"
    independent_variable: Any | None = None
    dependent_variable: Any | None = None
    unit: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    asset: DatasetAsset | None = None
    validity: DatasetValidity | None = None
    source: DatasetSource | None = None
    status: str = "draft"
    preferred: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def reaction_datasets_from_channel(channel: dict[str, Any]) -> list[ReactionDataset]:
    """Normalize explicit datasets and the legacy ``data.cross_section`` entry."""

    reaction_id = str(channel.get("id") or "unknown_reaction")
    data = channel.get("data") if isinstance(channel.get("data"), dict) else {}
    raw_datasets = channel.get("datasets", data.get("datasets", []))
    if not isinstance(raw_datasets, list):
        raw_datasets = []

    datasets = [
        _dataset_from_mapping(payload, reaction_id, index)
        for index, payload in enumerate(raw_datasets, start=1)
        if isinstance(payload, dict)
    ]

    legacy = data.get("cross_section")
    if isinstance(legacy, dict) and not _contains_legacy_cross_section(datasets, legacy):
        datasets.append(_legacy_cross_section_dataset(reaction_id, legacy, len(datasets) + 1))

    return datasets


def _dataset_from_mapping(
    payload: dict[str, Any],
    reaction_id: str,
    index: int,
) -> ReactionDataset:
    kind = str(payload.get("kind") or "cross_section")
    asset = _asset_from(payload.get("asset"), payload)
    source = _source_from(
        payload.get("source_record") or payload.get("provenance") or payload.get("source")
    )
    validity = _validity_from(payload.get("validity") or payload.get("validity_range"))
    dataset_id = str(payload.get("id") or _generated_id(reaction_id, kind, index))
    return ReactionDataset(
        id=dataset_id,
        reaction_id=str(payload.get("reaction_id") or reaction_id),
        kind=kind,
        representation=str(payload.get("representation") or ("table" if asset and asset.path else "reference_only")),
        independent_variable=payload.get("independent_variable"),
        dependent_variable=payload.get("dependent_variable"),
        unit=payload.get("unit"),
        parameters=dict(payload.get("parameters", {})) if isinstance(payload.get("parameters"), dict) else {},
        asset=asset,
        validity=validity,
        source=source,
        status=str(payload.get("status") or "draft"),
        preferred=bool(payload.get("preferred", False)),
        notes=[str(note) for note in payload.get("notes", [])] if isinstance(payload.get("notes", []), list) else [],
    )


def _legacy_cross_section_dataset(
    reaction_id: str,
    payload: dict[str, Any],
    index: int,
) -> ReactionDataset:
    asset = _asset_from(payload, payload)
    source = _source_from(payload.get("source_record") or payload.get("source"))
    return ReactionDataset(
        id=_generated_id(reaction_id, "cross_section", index),
        reaction_id=reaction_id,
        kind="cross_section",
        representation="table" if asset and asset.path else "reference_only",
        independent_variable=payload.get("independent_variable", "energy"),
        dependent_variable=payload.get("dependent_variable", "cross_section"),
        unit=payload.get("unit") or payload.get("cross_section_unit"),
        parameters={},
        asset=asset,
        validity=_validity_from(payload.get("validity") or payload.get("validity_range")),
        source=source,
        status=str(payload.get("status") or "reference_only_needs_import"),
        preferred=bool(payload.get("preferred", True)),
        notes=[str(note) for note in payload.get("notes", [])] if isinstance(payload.get("notes", []), list) else [],
    )


def _asset_from(value: Any, payload: dict[str, Any]) -> DatasetAsset | None:
    if isinstance(value, str):
        return DatasetAsset(path=value)
    if isinstance(value, dict):
        return DatasetAsset(
            path=value.get("path"),
            format=value.get("format"),
            checksum=value.get("checksum") or value.get("sha256"),
            metadata={
                key: item
                for key, item in value.items()
                if key not in {"path", "format", "checksum", "sha256"}
            },
        )
    path = payload.get("asset_path") or payload.get("path")
    if path is None:
        return None
    return DatasetAsset(
        path=str(path),
        format=payload.get("format"),
        checksum=payload.get("checksum") or payload.get("sha256"),
    )


def _validity_from(value: Any) -> DatasetValidity | None:
    if not isinstance(value, dict):
        return None
    return DatasetValidity(
        minimum=_as_float(value.get("minimum", value.get("min"))),
        maximum=_as_float(value.get("maximum", value.get("max"))),
        unit=value.get("unit"),
        conditions={
            key: item
            for key, item in value.items()
            if key not in {"minimum", "maximum", "min", "max", "unit"}
        },
    )


def _source_from(value: Any) -> DatasetSource | None:
    if isinstance(value, str):
        return DatasetSource(source_type=value)
    if not isinstance(value, dict):
        return None
    return DatasetSource(
        source_type=value.get("source_type") or value.get("type") or value.get("source"),
        source_id=value.get("source_id") or value.get("id"),
        citation=value.get("citation"),
        url=value.get("url"),
        accessed_date=value.get("accessed_date") or value.get("retrieved_at"),
        license=value.get("license") or value.get("license_note"),
        metadata={
            key: item
            for key, item in value.items()
            if key
            not in {
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
        },
    )


def _contains_legacy_cross_section(
    datasets: list[ReactionDataset],
    legacy: dict[str, Any],
) -> bool:
    legacy_path = legacy.get("path")
    return any(
        dataset.kind == "cross_section"
        and dataset.asset is not None
        and dataset.asset.path == legacy_path
        for dataset in datasets
    )


def _generated_id(reaction_id: str, kind: str, index: int) -> str:
    return f"ds_{to_file_key(reaction_id)}_{to_file_key(kind)}_{index:03d}"


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
