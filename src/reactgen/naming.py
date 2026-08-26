"""Parse external species spellings into composition, charge and state claims."""

from __future__ import annotations

import re
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
        count = int(digits) if digits else 1
        if count < 1:
            return {}
        counts[element] = counts.get(element, 0) + count
        consumed += len(element) + len(digits)
    return counts if consumed == len(text) else {}
