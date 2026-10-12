"""Read neutral-atom levels and qualified threshold summaries from NIST ASD.

ASD marks semi-empirical energies with square brackets and calculated energies
with parentheses. Question marks/daggers denote doubts; ``+x`` denotes an
unknown connection between level systems. Preserve these declarations rather
than interpreting every number as a definite absolute threshold. See:
https://physics.nist.gov/PhysRefData/ASD/Html/levelshelp.html

The E1 summaries check parity and J constraints over returned levels. They do
not establish transition probabilities, lifetimes, collisions or populations.
Ground-term fine structure is excluded only from the term-level summaries.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = "https://physics.nist.gov/cgi-bin/ASD/energy1.pl"
USER_AGENT = "reactgen/acquire"
TIMEOUT_S = 40
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass(frozen=True)
class Levels:
    """Summaries plus original levels; absent summaries remain unresolved."""

    symbol: str
    metastable_eV: float | None = None
    resonant_eV: float | None = None
    lowest_eV: float | None = None
    trapped: tuple[Level, ...] = ()
    error: str | None = None
    levels: tuple[Level, ...] = ()
    raw_response: str = ""
    query_url: str = ""
    notes: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.lowest_eV is not None


@dataclass(frozen=True)
class Level:
    configuration: str
    term: str
    j: Fraction | None
    energy_eV: float | None
    uncertainty_eV: float | None = None
    energy_origin: str = "unknown"
    withheld_reason: str | None = None
    source_row: int | None = None
    source_record: dict[str, str] = field(default_factory=dict)

    @property
    def odd(self) -> bool:
        return self.term.endswith("*")

    def same_term_as(self, other: Level) -> bool:
        return (self.configuration, self.term) == (other.configuration, other.term)


def fetch(symbols: list[str]) -> list[Levels]:
    return [_one(symbol) for symbol in symbols]


def _one(symbol: str) -> Levels:
    url = _query_url(symbol)
    try:
        text = _request(symbol)
    except (HTTPError, URLError, OSError, UnicodeError) as error:
        return Levels(symbol, error=f"{type(error).__name__}: {str(error)[:120]}", query_url=url)
    try:
        levels = _parse(text)
    except (ValueError, csv.Error) as error:
        return Levels(symbol, error=str(error), raw_response=text, query_url=url)
    return _summaries(symbol, levels, text, url)


def _summaries(symbol: str, levels: list[Level], text: str, url: str) -> Levels:
    original = Levels(symbol, levels=tuple(levels), raw_response=text, query_url=url)
    represented = [level for level in levels if level.term.lower() != "limit"]
    reasons = [
        f"row {level.source_row}: {level.withheld_reason}"
        for level in represented
        if level.withheld_reason
    ]
    if reasons:
        # Removing an uncertain row does not prove the next row is the minimum.
        return replace(original, error="absolute threshold summary withheld: " + "; ".join(reasons))
    if not represented or represented[0].energy_eV != 0.0:
        return replace(original, error="no definite zero-energy ground level returned")
    ground = represented[0]
    excited = [level for level in represented[1:] if not level.same_term_as(ground)]
    if not excited:
        return replace(original, error="ground term only")
    if any(level.j is None for level in represented):
        return replace(
            original,
            lowest_eV=excited[0].energy_eV,
            notes=("E1 parity/J summaries withheld: missing or unresolved J",),
        )
    trapped = [level for level in metastable(represented) if not level.same_term_as(ground)]
    return replace(
        original,
        metastable_eV=trapped[0].energy_eV if trapped else None,
        resonant_eV=_lowest(ground, excited, allowed=True),
        lowest_eV=excited[0].energy_eV,
        trapped=tuple(_distinct(trapped)),
    )


def _query_url(symbol: str) -> str:
    query = {
        "de": "0",
        "spectrum": f"{symbol} I",
        "units": "1",
        "format": "3",
        "output": "0",
        "page_size": "15",
        "multiplet_ordered": "0",
        "conf_out": "on",
        "term_out": "on",
        "level_out": "on",
        "unc_out": "1",
        "j_out": "on",
        "biblio": "on",
        "temp": "",
        "submit": "Retrieve Data",
    }
    return f"{ENDPOINT}?{urlencode(query)}"


def _request(symbol: str) -> str:
    request = Request(_query_url(symbol), headers={"User-Agent": USER_AGENT})  # noqa: S310 - fixed HTTPS endpoint
    with urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed HTTPS endpoint
        return response.read().decode("utf-8")


def _cell(value: str) -> str:
    """Read ASD's optional spreadsheet text wrapper without evaluating it."""
    value = value.strip()
    if value.startswith('="') and value.endswith('"'):
        return value[2:-1]
    return value


