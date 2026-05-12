from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SpeciesId = str
ReactionId = str
PairKey = str


@dataclass(frozen=True)
class SpeciesAmount:
    species: SpeciesId
    n: float = 1.0


@dataclass
class PropertyValue:
    value: Any | None = None
    unit: str | None = None
    source: str | None = None


@dataclass
class Species:
    id: SpeciesId
    composition: dict[str, int]
    charge: int
    classes: set[str]
    state: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, PropertyValue] = field(default_factory=dict)
    status: str = "draft"


@dataclass(frozen=True)
class CollisionPair:
    family: str
    projectile: SpeciesId
    target: SpeciesId

    @property
    def key(self) -> PairKey:
        return f"{self.family}|{self.projectile}|{self.target}"

    @property
    def label(self) -> str:
        return f"{self.projectile} + {self.target}"


@dataclass
class ReactionChannel:
    id: ReactionId
    type: str
    products: list[SpeciesAmount]
    threshold_eV: float | None = None
    deltaE_products_minus_reactants_eV: float | None = None
    dnt_class: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    status: str = "draft"
    notes: list[str] = field(default_factory=list)


@dataclass
class GeneratedReaction:
    id: ReactionId
    depth: int
    family: str
    type: str
    equation: str
    reactants: list[SpeciesAmount]
    products: list[SpeciesAmount]
    source_pair_key: PairKey
    source_pair_label: str
    introduced_species: list[SpeciesId]
    validation: dict[str, str]
    data_status: dict[str, str]
    threshold_eV: float | None = None
    deltaE_products_minus_reactants_eV: float | None = None
    dnt_class: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class NetworkSpeciesNode:
    species_id: SpeciesId
    depth_first_seen: int
    introduced_by: list[ReactionId] = field(default_factory=list)
    roles: set[str] = field(default_factory=set)
    propagated: bool = False


@dataclass
class CoverageItem:
    pair_key: PairKey
    pair_label: str
    family: str
    depth: int
    status: str
    reason: str | None = None
    n_channels: int = 0


@dataclass
class MissingDataItem:
    subject_kind: str
    subject_id: str
    field: str
    required_by: str
    severity: str
    message: str


@dataclass
class ReactionNetwork:
    species: dict[SpeciesId, Species]
    species_nodes: dict[SpeciesId, NetworkSpeciesNode]
    reactions: list[GeneratedReaction]
    coverage: list[CoverageItem]
    missing_data: list[MissingDataItem] = field(default_factory=list)
