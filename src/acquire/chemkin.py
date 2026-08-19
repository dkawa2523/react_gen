"""Parse a CHEMKIN thermodynamic file into NASA 7-coefficient records.

The format Burcat, Cantera and every CHEMKIN mechanism share: four fixed-column
lines per species, holding the polynomial twice — once for the low temperature
range and once for the high one.

::

    CF3               J 6/77 C  1.F  3.   0.G   300.000  5000.000 1000.00      1
     0.05563634E+02 0.02214913E-01 ...                                         2
     ...                                                                       3
     ...                                                                       4

The download is manual — Burcat's host rejects programmatic requests, measured
2026-08-16 — but the file itself is stable, and that is what stopped these
species being usable rather than the fetching.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

WIDTH = 15  # each coefficient occupies fifteen columns
ELEMENT_FIELD = slice(24, 44)
TEMPERATURE_FIELD = slice(45, 73)


@dataclass(frozen=True)
class Entry:
    """One species and its two-range polynomial, as the registry records them."""

    name: str
    composition: dict[str, int]
    low: tuple[float, ...]
    high: tuple[float, ...]
    t_min: float
    t_mid: float
    t_max: float


def parse(path: str | Path) -> list[Entry]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    blocks = _blocks(lines)
    return [entry for block in blocks if (entry := _entry(block)) is not None]


def _blocks(lines: list[str]) -> list[list[str]]:
    """Group the file into the four-line records the format is written in.

    The line number sits in column 80 by the standard, but real files pad
    differently, so the last non-space character is what is read.
    """

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.rstrip()
        marker = stripped[-1:] if stripped else ""
        if marker == "1":
            current = [line]
        elif current and marker in {"2", "3", "4"}:
            current.append(line)
            if marker == "4":
                blocks.append(current)
                current = []
    return blocks


def _entry(block: list[str]) -> Entry | None:
    if len(block) != 4:
        return None
    head = block[0]
    composition = _composition(head[ELEMENT_FIELD])
    temperatures = _floats(head[TEMPERATURE_FIELD], 3)
    coefficients = [value for line in block[1:] for value in _floats(line[:75], 0)]
    if not composition or len(temperatures) != 3 or len(coefficients) < 14:
        return None

    low, high, mid = temperatures
    # The file writes the high range first, then the low one.
    return Entry(
        name=head[:18].strip(),
        composition=composition,
        low=tuple(coefficients[7:14]),
        high=tuple(coefficients[0:7]),
        t_min=low,
        t_mid=mid,
        t_max=high,
    )


def _composition(field: str) -> dict[str, int]:
    """Four ``symbol + count`` pairs of five columns each."""

    counts: dict[str, int] = {}
    for start in range(0, 20, 5):
        chunk = field[start : start + 5]
        symbol = chunk[:2].strip().title()
        number = chunk[2:].strip()
        if not symbol or not number:
            continue
        try:
            value = int(float(number))
        except ValueError:
            continue
        if value:
            counts[symbol] = counts.get(symbol, 0) + value
    return counts


def _floats(text: str, expected: int) -> list[float]:
    """Fixed-width numbers, read a line at a time.

    Each coefficient line holds five fields of fifteen columns. Reading across
    a line break would split one number in half, so callers pass one line.
    """

    values = []
    for start in range(0, len(text) - WIDTH + 1, WIDTH):
        chunk = text[start : start + WIDTH].strip()
        if not chunk:
            continue
        try:
            values.append(float(chunk))
        except ValueError:
            continue
    if expected and len(values) != expected:
        return _loose(text)[:expected]
    return values


def _loose(text: str) -> list[float]:
    out = []
    for token in text.split():
        try:
            out.append(float(token))
        except ValueError:
            continue
    return out


def records(entries: list[Entry], citation: str) -> list[dict]:
    """Species records carrying the polynomial, for `rgen ingest`."""

    return [
        {
            "species": entry.name,
            "property": "thermo",
            "value": {
                "low": list(entry.low),
                "high": list(entry.high),
                "t_min": entry.t_min,
                "t_mid": entry.t_mid,
                "t_max": entry.t_max,
            },
            "composition": entry.composition,
            "source": {"citation": citation},
        }
        for entry in entries
    ]
