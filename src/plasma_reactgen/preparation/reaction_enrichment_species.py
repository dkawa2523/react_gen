from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.chemistry import (
    is_excited_state,
    make_electron_species,
    species_has_any_class,
)
from plasma_reactgen.domain.identifiers import to_file_key
from plasma_reactgen.domain.models import CollisionPair, PropertyValue, Species
from plasma_reactgen.infrastructure.file_registry import FileRegistry


@dataclass
class ProductSpeciesResolution:
    species: dict[str, Species]
    candidates: dict[str, dict[str, Any]]
    unresolved: list[dict[str, Any]]


def load_active_species(
    registry: FileRegistry,
    config: CaseConfig,
) -> dict[str, Species]:
    species: dict[str, Species] = {"e": make_electron_species()}
    for gas in config.gases:
        item = registry.get_species(gas)
        if item is not None:
            species[gas] = item
    return species


def collect_existing_channel_frontier(
    registry: FileRegistry,
    pair: CollisionPair,
    species: dict[str, Species],
    discovered_species: set[str],
    new_frontier: set[str],
    config: CaseConfig,
) -> None:
    for channel in registry.get_channels(pair):
        for amount in channel.products:
            if amount.species not in species:
                item = registry.get_species(amount.species)
                if item is not None:
                    species[amount.species] = item
        collect_new_frontier_species(
            {
                "products": [
                    {"species": amount.species, "n": amount.n} for amount in channel.products
                ]
            },
            species,
            discovered_species,
            new_frontier,
            config,
        )


def collect_new_frontier_species(
    channel: dict[str, Any],
    species: dict[str, Species],
    discovered_species: set[str],
    new_frontier: set[str],
    config: CaseConfig,
) -> None:
    for product in channel.get("products", []):
        species_id = product.get("species")
        if not species_id or species_id == "e" or species_id in discovered_species:
            continue
        discovered_species.add(species_id)
        item = species.get(species_id)
        if item is not None and _should_propagate_species(item, config):
            new_frontier.add(species_id)


def resolve_product_species(
    channel: dict[str, Any],
    species: dict[str, Species],
    registry: FileRegistry,
    species_providers: list[Any],
) -> ProductSpeciesResolution:
    resolved: dict[str, Species] = {}
    candidates: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    for product in channel.get("products", []):
        species_id = product.get("species")
        if _is_already_resolved(species_id, species, resolved):
            continue
        local_species = registry.get_species(species_id)
        if local_species is not None:
            resolved[species_id] = local_species
            continue
        candidate, reason = _species_candidate(
            product,
            species_id,
            species_providers,
        )
        if candidate is None:
            unresolved.append({"species": species_id, "reason": reason})
            continue
        resolved[species_id] = _species_from_candidate(species_id, candidate)
        candidates[species_id] = candidate
    return ProductSpeciesResolution(resolved, candidates, unresolved)


def persist_resolved_species(
    prepared_registry: Path,
    active_species: dict[str, Species],
    resolution: ProductSpeciesResolution,
    pair: CollisionPair,
    channel_id: str,
) -> list[dict[str, Any]]:
    records = []
    for species_id, seeded in sorted(resolution.species.items()):
        if species_id in active_species:
            continue
        active_species[species_id] = seeded
        candidate = resolution.candidates.get(species_id)
        if candidate is None:
            continue
        _write_species_seed(prepared_registry, seeded, candidate)
        records.append(
            {
                "species": species_id,
                "pair": pair.key,
                "channel": channel_id,
                "source_record": deepcopy(candidate.get("source_record")),
            }
        )
    return records


def _is_already_resolved(
    species_id: Any,
    species: dict[str, Species],
    resolved: dict[str, Species],
) -> bool:
    return bool(
        not species_id or species_id == "e" or species_id in species or species_id in resolved
    )


def _species_candidate(
    product: dict[str, Any],
    species_id: str,
    providers: list[Any],
) -> tuple[dict[str, Any] | None, str | None]:
    embedded = product.get("species_candidate")
    incomplete = isinstance(embedded, dict)
    if isinstance(embedded, dict) and _is_complete_candidate(embedded):
        return embedded, None
    for provider in providers:
        find_species = getattr(provider, "find_species", None)
        if not callable(find_species):
            continue
        for candidate in find_species(species_id):
            if not isinstance(candidate, dict) or candidate.get("id") != species_id:
                continue
            if _is_complete_candidate(candidate):
                return candidate, None
            incomplete = True
    reason = "incomplete_species_candidate" if incomplete else "missing_product_species"
    return None, reason


def _is_complete_candidate(candidate: dict[str, Any]) -> bool:
    return bool(
        isinstance(candidate.get("composition"), dict)
        and candidate.get("composition")
        and candidate.get("charge") is not None
    )


def _should_propagate_species(species: Species, config: CaseConfig) -> bool:
    return species_has_any_class(
        species,
        config.expansion.propagate_species_classes,
    ) and (config.expansion.propagate_excited_states or not is_excited_state(species))


def _species_from_candidate(
    species_id: str,
    candidate: dict[str, Any],
) -> Species:
    return Species(
        id=species_id,
        composition=deepcopy(candidate.get("composition", {})),
        charge=int(candidate.get("charge", 0)),
        classes=set(candidate.get("classes", [])),
        state=deepcopy(candidate.get("state", {})),
        properties={
            name: PropertyValue(
                value=(payload or {}).get("value"),
                unit=(payload or {}).get("unit"),
                source=(payload or {}).get("source"),
                source_record=deepcopy((payload or {}).get("source_record")),
                status=(payload or {}).get("status"),
            )
            for name, payload in candidate.get("properties", {}).items()
        },
        status=candidate.get("status", "imported"),
    )


def _write_species_seed(
    prepared_registry: Path,
    species: Species,
    candidate: dict[str, Any],
) -> None:
    payload = {
        "schema_version": 1,
        "id": species.id,
        "display_name": candidate.get("display_name", species.id),
        "composition": deepcopy(species.composition),
        "charge": species.charge,
        "classes": sorted(species.classes),
        "state": deepcopy(species.state),
        "properties": deepcopy(candidate.get("properties", {})),
        "metadata": {
            "status": species.status,
            "source_record": deepcopy(candidate.get("source_record")),
            "notes": ["Seeded from reaction enrichment; curated registry was not mutated."],
        },
    }
    path = prepared_registry / "species" / f"{to_file_key(species.id)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


__all__ = [
    "ProductSpeciesResolution",
    "collect_existing_channel_frontier",
    "collect_new_frontier_species",
    "load_active_species",
    "persist_resolved_species",
    "resolve_product_species",
]
