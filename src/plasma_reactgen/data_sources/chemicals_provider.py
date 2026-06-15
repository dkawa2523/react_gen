from __future__ import annotations

from typing import Any
import importlib

from plasma_reactgen.data_sources.base import PropertyProvider, SpeciesProvider


EV_J_PER_MOL = 96485.33212331002


class ChemicalsSpeciesProvider(SpeciesProvider):
    def __init__(self, provider_name: str = "chemicals_optional") -> None:
        self.provider_name = provider_name

    def find_species(self, query: str) -> list[dict[str, Any]]:
        modules = _load_chemicals_modules()
        if not modules.available:
            return []

        chemical = _search_chemical(modules, query)
        if chemical is None:
            return []

        formula = _first_attr(chemical, "formula")
        molecular_weight = _first_attr(chemical, "MW", "MW_g_mol", "molecular_weight")
        aliases = _list_attr(chemical, "synonyms", "aliases")
        cas = _first_attr(chemical, "CASs", "CAS", "CASRN")
        name = _first_attr(chemical, "common_name", "name", "iupac_name")
        source_id = cas or query

        candidate = {
            "id": formula or name or query,
            "formula": formula,
            "molecular_weight": _float_or_none(molecular_weight),
            "molecular_weight_amu": _molecular_weight_to_mass_amu(molecular_weight),
            "aliases": aliases,
            "cas": cas,
            "CAS": cas,
            "charge": 0,
            "classes": ["neutral"],
            "status": "imported",
            "source_name": self.provider_name,
            "source_record": _source_record(source_id, self.provider_name),
        }
        return [_without_none(candidate)]

    def status(self) -> dict[str, Any]:
        modules = _load_chemicals_modules()
        return {
            "available": modules.available,
            "source": "chemicals",
            "reason": modules.reason,
            "provider_name": self.provider_name,
        }


