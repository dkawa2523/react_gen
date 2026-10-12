"""Validated physical inputs and explicit bounds on the candidate grammar."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from math import isfinite
from pathlib import Path

from reactgen import yamlio
from reactgen.chemistry import formula
from reactgen.model import CONDITION_INPUT_FIELDS
from reactgen.naming import parse
from reactgen.selection import DataSelection


@dataclass(frozen=True)
class Conditions:
    gas_temperature_K: float | None = None
    electron_temperature_eV: float | None = None
    reduced_field_Td: float | None = None
    ion_energy_eV: float | None = None
    ion_temperature_K: float | None = None
    surface_temperature_K: float | None = None
    electron_energy_eV: float | None = None
    collision_energy_eV: float | None = None

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
                raise ValueError(f"conditions.{name} must be a finite number")
            if value < 0 or (
                (name.endswith("temperature_K") or name.endswith("temperature_eV")) and value == 0
            ):
                raise ValueError(f"conditions.{name} is outside its physical domain")

    def value_of(self, quantity: str) -> float | None:
        return getattr(self, CONDITION_INPUT_FIELDS.get(quantity, ""), None)

    @staticmethod
    def input_field(quantity: str) -> str | None:
        """Return the accepted input field for a supported physical quantity."""
        return CONDITION_INPUT_FIELDS.get(quantity)


@dataclass(frozen=True)
class Limits:
    max_depth: int = 12
    max_species: int = 300
    max_reactions: int = 10000
    max_charge_abs: int = 1
    max_leaving_atoms: int = 2

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise ValueError("all generation limits must be positive integers")
        if self.max_charge_abs != 1:
            raise ValueError(
                "the mechanical grammar supports max_charge_abs=1 only; "
                "evidence may supply other charges"
            )


@dataclass(frozen=True)
class Case:
    """An analysis request; name is display metadata, never a rule selector."""

    name: str
    gases: tuple[str, ...]
    conditions: Conditions = Conditions()
    surfaces: tuple[str, ...] = ()
    limits: Limits = Limits()
    data_selection: DataSelection = field(default_factory=DataSelection)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a nonempty string")
        if not isinstance(self.gases, tuple) or not self.gases:
            raise ValueError("gases must contain at least one neutral ground-state formula")
        normalized = []
        for gas in self.gases:
            if not isinstance(gas, str):
                raise ValueError("gases must contain chemical-formula strings")
            named = parse(gas)
            if not named.composition or named.charge or named.excited:
                raise ValueError(f"unsupported input formula: {gas}")
            normalized.append(formula(named.composition))
        object.__setattr__(self, "gases", tuple(sorted(set(normalized))))
        if not isinstance(self.surfaces, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.surfaces
        ):
            raise ValueError("surfaces must be a list of nonempty identifiers")
        object.__setattr__(self, "surfaces", tuple(sorted(set(self.surfaces))))
        if not isinstance(self.conditions, Conditions) or not isinstance(self.limits, Limits):
            raise ValueError("conditions and limits must be validated input types")
        if not isinstance(self.data_selection, DataSelection):
            raise ValueError("data_selection must be a validated DataSelection")

    @classmethod
    def load(cls, path: str | Path) -> Case:
        return cls.from_document(yamlio.load(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_document(cls, document: object) -> Case:
        data = _mapping(document, "input", {item.name for item in fields(cls)})
        gases = data.get("gases")
        if not isinstance(gases, list):
            raise ValueError("gases must be a list of neutral ground-state formulas")
        surfaces = data.get("surfaces", [])
        if not isinstance(surfaces, list):
            raise ValueError("surfaces must be a list of identifiers")
        conditions = _mapping(
            data.get("conditions", {}), "conditions", {item.name for item in fields(Conditions)}
        )
        values: dict[str, float | None] = {}
        for key, value in conditions.items():
            if value is None:
                values[key] = None
            else:
                if isinstance(value, bool):
                    raise ValueError(f"conditions.{key} must be numeric")
                try:
                    values[key] = float(value)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"conditions.{key} must be numeric") from error
        limits = _mapping(data.get("limits", {}), "limits", {item.name for item in fields(Limits)})
        return cls(
            data.get("name", "analysis"),
            tuple(gases),
            Conditions(**values),
            tuple(surfaces),
            Limits(**limits),
            DataSelection.from_document(data.get("data_selection", {})),
        )

    def document(self) -> dict:
        document = asdict(self)
        document["gases"] = list(self.gases)
        document["surfaces"] = list(self.surfaces)
        document["conditions"] = {
            key: value for key, value in document["conditions"].items() if value is not None
        }
        if self.data_selection.quantities:
            document["data_selection"] = self.data_selection.document()
        else:
            del document["data_selection"]
        return document


def _mapping(value: object, name: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    unexpected = set(value) - allowed
    if unexpected:
        raise ValueError(f"{name}: unsupported fields: {', '.join(sorted(map(str, unexpected)))}")
    return value
