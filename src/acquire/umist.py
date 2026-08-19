"""Parse a UMIST RATE release into snapshot records.

The download is a person's job — the release URL moves between versions — but
the file itself has a stable colon-separated layout, and that is what made these
sources unusable rather than the fetching::

    index:type:R1:R2:R3:P1:P2:P3:P4:alpha:beta:gamma:...:Tmin:Tmax:...

The coefficient is ``k = alpha (T/300)^beta exp(-gamma/T)`` in cm3/s, which is
converted to SI and to the eV activation energy the registry records.

UMIST is astrochemistry: the equations transfer to plasma work, the rates
usually do not. Every record therefore carries its declared temperature range,
so `rgen generate` flags it as out of range at a plasma gas temperature instead
of using it silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

CM3_PER_M3 = 1e-6
KELVIN_PER_EV = 11604.518
FIELDS = 12  # index, type, three reactants, four products, alpha, beta, gamma


@dataclass(frozen=True)
class Rate:
    """One reaction and its Arrhenius coefficient, in SI."""

    kind: str
    reactants: tuple[str, ...]
    products: tuple[str, ...]
    a_si: float
    beta: float
    activation_eV: float
    t_min: float | None
    t_max: float | None

    @property
    def equation(self) -> str:
        return f"{' + '.join(self.reactants)} -> {' + '.join(self.products)}"

    @property
    def order(self) -> int:
        return len(self.reactants)


def parse(path: str | Path) -> list[Rate]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    return [rate for line in lines if (rate := _row(line)) is not None]


def _row(line: str) -> Rate | None:
    parts = [field.strip() for field in line.split(":")]
    if len(parts) < FIELDS or not parts[0].strip().isdigit():
        return None

    reactants = tuple(name for name in parts[2:5] if name)
    products = tuple(name for name in parts[5:9] if name)
    alpha, beta, gamma = (_number(parts[index]) for index in (9, 10, 11))
    if not reactants or not products or alpha is None:
        return None

    low, high = _temperatures(parts[12:])
    return Rate(
        kind=parts[1] or "unspecified",
        reactants=reactants,
        products=products,
        a_si=alpha * CM3_PER_M3 ** (len(reactants) - 1),
        beta=beta or 0.0,
        activation_eV=(gamma or 0.0) / KELVIN_PER_EV,
        t_min=low,
        t_max=high,
    )


def _temperatures(tail: list[str]) -> tuple[float | None, float | None]:
    """The first ascending numeric pair after the coefficients is the range."""

    numbers = [value for value in (_number(field) for field in tail) if value is not None]
    for low, high in pairwise(numbers):
        if 0 < low < high:
            return (low, high)
    return (None, None)


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def records(rates: list[Rate], keep_order: int = 2) -> list[dict]:
    """Snapshot records for `rgen ingest`, two-body reactions only."""

    return [
        {
            "reaction": rate.equation,
            "form": "arrhenius",
            "unit": "m3/s",
            "parameters": {
                "A": rate.a_si,
                "n": rate.beta,
                "T_ref": 300.0,
                "Ea_eV": rate.activation_eV,
            },
            "validity": {"minimum": rate.t_min, "maximum": rate.t_max, "unit": "K"},
            "status": "imported",
            "notes": f"UMIST {rate.kind}; astrochemical range, verify before plasma use",
        }
        for rate in rates
        if rate.order == keep_order and rate.t_min
    ]
