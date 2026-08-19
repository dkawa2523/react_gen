"""Rank reactions by how fast they could possibly run.

The bound is deliberately one-sided. Each reaction is evaluated as if its
partner were the entire gas, which no partner ever is, so the result is an upper
limit on its frequency. A reaction whose *upper* limit is negligible can be
dropped with confidence; a high bound proves nothing on its own.

What counts as negligible depends on what it is compared against. Given a
residence time the comparison is physical: chemistry slower than the gas leaves
the chamber cannot matter. Without one, the fastest reaction in the set is used
instead, which only ranks reactions against each other. The basis used is always
reported. Nothing is removed here.
"""

from __future__ import annotations

from math import log10

from reactgen.case import Conditions
from reactgen.model import Network, Reaction
from reactgen.physics import Rate

# Decades below the reference at which a reaction stops being interesting.
# Against a residence time the claim is physical: three decades slower than gas
# exchange is a sub-0.1% contribution. Against the fastest reaction there is no
# such argument, so the same call is made far more conservatively.
THRESHOLDS = {
    "residence_time": (1.0, 3.0),
    "fastest_reaction": (3.0, 6.0),
    "none": (3.0, 6.0),
}


def frequency_bound(reaction: Reaction, rate: Rate | None, conditions: Conditions) -> float | None:
    """Largest frequency in 1/s this reaction could reach at these conditions."""

    if rate is None:
        return None
    if rate.unit == "1/s":  # wall loss and unimolecular are already frequencies
        return rate.value
    if reaction.family == "electron":
        density = conditions.electron_density_m3
        return rate.value * density if density else None
    density = conditions.gas_density_m3
    if density is None:
        return None
    return rate.value * density**2 if reaction.third_body else rate.value * density


def reference(bounds: dict[str, float | None], conditions: Conditions) -> tuple[float | None, str]:
    """The frequency everything is compared against, and where it came from."""

    if conditions.residence_time_s:
        return (1.0 / conditions.residence_time_s, "residence_time")
    known = [value for value in bounds.values() if value]
    return (max(known), "fastest_reaction") if known else (None, "none")


def relevance(bound: float | None, against: float | None, basis: str) -> str:
    """Where this reaction's ceiling sits relative to the reference frequency.

    Against a residence time the labels are physical: ``fast`` outruns gas
    exchange, ``negligible`` cannot contribute before the gas leaves. Against
    the fastest reaction they only order the set, so the bar is higher.
    """

    if bound is None or not against or bound <= 0:
        return "unknown"
    decades = log10(against / bound)
    if decades <= 0:  # at or above the reference; the fastest reaction lands here
        return "fast"
    slow_at, negligible_at = THRESHOLDS.get(basis, THRESHOLDS["none"])
    if decades < slow_at:
        return "comparable"
    return "slow" if decades < negligible_at else "negligible"


def annotate(network: Network, rates: dict[str, Rate | None], conditions: Conditions) -> dict:
    """Frequency bound and relevance for every reaction, keyed by reaction id."""

    bounds = {
        reaction.id: frequency_bound(reaction, rates.get(reaction.id), conditions)
        for reaction in network.reactions
    }
    against, basis = reference(bounds, conditions)
    return {
        reaction_id: {
            "frequency_upper_bound_s-1": bound,
            "relevance": relevance(bound, against, basis),
            "relevance_basis": basis,
        }
        for reaction_id, bound in bounds.items()
    }
