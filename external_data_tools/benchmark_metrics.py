from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def collect_metrics(
    output_dir: str | Path,
    prepared_registry: str | Path | None = None,
    *,
    missing_plan: str | Path | None = None,
    expectation_score: float | None = None,
    solver_status_summary: dict[str, int] | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    prepared_registry_path = Path(prepared_registry) if prepared_registry is not None else None
    missing_plan_path = Path(missing_plan) if missing_plan is not None else None

    reactions_payload = _read_yaml(output_dir / "network.reactions.yaml")
    states_payload = _read_yaml(output_dir / "network.states.yaml")
    coverage_payload = _read_yaml(output_dir / "coverage_report.yaml")
    missing_payload = _read_yaml(output_dir / "missing_data.yaml")
    dnt_payload = _read_yaml(output_dir / "dnt_tasks.yaml")
    plan_payload = _read_yaml(missing_plan_path) if missing_plan_path is not None else {}

    reactions = _as_list(reactions_payload.get("reactions"))
    states = _as_list(states_payload.get("species"))
    missing_data = _as_list(missing_payload.get("missing_data"))
    dnt_tasks = _as_list(dnt_payload.get("dnt_tasks"))
    reaction_summary = reactions_payload.get("summary", {}) if isinstance(reactions_payload.get("summary"), dict) else {}
    coverage_summary = coverage_payload.get("summary", {}) if isinstance(coverage_payload.get("summary"), dict) else {}
    dnt_summary = dnt_payload.get("summary", {}) if isinstance(dnt_payload.get("summary"), dict) else {}

    n_reactions = len(reactions)
    n_inferred = sum(1 for reaction in reactions if _reaction_status(reaction) == "inferred")
    n_imported = sum(1 for reaction in reactions if _reaction_status(reaction) == "imported")
    n_literature_supported = sum(1 for reaction in reactions if _reaction_status(reaction) == "literature_supported")
    n_imported_or_literature = sum(
        1 for reaction in reactions if _reaction_status(reaction) in {"imported", "literature_supported"}
    )
    n_electron = sum(1 for reaction in reactions if reaction.get("family") == "electron")
    n_ion_neutral = sum(1 for reaction in reactions if reaction.get("family") == "ion_neutral")
    n_with_cross_sections = sum(1 for reaction in reactions if _has_cross_section_asset(reaction))
    n_with_provenance = sum(1 for reaction in reactions if _has_provenance(reaction))

    return {
        "schema_version": 1,
        "n_species": len(states) or int(reaction_summary.get("n_species", 0)),
        "n_reactions": n_reactions,
        "n_electron_reactions": n_electron,
        "n_ion_neutral_reactions": n_ion_neutral,
        "max_depth_reached": int(reaction_summary.get("max_depth_reached", _max_depth(reactions))),
        "n_pairs_found": int(coverage_summary.get("n_pairs_found", 0)),
        "n_pairs_missing": int(coverage_summary.get("n_pairs_missing", 0)),
        "n_missing_data_items": len(missing_data),
        "n_missing_plan_actions": len(_as_list(plan_payload.get("actions"))),
        "n_dnt_tasks": len(dnt_tasks) or int(dnt_summary.get("n_dnt_pairs", 0)),
        "n_dnt_ready_pairs": int(dnt_summary.get("n_ready_pairs", 0)),
        "n_dnt_pairs_with_missing_properties": int(dnt_summary.get("n_pairs_with_missing_properties", 0)),
        "n_cross_section_assets": _count_cross_section_assets(prepared_registry_path),
        "n_reactions_with_cross_section_asset": n_with_cross_sections,
        "cross_section_asset_coverage_fraction": _fraction(n_with_cross_sections, n_electron),
        "n_reactions_with_provenance": n_with_provenance,
        "provenance_coverage_fraction": _fraction(n_with_provenance, n_reactions),
        "n_inferred_reactions": n_inferred,
        "n_imported_reactions": n_imported,
        "n_literature_supported_reactions": n_literature_supported,
        "inferred_reaction_fraction": _fraction(n_inferred, n_reactions),
        "imported_or_literature_supported_fraction": _fraction(n_imported_or_literature, n_reactions),
        "validation_error_count": _validation_error_count(reactions, missing_data),
        "expectation_score": 1.0 if expectation_score is None else float(expectation_score),
        "solver_status_summary": _solver_summary(solver_status_summary),
    }


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


def _max_depth(reactions: list[dict[str, Any]]) -> int:
    depths = []
    for reaction in reactions:
        try:
            depths.append(int(reaction.get("depth", 0)))
        except (TypeError, ValueError):
            continue
    return max(depths, default=0)


def _reaction_status(reaction: dict[str, Any]) -> str | None:
    data_status = reaction.get("data_status")
    if isinstance(data_status, dict):
        return data_status.get("reaction")
    return None


def _has_cross_section_asset(reaction: dict[str, Any]) -> bool:
    data = reaction.get("data")
    if not isinstance(data, dict):
        return False
    cross_section = data.get("cross_section")
    return isinstance(cross_section, dict) and bool(cross_section.get("path"))


def _has_provenance(reaction: dict[str, Any]) -> bool:
    data = reaction.get("data")
    if not isinstance(data, dict):
        return False
    return any(data.get(key) for key in ("provenance", "source_record", "evidence"))


def _count_cross_section_assets(prepared_registry: Path | None) -> int:
    if prepared_registry is None:
        return 0
    assets = prepared_registry / "assets" / "cross_sections"
    if not assets.exists():
        return 0
    return len(list(assets.glob("*.csv")))


def _fraction(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _solver_summary(value: dict[str, int] | None) -> dict[str, int]:
    defaults = {
        "ready": 0,
        "disabled": 0,
        "skipped_missing_executable": 0,
        "skipped_missing_adapter": 0,
        "skipped_missing_input_adapter": 0,
        "completed": 0,
        "failed": 0,
    }
    if isinstance(value, dict):
        for key in defaults:
            try:
                defaults[key] = int(value.get(key, defaults[key]))
            except (TypeError, ValueError):
                defaults[key] = 0
    return defaults


def _validation_error_count(reactions: list[dict[str, Any]], missing_data: list[dict[str, Any]]) -> int:
    reaction_errors = 0
    for reaction in reactions:
        validation = reaction.get("validation")
        if isinstance(validation, dict) and any(value not in {"ok", None} for value in validation.values()):
            reaction_errors += 1
    missing_errors = sum(1 for item in missing_data if isinstance(item, dict) and item.get("severity") == "error")
    return reaction_errors + missing_errors


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
