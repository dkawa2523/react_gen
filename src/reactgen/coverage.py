"""How much of each declared literature mechanism the network reproduces.

A mechanism paper declares a bounded set of rows. Coverage compares the row ids
the network carries against that declared scope, so "complete" means every row
in one table, never every reaction in plasma chemistry.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from reactgen.case import Case
from reactgen.model import Network


def build(case: Case, network: Network, registry_root: Path) -> dict:
    path = registry_root / "sources" / "semiconductor_mechanisms.yaml"
    if not path.is_file():
        return {"mechanisms": []}
    declared = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    generated = {reaction.id for reaction in network.reactions}
    cited = {
        reaction.source["record_id"]
        for reaction in network.reactions
        if reaction.source.get("record_id")
    }
    gases = set(case.gases)
    return {
        "mechanisms": [
            _one(entry, cited, generated)
            for entry in declared.get("mechanisms") or []
            if set(entry.get("required_seed_gases") or ()) <= gases
        ]
    }


def _one(entry: dict, cited: set[str], generated: set[str]) -> dict:
    """A row counts as present when a reaction cites it, or maps to it by id."""

    scope = entry.get("scope") or {}
    equivalents = entry.get("equivalent_reaction_ids") or {}
    present = cited | {row for row, name in equivalents.items() if name in generated}
    expected = _rows(scope.get("expected_record_ranges") or [])
    found = sorted(expected & present, key=_order)
    missing = sorted(expected - present, key=_order)
    return {
        "id": entry["id"],
        "citation": (entry.get("source") or {}).get("citation"),
        "scope": scope.get("description"),
        "expected": len(expected),
        "found": len(found),
        "complete": not missing,
        "missing": missing,
        "excluded": scope.get("excluded_records") or [],
        "exclusion_reason": scope.get("exclusion_reason"),
    }


def _rows(ranges: list[str]) -> set[str]:
    """Expand ``["R1-R60", "R119-R138"]`` into the row ids it names."""

    rows: set[str] = set()
    for span in ranges:
        first, _, last = span.partition("-")
        if not last:
            rows.add(first)
            continue
        start, end = _order(first), _order(last)
        prefix = first.rstrip("0123456789")
        rows.update(f"{prefix}{number}" for number in range(start, end + 1))
    return rows


def _order(record_id: str) -> int:
    digits = "".join(character for character in record_id if character.isdigit())
    return int(digits) if digits else 0
