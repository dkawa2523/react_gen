"""Explicit quantity source requests, separate from physical conditions.

Preferences rank only records that passed numerical assessment. They do not
review a source, establish a channel, or supply missing physical conditions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from reactgen import yamlio

NUMERICAL_QUANTITIES = frozenset({"rate_coefficient", "cross_section", "sticking_coefficient"})
STATE_QUANTITIES = frozenset(
    {
        "enthalpy_formation_eV",
        "ionization_energy_eV",
        "electron_affinity_eV",
        "excitation_energy_eV",
        "proton_affinity_eV",
        "gas_basicity_eV",
        "mass_amu",
        "thermochemical_model",
    }
)
REFERENCE_STATE_QUANTITIES = frozenset(
    {"enthalpy_formation_eV", "ionization_energy_eV", "electron_affinity_eV"}
)
REACTION_ENERGY_QUANTITIES = frozenset({"delta_e_eV"})
SELECTABLE_QUANTITIES = NUMERICAL_QUANTITIES | STATE_QUANTITIES | REACTION_ENERGY_QUANTITIES
METHODS = frozenset({"measured", "evaluated", "calculated", "estimated", "unknown"})


@dataclass(frozen=True)
class QuantitySelection:
    mode: str = "prefer"
    methods: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    collections: tuple[str, ...] = ()
    record: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in {"prefer", "only"}:
            raise ValueError("data selection mode must be prefer or only")
        for name in ("methods", "providers", "collections"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"data selection {name} must contain nonempty identifiers")
            if len(values) != len(set(values)):
                raise ValueError(f"data selection {name} must not repeat identifiers")
        if set(self.methods) - METHODS:
            raise ValueError("data selection methods contain unsupported method names")
        if self.record is not None and (
            not isinstance(self.record, str) or not self.record.strip()
        ):
            raise ValueError("data selection record must be a nonempty identifier")
        if self.mode == "only" and not (
            self.methods or self.providers or self.collections or self.record
        ):
            raise ValueError("data selection only requires at least one allowed axis")

    @classmethod
    def from_document(cls, value: object) -> QuantitySelection:
        data = yamlio.mapping(
            value, "quantity selection", {"mode", "methods", "providers", "collections", "record"}
        )
        axes: dict[str, tuple[str, ...]] = {}
        for name in ("methods", "providers", "collections"):
            values = data.get(name, [])
            if not isinstance(values, list):
                raise ValueError(f"data selection {name} must be a list")
            axes[name] = tuple(values)
        return cls(mode=data.get("mode", "prefer"), record=data.get("record"), **axes)

    def document(self) -> dict:
        result: dict = {"mode": self.mode}
        for name in ("methods", "providers", "collections"):
            if values := getattr(self, name):
                result[name] = list(values)
        if self.record is not None:
            result["record"] = self.record
        return result

    def allows(self, method: str, provider: str | None, collection: str | None) -> bool:
        if self.mode != "only":
            return True
        return all(
            not offered or actual in offered
            for offered, actual in zip(
                (self.methods, self.providers, self.collections),
                (method, provider, collection),
                strict=True,
            )
        )

    def rank(self, method: str, provider: str | None, collection: str | None) -> tuple[int, ...]:
        """Unlisted records share one fallback rank on each specified axis."""
        return tuple(
            offered.index(actual) if actual is not None and actual in offered else len(offered)
            for offered, actual in zip(
                (self.methods, self.providers, self.collections),
                (method, provider, collection),
                strict=True,
            )
            if offered
        )


@dataclass(frozen=True)
class DataSelection:
    quantities: dict[str, QuantitySelection] = field(default_factory=dict)
    targets: dict[str, dict[str, QuantitySelection]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.quantities, dict):
            raise ValueError("data_selection.quantities must be a mapping")
        if set(self.quantities) - SELECTABLE_QUANTITIES:
            raise ValueError("data_selection.quantities contain unsupported quantity names")
        if any(not isinstance(value, QuantitySelection) for value in self.quantities.values()):
            raise ValueError("data_selection requires validated QuantitySelection values")
        if not isinstance(self.targets, dict) or any(
            not isinstance(target, str) or not target.strip() for target in self.targets
        ):
            raise ValueError("data_selection.targets must map nonempty target identifiers")
        for target, policies in self.targets.items():
            if not isinstance(policies, dict) or not policies:
                raise ValueError(f"data_selection.targets.{target} must contain quantity policies")
            if set(policies) - SELECTABLE_QUANTITIES:
                raise ValueError("data_selection.targets contain unsupported quantity names")
            if any(not isinstance(value, QuantitySelection) for value in policies.values()):
                raise ValueError("data_selection requires validated QuantitySelection values")

    @classmethod
    def from_document(cls, value: object) -> DataSelection:
        data = yamlio.mapping(value, "data_selection", {"quantities", "targets"})
        quantities = yamlio.mapping(
            data.get("quantities", {}), "data_selection.quantities", set(SELECTABLE_QUANTITIES)
        )
        targets = data.get("targets", {})
        if not isinstance(targets, dict):
            raise ValueError("data_selection.targets must be a mapping")
        return cls(
            {name: QuantitySelection.from_document(value) for name, value in quantities.items()},
            {
                target: {
                    quantity: QuantitySelection.from_document(policy)
                    for quantity, policy in yamlio.mapping(
                        policies, f"data_selection.targets.{target}", set(SELECTABLE_QUANTITIES)
                    ).items()
                }
                for target, policies in targets.items()
            },
        )

    def document(self) -> dict:
        document = {
            "quantities": {
                name: policy.document() for name, policy in sorted(self.quantities.items())
            }
        }
        if self.targets:
            document["targets"] = {
                target: {
                    quantity: policy.document() for quantity, policy in sorted(policies.items())
                }
                for target, policies in sorted(self.targets.items())
            }
        return document

    def for_quantity(self, quantity: str, target: str | None = None) -> QuantitySelection | None:
        return self.targets.get(target or "", {}).get(quantity, self.quantities.get(quantity))

    def validate_targets(
        self,
        states: Iterable[str],
        reactions: Iterable[str],
        *,
        reference_states: Iterable[str] = (),
    ) -> None:
        """Validate requested identities/quantity domains, without evaluating data."""
        state_ids, reaction_ids = set(states), set(reactions)
        reference_ids = set(reference_states)
        for target, policies in self.targets.items():
            if target in state_ids:
                supported = STATE_QUANTITIES
            elif target in reaction_ids:
                supported = NUMERICAL_QUANTITIES | REACTION_ENERGY_QUANTITIES
            elif target in reference_ids:
                supported = REFERENCE_STATE_QUANTITIES
            else:
                raise ValueError(
                    "data_selection target is not an analyzed candidate or calculation reference: "
                    f"{target}"
                )
            if unknown := set(policies) - supported:
                raise ValueError(
                    f"data_selection target {target}: unsupported quantities for this target: "
                    + ", ".join(sorted(unknown))
                )
