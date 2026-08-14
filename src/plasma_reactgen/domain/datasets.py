from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from plasma_reactgen.domain.dataset_mapping import normalized_datasets_from_channel


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
    return [_dataset_from_normalized(item) for item in normalized_datasets_from_channel(channel)]


def _dataset_from_normalized(item: dict[str, Any]) -> ReactionDataset:
    payload = dict(item)
    asset = payload.pop("asset")
    validity = payload.pop("validity")
    source = payload.pop("source")
    return ReactionDataset(
        **payload,
        asset=DatasetAsset(**asset) if asset is not None else None,
        validity=DatasetValidity(**validity) if validity is not None else None,
        source=DatasetSource(**source) if source is not None else None,
    )
