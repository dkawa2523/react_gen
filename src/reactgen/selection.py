"""Explicit numerical source requests, separate from physical conditions.

Preferences rank only records that passed numerical assessment. They do not
review a source, establish a channel, or supply missing physical conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NUMERICAL_QUANTITIES = frozenset({"rate_coefficient", "cross_section", "sticking_coefficient"})
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
        data = _mapping(
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

    def __post_init__(self) -> None:
        if not isinstance(self.quantities, dict):
            raise ValueError("data_selection.quantities must be a mapping")
        if set(self.quantities) - NUMERICAL_QUANTITIES:
            raise ValueError("data_selection.quantities contain unsupported quantity names")
        if any(not isinstance(value, QuantitySelection) for value in self.quantities.values()):
            raise ValueError("data_selection requires validated QuantitySelection values")

    @classmethod
    def from_document(cls, value: object) -> DataSelection:
        data = _mapping(value, "data_selection", {"quantities"})
        quantities = _mapping(
            data.get("quantities", {}), "data_selection.quantities", set(NUMERICAL_QUANTITIES)
        )
        return cls(
            {name: QuantitySelection.from_document(value) for name, value in quantities.items()}
        )

    def document(self) -> dict:
        return {
            "quantities": {
                name: policy.document() for name, policy in sorted(self.quantities.items())
            }
        }

    def for_quantity(self, quantity: str) -> QuantitySelection | None:
        return self.quantities.get(quantity)


def _mapping(value: object, name: str, allowed: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    unexpected = set(value) - allowed
    if unexpected:
        raise ValueError(f"{name}: unsupported fields: {', '.join(sorted(map(str, unexpected)))}")
    return value