def _columns(header: list[str]) -> dict[str, int]:
    names = [re.sub(r"\s+", "", _cell(name).lower()) for name in header]
    if len(set(names)) != len(names):
        raise ValueError("unsupported ASD header: duplicate columns")
    required = {name: names.index(name) for name in ("configuration", "term", "j") if name in names}
    for quantity in ("level", "uncertainty"):
        for index, name in enumerate(names):
            if name == f"{quantity}(ev)":
                required[quantity] = index
            elif quantity == "uncertainty" and name.startswith("uncertainty"):
                raise ValueError("unsupported ASD uncertainty header: eV units are required")
    if {"configuration", "term", "j", "level"} - required.keys():
        raise ValueError(
            "unsupported ASD header: configuration, term, J and Level (eV) are required"
        )
    required.update({name: names.index(name) for name in ("prefix", "suffix") if name in names})
    return required


def _parse(text: str) -> list[Level]:
    """Parse named eV columns and retain every data row and source annotation."""
    rows = csv.reader(io.StringIO(text), delimiter="\t")
    header = next(rows, [])
    columns = _columns(header)
    found = []
    configuration = term = ""
    for row_number, row in enumerate(rows, 2):
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) == 1 and row[0].startswith("Bibliographic References"):
            break  # Reference text remains in the complete response.
        if len(row) != len(header):
            raise ValueError(
                f"unsupported ASD row {row_number}: expected {len(header)} columns, "
                f"found {len(row)}"
            )
        cells = [_cell(cell) for cell in row]
        if cells[columns["configuration"]] not in ("", configuration):
            term = ""  # A new configuration cannot inherit an unrelated term.
        configuration = cells[columns["configuration"]] or configuration
        term = cells[columns["term"]] or term
        found.append(_level(configuration, term, cells, columns, header, row_number))
    return sorted(
        found, key=lambda level: float("inf") if level.energy_eV is None else level.energy_eV
    )


def _level(
    configuration: str,
    term: str,
    cells: list[str],
    columns: dict[str, int],
    header: list[str],
    row_number: int,
) -> Level:
    energy_text = "".join(
        cells[columns[name]] for name in ("prefix", "level", "suffix") if name in columns
    )
    energy, origin, reason = _energy(energy_text)
    if not configuration or not term or "?" in configuration + term:
        reason = reason or "missing or doubtful configuration/term assignment"
    uncertainty = None
    if "uncertainty" in columns:
        written = cells[columns["uncertainty"]]
        if written:
            uncertainty = _float(written)
            if uncertainty is None or uncertainty < 0:
                reason = reason or f"unsupported uncertainty declaration: {written}"
    return Level(
        configuration,
        term,
        _fraction(cells[columns["j"]]),
        energy,
        uncertainty,
        origin,
        reason,
        row_number,
        dict(zip(header, cells, strict=True)),
    )


def _energy(text: str) -> tuple[float | None, str, str | None]:
    """Keep notation; uncertain offsets are not definite absolute values."""
    text = re.sub(r"\s+", "", text)
    origin = "unknown"
    if text.startswith(("[", "(")):
        closing = "]" if text[0] == "[" else ")"
        end = text.find(closing)
        if end == -1:
            return None, origin, f"unsupported level declaration: {text}"
        origin = "semi_empirical" if text[0] == "[" else "calculated"
        text = text[1:end] + text[end + 1 :]
    match = NUMBER.match(text)
    if match is None:
        return None, origin, f"missing or unsupported level declaration: {text}"
    energy = _float(match[0])
    if energy is None or energy < 0:
        return None, origin, f"invalid energy declaration: {text}"
    return energy, origin, _annotation_reason(text[match.end() :])


