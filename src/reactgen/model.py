"""Value types shared by every layer.

Pure data: no file access, no policy, no formatting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

ELECTRON = "e"
THIRD_BODY = "M"

# How a family delivers its numbers to a plasma model. Declaring this per family
# is what stops a cross section and an already-convolved rate being applied to
# the same reaction twice.
RATE_FORM = {
    "electron": "cross_section",
    "electron_ion": "rate_coefficient",
    "ion_neutral": "rate_coefficient",
    "ion_ion": "rate_coefficient",
    "neutral_neutral": "rate_coefficient",
    "three_body": "rate_coefficient",
    "unimolecular": "rate_coefficient",
    "surface": "sticking_coefficient",
}


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


@dataclass(frozen=True)
class Property:
    value: float | None = None
    unit: str | None = None
    source: str | None = None

    @property
    def known(self) -> bool:
        return self.value is not None


@dataclass(frozen=True)
class Thermo:
    """NASA 7-coefficient polynomial, low and high temperature ranges."""

    low: tuple[float, ...]
    high: tuple[float, ...]
    t_min: float
    t_mid: float
    t_max: float
    source: str | None = None

    def coefficients(self, temperature_K: float) -> tuple[float, ...]:
        return self.low if temperature_K < self.t_mid else self.high


@dataclass(frozen=True)
class State:
    """How finely this species resolves an internal state.

    ``resolution`` matters downstream: a lumped level must not be mixed with the
    resolved levels it stands for, or the same excitation is counted twice.
    """

    kind: str = "ground"  # ground | excited | ion
    label: str = ""
    # None where nothing states it. Zero would read as a level at the ground
    # state, which is a different claim from not knowing where the level sits.
    energy_eV: float | None = None
    resolution: str = "state_resolved"  # state_resolved | lumped | effective
    members: tuple[str, ...] = ()  # the resolved levels a lumped state stands for

    @property
    def manifold(self) -> str:
        """Which ladder this state belongs to: vibrational or electronic.

        Two resolutions of one manifold double count; one of each do not. A
        vibrational state declares itself by carrying ``vibrational`` as its
        label, which is what the proposer writes and what a registry adding a
        vibrational level should write too.
        """

        return "vibrational" if self.label == "vibrational" else "electronic"


@dataclass(frozen=True)
class Species:
    id: str
    composition: dict[str, int]
    charge: int
    classes: frozenset[str]
    state: State = State()
    properties: dict[str, Property] = field(default_factory=dict)
    thermo: Thermo | None = None
    status: str = "draft"

    def value(self, name: str) -> float | None:
        prop = self.properties.get(name)
        return prop.value if prop else None

    @property
    def is_neutral(self) -> bool:
        return self.charge == 0 and self.id != ELECTRON


@dataclass(frozen=True)
class Validity:
    """Range over which a dataset is declared applicable."""

    quantity: str  # gas_temperature | electron_temperature | reduced_field
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None

    def covers(self, value: float | None) -> bool | None:
        """True/False when decidable, None when the range or value is unknown."""
        if value is None or (self.minimum is None and self.maximum is None):
            return None
        below = self.minimum is not None and value < self.minimum
        above = self.maximum is not None and value > self.maximum
        return not (below or above)


@dataclass(frozen=True)
class Uncertainty:
    """Declared spread of a dataset, as a multiplicative factor or a fraction."""

    factor: float | None = None  # value lies within x/÷ factor
    relative: float | None = None  # value lies within +/- relative * value
    note: str | None = None

    def bounds(self, value: float) -> tuple[float, float] | None:
        if self.factor:
            return (value / self.factor, value * self.factor)
        if self.relative:
            return (value * (1 - self.relative), value * (1 + self.relative))
        return None


@dataclass(frozen=True)
class Dataset:
    """One numerical candidate for one reaction.

    A reaction may carry several. ``form`` decides how to read the numbers:
    ``constant`` and ``arrhenius`` use ``params``, ``table`` uses ``asset``.
    """

    id: str
    reaction_id: str
    kind: str  # cross_section | rate_coefficient | mobility | sticking_coefficient
    form: str  # constant | arrhenius | table | reference_only
    unit: str | None = None
    params: dict[str, float] = field(default_factory=dict)
    asset: str | None = None
    validity: Validity | None = None
    uncertainty: Uncertainty | None = None
    source: dict[str, str] = field(default_factory=dict)
    status: str = "draft"
    preferred: bool = False

    @property
    def usable(self) -> bool:
        """Whether the dataset carries numbers, not just a citation."""
        if self.form == "reference_only":
            return False
        return bool(self.asset) if self.form == "table" else bool(self.params)


@dataclass
class Reaction:
    id: str
    family: str
    type: str
    reactants: list[Term]
    products: list[Term]
    threshold_eV: float | None = None
    delta_e_eV: float | None = None
    dnt_class: str | None = None
    third_body: str | None = None
    surface: str | None = None
    reverse: str | None = None  # from_equilibrium | explicit | not_applicable
    datasets: list[Dataset] = field(default_factory=list)
    source: dict[str, str] = field(default_factory=dict)
    status: str = "draft"
    depth: int = 0
    precursors: list[str] = field(default_factory=list)

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

    @property
    def signature(self) -> tuple:
        """What makes two reactions the same process, ignoring their ids.

        Counts are summed per species first: a registry writes ``2 e`` where a
        proposal writes ``e + e``, and comparing term lists would call those
        two different reactions and carry both.

        ``type`` is deliberately absent. The same equation under two type
        labels is still one process, and treating the labels as distinguishing
        would let a duplicate through under a different name.
        """

        def side(terms: list[Term]) -> tuple:
            totals: dict[str, float] = {}
            for term in terms:
                totals[term.species] = totals.get(term.species, 0.0) + term.n
            return tuple(sorted(totals.items()))

        return (
            self.family,
            self.third_body,
            self.surface,
            side(self.reactants),
            side(self.products),
        )

    @property
    def rate_form(self) -> str:
        """What a plasma model should consume for this reaction."""
        return RATE_FORM.get(self.family, "rate_coefficient")

    @property
    def delta_moles(self) -> float:
        """Change in gas-phase particle count, used for equilibrium constants."""
        return sum(t.n for t in self.products) - sum(t.n for t in self.reactants)

    def data(self, kind: str) -> list[Dataset]:
        return [item for item in self.datasets if item.kind == kind]

    def best(self, kind: str) -> Dataset | None:
        usable = [item for item in self.data(kind) if item.usable]
        if not usable:
            return None
        return min(usable, key=lambda item: (not item.preferred, item.id))


@dataclass(frozen=True)
class Material:
    """A chamber or wafer surface that consumes gas-phase species."""

    id: str
    name: str
    notes: str = ""


@dataclass
class Network:
    species: dict[str, Species]
    reactions: list[Reaction]
    depth: dict[str, int] = field(default_factory=dict)
    origin: dict[str, list[str]] = field(default_factory=dict)
    truncated: list[str] = field(default_factory=list)

    def by_family(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reaction in self.reactions:
            counts[reaction.family] = counts.get(reaction.family, 0) + 1
        return dict(sorted(counts.items()))


@dataclass(frozen=True)
class Gap:
    """One thing a user must acquire or decide before the output is usable."""

    kind: str
    subject: str
    detail: str
    severity: str = "data"  # blocking | data | info

    def sort_key(self) -> tuple[int, str, str]:
        order = {"blocking": 0, "data": 1, "info": 2}
        return (order.get(self.severity, 3), self.kind, self.subject)
