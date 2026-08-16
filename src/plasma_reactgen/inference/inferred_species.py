from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.chemistry import get_property_value
from plasma_reactgen.domain.models import PropertyValue, Species


def species_from_candidate(
    candidate: dict[str, Any],
    *,
    species_id: str,
    parent: Species,
) -> Species:
    properties = _properties_from_payload(candidate.get("properties", {}))
    _ensure_mass_property(properties, parent)
    classes = set(candidate.get("classes", []))
    classes.update(_derived_ion_classes(parent))
    return Species(
        id=species_id,
        composition=dict(candidate.get("composition", parent.composition)),
        charge=int(candidate["charge"]),
        classes=classes,
        state={"kind": "ground"},
        properties=properties,
        status="inferred",
    )


def neutral_from_ion(ion: Species, species_id: str) -> Species:
    classes = {
        cls for cls in ion.classes if cls not in {"positive_ion", "negative_ion", "molecular_ion"}
    }
    classes.add("neutral")
    if "molecular_ion" in ion.classes:
        classes.add("molecule")
    if "atom" not in classes and "molecule" not in classes:
        classes.add("atom" if sum(ion.composition.values()) == 1 else "molecule")

    mass = get_property_value(ion, "mass_amu")
    properties = {}
    if mass is not None:
        properties["mass_amu"] = PropertyValue(
            value=mass,
            unit="amu",
            source="inferred_from_ion",
        )

    return Species(
        id=species_id,
        composition=dict(ion.composition),
        charge=0,
        classes=classes,
        state={"kind": "ground"},
        properties=properties,
        status="inferred",
    )


def neutral_counterpart_id(species_id: str) -> str:
    if species_id.endswith(("+", "-")):
        return species_id[:-1]
    return f"{species_id}_neutral"


def _properties_from_payload(payload: dict[str, Any]) -> dict[str, PropertyValue]:
    properties: dict[str, PropertyValue] = {}
    for name, value in payload.items():
        if not isinstance(value, dict):
            continue
        properties[name] = PropertyValue(
            value=value.get("value"),
            unit=value.get("unit"),
            source=value.get("source"),
            source_record=value.get("source_record"),
            status=value.get("status"),
        )
    return properties


def _ensure_mass_property(properties: dict[str, PropertyValue], parent: Species) -> None:
    if "mass_amu" in properties and properties["mass_amu"].value is not None:
        return
    mass = get_property_value(parent, "mass_amu")
    if mass is not None:
        properties["mass_amu"] = PropertyValue(
            value=mass,
            unit="amu",
            source="inferred_from_parent",
        )


def _derived_ion_classes(parent: Species) -> set[str]:
    classes: set[str] = set()
    if "atom" in parent.classes:
        classes.add("atom")
    if "molecule" in parent.classes:
        classes.add("molecular_ion")
    return classes


__all__ = ["neutral_counterpart_id", "neutral_from_ion", "species_from_candidate"]
