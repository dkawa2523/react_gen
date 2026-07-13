from __future__ import annotations

from plasma_reactgen.domain.chemistry import get_property_value, has_property_value
from plasma_reactgen.domain.models import ReactionNetwork, Species, SpeciesAmount


DNT_ION_REQUIRED = ["mass_amu", "charge"]
DNT_NEUTRAL_REQUIRED = ["mass_amu", "polarizability_A3", "dipole_moment_D", "collision_radius_A"]


def build_dnt_tasks(network: ReactionNetwork) -> list[dict]:
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
            pair_property_readiness = check_dnt_property_readiness(ion=ion, neutral=neutral)
            tasks[pair_id] = {
                "pair_id": pair_id,
                "ion": ion_id,
                "neutral": neutral_id,
                "model_variant": infer_dnt_model_variant(neutral),
                "pair_property_readiness": pair_property_readiness,
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
                "provenance": _channel_provenance(rxn.data),
                "products": [
                    {"species": product.species, "n": product.n}
                    for product in rxn.products
                ],
            }
        )

    result = list(tasks.values())
    for task in result:
        task["complete_readiness"] = build_complete_dnt_readiness(
            task["pair_property_readiness"],
            task["channels"],
        )
    return result


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


def check_dnt_property_readiness(ion: Species, neutral: Species) -> dict:
    """Return readiness of pair properties only.

    Channel energetics and thresholds are deliberately evaluated separately by
    :func:`build_complete_dnt_readiness`.
    """

    ion_missing = [name for name in DNT_ION_REQUIRED if not has_property_value(ion, name)]
    neutral_missing = [name for name in DNT_NEUTRAL_REQUIRED if not has_property_value(neutral, name)]
    status = "ready" if not ion_missing and not neutral_missing else "missing_properties"
    return {
        "status": status,
        "scope": "pair_properties",
        "missing": {
            "ion": ion_missing,
            "neutral": neutral_missing,
        },
    }


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


def _channel_provenance(data: dict) -> dict:
    for key in ("provenance", "evidence"):
        value = data.get(key)
        if isinstance(value, dict):
            return dict(value)
    return {"source_type": "registry", "source_id": None}
