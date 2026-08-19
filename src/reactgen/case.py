"""The user's input: which gases, under which process conditions.

Conditions are optional. When given they evaluate temperature-dependent rates,
check each dataset against its declared validity range, turn a wall sticking
coefficient into a loss frequency, and rank reactions by an upper bound on how
fast they can run. They never silently remove a reaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from reactgen import processes

BOLTZMANN = 1.380649e-23

DEFAULT_STATUS = ("curated", "literature_supported", "imported", "estimated")

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
    max_depth: int | None = None
    max_species: int = 300
    max_reactions: int = 5000


@dataclass(frozen=True)
class DntGrid:
    """Energy grid the DNT+ inputs are written on.

    The default spans a capacitively coupled sheath; raise ``energy_max_eV``
    for high reduced fields rather than trusting it silently.
    """

    energy_min_eV: float = 0.01
    energy_max_eV: float = 100.0
    points: int = 200
    spacing: str = "log"


@dataclass(frozen=True)
class Case:
    name: str
    gases: tuple[str, ...]
    conditions: Conditions = Conditions()
    surfaces: tuple[str, ...] = ()
    limits: Limits = Limits()
    dnt: DntGrid = DntGrid()
    accept_status: tuple[str, ...] = DEFAULT_STATUS
    accept_processes: tuple[str, ...] | None = None

    def accepts(self, reaction_type: str) -> bool:
        """Whether a collision family the case did not ask for is let through.

        Naming none accepts every one, which is what a curated registry wants.
        """

        return self.accept_processes is None or processes.allows(
            self.accept_processes, reaction_type
        )

    @classmethod
    def load(cls, path: str | Path) -> Case:
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        gases = data.get("gases") or []
        if not gases:
            raise ValueError(f"{path}: 'gases' must list at least one input gas")
        limits = data.get("limits") or {}
        return cls(
            name=data.get("name") or path.parent.name,
            gases=tuple(gases),
            conditions=Conditions(**_floats(data.get("conditions") or {})),
            surfaces=tuple(data.get("surfaces") or []),
            limits=Limits(
                max_depth=limits.get("max_depth"),
                max_species=int(limits.get("max_species", 300)),
                max_reactions=int(limits.get("max_reactions", 5000)),
            ),
            dnt=DntGrid(**(data.get("dnt") or {})),
            accept_status=tuple(data.get("accept_status") or DEFAULT_STATUS),
            accept_processes=_processes(data.get("accept_processes")),
        )


def _processes(names: list[str] | None) -> tuple[str, ...] | None:
    if not names:
        return None
    unknown = sorted(set(names) - set(processes.NAMES))
    if unknown:
        raise ValueError(f"unknown collision families {unknown}; known: {list(processes.NAMES)}")
    return tuple(names)


def _floats(data: dict) -> dict:
    """Coerce condition values to float.

    YAML 1.1 reads ``5.0e16`` as a string because the exponent has no sign, and
    a silently-stringy density would otherwise reach the arithmetic.
    """

    return {key: None if value is None else float(value) for key, value in data.items()}
