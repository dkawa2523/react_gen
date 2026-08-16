from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from plasma_reactgen.domain.datasets import ReactionDataset

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
    source_record: dict[str, Any] | None = None
    status: str | None = None


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
        if self.family == "unimolecular":
            return self.projectile
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
    evidence: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    source_record: dict[str, Any] | None = None
    confidence: Any | None = None
    datasets: list[ReactionDataset] = field(default_factory=list)
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
    evidence: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None
    source_record: dict[str, Any] | None = None
    confidence: Any | None = None
    datasets: list[ReactionDataset] = field(default_factory=list)
    precursor_reaction_ids: list[ReactionId] = field(default_factory=list)


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
class TruncationEvent:
    """Machine-readable record of output omitted by a configured limit.

    ``omitted_count`` may be ``None`` when generation stops at the first omitted
    item and the total number of remaining items is intentionally not scanned.
    ``details`` carries limit-specific identifiers without forcing every limit
    into one rigid schema.
    """

    limit_name: str
    scope: str
    limit_value: int
    depth: int | None
    observed_count: int
    retained_count: int
    omitted_count: int | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReactionNetwork:
    species: dict[SpeciesId, Species]
    species_nodes: dict[SpeciesId, NetworkSpeciesNode]
    reactions: list[GeneratedReaction]
    coverage: list[CoverageItem]
    missing_data: list[MissingDataItem] = field(default_factory=list)
    truncations: list[TruncationEvent] = field(default_factory=list)

    @property
    def generation_complete(self) -> bool:
        """Whether no configured generation/reporting limit omitted data."""

        return not self.truncations
