"""Experimental polarizability from the NIST CCCBDB list page.

CCCBDB is form-driven almost everywhere -- ask for one species, get one answer
-- which is why it was written off here as a manual export. Its *list* pages
are not: `pollistx.asp` is a plain GET returning every experimental
polarizability it holds, 261 species with a literature reference against each.
Nothing needs typing in.

This is the only source of molecular polarizability that exists for this
project. `chemicals` tabulates none, `cantera`'s transport blocks reach nine
species, and the Lorentz-Lorenz route needs a refractive index `chemicals` has
for three of the fifty-seven neutrals here. `mendeleev` answers for atoms and
stops there.

What it does not solve is the gap that matters. The list is stable molecules:
CF4, SF6, SO2, F2. The radicals a discharge is made of -- CF, CF2, CF3, SF,
SF2, SF4, SO, SOF2, SOF4 -- are absent from it, and from every other
compilation. CCCBDB has *calculated* polarizabilities for some of them, but
only behind a per-species form and only as a method-and-basis-set choice, so
they are not read here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

LIST_URL = "https://cccbdb.nist.gov/pollistx.asp"
# formula, name, electronic state, point group, value, reference
COLUMNS = 5
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
TAG = re.compile(r"<.*?>", re.S)
NUMBER = re.compile(r"-?\d+\.?\d*")


@dataclass(frozen=True)
class Listed:
    """One species as CCCBDB states it, in cubic angstrom."""

    formula: str
    name: str
    polarizability_A3: float
    reference: str = ""


def parse(body: str) -> list[Listed]:
    """The data rows of a CCCBDB list page, ignoring its navigation.

    The page wraps its menu in tables too, so rows are recognised by shape --
    six cells with a bare number in the fifth -- rather than by position. A
    layout change drops rows rather than importing the navigation as chemistry.
    """

    found = []
    for row in ROW.findall(body):
        cells = [TAG.sub("", cell).replace("&nbsp;", " ").strip() for cell in CELL.findall(row)]
        if len(cells) <= COLUMNS or not NUMBER.fullmatch(cells[COLUMNS - 1]):
            continue
        found.append(
            Listed(
                formula=cells[0],
                name=cells[1],
                polarizability_A3=float(cells[COLUMNS - 1]),
                reference=cells[COLUMNS] if len(cells) > COLUMNS else "",
            )
        )
    return found


def fetch(offline: str | None = None) -> tuple[list[Listed], str | None]:
    """The list, from the network or from a saved copy of the same page."""

    if offline is not None:
        return parse(offline), None
    from acquire.download import fetch as retrieve

    got = retrieve(LIST_URL, expect="html")
    if not got.ok or got.body is None:
        return [], got.error or "no body"
    return parse(got.body.decode("utf-8", "replace")), None


FORMULA = re.compile(r"([A-Z][a-z]?)(\d*)")


def composition(formula: str) -> tuple[tuple[str, int], ...] | None:
    """A CCCBDB formula as element counts, or None if it is not one.

    Matching on the written formula misses more than it catches: CCCBDB spells
    thionyl fluoride `F2SO` and this registry spells it `SOF2`, so a string
    comparison reports a species as unlisted while its value sits in the table.
    Atom counts are the same in either spelling.

    Anything with a charge, a phase or a structural marker is refused rather
    than guessed at -- the list is neutral ground states, and a row this cannot
    read is a row to leave alone.
    """

    if not formula or not formula[0].isupper() or set(formula) & set("+-()[]. "):
        return None
    counts: Counter[str] = Counter()
    consumed = 0
    for element, digits in FORMULA.findall(formula):
        counts[element] += int(digits) if digits else 1
        consumed += len(element) + len(digits)
    if consumed != len(formula):
        return None
    return tuple(sorted(counts.items()))


def records(found: list[Listed], wanted: dict[tuple, str], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, keyed by composition.

    `wanted` maps a composition to the id to record it under, so the caller
    decides what may take a value. Only neutral ground states belong in it: an
    ion is smaller or larger than its neutral by tens of percent, and an
    excited state is filled by `rgen derive` instead.
    """

    out = []
    for item in found:
        key = composition(item.formula)
        species_id = wanted.get(key) if key else None
        if species_id is None:
            continue
        out.append(
            {
                "species": species_id,
                "property": "polarizability_A3",
                "value": item.polarizability_A3,
                "unit": "A3",
                "source": {
                    "citation": f"{citation}; {item.name} listed as {item.formula}"
                    + (f", {item.reference}" if item.reference else "")
                },
            }
        )
    return out
