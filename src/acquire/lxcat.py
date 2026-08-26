"""Parse an LXCat export into per-process cross sections.

An export is a sequence of blocks. Each opens with a process kind, carries
``KEY: value`` headers, and holds its table between two dashed rules::

    IONIZATION
    Ar -> Ar^+
     1.575960e+1
    SPECIES: e / Ar
    PROCESS: E + Ar -> E + E + Ar+, Ionization
    PARAM.:  E = 15.7596 eV, complete set
    COLUMNS: Energy (eV) | Cross section (m2)
    -----------------------------
     1.575960e+1  0.000000e+0
     1.600000e+1  2.020000e-22
    -----------------------------

Downloading is a separate step: this reads a file the user already has.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

RULE = re.compile(r"^-{5,}\s*$")
HEADER = re.compile(r"^([A-Z][A-Z. ]*):\s*(.*)$")
KINDS = {
    "ELASTIC",
    "EFFECTIVE",
    "EXCITATION",
    "IONIZATION",
    "ATTACHMENT",
    "ROTATION",
    "VIBRATION",
}


def process_type(kind: str) -> str:
    return {
        "ELASTIC": "elastic",
        "EFFECTIVE": "elastic",
        "IONIZATION": "ionization",
        "ATTACHMENT": "attachment",
        "EXCITATION": "excitation",
        "ROTATION": "excitation",
        "VIBRATION": "excitation",
    }.get(kind.upper(), kind.lower())


def observable(kind: str) -> str:
    return {
        "ELASTIC": "elastic",
        "EFFECTIVE": "effective_momentum_transfer",
    }.get(kind.upper(), "reaction")


@dataclass
class Process:
    kind: str
    target: str = ""
    equation: str = ""
    threshold_eV: float | None = None
    headers: dict[str, str] = field(default_factory=dict)
    table: list[tuple[float, float]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.target or 'unknown'}_{self.kind.lower()}"


def parse(path: str | Path) -> list[Process]:
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    processes: list[Process] = []
    current: Process | None = None
    in_table = False

    for line in lines:
        text = line.strip()
        if not text:
            continue
        if RULE.match(text):
            in_table = not in_table
            if not in_table and current is not None:
                processes.append(current)
                current = None
            continue
        if in_table:
            if current is not None:
                _add_row(current, text)
            continue
        if text.upper() in KINDS:
            current = Process(kind=text.upper())
            continue
        if current is not None:
            _add_header(current, text)

    return [item for item in processes if item.table]


def _add_row(process: Process, text: str) -> None:
    parts = text.replace(",", " ").split()
    if len(parts) < 2:
        return
    try:
        process.table.append((float(parts[0]), float(parts[1])))
    except ValueError:
        return


def _add_header(process: Process, text: str) -> None:
    match = HEADER.match(text)
    if match is None:
        # The bare lines under the kind are the target and the threshold.
        if not process.target:
            process.target = text.split("->")[0].strip()
        elif process.threshold_eV is None:
            process.threshold_eV = _number(text)
        return

    key, value = match.group(1).strip().rstrip("."), match.group(2).strip()
    process.headers[key] = value
    if key == "PROCESS":
        process.equation = value.split(",")[0].strip()
    elif key == "SPECIES" and not process.target:
        process.target = value.split("/")[-1].strip()
    elif key == "PARAM" and process.threshold_eV is None:
        process.threshold_eV = _threshold(value)


def _threshold(param: str) -> float | None:
    match = re.search(r"E\s*=\s*([0-9.eE+-]+)", param)
    return _number(match.group(1)) if match else None


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None
