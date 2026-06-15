from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.pair_selection import select_pairs_involving_frontier
from plasma_reactgen.domain.chemistry import is_excited_state, make_electron_species, species_has_any_class
from plasma_reactgen.domain.identifiers import pair_filename, to_file_key
from plasma_reactgen.domain.models import CollisionPair, PropertyValue, ReactionChannel, Species, SpeciesAmount
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.validation.validators import validate_reaction


def enrich_reaction_channels(
    prepared_registry: Path,
    providers: list[Any],
    config: CaseConfig,
    source_profile: dict[str, Any],
    species_providers: list[Any] | None = None,
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    species_providers = species_providers or []
    registry = FileRegistry(prepared_registry)
    species = _load_active_species(registry, config)
    discovered_species: set[str] = {"e", *config.gases}
    frontier: set[str] = set(config.gases)
    seen_pair_keys: set[str] = set()

    report: dict[str, Any] = {
        "schema_version": 1,
        "source_profile": source_profile.get("name", "custom"),
        "reaction_pairs_imported": [],
        "reaction_channels_imported": [],
        "reaction_channels_skipped": [],
        "species_seeded_from_reactions": [],
        "unresolved_product_species": [],
        "unresolved_reactions": [],
        "summary": {
            "n_reaction_pairs_imported": 0,
            "n_reaction_channels_imported": 0,
            "n_reaction_channels_skipped": 0,
            "n_species_seeded_from_reactions": 0,
            "n_unresolved_product_species": 0,
            "n_unresolved_reactions": 0,
        },
    }

    for _depth in range(config.expansion.max_depth + 1):
        pairs = select_pairs_involving_frontier(species, frontier, config)
        new_frontier: set[str] = set()

        for pair in pairs:
            if pair.key in seen_pair_keys:
                continue
            seen_pair_keys.add(pair.key)

            _collect_frontier_from_existing_channels(
                registry,
                pair,
                species,
                discovered_species,
                new_frontier,
                config,
            )
            existing_ids = _existing_channel_ids(registry, pair)
            channels_to_write: list[dict[str, Any]] = []
            for provider in providers:
                if not hasattr(provider, "find_channels"):
                    continue
                for raw_channel in provider.find_channels(pair):
                    channel = _normalize_channel(raw_channel)
                    channel_id = channel.get("id")
                    if not channel_id:
                        _unresolved(report, pair, None, "missing_channel_id")
                        continue
                    if channel_id in existing_ids:
                        _skipped(report, pair, channel_id, "duplicate_channel")
                        continue

                    resolution = _resolve_missing_product_species(channel, species, species_providers)
                    if resolution["unresolved"]:
                        for item in resolution["unresolved"]:
                            _unresolved_product(report, pair, channel_id, item)
                        _unresolved(report, pair, channel_id, resolution["unresolved"][0]["reason"])
                        continue

                    validation_species = {**species, **resolution["species"]}
                    reaction = _reaction_channel(channel)
                    validation = validate_reaction(
                        reactants=[SpeciesAmount(pair.projectile), SpeciesAmount(pair.target)],
                        products=reaction.products,
                        species=validation_species,
                    )
                    if validation["species_reference"] != "ok":
                        _unresolved(report, pair, channel_id, "missing_product_species")
                        continue
                    if validation["charge_balance"] != "ok" or validation["element_balance"] != "ok":
                        _skipped(report, pair, channel_id, "validation_failed", validation)
                        continue

                    _write_resolved_species(
                        prepared_registry,
                        species,
                        resolution["species"],
                        resolution["candidates"],
                        report,
                        pair,
                        channel_id,
                    )
                    _collect_new_frontier_species(channel, species, discovered_species, new_frontier, config)
                    channels_to_write.append(channel)
                    existing_ids.add(channel_id)

            if channels_to_write:
                _append_channels(prepared_registry, pair, channels_to_write)
                report["reaction_pairs_imported"].append(pair.key)
                for channel in channels_to_write:
                    report["reaction_channels_imported"].append({"pair": pair.key, "id": channel["id"]})

        if not new_frontier:
            break
        frontier = new_frontier

    report["summary"]["n_reaction_pairs_imported"] = len(report["reaction_pairs_imported"])
    report["summary"]["n_reaction_channels_imported"] = len(report["reaction_channels_imported"])
    report["summary"]["n_reaction_channels_skipped"] = len(report["reaction_channels_skipped"])
    report["summary"]["n_species_seeded_from_reactions"] = len(report["species_seeded_from_reactions"])
    report["summary"]["n_unresolved_product_species"] = len(report["unresolved_product_species"])
    report["summary"]["n_unresolved_reactions"] = len(report["unresolved_reactions"])
    return report


def _collect_frontier_from_existing_channels(
    registry: FileRegistry,
    pair: CollisionPair,
    species: dict[str, Species],
    discovered_species: set[str],
    new_frontier: set[str],
    config: CaseConfig,
) -> None:
    for channel in registry.get_channels(pair):
        payload = {
            "products": [
                {"species": amount.species, "n": amount.n}
                for amount in channel.products
            ]
        }
        _collect_new_frontier_species(payload, species, discovered_species, new_frontier, config)


def _collect_new_frontier_species(
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


def _should_propagate_species(species: Species, config: CaseConfig) -> bool:
    if not species_has_any_class(species, config.expansion.propagate_species_classes):
        return False
    if is_excited_state(species) and not config.expansion.propagate_excited_states:
        return False
    return True


def _load_active_species(registry: FileRegistry, config: CaseConfig) -> dict[str, Species]:
    species: dict[str, Species] = {"e": make_electron_species()}
    for path in registry.iter_species_files():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        species_id = payload.get("id")
        if not species_id:
            continue
        item = registry.get_species(species_id)
        if item is not None:
            species[species_id] = item
    for gas in config.gases:
        item = registry.get_species(gas)
        if item is not None:
            species[gas] = item
    return species


def _existing_channel_ids(registry: FileRegistry, pair: CollisionPair) -> set[str]:
    return {channel.id for channel in registry.get_channels(pair)}


def _normalize_channel(raw_channel: dict[str, Any]) -> dict[str, Any]:
    channel = deepcopy(raw_channel)
    channel.pop("pair", None)
    channel.setdefault("status", "imported")
    channel.setdefault("data", {})
    provenance = channel.get("source_record")
    if provenance is not None:
        channel["data"].setdefault("source_record", provenance)
    channel["data"].setdefault("provenance", channel["data"].get("source_record"))
    return channel


def _resolve_missing_product_species(
    channel: dict[str, Any],
    species: dict[str, Species],
    species_providers: list[Any],
) -> dict[str, Any]:
    resolved_species: dict[str, Species] = {}
    resolved_candidates: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []

    for product in channel.get("products", []):
        species_id = product.get("species")
        if (
            not species_id
            or species_id == "e"
            or species_id in species
            or species_id in resolved_species
        ):
            continue
        candidate_info = _species_candidate_for_product(product, species_id, species_providers)
        candidate = candidate_info["candidate"]
        if candidate is None:
            unresolved.append({"species": species_id, "reason": candidate_info["reason"]})
            continue
        seeded = _species_from_candidate(species_id, candidate)
        resolved_species[species_id] = seeded
        resolved_candidates[species_id] = candidate

    return {
        "species": resolved_species,
        "candidates": resolved_candidates,
        "unresolved": unresolved,
    }


def _species_candidate_for_product(
    product: dict[str, Any],
    species_id: str,
    species_providers: list[Any],
) -> dict[str, Any]:
    product_candidate = product.get("species_candidate")
    saw_incomplete = False
    if isinstance(product_candidate, dict):
        if _is_complete_species_candidate(product_candidate):
            return {"candidate": product_candidate, "reason": None}
        saw_incomplete = True

    for provider in species_providers:
        if not hasattr(provider, "find_species"):
            continue
        for candidate in provider.find_species(species_id):
            if not isinstance(candidate, dict) or candidate.get("id") != species_id:
                continue
            if _is_complete_species_candidate(candidate):
                return {"candidate": candidate, "reason": None}
            saw_incomplete = True

    return {
        "candidate": None,
        "reason": "incomplete_species_candidate" if saw_incomplete else "missing_product_species",
    }


def _is_complete_species_candidate(candidate: dict[str, Any]) -> bool:
    return (
        isinstance(candidate.get("composition"), dict)
        and bool(candidate.get("composition"))
        and candidate.get("charge") is not None
    )


def _write_resolved_species(
    prepared_registry: Path,
    species: dict[str, Species],
    resolved_species: dict[str, Species],
    candidates: dict[str, dict[str, Any]],
    report: dict[str, Any],
    pair: CollisionPair,
    channel_id: str,
) -> None:
    for species_id, seeded in sorted(resolved_species.items()):
        if species_id in species:
            continue
        candidate = candidates[species_id]
        species[species_id] = seeded
        _write_species_seed(prepared_registry, seeded, candidate)
        item = {
            "species": species_id,
            "pair": pair.key,
            "channel": channel_id,
            "source_record": deepcopy(candidate.get("source_record")),
        }
        if item not in report["species_seeded_from_reactions"]:
            report["species_seeded_from_reactions"].append(item)


def _species_from_candidate(species_id: str, candidate: dict[str, Any]) -> Species:
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
            )
            for name, payload in candidate.get("properties", {}).items()
        },
        status=candidate.get("status", "imported"),
    )


