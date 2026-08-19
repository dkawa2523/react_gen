"""Which reaction equations a source lists, ignoring every number it carries.

Whether a reaction exists and what its coefficient is are separate questions
with separate answers. A UMIST row, an LXCat PROCESS block and a mechanism table
each *state a reaction*; reading only the equation settles existence, and the
temperature range or cross section beside it is a different matter entirely.

So this reads snapshots for their equations alone and answers one question:
is this candidate listed anywhere, and by whom. Species databases cannot answer
it — they index compounds, not reactions.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from reactgen import naming
from reactgen.model import THIRD_BODY, Term
from reactgen.registry import Registry

Side = tuple[tuple[str, int], ...]
Equation = tuple[Side, Side]


@dataclass(frozen=True)
class Listing:
    """One reaction a source states, with no claim about its magnitude."""

    equation: Equation
    source: str
    written: str


class Index:
    """Every equation the given snapshots list, matched structurally."""

    def __init__(self, listings: list[Listing]) -> None:
        self._by_equation: dict[Equation, list[Listing]] = {}
        for item in listings:
            self._by_equation.setdefault(item.equation, []).append(item)

    def __len__(self) -> int:
        return len(self._by_equation)

    @property
    def sources(self) -> dict[str, int]:
        return dict(Counter(item.source for group in self._by_equation.values() for item in group))

    def lists(self, written: str) -> list[Listing]:
        """The listings that state this reaction, whatever notation it uses."""

        return self._by_equation.get(parse(written), [])


def load(paths: list[Path], registry: Registry | None = None) -> Index:
    """Every equation the snapshots list, plus the registry's own reactions.

    The registry is the strongest listing there is: each reaction in it was
    read from a mechanism paper and reviewed. A candidate that matches one is
    not new work at all.
    """

    listings = _registered(registry) if registry else []
    for path in paths:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        source = (document.get("source") or {}).get("source_type") or path.stem
        for record in document.get("records") or []:
            written = record.get("reaction")
            if written:
                listings.append(Listing(parse(str(written)), source, str(written)))
    return Index(listings)


def _registered(registry: Registry) -> list[Listing]:
    return [
        Listing(
            (_terms(reaction.reactants), _terms(reaction.products)),
            "registry",
            reaction.equation,
        )
        for channels in registry.channels.values()
        for reaction in channels
    ]


def _terms(terms: list[Term]) -> Side:
    counts: Counter[str] = Counter()
    for term in terms:
        counts[_key(term.species)] += int(term.n)
    return tuple(sorted(counts.items()))


def parse(written: str) -> Equation:
    """A written equation as sorted reactant and product multisets.

    Names are folded through `reactgen.naming`, so a source's own notation —
    ``E``, ``Ar^+``, ``O2(a1Dg)`` — matches the candidate's.
    """

    left, _, right = written.partition("->")
    return (_side(left), _side(right))


def _key(name: str) -> str:
    """A species as its structure, so `Ar^+` and `Ar+` become one key.

    Folding the written name is not enough: the caret survives the fold and
    would split one species into two.
    """

    parsed = naming.parse(name)
    if not parsed.composition and parsed.charge != -1:
        return naming.fold(name)
    formula = "".join(f"{e}{n}" for e, n in sorted(parsed.composition.items()))
    return f"{formula}|{parsed.charge}|{naming.normalize_state(parsed.state) or ''}"


def _side(text: str) -> Side:
    counts: Counter[str] = Counter()
    for piece in text.split(" + "):
        term = piece.strip()
        if not term or term == THIRD_BODY:
            continue
        count, _, name = term.rpartition(" ")
        counts[_key(name)] += int(float(count)) if count.strip() else 1
    return tuple(sorted(counts.items()))
