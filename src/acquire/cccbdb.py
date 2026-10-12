"""Read measured neutral-ground polarizabilities from a CCCBDB list page.

Preserve the listed state, identity and reference. A composition match narrows
the lookup but does not resolve competing structures. No calculated per-species
values or excited/ionic substitutions are fetched implicitly.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from reactgen.chemistry import parse_state_id

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
    electronic_state: str = ""
    point_group: str = ""


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
                electronic_state=cells[2],
                point_group=cells[3],
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


def records(
    found: list[Listed],
    wanted: dict[tuple, str],
    citation: str,
    source_species: dict[tuple, str] | None = None,
) -> list[dict]:
    """Property records for `rgen ingest`, keyed by composition.

    `wanted` maps a composition to the id to record it under, so the caller
    decides what may take a value. Charge and excitation require separate
    measurements. Multiple structures or states require an explicit source
    species name; composition alone does not choose one.
    """

    out = []
    identities: dict[tuple, set[tuple[str, str, str]]] = {}
    for item in found:
        if (key := composition(item.formula)) is not None:
            identities.setdefault(key, set()).add(
                (item.name, item.electronic_state, item.point_group)
            )
    for item in found:
        key = composition(item.formula)
        if key is None:
            continue
        species_id = wanted.get(key)
        if species_id is None:
            continue
        identity = (source_species or {}).get(key)
        if identity and item.name != identity:
            continue
        if not identity and len(identities[key]) > 1:
            continue
        state = parse_state_id(species_id)
        if state is None or state.charge or state.state.kind != "ground" or state.phase != "gas":
            continue
        out.append(
            {
                "species": species_id,
                "property": "polarizability_A3",
                "value": item.polarizability_A3,
                "unit": "A3",
                "phase": "gas",
                "source_species": item.name,
                "structure": identity or state.structure,
                "electronic_state": item.electronic_state,
                "source": {
                    "citation": f"{citation}; {item.name} listed as {item.formula}"
                    + (f", {item.reference}" if item.reference else "")
                },
            }
        )
    return out