class ChemicalsPropertyProvider(PropertyProvider):
    def __init__(self, provider_name: str = "chemicals_optional") -> None:
        self.provider_name = provider_name
        self.notes: list[str] = []

    def find_properties(
        self,
        species_id: str,
        names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.notes = []
        modules = _load_chemicals_modules()
        if not modules.available:
            return []

        chemical = _search_chemical(modules, species_id)
        if chemical is None:
            return []

        requested = set(
            names
            if names is not None
            else ["mass_amu", "dipole_moment_D", "enthalpy_formation_eV", "collision_radius_A"]
        )
        cas = _first_attr(chemical, "CASs", "CAS", "CASRN")
        source_id = cas or species_id
        candidates: list[dict[str, Any]] = []

        if "mass_amu" in requested:
            molecular_weight = _first_attr(chemical, "MW", "MW_g_mol", "molecular_weight")
            mass = _molecular_weight_to_mass_amu(molecular_weight)
            if mass is not None:
                candidates.append(
                    _property_candidate(
                        species_id=species_id,
                        name="mass_amu",
                        value=mass,
                        unit="amu",
                        source_id=source_id,
                        source="chemicals molecular weight databank",
                        provider_name=self.provider_name,
                    )
                )

        if "dipole_moment_D" in requested:
            dipole = _dipole_moment_D(modules, cas)
            if dipole is not None:
                candidates.append(
                    _property_candidate(
                        species_id=species_id,
                        name="dipole_moment_D",
                        value=dipole,
                        unit="D",
                        source_id=source_id,
                        source="chemicals dipole databank",
                        provider_name=self.provider_name,
                    )
                )

        if "enthalpy_formation_eV" in requested:
            enthalpy_j_per_mol = _enthalpy_formation_j_per_mol(modules, cas)
            if enthalpy_j_per_mol is not None:
                candidates.append(
                    _property_candidate(
                        species_id=species_id,
                        name="enthalpy_formation_eV",
                        value=j_per_mol_to_ev(enthalpy_j_per_mol),
                        unit="eV",
                        source_id=source_id,
                        source="chemicals formation enthalpy databank",
                        provider_name=self.provider_name,
                    )
                )

        if "collision_radius_A" in requested:
            sigma = _collision_radius_A(modules, cas)
            if sigma is not None:
                candidates.append(
                    _property_candidate(
                        species_id=species_id,
                        name="collision_radius_A",
                        value=sigma,
                        unit="A",
                        source_id=source_id,
                        source="chemicals explicit Lennard-Jones sigma or molecular diameter databank",
                        provider_name=self.provider_name,
                    )
                )
            else:
                self.notes.append(
                    "collision_radius_A skipped: chemicals provider has no clearly selected "
                    "Lennard-Jones sigma or molecular diameter mapping in this adapter."
                )

        return candidates

    def status(self) -> dict[str, Any]:
        modules = _load_chemicals_modules()
        return {
            "available": modules.available,
            "source": "chemicals",
            "reason": modules.reason,
            "provider_name": self.provider_name,
            "notes": list(self.notes),
        }


class _ChemicalsModules:
    def __init__(
        self,
        identifiers: Any = None,
        dipole: Any = None,
        reaction: Any = None,
        lennard_jones: Any = None,
        reason: str | None = None,
        import_error: str | None = None,
    ):
        self.identifiers = identifiers
        self.dipole = dipole
        self.reaction = reaction
        self.lennard_jones = lennard_jones
        self.reason = reason
        self.import_error = import_error

    @property
    def available(self) -> bool:
        return self.identifiers is not None


def j_per_mol_to_ev(value: float) -> float:
    return float(value) / EV_J_PER_MOL


def kj_per_mol_to_ev(value: float) -> float:
    return j_per_mol_to_ev(float(value) * 1000.0)


def _load_chemicals_modules() -> _ChemicalsModules:
    try:
        identifiers = importlib.import_module("chemicals.identifiers")
    except ImportError as exc:
        return _ChemicalsModules(
            reason="chemicals package not installed",
            import_error=str(exc),
        )

    dipole = _optional_module("chemicals.dipole")
    reaction = _optional_module("chemicals.reaction")
    lennard_jones = _optional_module("chemicals.lennard_jones")
    return _ChemicalsModules(
        identifiers=identifiers,
        dipole=dipole,
        reaction=reaction,
        lennard_jones=lennard_jones,
    )


def _optional_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _search_chemical(modules: _ChemicalsModules, query: str) -> Any:
    search = getattr(modules.identifiers, "search_chemical", None)
    if search is None:
        return None
    try:
        return search(query)
    except Exception:
        return None


def _dipole_moment_D(modules: _ChemicalsModules, cas: str | None) -> float | None:
    if modules.dipole is None or not cas:
        return None
    fn = getattr(modules.dipole, "dipole_moment", None)
    if fn is None:
        return None
    try:
        value = fn(CASRN=cas)
    except TypeError:
        value = fn(cas)
    except Exception:
        return None
    return _float_or_none(value)


def _enthalpy_formation_j_per_mol(modules: _ChemicalsModules, cas: str | None) -> float | None:
    if modules.reaction is None or not cas:
        return None
    fn = getattr(modules.reaction, "Hfg", None)
    if fn is None:
        return None
    try:
        value = fn(CASRN=cas)
    except TypeError:
        value = fn(cas)
    except Exception:
        return None
    return _float_or_none(value)


def _collision_radius_A(modules: _ChemicalsModules, cas: str | None) -> float | None:
    if modules.lennard_jones is None or not cas:
        return None
    for name in ("molecular_diameter_A", "molecular_diameter_angstrom", "sigma_A", "sigma_angstrom"):
        fn = getattr(modules.lennard_jones, name, None)
        if fn is None:
            continue
        try:
            value = fn(CASRN=cas)
        except TypeError:
            value = fn(cas)
        except Exception:
            continue
        numeric = _float_or_none(value)
        if numeric is None:
            continue
        # chemicals Lennard-Jones sigma style helpers commonly use angstroms.
        return numeric
    return None


def _property_candidate(
    species_id: str,
    name: str,
    value: float,
    unit: str,
    source_id: str,
    source: str,
    provider_name: str,
) -> dict[str, Any]:
    return {
        "species": species_id,
        "property": name,
        "value": value,
        "unit": unit,
        "source": source,
        "source_name": provider_name,
        "evidence_type": "local_package_databank",
        "status": "imported",
        "source_record": _source_record(f"{source_id}:{name}", provider_name),
    }


def _source_record(source_id: str, provider_name: str) -> dict[str, str]:
    return {
        "source_type": "python_package",
        "database": "chemicals",
        "source_name": provider_name,
        "source_id": f"chemicals:{source_id}",
        "evidence_type": "local_package_databank",
    }


def _molecular_weight_to_mass_amu(value: Any) -> float | None:
    return _float_or_none(value)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def _list_attr(obj: Any, *names: str) -> list[str]:
    for name in names:
        value = getattr(obj, name, None)
        if value:
            if isinstance(value, str):
                return [value]
            return [str(item) for item in value]
    return []


def _without_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}
