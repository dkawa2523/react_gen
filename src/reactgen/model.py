"""Registry-independent candidate types and canonical keys."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import NamedTuple

ELECTRON = "e"
THIRD_BODY = "M"

FAMILY_ALIASES = {
    "electron_ion": "electron",
    "ion_neutral": "ion",
    "ion_ion": "ion",
    "neutral_neutral": "neutral",
    "three_body": "neutral",
    "unimolecular": "neutral",
}

PROCESS_ALIASES = {
    "charge_transfer": "charge_exchange",
    "electron_detachment": "collisional_detachment",
    "neutralization": "mutual_neutralization",
    "three_body_recombination": "three_body_association",
}


def canonical_family(family: str) -> str:
    written = _channel_name(family)
    return FAMILY_ALIASES.get(written, written)


def canonical_process(
    process: str,
    *,
    family: str = "",
    third_body: str | None = None,
    surface: str | None = None,
) -> str:
    """Resolve source vocabulary before reaction identity is built."""

    raw_family = _channel_name(family)
    written = PROCESS_ALIASES.get(_channel_name(process), _channel_name(process))
    if (surface is not None or raw_family == "surface") and written in {
        "association",
        "recombination",
    }:
        return "surface_recombination"
    if (third_body is not None or raw_family == "three_body") and written in {
        "association",
        "recombination",
        "three_body_association",
    }:
        return "three_body_association"
    return written


def _channel_name(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class Term(NamedTuple):
    """One species with its stoichiometric count.

    The count is a float so surface channels can express a branching fraction
    such as ``F -> 0.5 F2``.
    """

    species: str
    n: float = 1.0

    def __str__(self) -> str:
        if self.n == 1:
            return self.species
        count = int(self.n) if self.n == int(self.n) else self.n
        return f"{count} {self.species}"


StateKey = tuple[tuple[tuple[str, int], ...], int, str, str]
# A reaction channel is not identified by stoichiometry alone.  Elastic
# scattering and charge exchange can have the same equation while requiring
# different evidence and numerical data.
ReactionKey = tuple[str, str, str | None, str | None, tuple, tuple]
EquationKey = tuple[str | None, str | None, tuple, tuple]


def state_excitation(kind: str, label: str = "") -> str:
    """Return the physical excitation axis without resolution or lifetime semantics."""

    if kind == "vibrational" or (kind == "resolved" and label.startswith("v")):
        return "vibrational"
    if kind in {"electronic", "metastable", "resonant", "resolved"}:
        return "electronic"
    return kind


def state_lifetime_class(kind: str, classes: frozenset[str] | set[str]) -> str:
    """Return the radiative/lifetime role independently of excitation and resolution."""

    if "mixed_lifetime" in classes:
        return "mixed_metastable_resonant"
    if kind == "metastable" or "metastable" in classes:
        return "metastable"
    if kind == "resonant" or "resonant" in classes:
        return "resonant_radiative"
    if state_excitation(kind) == "electronic" and kind != "ground":
        return "unspecified"
    return "not_applicable"


def canonical_state_label(kind: str, label: str = "") -> str:
    """Return a stable machine label; display symbols are a separate concern."""

    return label or kind


@dataclass(frozen=True)
class CandidateState:
    kind: str
    resolution: str = "lumped"
    label: str = ""

    @property
    def manifold(self) -> str:
        return state_excitation(self.kind, self.label)


@dataclass(frozen=True)
class StateCandidate:
    id: str
    composition: dict[str, int]
    charge: int
    state: CandidateState
    classes: frozenset[str] = frozenset()
    origin: str = "mechanical"
    depth: int = 0
    introduced_by: tuple[str, ...] = ()

    @property
    def key(self) -> StateKey:
        return (
            tuple(sorted(self.composition.items())),
            self.charge,
            self.state.kind,
            self.state.label,
        )


def side_key(terms: tuple[Term, ...] | list[Term]) -> tuple[tuple[str, float], ...]:
    totals: dict[str, float] = {}
    for term in terms:
        totals[term.species] = totals.get(term.species, 0.0) + term.n
    return tuple(sorted((name, count) for name, count in totals.items() if count))


@dataclass(frozen=True)
class ReactionCandidate:
    id: str
    reactants: tuple[Term, ...]
    products: tuple[Term, ...]
    family: str
    process: str
    origin: str
    generation_rule: str
    depth: int
    third_body: str | None = None
    surface: str | None = None
    kinetic_effects: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        raw_family = self.family
        object.__setattr__(self, "family", canonical_family(raw_family))
        object.__setattr__(
            self,
            "process",
            canonical_process(
                self.process,
                family=raw_family,
                third_body=self.third_body,
                surface=self.surface,
            ),
        )

    @property
    def key(self) -> ReactionKey:
        return (
            self.family,
            self.process,
            self.third_body,
            self.surface,
            side_key(self.reactants),
            side_key(self.products),
        )

    @property
    def equation_key(self) -> EquationKey:
        return (
            self.third_body,
            self.surface,
            side_key(self.reactants),
            side_key(self.products),
        )

    @property
    def equation(self) -> str:
        left = [str(term) for term in self.reactants]
        right = [str(term) for term in self.products]
        if self.third_body:
            left.append(THIRD_BODY)
            right.append(THIRD_BODY)
        if self.surface:
            left.append(f"[{self.surface}]")
        return f"{' + '.join(left)} -> {' + '.join(right)}"


def reaction_id(key: ReactionKey) -> str:
    encoded = json.dumps(key, separators=(",", ":"), ensure_ascii=True)
    return "rxn_" + hashlib.sha256(encoded.encode()).hexdigest()[:12]


@dataclass
class CandidateSet:
    states: dict[str, StateCandidate] = field(default_factory=dict)
    reactions: dict[str, ReactionCandidate] = field(default_factory=dict)
    complete: bool = True
    stop_reason: str = "closure"
    limits: dict[str, int] = field(default_factory=dict)

    def state_by_key(self) -> dict[StateKey, StateCandidate]:
        return {state.key: state for state in self.states.values()}

    def reaction_by_key(self) -> dict[ReactionKey, ReactionCandidate]:
        return {reaction.key: reaction for reaction in self.reactions.values()}

    def equation_index(self) -> dict[EquationKey, list[ReactionCandidate]]:
        found: dict[EquationKey, list[ReactionCandidate]] = {}
        for reaction in self.reactions.values():
            found.setdefault(reaction.equation_key, []).append(reaction)
        return found


@dataclass(frozen=True)
class Assessment:
    verdict: str  # pass | fail | unknown | not_applicable
    basis: tuple[str, ...] = ()
    message: str = ""
