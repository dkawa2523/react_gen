from __future__ import annotations

from plasma_reactgen.domain.models import PropertyValue, Species


def get_property_value(species: Species, name: str):
    prop = species.properties.get(name)
    return None if prop is None else prop.value


def has_property_value(species: Species, name: str) -> bool:
    if name == "charge":
        return species.charge is not None
    if name == "composition":
        return bool(species.composition)
    prop = species.properties.get(name)
    return prop is not None and prop.value is not None


def property_needs_acquisition(species: Species, name: str) -> bool:
    """Whether a property lacks both a value and a reviewed non-numeric outcome."""

    if has_property_value(species, name):
        return False
    prop = species.properties.get(name)
    return prop is None or prop.status not in {"not_applicable", "unbound"}


def species_has_any_class(species: Species, classes: list[str] | set[str]) -> bool:
    return bool(species.classes.intersection(set(classes)))


def is_excited_state(species: Species) -> bool:
    state = species.state or {}
    if state.get("kind") == "excited":
        return True
    energy = state.get("excitation_energy_eV")
    try:
        return energy is not None and float(energy) > 0.0
    except (TypeError, ValueError):
        return False


def make_electron_species() -> Species:
    return Species(
        id="e",
        composition={},
        charge=-1,
        classes={"electron"},
        state={"kind": "electron"},
        properties={
            "mass_amu": PropertyValue(value=5.48579909065e-4, unit="amu", source="internal")
        },
        status="internal",
    )
