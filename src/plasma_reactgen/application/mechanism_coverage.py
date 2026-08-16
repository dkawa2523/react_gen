"""Report coverage of explicitly scoped literature mechanisms."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.models import ReactionNetwork

_RECORD_RANGE = re.compile(r"^([A-Za-z_-]+)(\d+)-\1?(\d+)$")


def build_mechanism_coverage(
    seed_gases: list[str],
    network: ReactionNetwork,
    registry_root: str | Path,
) -> dict[str, Any]:
    """Compare generated reactions with applicable, bounded source tables."""

    catalog = _load_catalog(Path(registry_root) / "sources" / "semiconductor_mechanisms.yaml")
    reactions = {reaction.id: reaction for reaction in network.reactions}
    source_records = _source_records(network)
    seed_set = set(seed_gases)
    reports = []
    for mechanism in catalog.get("mechanisms", []):
        required = set(mechanism.get("required_seed_gases", []))
        if not required <= seed_set:
            continue
        reports.append(_mechanism_report(mechanism, reactions, source_records))

    return {
        "schema_version": 1,
        "scope": "bounded_literature_tables_not_global_chemistry_completeness",
        "summary": {
            "n_applicable_mechanisms": len(reports),
            "n_complete_mechanisms": sum(report["complete"] for report in reports),
            "n_missing_source_records": sum(
                len(report["missing_record_ids"]) for report in reports
            ),
        },
        "mechanisms": reports,
        "notes": [
            "A complete result means every row in the declared source-table scope is represented.",
            "It does not claim that all reactions for every semiconductor process gas are known.",
            (
                "Numerical cross sections, rate coefficients, DNT, and calculated "
                "results are independent."
            ),
        ],
    }


def _mechanism_report(
    mechanism: dict[str, Any],
    reactions: dict[str, Any],
    source_records: dict[str, set[str]],
) -> dict[str, Any]:
    source = mechanism["source"]
    expected = _expected_records(mechanism["scope"])
    direct = source_records.get(source["source_id"], set())
    equivalents = mechanism.get("equivalent_reaction_ids", {})
    covered = {
        record_id
        for record_id in expected
        if record_id in direct or equivalents.get(record_id) in reactions
    }
    missing = sorted(expected - covered, key=_record_sort_key)
    return {
        "id": mechanism["id"],
        "source": source,
        "scope": mechanism["scope"],
        "complete": not missing,
        "n_expected_records": len(expected),
        "n_covered_records": len(covered),
        "covered_record_ids": sorted(covered, key=_record_sort_key),
        "missing_record_ids": missing,
    }


def _source_records(network: ReactionNetwork) -> dict[str, set[str]]:
    records: dict[str, set[str]] = {}
    for reaction in network.reactions:
        source = reaction.source_record or {}
        source_id = source.get("source_id")
        record_id = source.get("record_id")
        if source_id and record_id:
            records.setdefault(str(source_id), set()).add(str(record_id))
    return records


def _expected_records(scope: dict[str, Any]) -> set[str]:
    records = {str(item) for item in scope.get("expected_record_ids", [])}
    for value in scope.get("expected_record_ranges", []):
        match = _RECORD_RANGE.fullmatch(str(value))
        if match is None:
            raise ValueError(f"Invalid mechanism record range: {value}")
        prefix, start, end = match.groups()
        records.update(f"{prefix}{number}" for number in range(int(start), int(end) + 1))
    return records


def _record_sort_key(record_id: str) -> tuple[str, int, str]:
    match = re.fullmatch(r"([^0-9]*)(\d+)", record_id)
    if match is None:
        return record_id, -1, record_id
    return match.group(1), int(match.group(2)), record_id


def _load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Mechanism catalog must be a mapping: {path}")
    return payload


__all__ = ["build_mechanism_coverage"]
