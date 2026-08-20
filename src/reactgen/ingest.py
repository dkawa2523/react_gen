"""Match a data snapshot onto registered reactions and species.

Imported numbers never touch the curated registry. Accepted records go into an
overlay file that `generate --overlay` reads; anything that matched zero or
several targets goes into a review queue for a person to resolve.

A snapshot is one YAML document::

    kind: rate_coefficient        # or cross_section, mobility, sticking_coefficient
    source: {source_id: ..., citation: ...}
    records:
      - reaction: "Ar+ + SF6 -> Ar + SF5+ + F"   # or: reaction_id: Arp_SF6_...
        form: constant
        unit: m3/s
        parameters: {value: 1.54e-15}
      - species: SF5              # a property record instead of a reaction one
        property: polarizability_A3
        value: 5.6
        unit: A3

DNT+ output is imported the same way, as a dataset whose source declares
``source_type: calculated_dnt``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reactgen.model import THIRD_BODY
from reactgen.registry import Registry

Side = tuple[tuple[str, int], ...]


@dataclass
class Report:
    accepted: int = 0
    review: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.review


def ingest(snapshot_path: Path, registry: Registry, overlay_path: Path) -> Report:
    snapshot = yaml.safe_load(snapshot_path.read_text(encoding="utf-8")) or {}
    kind = snapshot.get("kind", "rate_coefficient")
    source = dict(snapshot.get("source") or {})
    overlay = _read_overlay(overlay_path)
    report = Report()

    for index, record in enumerate(snapshot.get("records") or []):
        if record.get("species") and record.get("thermo"):
            _apply_thermo(record, registry, overlay, report, index)
        elif record.get("species"):
            _apply_property(record, registry, overlay, report, source, index)
        else:
            _apply_dataset(record, kind, registry, overlay, report, source, index)

    _write(overlay_path, overlay)
    _write(overlay_path.with_name("review_queue.yaml"), {"review": report.review})
    return report


# --------------------------------------------------------------------------- records


def _apply_dataset(
    record: dict,
    kind: str,
    registry: Registry,
    overlay: dict,
    report: Report,
    source: dict,
    index: int,
) -> None:
    targets, unresolved = _targets(record, registry)
    if len(targets) != 1:
        report.review.append(_queued(record, index, targets, unresolved, "reaction"))
        return
    reaction_id = targets[0]
    entry = {
        "id": record.get("id") or f"{reaction_id}__{kind}_{index}",
        "kind": kind,
        "representation": record.get("form", "constant"),
        "unit": record.get("unit"),
        "parameters": record.get("parameters") or {},
        "asset": {"path": record.get("asset")},
        "validity": record.get("validity"),
        "uncertainty": record.get("uncertainty"),
        "source": source | (record.get("source") or {}),
        "status": record.get("status", "imported"),
        "preferred": bool(record.get("preferred")),
    }
    overlay.setdefault("datasets", {}).setdefault(reaction_id, []).append(entry)
    report.accepted += 1


def _apply_property(
    record: dict,
    registry: Registry,
    overlay: dict,
    report: Report,
    source: dict,
    index: int,
) -> None:
    match = registry.identify(str(record["species"]))
    if match.species is None:
        report.review.append(_queued(record, index, list(match.candidates), [], "species"))
        return
    species_id = match.species
    overlay.setdefault("properties", {}).setdefault(species_id, {})[record["property"]] = {
        "value": record.get("value"),
        "unit": record.get("unit"),
        "source": (record.get("source") or source).get("citation") or source.get("source_id"),
    }
    report.accepted += 1


def _apply_thermo(
    record: dict, registry: Registry, overlay: dict, report: Report, index: int
) -> None:
    """A NASA polynomial for one species, held beside its scalar properties.

    Separate from `_apply_property` because a polynomial is not a value with a
    unit: it is fourteen coefficients and three temperatures that only mean
    anything together, and splitting it across fourteen property records would
    let half of one fit merge with half of another.
    """

    match = registry.identify(str(record["species"]))
    if match.species is None:
        report.review.append(_queued(record, index, list(match.candidates), [], "species"))
        return
    overlay.setdefault("thermo", {})[match.species] = dict(record["thermo"])
    report.accepted += 1


def _queued(
    record: dict, index: int, targets: list[str], unresolved: list[str], subject: str
) -> dict:
    if unresolved:
        reason = "species not identified"
    else:
        reason = "no match" if not targets else "several matches"
    return {
        "record": index,
        "subject": subject,
        "wrote": record.get("reaction") or record.get("reaction_id") or record.get("species"),
        "candidates": targets,
        "unresolved": unresolved,
        "reason": reason,
    }


# --------------------------------------------------------------------------- matching


def _targets(record: dict, registry: Registry) -> tuple[list[str], list[str]]:
    """Registered reaction ids this record could describe, and any unresolved names."""

    if record.get("reaction_id"):
        known = {r.id for channels in registry.channels.values() for r in channels}
        return ([record["reaction_id"]] if record["reaction_id"] in known else [], [])
    if not record.get("reaction"):
        return ([], [])

    wanted, unresolved = parse_equation(str(record["reaction"]), registry)
    if unresolved:
        return ([], unresolved)
    return (
        sorted(
            reaction.id
            for channels in registry.channels.values()
            for reaction in channels
            if _sides(reaction) == wanted
        ),
        [],
    )


def parse_equation(text: str, registry: Registry) -> tuple[tuple[Side, Side], list[str]]:
    """``"E + O2 -> E + 2 O"`` into registered-species multisets.

    Every name is identified structurally, so a foreign spelling matches. Names
    that resolve to nothing, or to several species, are returned instead of being
    guessed at, and the caller sends the record to review.
    """

    left, _, right = text.partition("->")
    reactants, missing_left = _side(left, registry)
    products, missing_right = _side(right, registry)
    return ((reactants, products), missing_left + missing_right)


def _side(text: str, registry: Registry) -> tuple[Side, list[str]]:
    """Split on a separating plus, never on the plus inside ``Ar+``."""

    counts: Counter[str] = Counter()
    unresolved = []
    for piece in re.split(r"\s+\+\s+", text.strip()):
        token = piece.strip()
        if not token or token == THIRD_BODY:
            continue
        count, _, name = token.rpartition(" ")
        match = registry.identify(name)
        if match.species is None:
            detail = f"{name} -> {list(match.candidates)}" if match.candidates else name
            unresolved.append(detail)
            continue
        counts[match.species] += int(float(count)) if count.strip() else 1
    return (tuple(sorted(counts.items())), unresolved)


def _sides(reaction) -> tuple[Side, Side]:
    def side(terms) -> Side:
        counts: Counter[str] = Counter()
        for term in terms:
            counts[term.species] += int(term.n)
        return tuple(sorted(counts.items()))

    return (side(reaction.reactants), side(reaction.products))


# --------------------------------------------------------------------------- files


def _read_overlay(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
