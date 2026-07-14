from __future__ import annotations

from typing import Any

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.channel_compat import confidence_score
from plasma_reactgen.domain.chemistry import get_property_value
from plasma_reactgen.domain.models import (
    CollisionPair,
    PropertyValue,
    ReactionChannel,
    Species,
)
from plasma_reactgen.inference.reaction_templates import (
    electron_parent_ionization_channel,
    ion_neutral_parent_charge_transfer_channel,
)
from plasma_reactgen.inference.screening import passes_hard_filters
from plasma_reactgen.inference.species_candidates import make_parent_ion_candidates


class RegisteredReactionProvider:
    """Thin adapter around the local registry reaction repository."""

    def __init__(self, repository: Any):
        self.repository = repository

    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        return self.repository.get_channels(pair)

    def find_pairs_involving(
        self,
        active_species_ids: set[str],
        frontier_species_ids: set[str],
    ) -> list[CollisionPair]:
        return self.repository.find_pairs_involving(
            active_species_ids,
            frontier_species_ids,
        )

    def has_pair(self, pair: CollisionPair) -> bool:
        return self.repository.has_pair(pair)

    def get_species(self, species_id: str) -> Species | None:
        if hasattr(self.repository, "get_species"):
            return self.repository.get_species(species_id)
        return None

    def has_species(self, species_id: str) -> bool:
        if hasattr(self.repository, "has_species"):
            return bool(self.repository.has_species(species_id))
        return self.get_species(species_id) is not None


class InferredReactionProvider:
    """Generate conservative in-memory reaction channels when enabled.

    The provider emits only reviewable inferred candidates and keeps generated
    species in memory. It never writes to or mutates curated registry files.
    """

    def __init__(self, species_repo: Any | None = None):
        self.species_repo = species_repo
        self._species_cache: dict[str, Species] = {}

    def get_channels(self, pair: CollisionPair, context: Any = None) -> list[ReactionChannel]:
        config = _context_config(context)
        if not _inference_enabled(config):
            return []

        if pair.family == "electron":
            return self._electron_parent_ionization(pair, config)
        if pair.family == "ion_neutral":
            return self._ion_neutral_parent_charge_transfer(pair, config)
        return []

    def get_species(self, species_id: str) -> Species | None:
        return self._species_cache.get(species_id)

    def has_species(self, species_id: str) -> bool:
        return species_id in self._species_cache

    def _electron_parent_ionization(
        self,
        pair: CollisionPair,
        config: CaseConfig,
    ) -> list[ReactionChannel]:
        if pair.projectile != "e":
            return []

        target = self._get_species(pair.target)
        if target is None or target.charge != 0:
            return []

        product_ion = self._ensure_parent_cation(target, config)
        if product_ion is None:
            return []

        return [electron_parent_ionization_channel(target, product_ion)]

    def _ion_neutral_parent_charge_transfer(
        self,
        pair: CollisionPair,
        config: CaseConfig,
    ) -> list[ReactionChannel]:
        projectile = self._get_species(pair.projectile)
        target = self._get_species(pair.target)
        if projectile is None or target is None:
            return []
        if projectile.charge <= 0 or target.charge != 0:
            return []

        neutral_projectile = self._ensure_neutral_counterpart(projectile, config)
        target_cation = self._ensure_parent_cation(target, config)
        if neutral_projectile is None or target_cation is None:
            return []

        return [
            ion_neutral_parent_charge_transfer_channel(
                projectile,
                target,
                neutral_projectile,
                target_cation,
            )
        ]

    def _ensure_parent_cation(self, parent: Species, config: CaseConfig) -> str | None:
        species_id = f"{parent.id}+"
        if self._get_registered_species(species_id) is not None:
            return species_id
        if not config.inference.include_inferred_species:
            return None
        if species_id in self._species_cache:
            return species_id

        candidates = [
            candidate
            for candidate in make_parent_ion_candidates(parent)
            if candidate.get("charge") == 1
        ]
        if not candidates:
            return None

        self._species_cache[species_id] = _species_from_candidate(
            candidates[0],
            species_id=species_id,
            parent=parent,
        )
        return species_id

    def _ensure_neutral_counterpart(self, ion: Species, config: CaseConfig) -> str | None:
        species_id = _neutral_counterpart_id(ion.id)
        if self._get_registered_species(species_id) is not None:
            return species_id
        if not config.inference.include_inferred_species:
            return None
        if species_id in self._species_cache:
            return species_id

        self._species_cache[species_id] = _neutral_from_ion(ion, species_id)
        return species_id

    def _get_species(self, species_id: str) -> Species | None:
        registered = self._get_registered_species(species_id)
        if registered is not None:
            return registered
        return self._species_cache.get(species_id)

    def _get_registered_species(self, species_id: str) -> Species | None:
        if self.species_repo is None or not hasattr(self.species_repo, "get_species"):
            return None
        return self.species_repo.get_species(species_id)


