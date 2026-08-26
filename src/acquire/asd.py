"""Read atomic energy levels from the NIST Atomic Spectra Database.

The levels provide evidence for the compact hypotheses in `reactgen.generate`
can only name. That module splits an atom into a metastable ``X_m`` and a
radiating ``X_r`` from the shell it starts in; this one reads the levels and
says which is which, and at what energy, by applying the same selection rule to
measured data::

    Ar I   11.548  2[3/2]*  J=2   forbidden -> metastable
           11.624  2[3/2]*  J=1   allowed   -> resonant
           11.723  2[1/2]*  J=0   forbidden -> metastable
           11.828  2[1/2]*  J=1   allowed   -> resonant

An electric dipole transition to the ground state needs a parity change and
``dJ`` of 0 or 1, never 0 to 0. A level that cannot take one has no route down
and accumulates, which is what makes a metastable matter in a discharge.

The query endpoint is ``energy1.pl``, which returns the levels as delimited
text. ``lines1.pl`` answers about spectral lines instead and does not carry
level energies, which is worth stating because asking the wrong one looks like
the database refusing the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = "https://physics.nist.gov/cgi-bin/ASD/energy1.pl"
USER_AGENT = "reactgen/acquire"
TIMEOUT_S = 40


@dataclass(frozen=True)
class Levels:
    """The two lowest excited levels of one atom, split by whether they radiate."""

    symbol: str
    metastable_eV: float | None = None
    resonant_eV: float | None = None
    lowest_eV: float | None = None
    trapped: tuple[Level, ...] = ()  # every metastable, lowest first
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.lowest_eV is not None


@dataclass(frozen=True)
class Level:
    configuration: str
    term: str
    j: Fraction
    energy_eV: float

    @property
    def odd(self) -> bool:
        return self.term.endswith("*")

    def same_term_as(self, other: Level) -> bool:
        """Spin-orbit siblings, not a separate state.

        Oxygen's ground term splits into 3P2, 3P1 and 3P0 across 0.03 eV. They
        are one chemical species; the first state a discharge can populate
        separately is 1D, an eV higher.
        """

        return (self.configuration, self.term) == (other.configuration, other.term)


def fetch(symbols: list[str]) -> list[Levels]:
    return [_one(symbol) for symbol in symbols]


def _one(symbol: str) -> Levels:
    try:
        text = _request(symbol)
    except Exception as error:  # urllib raises several unrelated types
        return Levels(symbol, error=f"{type(error).__name__}: {str(error)[:60]}")

    levels = _parse(text)
    if not levels:
        return Levels(symbol, error="no levels returned")

    ground = levels[0]
    excited = [item for item in levels[1:] if not item.same_term_as(ground)]
    if not excited:
        return Levels(symbol, error="ground term only")
    # Spin-orbit siblings of the ground term are metastable in the formal sense
    # and chemically the same species, so they are filtered before the search.
    trapped = [item for item in metastable(levels) if not item.same_term_as(ground)]
    return Levels(
        symbol=symbol,
        metastable_eV=trapped[0].energy_eV if trapped else None,
        resonant_eV=_lowest(ground, excited, radiates=True),
        lowest_eV=excited[0].energy_eV,
        trapped=tuple(_distinct(trapped)),
    )


def _request(symbol: str) -> str:
    query = {
        "de": "0",
        "spectrum": f"{symbol} I",  # the neutral atom
        "units": "1",  # eV
        "format": "3",  # delimited text
        "output": "0",
        "page_size": "15",
        "multiplet_ordered": "0",
        "conf_out": "on",
        "term_out": "on",
        "level_out": "on",
        "j_out": "on",
        "temp": "",
        "submit": "Retrieve Data",
    }
    url = f"{ENDPOINT}?{urlencode(query)}"
    if not url.startswith(ENDPOINT):
        raise ValueError(f"refusing a request outside the ASD endpoint: {url}")
    request = Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 - checked above
    with urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https host
        return response.read().decode("utf-8", "replace")


def _parse(text: str) -> list[Level]:
    """Rows of ``configuration, term, J, prefix, level, suffix``, sorted by energy."""

    levels = []
    for line in text.splitlines()[1:]:  # the first line names the columns
        cells = [cell.strip().strip('"') for cell in line.split("\t")]
        if len(cells) < 5:
            continue
        configuration, term, j_text, energy_text = cells[0], cells[1], cells[2], cells[4]
        j, energy = _fraction(j_text), _float(energy_text)
        if j is None or energy is None or not term:
            continue
        levels.append(Level(configuration, term, j, energy))
    return sorted(levels, key=lambda item: item.energy_eV)


def _distinct(levels: list[Level]) -> list[Level]:
    """One entry per term. The J components of a term are one chemical species."""

    seen: set[tuple[str, str]] = set()
    out = []
    for level in levels:
        key = (level.configuration, level.term)
        if key not in seen:
            seen.add(key)
            out.append(level)
    return out


def _lowest(ground: Level, excited: list[Level], radiates: bool) -> float | None:
    for level in excited:
        if _radiates_to(ground, level) is radiates:
            return level.energy_eV
    return None


def _radiates_to(lower: Level, level: Level) -> bool:
    """Whether an electric dipole transition down to ``lower`` is allowed."""

    if lower.odd == level.odd:  # parity must change
        return False
    if abs(level.j - lower.j) > 1:
        return False
    return not (level.j == 0 and lower.j == 0)  # 0 -> 0 is forbidden


def metastable(levels: list[Level]) -> list[Level]:
    """Levels with nowhere to radiate, which is what makes one accumulate.

    Every lower level is checked, not only the ground state. A level high up
    is usually barred from the ground state by parity while being perfectly
    free to drop to something in between, and reading only the ground state
    called three hundred of argon's levels metastable where two are.
    """

    out = []
    for index, level in enumerate(levels[1:], 1):
        if not any(_radiates_to(lower, level) for lower in levels[:index]):
            out.append(level)
    return out


def _fraction(text: str) -> Fraction | None:
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def _float(text: str) -> float | None:
    # Energies carry brackets or a trailing + for interpolated and limit values.
    cleaned = text.strip().strip("[]()").rstrip("+?abcdefx ")
    try:
        return float(cleaned)
    except ValueError:
        return None


PROPERTY = {
    "metastable_eV": "metastable_energy_eV",
    "resonant_eV": "resonant_energy_eV",
    "lowest_eV": "excitation_energy_eV",
}


def records(found: list[Levels], citation: str) -> list[dict]:
    """One property record per level that exists, for `rgen ingest`.

    They are recorded against the *ground state* atom, which is what a proposer
    holds when it decides to invent ``Ar_m``. Writing them against the excited
    species instead would need that species to exist first.
    """

    out = []
    for item in found:
        for field, name in PROPERTY.items():
            value = getattr(item, field)
            if value is not None:
                out.append(
                    {
                        "species": item.symbol,
                        "property": name,
                        "value": round(value, 6),
                        "unit": "eV",
                        "source": {"citation": citation},
                    }
                )
    return out
