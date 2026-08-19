"""Identify a species written in someone else's notation.

Every database spells a species differently: ``Ar+``, ``Ar^+``, ``Ar_p``,
``AR 1+``; ``O2(a1Dg)``, ``O2(a1Delta_g)``, ``O2*``. Folding the string cannot
settle these, because ``O2*`` and ``O2(a1Dg)`` differ in what they *mean*, not
in how they are spelled.

So a name is parsed into what it asserts — composition, charge, and a state
label if it names one — and matched structurally. Composition and charge are
decidable. The state label is not: ``1s5`` (Paschen), ``3P2`` (term symbol) and
``4s`` (configuration) all name argon levels and no rule relates them, so those
equivalences live in the registry's ``aliases``.

A name that fits several registered species resolves to ``ambiguous`` with the
candidates listed. It is never silently assigned to one of them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

# Charge written after the formula. Digits *before* the sign are a subscript
# (``SF5-`` is SF5 with charge -1), so a magnitude only counts when a caret or a
# space separates it, or when it follows the sign.
CHARGE = re.compile(
    r"(?:"
    r"\^(?P<cmag>\d*)(?P<csign>[+-])"  # Ar^2+, Ar^+
    r"|\s+(?P<smag>\d*)(?P<ssign>[+-])"  # "Ar 2+", "Ar +"
    r"|(?P<sign>[+-])(?P<tmag>\d*)"  # Ar+, Ar+2, SF5-
    r"|\((?P<paren>[+-])\)"  # Ar(+)
    r"|_(?P<suffix>[pm])"  # Ar_p, SF5_m
    r")$"
)
ELEMENT = re.compile(r"([A-Z][a-z]?)(\d*)")
STATE_IN_PARENS = re.compile(r"\((?P<label>[^)]+)\)$")
ELECTRON_NAMES = {"e", "e-", "e^-", "electron", "elec"}

# Element symbols this domain uses. Anything outside it is not a formula, which
# keeps `Ar(+)` from parsing as an element and lets all-caps names be retried.
# fmt: off
ELEMENTS = frozenset({
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P",
    "S", "Cl", "Ar", "K", "Ca", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Y", "Zr", "Nb", "Mo", "Ru", "Rh", "Pd", "Ag",
    "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Hf", "Ta", "W", "Pt", "Au", "Hg", "Pb", "Bi",
})
# fmt: on


@dataclass(frozen=True)
class Name:
    """What a written name asserts about a species."""

    composition: dict[str, int] = field(default_factory=dict)
    charge: int = 0
    state: str | None = None
    excited: bool = False

    @property
    def key(self) -> tuple[tuple[tuple[str, int], ...], int]:
        return (tuple(sorted(self.composition.items())), self.charge)


@dataclass(frozen=True)
class Match:
    """The outcome of resolving one written name."""

    status: str  # exact | ambiguous | unknown
    species: str | None = None
    candidates: tuple[str, ...] = ()


def parse(text: str) -> Name:
    """Split a written name into composition, charge and state."""

    body = text.strip()
    if body.lower() in ELECTRON_NAMES:
        return Name(composition={}, charge=-1)

    body, charge = _take_charge(body)
    body, state, excited = _take_state(body)
    return Name(composition=_composition(body), charge=charge, state=state, excited=excited)


def normalize_state(label: str | None) -> str | None:
    """Fold a state label to compare spellings of the same written term."""

    if not label:
        return None
    folded = re.sub(r"[_\s\-()]", "", label).lower()
    # Greek letters are written out or abbreviated to their initial.
    for name, initial in (("delta", "d"), ("sigma", "s"), ("pi", "p"), ("gamma", "g")):
        folded = folded.replace(name, initial)
    return folded or None


def _take_charge(text: str) -> tuple[str, int]:
    match = CHARGE.search(text)
    if match is None:
        return (text, 0)
    body = text[: match.start()]
    groups = match.groupdict()

    if groups["suffix"]:
        return (body, 1 if groups["suffix"] == "p" else -1)
    if groups["paren"]:
        return (body, 1 if groups["paren"] == "+" else -1)

    sign = groups["csign"] or groups["ssign"] or groups["sign"]
    magnitude = groups["cmag"] or groups["smag"] or groups["tmag"] or "1"
    return (body, int(magnitude) * (1 if sign == "+" else -1))


def _take_state(text: str) -> tuple[str, str | None, bool]:
    excited = text.endswith("*")
    body = text.rstrip("*").strip()

    match = STATE_IN_PARENS.search(body)
    if match:
        return (body[: match.start()], match.group("label"), True)

    head, separator, tail = body.partition("_")
    if separator and tail and not _composition(tail):
        return (head, tail, True)
    return (body, None, excited)


def _composition(text: str) -> dict[str, int]:
    """Element counts, or empty when the text is not a plain formula.

    All-caps spellings such as Chemkin's ``AR`` are retried title-cased, so they
    resolve without every caller having to know about that convention.
    """

    parsed = _tokenize(text)
    if parsed or not text.isupper():
        return parsed
    return _tokenize(text.title())


def _tokenize(text: str) -> dict[str, int]:
    if not text or not text[0].isupper():
        return {}
    counts: dict[str, int] = {}
    consumed = 0
    for element, digits in ELEMENT.findall(text):
        if element not in ELEMENTS:
            return {}
        counts[element] = counts.get(element, 0) + (int(digits) if digits else 1)
        consumed += len(element) + len(digits)
    return counts if consumed == len(text) else {}


class Index:
    """Resolve written names against the registered species."""

    def __init__(self, species: Mapping[str, object], aliases: Mapping[str, str]) -> None:
        self._aliases = aliases
        self._by_structure: dict[tuple, list[str]] = {}
        self._states: dict[str, str | None] = {}
        for species_id, item in species.items():
            name = Name(
                composition=dict(getattr(item, "composition", {}) or {}),
                charge=int(getattr(item, "charge", 0)),
            )
            self._by_structure.setdefault(name.key, []).append(species_id)
            state = getattr(item, "state", None)
            self._states[species_id] = normalize_state(getattr(state, "label", None))

    def resolve(self, text: str) -> Match:
        if text in self._states:
            return Match("exact", text)
        if (aliased := self._aliases.get(fold(text))) is not None:
            return Match("exact", aliased)

        name = parse(text)
        candidates = sorted(self._by_structure.get(name.key, ()))
        if not candidates:
            return Match("unknown")
        if len(candidates) == 1:
            return Match("exact", candidates[0])
        return self._disambiguate(name, candidates)

    def _disambiguate(self, name: Name, candidates: list[str]) -> Match:
        """Several species share this composition and charge; the state decides."""

        wanted = normalize_state(name.state)
        if wanted is not None:
            hit = [item for item in candidates if self._states.get(item) == wanted]
            if len(hit) == 1:
                return Match("exact", hit[0])
        if not name.excited:
            ground = [item for item in candidates if not self._states.get(item)]
            if len(ground) == 1:
                return Match("exact", ground[0])
        return Match("ambiguous", None, tuple(candidates))


def fold(text: str) -> str:
    """Strip the punctuation that separates one spelling from another."""

    return re.sub(r"[_\s\-()]", "", text).lower()
