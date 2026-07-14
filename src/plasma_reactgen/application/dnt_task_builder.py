from __future__ import annotations

from plasma_reactgen.application.reaction_catalog import (
    AssetExists,
    DATASET_OUTPUT_KINDS,
    dataset_payloads,
    provenance_record,
)
from plasma_reactgen.domain.chemistry import get_property_value
from plasma_reactgen.domain.formula import composition_mass_amu
from plasma_reactgen.domain.models import ReactionNetwork, Species, SpeciesAmount


DNT_ION_REQUIRED = ["mass_amu", "charge"]
DNT_NEUTRAL_REQUIRED = ["mass_amu", "polarizability_A3", "dipole_moment_D", "collision_radius_A"]


def build_dnt_tasks(
    network: ReactionNetwork,
    asset_exists: AssetExists | None = None,
) -> list[dict]:
    tasks: dict[str, dict] = {}

    for rxn in network.reactions:
        if rxn.family != "ion_neutral":
            continue

        inferred = infer_ion_neutral_pair(rxn.reactants, network.species)
        if inferred is None:
            continue
        ion_id, neutral_id = inferred
        pair_id = f"{ion_id}__{neutral_id}"

        if pair_id not in tasks:
            ion = network.species[ion_id]
            neutral = network.species[neutral_id]
            required_properties = build_required_properties(ion=ion, neutral=neutral)
            pair_property_readiness = check_dnt_property_readiness(
                ion=ion, neutral=neutral, required_properties=required_properties
            )
            tasks[pair_id] = {
                "pair_id": pair_id,
                "ion": ion_id,
                "neutral": neutral_id,
                "model_variant": infer_dnt_model_variant(neutral),
                "pair_property_readiness": pair_property_readiness,
                "required_properties": required_properties,
                "reaction_ids": [],
                "existing_datasets": {name: [] for name in DATASET_OUTPUT_KINDS},
                "channels": [],
            }

        missing_for_complete_dnt = dnt_channel_missing_fields(
            reaction_type=rxn.type,
            dnt_class=rxn.dnt_class,
            threshold_eV=rxn.threshold_eV,
            delta_e_eV=rxn.deltaE_products_minus_reactants_eV,
        )
        tasks[pair_id]["channels"].append(
            {
                "reaction_id": rxn.id,
                "type": rxn.type,
                "dnt_class": rxn.dnt_class,
                "threshold_eV": rxn.threshold_eV,
                "deltaE_products_minus_reactants_eV": rxn.deltaE_products_minus_reactants_eV,
                "missing_for_complete_dnt": missing_for_complete_dnt,
                "status": rxn.data_status.get("reaction"),
                "provenance": _channel_provenance(rxn),
                "products": [
                    {"species": product.species, "n": product.n}
                    for product in rxn.products
                ],
            }
        )
        tasks[pair_id]["reaction_ids"].append(rxn.id)
        for field, kind in DATASET_OUTPUT_KINDS.items():
            known = {item["id"] for item in tasks[pair_id]["existing_datasets"][field]}
            tasks[pair_id]["existing_datasets"][field].extend(
                item
                for item in dataset_payloads(rxn, kind, asset_exists)
                if item["id"] not in known
            )

    result = list(tasks.values())
    for task in result:
        task["reaction_ids"] = sorted(set(task["reaction_ids"]))
        for datasets in task["existing_datasets"].values():
            datasets.sort(key=lambda item: item["id"])
        task["complete_readiness"] = build_complete_dnt_readiness(
            task["pair_property_readiness"],
            task["channels"],
        )
        task["data_choice"] = {"status": _data_choice_status(task)}
    return sorted(result, key=lambda task: task["pair_id"])


def infer_ion_neutral_pair(
    reactants: list[SpeciesAmount],
    species: dict[str, Species],
) -> tuple[str, str] | None:
    ions: list[str] = []
    neutrals: list[str] = []

    for amount in reactants:
        sid = amount.species
        if sid == "e" or sid not in species:
            continue
        if species[sid].charge == 0:
            neutrals.append(sid)
        else:
            ions.append(sid)

    if len(ions) == 1 and len(neutrals) == 1:
        return ions[0], neutrals[0]
    return None


def infer_dnt_model_variant(neutral: Species) -> str:
    dipole = get_property_value(neutral, "dipole_moment_D")
    if dipole is None:
        return "dnt_plus_or_dm_unknown"
    try:
        return "dnt_plus_dm" if abs(float(dipole)) > 1.0e-8 else "dnt_plus"
    except (TypeError, ValueError):
        return "dnt_plus_or_dm_unknown"


