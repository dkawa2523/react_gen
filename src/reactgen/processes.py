"""Which collision processes a case asks for.

A family, not a reaction type: what a user turns off is attachment, not
``dissociative_attachment``. Families that are not built yet are named here
anyway, so the interface says what is missing instead of hiding it — asking for
one reports that it does not exist rather than quietly returning nothing.

A case that names no family accepts every one, which is what a curated registry
wants. Naming them restricts both what the registry contributes and what a
proposer may invent, so the choice means the same thing on both paths.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Process:
    """One family, the reaction types it covers, and whether it runs by default."""

    name: str
    types: frozenset[str]
    default: bool
    implemented: bool = True
    note: str = ""


CATALOG: tuple[Process, ...] = (
    Process("elastic", frozenset({"elastic"}), True),
    Process("excitation", frozenset({"excitation", "deexcitation"}), True),
    Process("dissociation", frozenset({"dissociation"}), True),
    Process(
        "ionization",
        frozenset({"ionization", "ionization_2", "ionization_3", "dissociative_ionization"}),
        True,
    ),
    Process(
        "vibrational_relaxation",
        frozenset({"vibrational_relaxation"}),
        True,
        note=(
            "heavy-particle loss of a vibrational manifold. On by default because "
            "carrying X_v without it leaves electron superelastic as the only way "
            "down, and neutrals outnumber electrons by ten thousand to one"
        ),
    ),
    Process(
        "attachment",
        frozenset({"attachment", "electron_detachment"}),
        False,
        note=(
            "needs electron affinity to gate; without it a parent anion is written "
            "for species that bind no electron, such as N2- and H2-"
        ),
    ),
    Process(
        "heavy_particle",
        frozenset(
            {
                "charge_transfer",
                "dissociative_charge_transfer",
                "penning_ionization",
                "mutual_neutralization",
                "reactive_scattering",
            }
        ),
        True,
        note=(
            "ion-neutral and neutral-neutral collisions. On by default: almost "
            "none of it is in any database, and deciding what DNT+ should "
            "compute is what this list is for"
        ),
    ),
    Process("three_body", frozenset({"three_body", "association"}), False),
    Process(
        "growth",
        frozenset(),
        False,
        implemented=False,
        note=(
            "radical association into larger species. Deposition and particle "
            "formation are surface processes and out of scope for a gas-phase list"
        ),
    ),
)

BY_NAME = {process.name: process for process in CATALOG}
NAMES = tuple(process.name for process in CATALOG)
DEFAULT = tuple(process.name for process in CATALOG if process.default)


def allows(names: Iterable[str], reaction_type: str) -> bool:
    return any(reaction_type in BY_NAME[name].types for name in names if name in BY_NAME)


@dataclass(frozen=True)
class Selection:
    """The families a run generates, and what it was asked for but cannot do."""

    active: tuple[str, ...]
    missing: tuple[str, ...]

    def allows(self, reaction_type: str) -> bool:
        return allows(self.active, reaction_type)

    def on(self, name: str) -> bool:
        return name in self.active

    def report(self) -> dict[str, list[str]]:
        """What the summary records, so a reader sees the shape of the run."""

        chosen = set(self.active) | set(self.missing)
        return {
            "on": sorted(self.active),
            "off": sorted(set(NAMES) - chosen),
            "not_implemented": sorted(self.missing),
        }


def select(enable: Iterable[str] | None = None, disable: Iterable[str] | None = None) -> Selection:
    chosen = set(DEFAULT) | set(enable or ())
    chosen -= set(disable or ())
    missing = {name for name in chosen if not BY_NAME[name].implemented}
    return Selection(tuple(sorted(chosen - missing)), tuple(sorted(missing)))


def describe() -> str:
    """One line per family, for ``--help``."""

    lines = []
    for process in CATALOG:
        state = "on" if process.default else "off"
        if not process.implemented:
            state = "not implemented"
        tail = f" - {process.note}" if process.note else ""
        lines.append(f"  {process.name:<15} {state}{tail}")
    return "\n".join(lines)
