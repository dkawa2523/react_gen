from __future__ import annotations

from copy import deepcopy
from typing import Any

WARNING = "Review sign convention and source consistency before final DNT use."


def reactants_from_pair(pair: dict[str, Any]) -> list[tuple[str, float]]:
    reactants = []
    if pair.get("projectile"):
        reactants.append((str(pair["projectile"]), 1.0))
    if pair.get("target"):
        reactants.append((str(pair["target"]), 1.0))
    return reactants


def species_amounts(items: Any) -> list[tuple[str, float]]:
    if not isinstance(items, list):
        return []
    return [
        (str(item["species"]), float(item.get("n", 1.0)))
        for item in items
        if isinstance(item, dict) and item.get("species")
    ]


def required_species(
    reactants: list[tuple[str, float]],
    products: list[tuple[str, float]],
) -> list[str]:
    return sorted({species for species, _ in [*reactants, *products]})


def products_minus_reactants(
    reactants: list[tuple[str, float]],
    products: list[tuple[str, float]],
    enthalpies: dict[str, dict[str, Any]],
) -> float:
    return _sum_enthalpy(products, enthalpies) - _sum_enthalpy(reactants, enthalpies)


def apply_computed_energetics(
    channel: dict[str, Any],
    delta_e: float,
    species_ids: list[str],
    enthalpies: dict[str, dict[str, Any]],
) -> None:
    channel["deltaE_products_minus_reactants_eV"] = delta_e
    channel.setdefault("data", {})["energetics"] = {
        "status": "computed_from_snapshot",
        "method": "products_minus_reactants_enthalpy_formation",
        "source_records": _source_records(species_ids, enthalpies),
        "warning": WARNING,
    }


def _sum_enthalpy(
    amounts: list[tuple[str, float]],
    enthalpies: dict[str, dict[str, Any]],
) -> float:
    return sum(
        coefficient * float(enthalpies[species]["value"]) for species, coefficient in amounts
    )


def _source_records(
    species_ids: list[str],
    enthalpies: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "species": species_id,
            "property": "enthalpy_formation_eV",
            "source_record": deepcopy(enthalpies[species_id].get("source_record")),
        }
        for species_id in species_ids
    ]
