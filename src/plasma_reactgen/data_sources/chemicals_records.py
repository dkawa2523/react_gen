"""Project chemicals package records into reactgen source candidates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from plasma_reactgen.data_sources.chemicals_adapter import (
    ChemicalsModules,
    cas_numeric_value,
    first_attr,
    float_or_none,
    list_attr,
)

EV_J_PER_MOL = 96485.33212331002
DEFAULT_PROPERTY_NAMES = (
    "mass_amu",
    "dipole_moment_D",
    "enthalpy_formation_eV",
    "collision_radius_A",
)
_PROPERTY_METADATA = {
    "mass_amu": ("amu", "chemicals molecular weight databank"),
    "dipole_moment_D": ("D", "chemicals dipole databank"),
    "enthalpy_formation_eV": (
        "eV",
        "chemicals formation enthalpy databank",
    ),
    "collision_radius_A": (
        "A",
        "chemicals explicit Lennard-Jones sigma or molecular diameter databank",
    ),
}


def species_candidate(
    chemical: Any,
    query: str,
    provider_name: str,
) -> dict[str, Any]:
    formula = first_attr(chemical, "formula")
    molecular_weight = first_attr(
        chemical,
        "MW",
        "MW_g_mol",
        "molecular_weight",
    )
    cas = first_attr(chemical, "CASs", "CAS", "CASRN")
    name = first_attr(chemical, "common_name", "name", "iupac_name")
    candidate = {
        "id": formula or name or query,
        "formula": formula,
        "molecular_weight": float_or_none(molecular_weight),
        "molecular_weight_amu": float_or_none(molecular_weight),
        "aliases": list_attr(chemical, "synonyms", "aliases"),
        "cas": cas,
        "CAS": cas,
        "charge": 0,
        "classes": ["neutral"],
        "status": "imported",
        "source_name": provider_name,
        "source_record": source_record(cas or query, provider_name),
    }
    return {key: value for key, value in candidate.items() if value is not None}


def property_candidates(
    chemical: Any,
    modules: ChemicalsModules,
    species_id: str,
    names: list[str] | None,
    provider_name: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    requested = set(names if names is not None else DEFAULT_PROPERTY_NAMES)
    cas = first_attr(chemical, "CASs", "CAS", "CASRN")
    values = {
        name: reader(chemical, modules, cas)
        for name, reader in _PROPERTY_READERS.items()
        if name in requested
    }
    candidates = [
        _property_candidate(
            species_id,
            name,
            value,
            cas or species_id,
            provider_name,
        )
        for name in DEFAULT_PROPERTY_NAMES
        if (value := values.get(name)) is not None
    ]
    notes = []
    if "collision_radius_A" in requested and values.get("collision_radius_A") is None:
        notes.append(
            "collision_radius_A skipped: chemicals provider has no clearly selected "
            "Lennard-Jones sigma or molecular diameter mapping in this adapter."
        )
    return candidates, notes


def j_per_mol_to_ev(value: float) -> float:
    return float(value) / EV_J_PER_MOL


def kj_per_mol_to_ev(value: float) -> float:
    return j_per_mol_to_ev(float(value) * 1000.0)


def source_record(source_id: str, provider_name: str) -> dict[str, str]:
    return {
        "source_type": "python_package",
        "database": "chemicals",
        "source_name": provider_name,
        "source_id": f"chemicals:{source_id}",
        "evidence_type": "local_package_databank",
    }


def _property_candidate(
    species_id: str,
    name: str,
    value: float,
    source_id: str,
    provider_name: str,
) -> dict[str, Any]:
    unit, source = _PROPERTY_METADATA[name]
    return {
        "species": species_id,
        "property": name,
        "value": value,
        "unit": unit,
        "source": source,
        "source_name": provider_name,
        "evidence_type": "local_package_databank",
        "status": "imported",
        "source_record": source_record(f"{source_id}:{name}", provider_name),
    }


def _mass_amu(chemical: Any, modules: ChemicalsModules, cas: str | None) -> float | None:
    _ = modules, cas
    return float_or_none(first_attr(chemical, "MW", "MW_g_mol", "molecular_weight"))


def _dipole_moment(
    chemical: Any,
    modules: ChemicalsModules,
    cas: str | None,
) -> float | None:
    _ = chemical
    return cas_numeric_value(modules.dipole, ("dipole_moment",), cas)


def _enthalpy_formation(
    chemical: Any,
    modules: ChemicalsModules,
    cas: str | None,
) -> float | None:
    _ = chemical
    value = cas_numeric_value(modules.reaction, ("Hfg",), cas)
    return j_per_mol_to_ev(value) if value is not None else None


def _collision_radius(
    chemical: Any,
    modules: ChemicalsModules,
    cas: str | None,
) -> float | None:
    _ = chemical
    return cas_numeric_value(
        modules.lennard_jones,
        (
            "molecular_diameter_A",
            "molecular_diameter_angstrom",
            "sigma_A",
            "sigma_angstrom",
        ),
        cas,
    )


PropertyReader = Callable[[Any, ChemicalsModules, str | None], float | None]
_PROPERTY_READERS: dict[str, PropertyReader] = {
    "mass_amu": _mass_amu,
    "dipole_moment_D": _dipole_moment,
    "enthalpy_formation_eV": _enthalpy_formation,
    "collision_radius_A": _collision_radius,
}


__all__ = [
    "DEFAULT_PROPERTY_NAMES",
    "j_per_mol_to_ev",
    "kj_per_mol_to_ev",
    "property_candidates",
    "source_record",
    "species_candidate",
]