class CompositeReactionProvider:
    """Compose registered and inferred channels with registered data priority."""

    def __init__(
        self,
        registered: RegisteredReactionProvider,
        inferred: InferredReactionProvider,
        config: CaseConfig,
    ):
        self.registered = registered
        self.inferred = inferred
        self.config = config

    def get_channels(self, pair: CollisionPair) -> list[ReactionChannel]:
        registered_channels = self.registered.get_channels(pair)
        if not _inference_enabled(self.config):
            return registered_channels

        seen_ids = {channel.id for channel in registered_channels}
        inferred_channels = [
            channel
            for channel in self.inferred.get_channels(pair, {"config": self.config})
            if channel.id not in seen_ids
            and (confidence_score(channel) or 0.0)
            >= self.config.inference.min_confidence
            and passes_hard_filters(
                channel,
                {"max_products": self.config.inference.max_products},
            )
        ]
        return [*registered_channels, *inferred_channels]

    def find_pairs_involving(
        self,
        active_species_ids: set[str],
        frontier_species_ids: set[str],
    ) -> list[CollisionPair]:
        pairs = self.registered.find_pairs_involving(
            active_species_ids,
            frontier_species_ids,
        )
        if not _inference_enabled(self.config):
            return pairs

        candidates = list(pairs)
        for species_id in sorted(frontier_species_ids):
            if species_id != "e":
                candidates.append(CollisionPair("electron", "e", species_id))
        ions = sorted(
            species_id
            for species_id in active_species_ids
            if species_id != "e"
            and (species := self.get_species(species_id)) is not None
            and species.charge > 0
        )
        neutrals = sorted(
            species_id
            for species_id in active_species_ids
            if species_id != "e"
            and (species := self.get_species(species_id)) is not None
            and species.charge == 0
        )
        for ion in ions:
            for neutral in neutrals:
                if ion in frontier_species_ids or neutral in frontier_species_ids:
                    candidates.append(CollisionPair("ion_neutral", ion, neutral))
        return _unique_pairs(candidates)

    def has_pair(self, pair: CollisionPair) -> bool:
        if self.registered.has_pair(pair):
            return True
        return bool(self.get_channels(pair))

    def get_species(self, species_id: str) -> Species | None:
        registered = self.registered.get_species(species_id)
        if registered is not None:
            return registered
        return self.inferred.get_species(species_id)

    def has_species(self, species_id: str) -> bool:
        return self.get_species(species_id) is not None


def _context_config(context: Any) -> CaseConfig | None:
    if isinstance(context, dict):
        config = context.get("config")
        return config if isinstance(config, CaseConfig) else None
    return context if isinstance(context, CaseConfig) else None


def _inference_enabled(config: CaseConfig | None) -> bool:
    return bool(
        config
        and config.inference.enabled
        and config.inference.include_inferred_reactions
    )


def _unique_pairs(pairs: list[CollisionPair]) -> list[CollisionPair]:
    return [
        pair
        for _, pair in sorted({pair.key: pair for pair in pairs}.items())
    ]


def _species_from_candidate(
    candidate: dict[str, Any],
    *,
    species_id: str,
    parent: Species,
) -> Species:
    properties = _properties_from_payload(candidate.get("properties", {}))
    _ensure_mass_property(properties, parent)
    classes = set(candidate.get("classes", []))
    classes.update(_derived_ion_classes(parent))
    return Species(
        id=species_id,
        composition=dict(candidate.get("composition", parent.composition)),
        charge=int(candidate["charge"]),
        classes=classes,
        state={"kind": "ground"},
        properties=properties,
        status="inferred",
    )


def _neutral_from_ion(ion: Species, species_id: str) -> Species:
    classes = {
        cls
        for cls in ion.classes
        if cls not in {"positive_ion", "negative_ion", "molecular_ion"}
    }
    classes.add("neutral")
    if "molecular_ion" in ion.classes:
        classes.add("molecule")
    if "atom" not in classes and "molecule" not in classes:
        classes.add("atom" if sum(ion.composition.values()) == 1 else "molecule")

    mass = get_property_value(ion, "mass_amu")
    properties = {}
    if mass is not None:
        properties["mass_amu"] = PropertyValue(
            value=mass,
            unit="amu",
            source="inferred_from_ion",
        )

    return Species(
        id=species_id,
        composition=dict(ion.composition),
        charge=0,
        classes=classes,
        state={"kind": "ground"},
        properties=properties,
        status="inferred",
    )


def _properties_from_payload(payload: dict[str, Any]) -> dict[str, PropertyValue]:
    properties: dict[str, PropertyValue] = {}
    for name, value in payload.items():
        if not isinstance(value, dict):
            continue
        properties[name] = PropertyValue(
            value=value.get("value"),
            unit=value.get("unit"),
            source=value.get("source"),
            source_record=value.get("source_record"),
        )
    return properties


def _ensure_mass_property(properties: dict[str, PropertyValue], parent: Species) -> None:
    if "mass_amu" in properties and properties["mass_amu"].value is not None:
        return
    mass = get_property_value(parent, "mass_amu")
    if mass is not None:
        properties["mass_amu"] = PropertyValue(
            value=mass,
            unit="amu",
            source="inferred_from_parent",
        )


def _derived_ion_classes(parent: Species) -> set[str]:
    classes: set[str] = set()
    if "atom" in parent.classes:
        classes.add("atom")
    if "molecule" in parent.classes:
        classes.add("molecular_ion")
    return classes


def _neutral_counterpart_id(species_id: str) -> str:
    if species_id.endswith("+") or species_id.endswith("-"):
        return species_id[:-1]
    return f"{species_id}_neutral"
