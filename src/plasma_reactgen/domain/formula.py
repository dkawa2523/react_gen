from __future__ import annotations

import re


ATOMIC_MASS_AMU = {
    "H": 1.00784,
    "C": 12.011,
    "N": 14.0067,
    "O": 15.999,
    "F": 18.998403163,
    "Si": 28.085,
    "Cl": 35.45,
    "Ar": 39.948,
}

_TOKEN_RE = re.compile(r"([A-Z][a-z]?)(\d*)")
_UNSUPPORTED_RE = re.compile(r"[\(\)\[\]\{\}\*\+\-\.:]")


def parse_formula(formula: str) -> dict[str, int]:
    """Parse a simple chemical formula into element counts.

    This intentionally supports only plain element/count strings such as
    ``CF4`` or ``SiH4``. Unsupported notation returns an empty dict so callers
    can skip inference without breaking normal generation.
    """

    text = formula.strip()
    if not text or _UNSUPPORTED_RE.search(text):
        return {}

    pos = 0
    composition: dict[str, int] = {}
    for match in _TOKEN_RE.finditer(text):
        if match.start() != pos:
            return {}
        element, count_text = match.groups()
        count = int(count_text) if count_text else 1
        if count <= 0:
            return {}
        composition[element] = composition.get(element, 0) + count
        pos = match.end()

    if pos != len(text):
        return {}
    return composition


def composition_mass_amu(composition: dict[str, int]) -> float | None:
    """Return composition mass or ``None`` when an element is unknown."""

    if not composition:
        return None

    total = 0.0
    for element, count in composition.items():
        if element not in ATOMIC_MASS_AMU:
            return None
        if isinstance(count, bool):
            return None
        try:
            count_float = float(count)
        except (TypeError, ValueError):
            return None
        if not count_float.is_integer():
            return None
        n = int(count_float)
        if n <= 0:
            return None
        total += ATOMIC_MASS_AMU[element] * n
    return total
