"""Parse a UMIST RATE release into snapshot records.

Downloading is explicit and separate. RATE12 and RATE22 have different fit
layouts: RATE22 adds a notes field. A complete row is validated before any of
its fits are returned; an unsupported or malformed row is never partly used::

    index:type:R1:R2:P1:P2:P3:P4:NE:[alpha:beta:gamma:Tmin:Tmax:ST:ACC:REF]

RATE22 appends NOTE to each bracket. See the release descriptions:
https://www.aanda.org/articles/aa/pdf/2013/02/aa20465-12.pdf
https://umistdatabase.uk/files/UDfA2024.pdf

The coefficient is ``k = alpha (T/300)^beta exp(-gamma/T)`` in cm3/s, which is
converted to SI and to the eV activation energy the registry records.

UMIST is astrochemistry: the equations transfer to plasma work, the rates
usually do not. Every record therefore carries its declared temperature range,
so `rgen analyze` flags it as out of range at a plasma gas temperature instead
of using it silently.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

CM3_PER_M3 = 1e-6
KELVIN_PER_EV = 11604.518
HEAD_FIELDS = 9
FIT_FIELDS = {"RATE12": 8, "RATE22": 9}


@dataclass(frozen=True)
class Rate:
    """One reaction and its Arrhenius coefficient, in SI."""

    kind: str
    reactants: tuple[str, ...]
    products: tuple[str, ...]
    a_si: float
    beta: float
    activation_eV: float
    t_min: float | None
    t_max: float | None
    source_id: str = ""
    reference: str = ""
    source_type: str = ""
    accuracy: str = ""
    note: str = ""
    format_version: str = ""
    reaction_id: str = ""
    raw_row: str = ""

    @property
    def equation(self) -> str:
        return f"{' + '.join(self.reactants)} -> {' + '.join(self.products)}"

    @property
    def order(self) -> int:
        return len(self.reactants)


def parse(path: str | Path, version: str | None = None) -> list[Rate]:
    """Read all declared fits, with an explicit version or unambiguous layout.

    Auto detection describes the file format, not scientific provenance. It
    uses the whole file and refuses ambiguous layouts rather than guessing
    from a filename. Original rows, method, accuracy and notes remain attached.
    """
    rows = _read_rows(Path(path))
    if version is not None and version not in FIT_FIELDS:
        raise ValueError(f"unsupported UMIST format version: {version}")
    if not rows:
        return []
    if version is None:
        choices = set(FIT_FIELDS)
        for index, _, parts in rows:
            matching = {name for name, width in FIT_FIELDS.items() if _fits_layout(parts, width)}
            if not matching:
                raise ValueError(f"UMIST line {index}: unsupported or malformed fit layout")
            choices &= matching
        if len(choices) != 1:
            raise ValueError("UMIST layout is ambiguous or mixed; specify RATE12 or RATE22")
        version = choices.pop()
    found = []
    for index, line, parts in rows:
        try:
            found.extend(_row(line, parts, version))
        except ValueError as error:
            raise ValueError(f"UMIST line {index}: {error}") from error
    return found


def _read_rows(path: Path) -> list[tuple[int, str, list[str]]]:
    rows = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        try:
            rows.append((index, line, _fields(line.rstrip())))
        except ValueError as error:
            raise ValueError(f"UMIST line {index}: {error}") from error
    return rows


def _fields(line: str) -> list[str]:
    try:
        return [field.strip() for field in next(csv.reader([line], delimiter=":", strict=True))]
    except csv.Error as error:
        raise ValueError(f"UMIST row has invalid quoting: {error}") from error


def _fits_layout(parts: list[str], width: int) -> bool:
    if len(parts) < HEAD_FIELDS or not parts[0].isdigit() or not parts[8].isdigit():
        return False
    count = int(parts[8])
    expected = HEAD_FIELDS + count * width
    return count > 0 and len(parts) >= expected and not any(parts[expected:])


def _row(line: str, parts: list[str], version: str) -> list[Rate]:
    width = FIT_FIELDS[version]
    if not _fits_layout(parts, width):
        raise ValueError(f"row does not match the declared {version} fit layout")
    count = int(parts[8])
    reactants = tuple("e" if name in {"e-", "e\u2212"} else name for name in parts[2:4] if name)
    products = tuple("e" if name in {"e-", "e\u2212"} else name for name in parts[4:8] if name)
    if not reactants or not products:
        raise ValueError("reactants and products must be declared")
    found = []
    for index in range(count):
        fit = parts[HEAD_FIELDS + width * index : HEAD_FIELDS + width * (index + 1)]
        values = [_number(text) for text in fit[:5]]
        if any(value is None for value in values):
            raise ValueError(f"fit {index + 1} contains a non-finite or invalid number")
        alpha, beta, gamma, low, high = (float(value) for value in values if value is not None)
        if alpha < 0 or not 0 < low <= high:
            raise ValueError(f"fit {index + 1} has an invalid coefficient or temperature range")
        found.append(
            Rate(
                parts[1],
                reactants,
                products,
                alpha * CM3_PER_M3 ** (len(reactants) - 1),
                beta,
                gamma / KELVIN_PER_EV,
                low,
                high,
                f"{parts[0]}:{index}",
                fit[7],
                fit[5],
                fit[6],
                fit[8] if width == 9 else "",
                version,
                parts[0],
                line,
            )
        )
    return found


def _number(text: str) -> float | None:
    try:
        value = float(text)
        return value if isfinite(value) else None
    except (TypeError, ValueError):
        return None


def records(rates: list[Rate], keep_order: int = 2) -> list[dict]:
    """Two-body records; overlapping lines with unresolved composition are held.

    RATE22 includes sums of several Arrhenius terms on separate rows. Those
    cannot be treated as alternative complete rates. Until the composition is
    identified and supported, preserve every term as reference_only, with the
    original row and parameters, rather than silently choosing one.
    """
    grouped: dict[tuple, list[Rate]] = defaultdict(list)
    for rate in rates:
        grouped[(rate.kind, tuple(sorted(rate.reactants)), tuple(sorted(rate.products)))].append(
            rate
        )
    held = {
        rate.source_id
        for group in grouped.values()
        for rate in group
        if any(_overlapping_rows(rate, other) for other in group)
    }

    return [
        {
            "reaction": rate.equation,
            "form": "reference_only" if rate.source_id in held else "arrhenius",
            "unit": "m3/s",
            "independent_variable": _temperature_axis(rate),
            "channel_scope": "product_resolved",
            "parameters": {
                "A": rate.a_si,
                "b": rate.beta,
                "Ea": rate.activation_eV,
            },
            "parameter_units": {"Ea": "eV"},
            "reference_temperature_K": 300.0,
            "reaction_order": rate.order,
            "validity": {
                "quantity": _temperature_axis(rate),
                "minimum": rate.t_min,
                "maximum": rate.t_max,
                "unit": "K",
            },
            "source": {
                "record_id": rate.source_id,
                "citation": rate.reference,
                "source_type": rate.source_type,
                "provider": "umist",
                "collection": "gas_phase_rates",
                "format_version": rate.format_version,
            },
            "status": "imported",
            "method": {"M": "measured", "C": "calculated", "E": "estimated"}.get(
                rate.source_type, "unknown"
            ),
            "notes": "model composition is unresolved; overlapping source rows are not "
            "independent alternative rates"
            if rate.source_id in held
            else f"UMIST {rate.kind}; source thermal conditions must be reviewed before plasma use",
            "source_declaration": {
                "reaction_id": rate.reaction_id,
                "method": rate.source_type,
                "accuracy": rate.accuracy,
                "note": rate.note,
                "row": rate.raw_row,
                "fit_id": rate.source_id,
                "fit_relation": "unresolved" if rate.source_id in held else "temperature_interval",
            },
        }
        for rate in rates
        if rate.order == keep_order and rate.t_min and rate.kind not in {"CP", "CR", "PH"}
    ]


def _overlapping_rows(left: Rate, right: Rate) -> bool:
    if left.reaction_id == right.reaction_id:
        return False
    return (
        left.t_min is not None
        and left.t_max is not None
        and right.t_min is not None
        and right.t_max is not None
        and max(left.t_min, right.t_min) <= min(left.t_max, right.t_max)
    )


def _temperature_axis(rate: Rate) -> str:
    return "electron_temperature" if "e" in rate.reactants else "gas_temperature"
