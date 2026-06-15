from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return _to_plain(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item) for item in value]
    return value


@dataclass
class SourceRecord:
    name: str
    kind: str | None = None
    status: str | None = None
    citation: str | None = None
    version: str | None = None
    retrieved_at: str | None = None
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass
class SpeciesCandidate:
    species_id: str
    display_name: str | None = None
    composition: dict[str, int] = field(default_factory=dict)
    charge: int | None = None
    classes: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, Any] = field(default_factory=dict)
    source: SourceRecord | dict[str, Any] | None = None
    confidence: float | None = None
    status: str = "candidate"
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass
class PropertyCandidate:
    species_id: str
    name: str
    value: Any | None = None
    unit: str | None = None
    source: SourceRecord | dict[str, Any] | None = None
    confidence: float | None = None
    status: str = "candidate"
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass
class ReactionCandidate:
    reactants: list[dict[str, Any]]
    products: list[dict[str, Any]]
    reaction_id: str | None = None
    family: str | None = None
    reaction_type: str | None = None
    threshold_eV: float | None = None
    deltaE_products_minus_reactants_eV: float | None = None
    dnt_class: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    source: SourceRecord | dict[str, Any] | None = None
    confidence: float | None = None
    status: str = "candidate"
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass
class CrossSectionCandidate:
    pair: dict[str, Any]
    path: str | None = None
    format: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    source: SourceRecord | dict[str, Any] | None = None
    confidence: float | None = None
    status: str = "candidate"
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)


@dataclass
class EnrichmentResult:
    schema_version: int = 1
    species: list[SpeciesCandidate] = field(default_factory=list)
    properties: list[PropertyCandidate] = field(default_factory=list)
    reactions: list[ReactionCandidate] = field(default_factory=list)
    cross_sections: list[CrossSectionCandidate] = field(default_factory=list)
    registry_mutated: bool = False
    summary: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_plain(self)