def _write_species_seed(prepared_registry: Path, species: Species, candidate: dict[str, Any]) -> None:
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
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _reaction_channel(channel: dict[str, Any]) -> ReactionChannel:
    return ReactionChannel(
        id=channel["id"],
        type=channel["type"],
        products=[
            SpeciesAmount(species=item["species"], n=float(item.get("n", 1.0)))
            for item in channel.get("products", [])
        ],
        threshold_eV=channel.get("threshold_eV"),
        deltaE_products_minus_reactants_eV=channel.get("deltaE_products_minus_reactants_eV"),
        dnt_class=channel.get("dnt_class"),
        data=channel.get("data", {}),
        status=channel.get("status", "imported"),
    )


def _append_channels(prepared_registry: Path, pair: CollisionPair, channels: list[dict[str, Any]]) -> None:
    path = prepared_registry / "reactions" / pair.family / pair_filename(pair.projectile, pair.target)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        payload = {
            "schema_version": 1,
            "pair": {"family": pair.family, "projectile": pair.projectile, "target": pair.target},
            "channels": [],
            "metadata": {
                "status": "prepared",
                "notes": ["Prepared reaction enrichment; curated registry was not mutated."],
            },
        }
    payload.setdefault("channels", []).extend(channels)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _skipped(
    report: dict[str, Any],
    pair: CollisionPair,
    channel_id: str,
    reason: str,
    validation: dict[str, str] | None = None,
) -> None:
    item = {"pair": pair.key, "id": channel_id, "reason": reason}
    if validation is not None:
        item["validation"] = validation
    report["reaction_channels_skipped"].append(item)


def _unresolved(report: dict[str, Any], pair: CollisionPair, channel_id: str | None, reason: str) -> None:
    report["unresolved_reactions"].append({"pair": pair.key, "id": channel_id, "reason": reason})


def _unresolved_product(
    report: dict[str, Any],
    pair: CollisionPair,
    channel_id: str,
    item: dict[str, Any],
) -> None:
    report["unresolved_product_species"].append(
        {
            "pair": pair.key,
            "channel": channel_id,
            "species": item.get("species"),
            "reason": item.get("reason"),
        }
    )
