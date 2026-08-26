"""Neutral formula inputs, assessment conditions, surfaces and safety limits."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import yaml

BOLTZMANN = 1.380649e-23

_FIELD_OF_QUANTITY = {
    "gas_temperature": "gas_temperature_K",
    "electron_temperature": "electron_temperature_eV",
    "reduced_field": "reduced_field_Td",
    "pressure": "pressure_Pa",
}


@dataclass(frozen=True)
class Conditions:
    pressure_Pa: float | None = None
    gas_temperature_K: float | None = None
    electron_temperature_eV: float | None = None
    electron_density_m3: float | None = None
    reduced_field_Td: float | None = None
    volume_m3: float | None = None
    surface_area_m2: float | None = None
    residence_time_s: float | None = None

    def __post_init__(self) -> None:
        values = {
            name: value
            for name, value in (
                ("pressure_Pa", self.pressure_Pa),
                ("gas_temperature_K", self.gas_temperature_K),
                ("electron_temperature_eV", self.electron_temperature_eV),
                ("electron_density_m3", self.electron_density_m3),
                ("reduced_field_Td", self.reduced_field_Td),
                ("volume_m3", self.volume_m3),
                ("surface_area_m2", self.surface_area_m2),
                ("residence_time_s", self.residence_time_s),
            )
            if value is not None
        }
        for name, value in values.items():
            if not isfinite(value):
                raise ValueError(f"conditions.{name} must be finite")
        for name in (
            "pressure_Pa",
            "gas_temperature_K",
            "electron_temperature_eV",
            "volume_m3",
            "residence_time_s",
        ):
            checked = values.get(name)
            if checked is not None and checked <= 0.0:
                raise ValueError(f"conditions.{name} must be positive")
        for name in ("electron_density_m3", "reduced_field_Td", "surface_area_m2"):
            checked = values.get(name)
            if checked is not None and checked < 0.0:
                raise ValueError(f"conditions.{name} must be non-negative")

    def value_of(self, quantity: str) -> float | None:
        return getattr(self, _FIELD_OF_QUANTITY.get(quantity, ""), None)

    @property
    def gas_density_m3(self) -> float | None:
        """Neutral density from the ideal gas law."""
        if self.pressure_Pa is None or not self.gas_temperature_K:
            return None
        return self.pressure_Pa / (BOLTZMANN * self.gas_temperature_K)

    @property
    def area_to_volume(self) -> float | None:
        """Wall area per unit volume, the geometry factor in a loss frequency."""
        if self.surface_area_m2 is None or not self.volume_m3:
            return None
        return self.surface_area_m2 / self.volume_m3


@dataclass(frozen=True)
class Limits:
    max_depth: int = 6
    max_species: int = 300
    max_reactions: int = 5000
    max_charge_abs: int = 1
    max_leaving_atoms: int = 2

    def __post_init__(self) -> None:
        values = (
            self.max_depth,
            self.max_species,
            self.max_reactions,
            self.max_charge_abs,
            self.max_leaving_atoms,
        )
        if any(value < 1 for value in values):
            raise ValueError("all generation limits must be positive integers")


@dataclass(frozen=True)
class Case:
    name: str
    gases: tuple[str, ...]
    conditions: Conditions = Conditions()
    surfaces: tuple[str, ...] = ()
    limits: Limits = Limits()

    @classmethod
    def load(cls, path: str | Path) -> Case:
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        removed = {
            "fraction",
            "fractions",
            "dnt",
            "accept_status",
            "accept_processes",
        }
        obsolete = sorted(set(data).intersection(removed))
        if obsolete:
            raise ValueError(f"{path}: removed case fields: {', '.join(obsolete)}")
        gases = data.get("gases") or []
        if not isinstance(gases, list) or not gases:
            raise ValueError(f"{path}: 'gases' must list at least one input gas")
        if any(not isinstance(gas, str) for gas in gases):
            raise ValueError(f"{path}: every input gas must be a chemical-formula string")
        limits = data.get("limits") or {}
        return cls(
            name=data.get("name") or path.parent.name,
            gases=tuple(gases),
            conditions=Conditions(**_floats(data.get("conditions") or {})),
            surfaces=tuple(data.get("surfaces") or []),
            limits=Limits(
                max_depth=int(limits.get("max_depth", 6)),
                max_species=int(limits.get("max_species", 300)),
                max_reactions=int(limits.get("max_reactions", 5000)),
                max_charge_abs=int(limits.get("max_charge_abs", 1)),
                max_leaving_atoms=int(limits.get("max_leaving_atoms", 2)),
            ),
        )


def _floats(data: dict) -> dict:
    """Coerce condition values to float.

    YAML 1.1 reads ``5.0e16`` as a string because the exponent has no sign, and
    a silently-stringy density would otherwise reach the arithmetic.
    """

    return {key: None if value is None else float(value) for key, value in data.items()}