def _annotation_reason(suffix: str) -> str | None:
    if re.search(r"\+[a-z]", suffix):
        return "unknown absolute energy offset"
    if "?" in suffix or "\u2020" in suffix:
        return "doubtful level energy or assignment"
    if suffix == "a":
        # Broadening is not an unknown absolute offset. The suffix remains in
        # the source row; an E1-only summary does not establish its lifetime.
        return None
    return f"unsupported level annotation: {suffix}" if suffix else None


def _distinct(levels: list[Level]) -> list[Level]:
    """One summary per term; original J components remain in source records."""
    seen: set[tuple[str, str]] = set()
    out = []
    for level in levels:
        key = (level.configuration, level.term)
        if key not in seen:
            seen.add(key)
            out.append(level)
    return out


def _lowest(ground: Level, excited: list[Level], allowed: bool) -> float | None:
    return next(
        (level.energy_eV for level in excited if _e1_parity_j(ground, level) is allowed), None
    )


def _e1_parity_j(lower: Level, level: Level) -> bool:
    """Satisfies parity/J E1 constraints; a matrix element is not established."""
    if lower.j is None or level.j is None or lower.odd == level.odd:
        return False
    return abs(level.j - lower.j) <= 1 and not (level.j == 0 and lower.j == 0)


def metastable(levels: list[Level]) -> list[Level]:
    """No lower returned level satisfies parity/J E1 constraints.

    This alone does not establish lifetime/trapping. The caller must first
    establish absolute energies and unambiguous J values.
    """
    if any(level.withheld_reason or level.j is None or level.energy_eV is None for level in levels):
        raise ValueError("E1 classification requires definite absolute levels and J values")
    return [
        level
        for index, level in enumerate(levels[1:], 1)
        if not any(_e1_parity_j(lower, level) for lower in levels[:index])
    ]


def _fraction(text: str) -> Fraction | None:
    try:
        value = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value >= 0 else None


def _float(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


PROPERTY = {
    "metastable_eV": "metastable_energy_eV",
    "resonant_eV": "resonant_energy_eV",
    "lowest_eV": "lowest_excitation_energy_eV",
}


def _source_level(level: Level) -> dict:
    return {
        "row": level.source_row,
        "declared": level.source_record,
        "configuration": level.configuration,
        "term": level.term,
        "J": str(level.j) if level.j is not None else None,
        "declared_numeric_component_eV": level.energy_eV,
        "energy_origin": level.energy_origin,
        "uncertainty": {
            "absolute": level.uncertainty_eV,
            "unit": "eV",
            "interpretation": "one standard deviation when declared by ASD",
        },
        "withheld_reason": level.withheld_reason,
    }


def records(found: list[Levels], citation: str) -> list[dict]:
    """Ground-atom summaries plus intact acquisition evidence.

    Original levels are not assigned to invented excited-state identities or
    promoted to existence evidence. A withheld summary has no numeric value.
    """
    out = []
    for item in found:
        records_for_atom = [
            {
                "species": item.symbol,
                "property": name,
                "value": value,
                "unit": "eV",
                "phase": "gas",
                "status": "imported",
                "qualifier": (
                    "returned-level term summary; "
                    "E1 parity/J constraints do not establish a lifetime"
                ),
                "source": {"citation": citation, "query_url": item.query_url},
            }
            for field, name in PROPERTY.items()
            if (value := getattr(item, field)) is not None
        ]
        if not records_for_atom and item.raw_response:
            records_for_atom.append(
                {
                    "species": item.symbol,
                    "property": "lowest_excitation_energy_eV",
                    "value": None,
                    "unit": "eV",
                    "phase": "gas",
                    "status": "imported",
                    "qualifier": item.error or "absolute threshold is unresolved",
                    "source": {"citation": citation, "query_url": item.query_url},
                }
            )
        if records_for_atom:
            records_for_atom[0]["source_levels"] = [_source_level(level) for level in item.levels]
            records_for_atom[0]["source_response"] = {
                "text": item.raw_response,
                "sha256": hashlib.sha256(item.raw_response.encode("utf-8")).hexdigest(),
            }
            records_for_atom[0]["review_notes"] = list(item.notes)
        out.extend(records_for_atom)
    return out
