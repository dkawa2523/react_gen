from __future__ import annotations

from copy import deepcopy
from typing import Any

from plasma_reactgen.data_sources.base import (
    CrossSectionProvider,
    PropertyProvider,
    ReactionProvider,
    SpeciesProvider,
)
from plasma_reactgen.domain.models import CollisionPair, PropertyValue, ReactionChannel, SpeciesAmount


class LocalRegistrySpeciesProvider(SpeciesProvider):
    def __init__(self, registry: Any):
        self.registry = registry

    def find_species(self, query: str) -> list[dict[str, Any]]:
        species = self.registry.get_species(query)
        if species is None:
            return []
        return [_species_payload(species)]


class LocalRegistryPropertyProvider(PropertyProvider):
    def __init__(self, registry: Any):
        self.registry = registry

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        species = self.registry.get_species(species_id)
        if species is None:
            return []

        requested = names if names is not None else sorted(species.properties)
        candidates: list[dict[str, Any]] = []
        for name in requested:
            prop = species.properties.get(name)
            if prop is None:
                continue
            candidates.append(_property_payload(species_id, name, prop, species.status))
        return candidates


class LocalRegistryReactionProvider(ReactionProvider):
    def __init__(self, registry: Any):
        self.registry = registry

    def find_channels(self, pair: CollisionPair) -> list[dict[str, Any]]:
        return [_reaction_payload(pair, channel) for channel in self.registry.get_channels(pair)]


class LocalAssetCrossSectionProvider(CrossSectionProvider):
    def __init__(self, registry: Any):
        self.registry = registry

    def find_cross_sections(self, pair: CollisionPair) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for channel in self.registry.get_channels(pair):
            cs = channel.data.get("cross_section")
            path = cs.get("path") if isinstance(cs, dict) else None
            candidates.append(_cross_section_payload(pair, channel, cs, path, self.registry))
        return candidates


def _species_payload(species) -> dict[str, Any]:
    return {
        "id": species.id,
        "composition": deepcopy(species.composition),
        "charge": species.charge,
        "classes": sorted(species.classes),
        "state": deepcopy(species.state),
        "properties": {
            name: _property_value_payload(prop)
            for name, prop in sorted(species.properties.items())
        },
        "status": species.status,
        "source_record": _source_record("local_registry", species.id),
    }


def _property_payload(
    species_id: str,
    name: str,
    prop: PropertyValue,
    status: str,
) -> dict[str, Any]:
    return {
        "species": species_id,
        "property": name,
        "value": prop.value,
        "unit": prop.unit,
        "source": prop.source,
        "status": status,
        "source_record": _source_record("local_registry", f"{species_id}.{name}"),
    }


def _reaction_payload(pair: CollisionPair, channel: ReactionChannel) -> dict[str, Any]:
    return {
        "pair": _pair_payload(pair),
        "type": channel.type,
        "products": [_amount_payload(amount) for amount in channel.products],
        "threshold_eV": channel.threshold_eV,
        "deltaE_products_minus_reactants_eV": channel.deltaE_products_minus_reactants_eV,
        "dnt_class": channel.dnt_class,
        "status": channel.status,
        "data": deepcopy(channel.data),
        "source_record": _source_record("local_registry", channel.id),
    }


def _cross_section_payload(
    pair: CollisionPair,
    channel: ReactionChannel,
    cross_section: Any,
    path: str | None,
    registry: Any,
) -> dict[str, Any]:
    return {
        "pair": _pair_payload(pair),
        "channel_id": channel.id,
        "path": path,
        "format": cross_section.get("format") if isinstance(cross_section, dict) else None,
        "source": cross_section.get("source") if isinstance(cross_section, dict) else None,
        "status": _cross_section_status(path, registry),
        "source_record": _source_record("local_assets", path or channel.id),
    }


def _property_value_payload(prop: PropertyValue) -> dict[str, Any]:
    return {
        "value": prop.value,
        "unit": prop.unit,
        "source": prop.source,
    }


def _pair_payload(pair: CollisionPair) -> dict[str, str]:
    return {
        "family": pair.family,
        "projectile": pair.projectile,
        "target": pair.target,
    }


def _amount_payload(amount: SpeciesAmount) -> dict[str, Any]:
    return {
        "species": amount.species,
        "n": amount.n,
    }


def _cross_section_status(path: str | None, registry: Any) -> str:
    if not path:
        return "missing"
    if registry.asset_exists(path):
        return "local_file_registered"
    return "path_registered_but_missing"


def _source_record(source_type: str, source_id: str) -> dict[str, str]:
    return {
        "source_type": source_type,
        "source_id": source_id,
    }
