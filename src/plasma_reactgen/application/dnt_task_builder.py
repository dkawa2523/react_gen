"""Assemble the stable DNT task artifact from a generated reaction network."""

from __future__ import annotations

from typing import Any

from plasma_reactgen.application.dnt_properties import (
    build_required_properties,
    check_dnt_property_readiness,
    infer_dnt_model_variant,
    infer_ion_neutral_pair,
)
from plasma_reactgen.application.dnt_readiness import (
    build_complete_dnt_readiness,
    dnt_channel_missing_fields,
)
from plasma_reactgen.application.reaction_catalog import (
    DATASET_OUTPUT_KINDS,
    AssetExists,
    dataset_payloads,
    provenance_record,
)
from plasma_reactgen.domain.models import GeneratedReaction, ReactionNetwork


def build_dnt_tasks(
    network: ReactionNetwork,
    asset_exists: AssetExists | None = None,
) -> list[dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for reaction in network.reactions:
        pair = _reaction_pair(reaction, network)
        if pair is None:
            continue
        ion_id, neutral_id = pair
        pair_id = f"{ion_id}__{neutral_id}"
        task = tasks.get(pair_id)
        if task is None:
            task = _new_task(pair_id, ion_id, neutral_id, network)
            tasks[pair_id] = task
        _add_reaction(task, reaction, asset_exists)
    return sorted(
        (_finalize_task(task) for task in tasks.values()),
        key=lambda task: task["pair_id"],
    )


def _reaction_pair(
    reaction: GeneratedReaction,
    network: ReactionNetwork,
) -> tuple[str, str] | None:
    if reaction.family != "ion_neutral":
        return None
    return infer_ion_neutral_pair(reaction.reactants, network.species)


def _new_task(
    pair_id: str,
    ion_id: str,
    neutral_id: str,
    network: ReactionNetwork,
) -> dict[str, Any]:
    ion = network.species[ion_id]
    neutral = network.species[neutral_id]
    required_properties = build_required_properties(ion, neutral)
    return {
        "pair_id": pair_id,
        "ion": ion_id,
        "neutral": neutral_id,
        "model_variant": infer_dnt_model_variant(neutral),
        "pair_property_readiness": check_dnt_property_readiness(
            ion,
            neutral,
            required_properties,
        ),
        "required_properties": required_properties,
        "reaction_ids": [],
        "existing_datasets": {name: [] for name in DATASET_OUTPUT_KINDS},
        "channels": [],
    }


def _add_reaction(
    task: dict[str, Any],
    reaction: GeneratedReaction,
    asset_exists: AssetExists | None,
) -> None:
    task["channels"].append(_channel_payload(reaction))
    task["reaction_ids"].append(reaction.id)
    for output_name, dataset_kind in DATASET_OUTPUT_KINDS.items():
        _merge_datasets(
            task["existing_datasets"][output_name],
            dataset_payloads(reaction, dataset_kind, asset_exists),
        )


def _channel_payload(reaction: GeneratedReaction) -> dict[str, Any]:
    return {
        "reaction_id": reaction.id,
        "type": reaction.type,
        "dnt_class": reaction.dnt_class,
        "threshold_eV": reaction.threshold_eV,
        "deltaE_products_minus_reactants_eV": (reaction.deltaE_products_minus_reactants_eV),
        "missing_for_complete_dnt": dnt_channel_missing_fields(
            reaction_type=reaction.type,
            dnt_class=reaction.dnt_class,
            threshold_eV=reaction.threshold_eV,
            delta_e_eV=reaction.deltaE_products_minus_reactants_eV,
        ),
        "status": reaction.data_status.get("reaction"),
        "provenance": provenance_record(reaction) or {"source_type": "registry", "source_id": None},
        "products": [{"species": product.species, "n": product.n} for product in reaction.products],
    }


def _merge_datasets(
    existing: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> None:
    known_ids = {item["id"] for item in existing}
    for candidate in candidates:
        if candidate["id"] not in known_ids:
            existing.append(candidate)
            known_ids.add(candidate["id"])


def _finalize_task(task: dict[str, Any]) -> dict[str, Any]:
    task["reaction_ids"] = sorted(set(task["reaction_ids"]))
    for datasets in task["existing_datasets"].values():
        datasets.sort(key=lambda item: item["id"])
    task["complete_readiness"] = build_complete_dnt_readiness(
        task["pair_property_readiness"],
        task["channels"],
    )
    task["data_choice"] = {"status": _data_choice_status(task)}
    return task


def _data_choice_status(task: dict[str, Any]) -> str:
    datasets = task["existing_datasets"]
    if any(item["available"] for item in datasets["cross_sections"]):
        return "existing_cross_section_available"
    if any(item["available"] for item in datasets["rate_coefficients"]):
        return "existing_rate_coefficient_available"
    if task["pair_property_readiness"]["status"] != "ready":
        return "missing_dnt_properties"
    return "dnt_properties_ready"


__all__ = [
    "build_complete_dnt_readiness",
    "build_dnt_tasks",
    "build_required_properties",
    "check_dnt_property_readiness",
    "dnt_channel_missing_fields",
    "infer_dnt_model_variant",
    "infer_ion_neutral_pair",
]
