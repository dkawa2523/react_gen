"""Read gas-phase formation enthalpy and standard entropy from ``chemicals``.

Formula lookup is verified against the requested composition. These standard
quantities do not determine a reaction barrier, rate or occurrence under plasma
conditions. Values remain imported until their own domain review.
"""

from __future__ import annotations

from dataclasses import dataclass

from acquire.pubchem import parse_formula

JOULE_PER_EV = 96485.33212  # J/mol per eV/molecule


@dataclass(frozen=True)
class Thermo:
    species: str
    cas: str | None = None
    formula: str | None = None
    enthalpy_eV: float | None = None
    entropy_J_mol_K: float | None = None
    error: str | None = None
    enthalpy_method: str | None = None
    entropy_method: str | None = None
    package_version: str | None = None

    @property
    def known(self) -> bool:
        return self.enthalpy_eV is not None


def available() -> bool:
    try:
        import chemicals  # noqa: F401
    except ImportError:
        return False
    return True


def fetch(names: list[str], composition: dict[str, dict[str, int]] | None = None) -> list[Thermo]:
    """One record per species, in the order given.

    ``composition`` is checked against the formula the package returns. Name
    lookup here is fuzzy — asking for the radical ``CF`` yields fluoromethane —
    and a wrong enthalpy would silently corrupt every reaction it screens, so a
    mismatch is refused rather than recorded.
    """

    if not available():
        return [Thermo(name, error="chemicals is not installed") for name in names]
    wanted = composition or {}
    return [_one(name, wanted.get(name)) for name in names]


def _one(name: str, wanted: dict[str, int] | None) -> Thermo:
    import chemicals
    from chemicals import CAS_from_any, Hfg, Hfg_methods, S0g, S0g_methods, search_chemical

    try:
        cas = CAS_from_any(name)
        formula = search_chemical(cas).formula
    except (ValueError, LookupError, AttributeError) as error:
        return Thermo(name, error=f"{type(error).__name__}: {str(error)[:60]}")

    if wanted and parse_formula(formula) != wanted:
        return Thermo(name, cas, formula, error=f"resolves to {formula}, a different compound")

    # Pin the selected upstream table, rather than saving a value with only a
    # package-level citation. Explicit method bypasses a separate constants
    # cache and names the exact table which supplied this declaration.
    enthalpy_methods, entropy_methods = Hfg_methods(cas), S0g_methods(cas)
    enthalpy_method = enthalpy_methods[0] if enthalpy_methods else None
    entropy_method = entropy_methods[0] if entropy_methods else None
    enthalpy = Hfg(cas, method=enthalpy_method) if enthalpy_method is not None else None
    return Thermo(
        species=name,
        cas=cas,
        formula=formula,
        enthalpy_eV=None if enthalpy is None else enthalpy / JOULE_PER_EV,
        entropy_J_mol_K=S0g(cas, method=entropy_method) if entropy_method is not None else None,
        enthalpy_method=enthalpy_method,
        entropy_method=entropy_method,
        package_version=chemicals.__version__,
    )


def records(found: list[Thermo], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, one per value that exists."""

    out = []
    for item in found:
        if item.enthalpy_eV is not None:
            out.append(_record(item, "enthalpy_formation_eV", item.enthalpy_eV, "eV", citation))
        if item.entropy_J_mol_K is not None:
            out.append(_record(item, "entropy_J_mol_K", item.entropy_J_mol_K, "J/mol/K", citation))
    return out


def _record(item: Thermo, name: str, value: float, unit: str, citation: str) -> dict:
    method = item.enthalpy_method if name == "enthalpy_formation_eV" else item.entropy_method
    reference = {}
    if name == "enthalpy_formation_eV":
        # ATcT's Hfg column is explicitly the 298.15 K column; CRC's standard
        # table is also specified at 298.15 K. Other table temperatures and
        # their pressures/electron conventions remain unstated, pending review.
        # https://atct.anl.gov/Thermochemical%20Data/version%201.112/
        # https://chemicals.readthedocs.io/chemicals.heat_capacity.html
        reference["formation_reference"] = {
            "temperature_K": 298.15 if method in {"ATCT_G", "CRC"} else None,
            "basis": "standard_elements",
        }
    return {
        "species": item.species,
        "property": name,
        "value": value,
        "unit": unit,
        "phase": "gas",
        "source_species": item.formula,
        "source": {
            "provider": "chemicals",
            "collection": method,
            "release": item.package_version,
            "record_id": f"{item.cas}:{name}",
            "citation": f"{citation}, CAS {item.cas}" + (f", table {method}" if method else ""),
        },
        **reference,
    }
