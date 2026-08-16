"""Safe adapter around the optional :mod:`chemicals` package."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChemicalsModules:
    """Loaded optional modules and their availability status."""

    identifiers: Any = None
    dipole: Any = None
    reaction: Any = None
    lennard_jones: Any = None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.identifiers is not None


def load_chemicals_modules() -> ChemicalsModules:
    """Load the required identifier module and optional property modules."""

    try:
        identifiers = importlib.import_module("chemicals.identifiers")
    except ImportError:
        return ChemicalsModules(reason="chemicals package not installed")
    return ChemicalsModules(
        identifiers=identifiers,
        dipole=_optional_module("chemicals.dipole"),
        reaction=_optional_module("chemicals.reaction"),
        lennard_jones=_optional_module("chemicals.lennard_jones"),
    )


def search_chemical(modules: ChemicalsModules, query: str) -> Any:
    """Return one chemicals record, treating adapter failures as unavailable data."""

    search = getattr(modules.identifiers, "search_chemical", None)
    if not callable(search):
        return None
    try:
        return search(query)
    except Exception:
        return None


def cas_numeric_value(
    module: Any,
    function_names: tuple[str, ...],
    cas: str | None,
) -> float | None:
    """Read the first numeric value from compatible keyword or positional APIs."""

    if module is None or not cas:
        return None
    for function_name in function_names:
        function = getattr(module, function_name, None)
        if not callable(function):
            continue
        value = _call_cas_function(function, cas)
        numeric = float_or_none(value)
        if numeric is not None:
            return numeric
    return None


def first_attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value not in (None, ""):
            return value
    return None


def list_attr(obj: Any, *names: str) -> list[str]:
    for name in names:
        value = getattr(obj, name, None)
        if value:
            return [value] if isinstance(value, str) else [str(item) for item in value]
    return []


def float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _call_cas_function(function: Callable[..., Any], cas: str) -> Any:
    try:
        return function(CASRN=cas)
    except TypeError:
        try:
            return function(cas)
        except Exception:
            return None
    except Exception:
        return None


__all__ = [
    "ChemicalsModules",
    "cas_numeric_value",
    "first_attr",
    "float_or_none",
    "list_attr",
    "load_chemicals_modules",
    "search_chemical",
]
