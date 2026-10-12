"""Conversions used by evidence calculations, with explicit physical quantities.

Temperature in eV denotes k_B T, not a particle's collision energy. These
conversions never infer an EEDF or interchange gas and electron temperatures.
"""

from __future__ import annotations

import re
from math import isfinite

JOULE_PER_EV = 1.602176634e-19
BOLTZMANN = 1.380649e-23
AVOGADRO = 6.02214076e23
EV_PER_K = BOLTZMANN / JOULE_PER_EV
TEMPERATURE_QUANTITIES = frozenset(
    {"gas_temperature", "electron_temperature", "ion_temperature", "surface_temperature"}
)


def energy_eV(value: float, unit: str | None) -> float | None:
    """Energy per particle; molar energy units are explicitly converted."""
    factors = {
        "eV": 1.0,
        "J": 1.0 / JOULE_PER_EV,
        "J/mol": 1.0 / (AVOGADRO * JOULE_PER_EV),
        "kJ/mol": 1000.0 / (AVOGADRO * JOULE_PER_EV),
        "K": EV_PER_K,
    }
    factor = factors.get(unit or "")
    if factor is None or not isfinite(value):
        return None
    converted = value * factor
    return converted if isfinite(converted) else None


def quantity_value(value: float, quantity: str, source_unit: str, target_unit: str) -> float | None:
    """Convert a value without changing its named physical quantity."""
    if not isfinite(value):
        return None
    if quantity in TEMPERATURE_QUANTITIES:
        units = {"K": EV_PER_K, "eV": 1.0}
    elif quantity in {"collision_energy", "electron_energy", "ion_energy"}:
        units = {"eV": 1.0, "J": 1.0 / JOULE_PER_EV}
    elif quantity == "reduced_field":
        units = {"Td": 1.0, "V*m2": 1e21}
    else:
        return None
    if source_unit not in units or target_unit not in units:
        return None
    converted = value * units[source_unit] / units[target_unit]
    return converted if isfinite(converted) else None


def canonical_axis_unit(quantity: str | None) -> str | None:
    if quantity in TEMPERATURE_QUANTITIES:
        return "K"
    if quantity in {"collision_energy", "electron_energy", "ion_energy"}:
        return "eV"
    return "Td" if quantity == "reduced_field" else None


def numerical_unit(unit: str | None, kind: str, order: float | None) -> tuple[str, float] | None:
    """Canonical number-density coefficient units and scale, never molar units."""
    written = (unit or "").lower().replace("^", "").replace(" ", "")
    if kind == "cross_section":
        return {"m2": ("m2", 1.0), "cm2": ("m2", 1e-4)}.get(written)
    if kind == "sticking_coefficient":
        return ("1", 1.0) if written in {"1", "dimensionless"} else None
    if kind != "rate_coefficient" or order is None or not isfinite(order):
        return None
    if order == 1 and written in {"s-1", "1/s"}:
        return ("s-1", 1.0)
    match = re.fullmatch(r"(m|cm)(\d+(?:\.\d+)?)/s", written)
    if match is None:
        return None
    exponent = float(match[2])
    if abs(exponent - 3 * (order - 1)) > 1e-9:
        return None
    canonical = f"m{exponent:g}/s"
    return (canonical, 10.0 ** (-2 * exponent) if match[1] == "cm" else 1.0)
