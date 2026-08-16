from __future__ import annotations

import re
from typing import Any

from external_data_tools.cache import safe_filename


def convert_reaction_row(
    row: dict[str, str],
    *,
    database: str,
    line_number: int,
) -> dict[str, Any] | None:
    reactants = _reactants(row)
    if reactants is None:
        raise ValueError("reactant notation could not be normalized")
    pair = _reaction_pair(*reactants)
    if pair is None:
        return None
    family, projectile, target = pair
    products = _products(row)
    if products is None:
        raise ValueError("product notation could not be normalized")
    reaction_id = _reaction_id(database, projectile, target, products, line_number)
    reaction = _reaction_record(
        row,
        database,
        reaction_id,
        family,
        projectile,
        target,
        products,
    )
    dnt_class = (
        _dnt_class_if_simple_charge_transfer(projectile, target, products)
        if family == "ion_neutral"
        else None
    )
    if dnt_class:
        reaction["dnt_class"] = dnt_class
    return reaction


def reaction_pair_key(row: dict[str, str]) -> str | None:
    """Return the normalized registry pair key without converting the full row."""

    reactants = _reactants(row)
    if reactants is None:
        return None
    pair = _reaction_pair(*reactants)
    return "|".join(pair) if pair is not None else None


def normalize_species(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text or any(token in text for token in (" ", "/", "?", "*")):
        return None
    if text.lower() in {"e", "e-", "electron"}:
        return "e"
    text = text.replace("(+)", "+").replace("(-)", "-")
    if text.endswith(("+", "-")):
        return text
    if text.endswith("_p"):
        return f"{text[:-2]}+"
    if text.endswith("_m"):
        return f"{text[:-2]}-"
    return _normalize_explicit_charge(text)


def _reactants(row: dict[str, str]) -> tuple[str, str] | None:
    first = normalize_species(row.get("reactant1", ""))
    second = normalize_species(row.get("reactant2", ""))
    return (first, second) if first is not None and second is not None else None


def _reaction_pair(first: str, second: str) -> tuple[str, str, str] | None:
    if "e" in {first, second}:
        other = second if first == "e" else first
        family = "electron" if _charge(other) == 0 else "electron_ion"
        return family, "e", other
    first_charge = _charge(first)
    second_charge = _charge(second)
    if first_charge == 0 and second_charge == 0:
        return "neutral_neutral", first, second
    if first_charge and second_charge:
        if first_charge * second_charge > 0:
            return None
        return "ion_ion", first, second
    projectile, target = (first, second) if first_charge else (second, first)
    return "ion_neutral", projectile, target


def _products(row: dict[str, str]) -> list[str] | None:
    products = []
    for key in ("product1", "product2", "product3", "product4"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        product = normalize_species(raw)
        if product is None:
            return None
        products.append(product)
    return products


def _reaction_record(
    row: dict[str, str],
    database: str,
    reaction_id: str,
    family: str,
    projectile: str,
    target: str,
    products: list[str],
) -> dict[str, Any]:
    return {
        "id": reaction_id,
        "projectile": projectile,
        "target": target,
        "family": family,
        "type": _reaction_type(family, projectile, target, products),
        "products": [{"species": product, "n": 1} for product in products],
        "status": "imported",
        "data": {
            "rate_form": _rate_form(row),
            "provenance": {
                "database": database,
                "original_source": row.get("source"),
                "reference": row.get("reference"),
            },
            "review_status": "astrochem_candidate_not_semiconductor_validated",
        },
        "source_record": {
            "source_type": "local_snapshot",
            "database": database,
            "source_id": row.get("source") or reaction_id,
            "citation": row.get("reference"),
            "review_required": True,
        },
    }


def _reaction_type(
    family: str,
    projectile: str,
    target: str,
    products: list[str],
) -> str:
    if family == "electron_ion":
        return "dissociative_recombination" if len(products) > 1 else "recombination"
    if family == "ion_ion":
        return "mutual_neutralization"
    if family == "electron":
        return _electron_reaction_type(products)
    if family == "ion_neutral":
        return "reactive_scattering"
    return "reactive_scattering"


def _electron_reaction_type(products: list[str]) -> str:
    if any(_charge(product) < 0 for product in products):
        return "attachment"
    if len(products) > 1:
        return "dissociation"
    return "excitation"


def _rate_form(row: dict[str, str]) -> dict[str, float | None]:
    return {
        key: _float_or_none(row.get(key))
        for key in (
            "alpha",
            "beta",
            "gamma",
            "temperature_min_K",
            "temperature_max_K",
        )
    }


def _normalize_explicit_charge(text: str) -> str | None:
    match = re.match(r"^(.+?)([+-])(\d*)$", text)
    if match is None:
        return text
    base, sign, magnitude = match.groups()
    return f"{base}{sign}" if magnitude in {"", "1"} else None


def _charge(species: str) -> int:
    if species == "e":
        return -1
    if species.endswith("+"):
        return 1
    if species.endswith("-"):
        return -1
    return 0


def _dnt_class_if_simple_charge_transfer(
    projectile: str,
    target: str,
    products: list[str],
) -> str | None:
    if len(products) != 2:
        return None
    neutral_projectile = projectile.rstrip("+-")
    charged_target = f"{target}{projectile[-1]}" if projectile.endswith(("+", "-")) else target
    if neutral_projectile in products and charged_target in products:
        return "long_range_charge_exchange"
    return None


def _reaction_id(
    database: str,
    projectile: str,
    target: str,
    products: list[str],
    line_number: int,
) -> str:
    pieces = [database.lower(), projectile, target, *products, str(line_number)]
    return "_".join(safe_filename(piece) for piece in pieces if piece)


def _float_or_none(value: Any) -> float | None:
    text = str(value or "").strip()
    return float(text) if text else None
