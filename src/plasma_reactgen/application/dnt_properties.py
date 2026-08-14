"""DNT pair inference and required-property readiness."""

from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.chemistry import get_property_value
from plasma_reactgen.domain.formula import composition_mass_amu
from plasma_reactgen.domain.models import Species, SpeciesAmount

DNT_ION_REQUIRED = ("mass_amu", "charge")
DNT_NEUTRAL_REQUIRED = (
    "mass_amu",
    "polarizability_A3",
    "dipole_moment_D",
    "collision_radius_A",
)


def infer_ion_neutral_pair(
    reactants: list[SpeciesAmount],
    species: dict[str, Species],
) -> tuple[str, str] | None:
    ions: list[str] = []
    neutrals: list[str] = []
    for amount in reactants:
        species_id = amount.species
        if species_id == "e" or species_id not in species:
            continue
        target = neutrals if species[species_id].charge == 0 else ions
        target.append(species_id)
    return (ions[0], neutrals[0]) if len(ions) == len(neutrals) == 1 else None


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
    required_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return pair-property readiness without channel completeness."""

    required = required_properties or build_required_properties(ion, neutral)
    missing = {side: _missing_properties(required[side]) for side in ("ion", "neutral")}
    return {
        "status": (
            "ready" if not missing["ion"] and not missing["neutral"] else "missing_properties"
        ),
        "scope": "pair_properties",
        "missing": missing,
    }


def build_required_properties(
    ion: Species,
    neutral: Species,
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        "ion": {name: _property_payload(ion, name) for name in DNT_ION_REQUIRED},
        "neutral": {name: _property_payload(neutral, name) for name in DNT_NEUTRAL_REQUIRED},
    }


def _missing_properties(properties: dict[str, dict[str, Any]]) -> list[str]:
    return [name for name, payload in properties.items() if not payload["available"]]


def _property_payload(species: Species, name: str) -> dict[str, Any]:
    if name == "charge":
        return _availability_payload(species.charge, "e", "species", None)
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
    return _availability_payload(value, unit, source, source_record)


def _availability_payload(
    value: Any,
    unit: str | None,
    source: str | None,
    source_record: dict[str, Any] | None,
) -> dict[str, Any]:
    available = value is not None
    return {
        "value": value,
        "unit": unit,
        "source": source,
        "source_record": source_record,
        "available": available,
        "missing": not available,
    }


__all__ = [
    "DNT_ION_REQUIRED",
    "DNT_NEUTRAL_REQUIRED",
    "build_required_properties",
    "check_dnt_property_readiness",
    "infer_dnt_model_variant",
    "infer_ion_neutral_pair",
]