def check_dnt_property_readiness(
    ion: Species,
    neutral: Species,
    required_properties: dict | None = None,
) -> dict:
    """Return readiness of pair properties only.

    Channel energetics and thresholds are deliberately evaluated separately by
    :func:`build_complete_dnt_readiness`.
    """

    required_properties = required_properties or build_required_properties(ion, neutral)
    ion_missing = _missing_properties(required_properties["ion"])
    neutral_missing = _missing_properties(required_properties["neutral"])
    status = "ready" if not ion_missing and not neutral_missing else "missing_properties"
    return {
        "status": status,
        "scope": "pair_properties",
        "missing": {
            "ion": ion_missing,
            "neutral": neutral_missing,
        },
    }


def _missing_properties(properties: dict) -> list[str]:
    return [name for name, payload in properties.items() if not payload["available"]]


def build_required_properties(ion: Species, neutral: Species) -> dict:
    return {
        "ion": {name: _property_payload(ion, name) for name in DNT_ION_REQUIRED},
        "neutral": {name: _property_payload(neutral, name) for name in DNT_NEUTRAL_REQUIRED},
    }


def _property_payload(species: Species, name: str) -> dict:
    if name == "charge":
        value, unit, source, source_record = species.charge, "e", "species", None
    else:
        prop = species.properties.get(name)
        value = None if prop is None else prop.value
        unit = None if prop is None else prop.unit
        source = None if prop is None else prop.source
        source_record = None if prop is None else prop.source_record
        if name == "mass_amu" and value is None:
            value = composition_mass_amu(species.composition)
            if value is not None:
                unit = "amu"
                source = "computed_from_composition"
                source_record = {
                    "source_type": "derived",
                    "method": "composition_mass_sum",
                }
    available = value is not None
    return {
        "value": value,
        "unit": unit,
        "source": source,
        "source_record": source_record,
        "available": available,
        "missing": not available,
    }


def _data_choice_status(task: dict) -> str:
    datasets = task["existing_datasets"]
    if any(item["available"] for item in datasets["cross_sections"]):
        return "existing_cross_section_available"
    if any(item["available"] for item in datasets["rate_coefficients"]):
        return "existing_rate_coefficient_available"
    if task["pair_property_readiness"]["status"] != "ready":
        return "missing_dnt_properties"
    return "dnt_properties_ready"


def dnt_channel_missing_fields(
    *,
    reaction_type: str | None,
    dnt_class: str | None,
    threshold_eV,
    delta_e_eV,
) -> list[str]:
    """Return fields needed to make one DNT channel complete.

    An elastic channel has an implicit zero threshold, so an omitted threshold
    is not a data gap.  Other channel types must provide it explicitly.
    """

    missing: list[str] = []
    if not dnt_class:
        missing.append("dnt_class")
    if threshold_eV is None and reaction_type != "elastic":
        missing.append("threshold_eV")
    if delta_e_eV is None:
        missing.append("deltaE_products_minus_reactants_eV")
    return missing


def build_complete_dnt_readiness(
    pair_property_readiness: dict,
    channels: list[dict],
) -> dict:
    """Combine pair properties and channel completeness into one status."""

    missing_properties = _flatten_property_missing(pair_property_readiness.get("missing", {}))
    dnt_channels = [channel for channel in channels if channel.get("dnt_class")]
    channel_warnings = [
        {
            "reaction_id": channel.get("reaction_id"),
            "fields": list(channel.get("missing_for_complete_dnt", [])),
        }
        for channel in dnt_channels
        if channel.get("missing_for_complete_dnt")
    ]

    if missing_properties:
        status = "missing_required_data"
    elif not dnt_channels:
        status = "no_dnt_channels"
    elif channel_warnings:
        status = "ready_with_warnings"
    else:
        status = "ready"

    return {
        "status": status,
        "scope": "pair_properties_and_channels",
        "missing_required_properties": missing_properties,
        "channel_warnings": channel_warnings,
    }


def _flatten_property_missing(missing) -> list[str]:
    if isinstance(missing, list):
        return [str(field) for field in missing]
    if not isinstance(missing, dict):
        return []
    flattened: list[str] = []
    for side, fields in missing.items():
        if not isinstance(fields, list):
            continue
        flattened.extend(f"{side}.{field}" for field in fields)
    return flattened


def _channel_provenance(reaction) -> dict:
    return provenance_record(reaction) or {
        "source_type": "registry",
        "source_id": None,
    }
