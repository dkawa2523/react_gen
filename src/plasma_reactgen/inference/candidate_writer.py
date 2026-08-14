from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import Species
from plasma_reactgen.inference.provider import (
    CompositeReactionProvider,
    InferredReactionProvider,
    RegisteredReactionProvider,
)
from plasma_reactgen.inference.reaction_candidate_builder import build_reaction_candidates
from plasma_reactgen.inference.species_candidates import (
    make_basic_fragment_candidates,
    make_parent_ion_candidates,
)


def build_candidate_registry(config: CaseConfig, registry: Any) -> dict[str, Any]:
    """Build review-only inferred candidates without mutating the registry."""

    candidate_config = _candidate_config(config)
    provider = CompositeReactionProvider(
        registered=RegisteredReactionProvider(registry),
        inferred=InferredReactionProvider(species_repo=registry),
        config=candidate_config,
    )
    input_species = [
        species
        for species_id in config.gases
        if (species := registry.get_species(species_id)) is not None
    ]

    species_candidates = _species_candidates(input_species, candidate_config, registry)
    reaction_candidates = build_reaction_candidates(input_species, provider)

    return {
        "schema_version": 2,
        "species": species_candidates,
        "reactions": reaction_candidates,
        "summary": {
            "n_input_species": len(input_species),
            "n_species_candidates": len(species_candidates),
            "n_reaction_candidates": len(reaction_candidates),
        },
    }


def write_candidate_registry(output_dir: str | Path, candidates: dict[str, Any]) -> None:
    """Write inferred candidates to a developer review directory."""

    output_dir = Path(output_dir)
    species_dir = output_dir / "species"
    reactions_dir = output_dir / "reactions"
    species_dir.mkdir(parents=True, exist_ok=True)
    reactions_dir.mkdir(parents=True, exist_ok=True)

    for candidate in candidates.get("species", []):
        _write_yaml(species_dir / f"{candidate['id']}.yaml", candidate)
    for candidate in candidates.get("reactions", []):
        _write_yaml(reactions_dir / f"{candidate['id']}.yaml", candidate)

    _write_yaml(
        output_dir / "summary.yaml",
        {
            "schema_version": candidates.get("schema_version", 2),
            "summary": candidates.get("summary", {}),
        },
    )


def _candidate_config(config: CaseConfig) -> CaseConfig:
    return replace(
        config,
        inference=replace(
            config.inference,
            enabled=True,
            include_inferred_reactions=True,
        ),
    )


def _species_candidates(
    species: list[Species],
    config: CaseConfig,
    registry: Any,
) -> list[dict[str, Any]]:
    if not config.inference.include_inferred_species:
        return []

    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in species:
        for candidate in [
            *make_parent_ion_candidates(item),
            *make_basic_fragment_candidates(
                item,
                max_fragment_depth=config.inference.max_fragment_depth,
            ),
        ]:
            candidate_id = candidate.get("id")
            if (
                not candidate_id
                or candidate_id in seen_ids
                or _is_registered_species(candidate, registry)
            ):
                continue
            seen_ids.add(candidate_id)
            candidates.append(candidate)
    return candidates


def _is_registered_species(candidate: dict[str, Any], registry: Any) -> bool:
    if not hasattr(registry, "has_species"):
        return False
    for species_id in (candidate.get("display_id"), candidate.get("id")):
        if species_id and registry.has_species(species_id):
            return True
    return False


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
