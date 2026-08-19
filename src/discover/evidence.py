"""Ask the reachable sources whether a candidate is real.

One function per source that can answer. Adding a database means adding a
function here and an entry in the catalog; nothing else changes.

No source is asked for a rate. The question is only whether the species and the
channel are known to exist, because a candidate's problem is existence, not
magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass

from acquire import pubchem
from discover.fragments import Candidate


@dataclass(frozen=True)
class Evidence:
    source: str
    verdict: str  # supported | not_found | unavailable
    note: str = ""


def gather(candidates: list[Candidate], species: dict[str, dict], reachable: set[str]) -> dict:
    """Evidence per candidate id, keyed by the candidate's equation."""

    identity = _pubchem(species) if "pubchem" in reachable else {}
    found = {}
    for candidate in candidates:
        marks = []
        for name in _neutral_terms(candidate, species):
            marks.append(identity.get(name, Evidence("pubchem", "unavailable")))
        found[candidate.equation] = [_summarize(marks)]
    return found


CONFIDENCE = ("supported", "not_found", "unavailable")


def _summarize(marks: list[Evidence]) -> dict:
    """A candidate is only as confirmed as its least confirmed term."""

    if not marks:
        return {"source": "none", "verdict": "unavailable", "note": "no reachable source"}
    weakest = max(marks, key=lambda item: CONFIDENCE.index(item.verdict))
    return {"source": weakest.source, "verdict": weakest.verdict, "note": weakest.note}


def _neutral_terms(candidate: Candidate, species: dict[str, dict]) -> list[str]:
    return [
        name
        for name in (*candidate.reactants, *candidate.products)
        if name != "e" and species.get(name, {}).get("charge") == 0
    ]


def _pubchem(species: dict[str, dict]) -> dict[str, Evidence]:
    """Confirm each neutral exists as a compound with the composition claimed.

    A radical or an excited state has no PubChem entry by design. That is the
    source declining to answer, not evidence against the species, so it reads
    ``unavailable`` rather than ``not_found``.
    """

    names = sorted(name for name, item in species.items() if item.get("charge") == 0)
    out = {}
    for name, identity in zip(names, pubchem.fetch(names), strict=True):
        verdict = pubchem.compare(identity, species[name].get("composition"))
        out[name] = Evidence("pubchem", *_read(verdict, identity.formula))
    return out


def _read(verdict: str, formula: str | None) -> tuple[str, str]:
    """A name collision is not the absence of the species, and must say so.

    Compound databases index stable neutrals. Asked for a radical they answer
    confidently about something else — ``CF3`` returns californium, ``SF5`` an
    unrelated organic — so the collided formula is recorded rather than reading
    as evidence against the species.
    """

    if verdict in {"agrees", "fills_gap"}:
        return ("supported", "")
    if verdict == "wrong_compound":
        return ("unavailable", f"the name collides with {formula} in this database")
    return ("unavailable", "no entry; compound databases do not index radicals or ions")
