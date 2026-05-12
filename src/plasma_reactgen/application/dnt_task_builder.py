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
            tasks[pair_id] = {
                "pair_id": pair_id,
                "ion": ion_id,
                "neutral": neutral_id,
                "model_variant": infer_dnt_model_variant(neutral),
                "readiness": check_dnt_readiness(ion=ion, neutral=neutral),
                "channels": [],
            }

        tasks[pair_id]["channels"].append(
            {
                "reaction_id": rxn.id,
                "type": rxn.type,
                "dnt_class": rxn.dnt_class,
                "deltaE_products_minus_reactants_eV": rxn.deltaE_products_minus_reactants_eV,
                "products": [
                    {"species": product.species, "n": product.n}
                    for product in rxn.products
                ],
            }
        )

    return list(tasks.values())


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


def check_dnt_readiness(ion: Species, neutral: Species) -> dict:
    ion_missing = [name for name in DNT_ION_REQUIRED if not has_property_value(ion, name)]
    neutral_missing = [name for name in DNT_NEUTRAL_REQUIRED if not has_property_value(neutral, name)]
    status = "ready" if not ion_missing and not neutral_missing else "missing_properties"
    return {
        "status": status,
        "missing": {
            "ion": ion_missing,
            "neutral": neutral_missing,
        },
    }
