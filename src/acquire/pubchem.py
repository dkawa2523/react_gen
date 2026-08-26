"""Fetch species identity from the PubChem PUG REST API.

Identity is what makes an imported reaction findable: a foreign file writes
``silane`` or ``H4Si`` where the registry says ``SiH4``, and only a shared
identifier connects them. This fetches formula, mass, InChIKey and synonyms so
those spellings resolve.

It never returns reaction channels, and PubChem is not evidence that a reaction
exists. Radicals, ions and excited states have no PubChem entry by design and
are reported as unresolved rather than guessed at.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
PROPERTIES = "MolecularFormula,MolecularWeight,InChIKey,CanonicalSMILES"
USER_AGENT = "reactgen-acquire/1.0"
# PubChem asks for no more than five requests per second.
THROTTLE_S = 0.25
TIMEOUT_S = 30


@dataclass
class Identity:
    species: str
    cid: int | None = None
    formula: str | None = None
    mass_amu: float | None = None
    inchikey: str | None = None
    smiles: str | None = None
    synonyms: list[str] = field(default_factory=list)
    matches: int = 0
    error: str | None = None

    @property
    def resolved(self) -> bool:
        return self.cid is not None


def fetch(species: list[str], throttle_s: float = THROTTLE_S) -> list[Identity]:
    """One identity per species, in the order given."""

    results = []
    for index, name in enumerate(species):
        if index:
            time.sleep(throttle_s)
        results.append(_one(name))
    return results


def _one(name: str) -> Identity:
    payload = _get(f"{BASE}/name/{quote(name)}/property/{PROPERTIES}/JSON")
    if payload is None:
        payload = _get(f"{BASE}/formula/{quote(name)}/property/{PROPERTIES}/JSON")
    if payload is None:
        return Identity(species=name, error="no PubChem entry")

    records = (payload.get("PropertyTable") or {}).get("Properties") or []
    if len(records) != 1:
        return Identity(
            species=name,
            matches=len(records),
            error=f"ambiguous PubChem identity: {len(records)} matches",
        )
    first = records[0]
    return Identity(
        species=name,
        cid=first.get("CID"),
        formula=first.get("MolecularFormula"),
        mass_amu=_number(first.get("MolecularWeight")),
        inchikey=first.get("InChIKey"),
        smiles=first.get("CanonicalSMILES"),
        synonyms=_synonyms(first.get("CID")),
        matches=1,
    )


def _synonyms(cid: int | None, limit: int = 6) -> list[str]:
    if cid is None:
        return []
    payload = _get(f"{BASE}/cid/{cid}/synonyms/JSON")
    if payload is None:
        return []
    entries = (payload.get("InformationList") or {}).get("Information") or [{}]
    return [str(item) for item in (entries[0].get("Synonym") or [])[:limit]]


def _get(url: str) -> dict | None:
    if not url.startswith(BASE):
        raise ValueError(f"refusing a request outside the PubChem API: {url}")
    request = Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - checked above
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https host
            return json.loads(response.read())
    except (HTTPError, URLError, OSError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")
# PubChem rounds molecular weight to a few significant figures.
MASS_TOLERANCE = 5e-3


def parse_formula(formula: str | None) -> dict[str, int]:
    """``"C4F8"`` into ``{"C": 4, "F": 8}``."""

    if not formula:
        return {}
    return {
        element: int(count) if count else 1
        for element, count in FORMULA_TOKEN.findall(formula)
        if element
    }


def compare(
    identity: Identity,
    composition: dict[str, int] | None = None,
    registered_mass: float | None = None,
) -> str:
    """Whether the fetched entry is the compound the registry meant.

    Composition is checked before mass, because a name lookup can silently
    return a different compound: PubChem reads ``CO`` as cobalt, whose mass
    would otherwise just look like a disagreement.
    """

    if not identity.resolved:
        return "unresolved"
    if composition and parse_formula(identity.formula) != composition:
        return "wrong_compound"
    if registered_mass is None:
        return "fills_gap"
    if identity.mass_amu is None:
        return "no_mass"
    return (
        "agrees"
        if abs(identity.mass_amu - registered_mass) / registered_mass < MASS_TOLERANCE
        else "differs"
    )
