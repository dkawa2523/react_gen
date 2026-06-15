from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def evaluate_expectations(output_dir: str | Path, expectation_path: str | Path | None) -> dict[str, Any]:
    if expectation_path is None:
        return {
            "schema_version": 1,
            "passed": True,
            "score": 1.0,
            "missing_species": [],
            "missing_reaction_families": [],
            "missing_reaction_types": {},
            "missing_outputs": [],
            "forbidden_violations": [],
        }

    output_dir = Path(output_dir)
    expectation_path = Path(expectation_path)
    expectation = _read_yaml(expectation_path)
    states = _as_list(_read_yaml(output_dir / "network.states.yaml").get("species"))
    reactions = _as_list(_read_yaml(output_dir / "network.reactions.yaml").get("reactions"))

    species_ids = {str(state.get("id")) for state in states if isinstance(state, dict)}
    families = {str(reaction.get("family")) for reaction in reactions if isinstance(reaction, dict)}
    types_by_family: dict[str, set[str]] = {}
    for reaction in reactions:
        if not isinstance(reaction, dict):
            continue
        family = str(reaction.get("family"))
        types_by_family.setdefault(family, set()).add(str(reaction.get("type")))

    required_species = [str(item) for item in _as_list(expectation.get("required_species"))]
    required_families = [str(item) for item in _as_list(expectation.get("required_reaction_families"))]
    required_outputs = [str(item) for item in _as_list(expectation.get("required_outputs"))]
    required_types = expectation.get("required_reaction_types", {})
    if not isinstance(required_types, dict):
        required_types = {}

    missing_species = [item for item in required_species if item not in species_ids]
    missing_families = [item for item in required_families if item not in families]
    missing_outputs = [item for item in required_outputs if not (output_dir / item).exists()]
    missing_types: dict[str, list[str]] = {}
    for family, required in required_types.items():
        missing = [str(item) for item in _as_list(required) if str(item) not in types_by_family.get(str(family), set())]
        if missing:
            missing_types[str(family)] = missing
    forbidden_violations = _forbidden_violations(reactions, expectation.get("forbidden"))

    total_checks = (
        len(required_species)
        + len(required_families)
        + len(required_outputs)
        + sum(len(_as_list(required)) for required in required_types.values())
        + len(forbidden_violations)
    )
    failed_checks = len(missing_species) + len(missing_families) + len(missing_outputs) + sum(
        len(items) for items in missing_types.values()
    ) + len(forbidden_violations)
    score = 1.0 if total_checks == 0 else max(0.0, (total_checks - failed_checks) / total_checks)

    return {
        "schema_version": 1,
        "expectation": str(expectation_path),
        "passed": failed_checks == 0,
        "score": round(score, 6),
        "missing_species": missing_species,
        "missing_reaction_families": missing_families,
        "missing_reaction_types": missing_types,
        "missing_outputs": missing_outputs,
        "forbidden_violations": forbidden_violations,
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_violations(reactions: list[dict[str, Any]], forbidden: Any) -> list[dict[str, Any]]:
    if not isinstance(forbidden, dict) or not forbidden.get("reactions_with_failed_balance"):
        return []
    violations = []
    for reaction in reactions:
        if not isinstance(reaction, dict):
            continue
        validation = reaction.get("validation")
        if not isinstance(validation, dict):
            continue
        failed = {
            key: value
            for key, value in validation.items()
            if key in {"charge_balance", "element_balance"} and value not in {"ok", None}
        }
        if failed:
            violations.append({"reaction_id": reaction.get("id"), "validation": failed})
    return violations
