from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.benchmark_io import read_optional_yaml


def evaluate_expectations(
    output_dir: str | Path,
    expectation_path: str | Path | None,
) -> dict[str, Any]:
    if expectation_path is None:
        return _empty_evaluation()

    output_dir = Path(output_dir)
    expectation_path = Path(expectation_path)
    expectation = read_optional_yaml(expectation_path)
    states = _records(output_dir / "network.states.yaml", "species")
    reactions = _records(output_dir / "network.reactions.yaml", "reactions")
    required_species = _strings(expectation.get("required_species"))
    required_families = _strings(expectation.get("required_reaction_families"))
    required_outputs = _strings(expectation.get("required_outputs"))
    required_types = _required_types(expectation.get("required_reaction_types"))

    missing_species = _missing_values(required_species, _species_ids(states))
    missing_families = _missing_values(required_families, _families(reactions))
    missing_types = _missing_types(required_types, reactions)
    missing_outputs = [item for item in required_outputs if not (output_dir / item).exists()]
    forbidden = _forbidden_violations(reactions, expectation.get("forbidden"))
    total, failed = _check_counts(
        required_species,
        required_families,
        required_outputs,
        required_types,
        missing_species,
        missing_families,
        missing_outputs,
        missing_types,
        forbidden,
    )
    score = 1.0 if total == 0 else max(0.0, (total - failed) / total)
    return {
        "schema_version": 1,
        "expectation": str(expectation_path),
        "passed": failed == 0,
        "score": round(score, 6),
        "missing_species": missing_species,
        "missing_reaction_families": missing_families,
        "missing_reaction_types": missing_types,
        "missing_outputs": missing_outputs,
        "forbidden_violations": forbidden,
    }


def _empty_evaluation() -> dict[str, Any]:
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


def _records(path: Path, key: str) -> list[dict[str, Any]]:
    return [item for item in _as_list(read_optional_yaml(path).get(key)) if isinstance(item, dict)]


def _species_ids(states: list[dict[str, Any]]) -> set[str]:
    return {str(state.get("id")) for state in states}


def _families(reactions: list[dict[str, Any]]) -> set[str]:
    return {str(reaction.get("family")) for reaction in reactions}


def _required_types(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {str(family): _strings(types) for family, types in value.items()}


def _missing_values(required: list[str], observed: set[str]) -> list[str]:
    return [item for item in required if item not in observed]


def _missing_types(
    required: dict[str, list[str]],
    reactions: list[dict[str, Any]],
) -> dict[str, list[str]]:
    observed: dict[str, set[str]] = {}
    for reaction in reactions:
        observed.setdefault(str(reaction.get("family")), set()).add(str(reaction.get("type")))
    return {
        family: missing
        for family, types in required.items()
        if (missing := _missing_values(types, observed.get(family, set())))
    }


def _check_counts(
    required_species: list[str],
    required_families: list[str],
    required_outputs: list[str],
    required_types: dict[str, list[str]],
    missing_species: list[str],
    missing_families: list[str],
    missing_outputs: list[str],
    missing_types: dict[str, list[str]],
    forbidden: list[dict[str, Any]],
) -> tuple[int, int]:
    total = (
        len(required_species)
        + len(required_families)
        + len(required_outputs)
        + sum(len(types) for types in required_types.values())
        + len(forbidden)
    )
    failed = (
        len(missing_species)
        + len(missing_families)
        + len(missing_outputs)
        + sum(len(types) for types in missing_types.values())
        + len(forbidden)
    )
    return total, failed


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _as_list(value)]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _forbidden_violations(
    reactions: list[dict[str, Any]],
    forbidden: Any,
) -> list[dict[str, Any]]:
    if not isinstance(forbidden, dict) or not forbidden.get("reactions_with_failed_balance"):
        return []
    violations = []
    for reaction in reactions:
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


__all__ = ["evaluate_expectations"]
