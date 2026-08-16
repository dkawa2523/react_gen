from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.network_metrics import count_dnt_status
from plasma_reactgen.application.output_summary import (
    build_quality_summary,
    build_summary,
)
from plasma_reactgen.application.reaction_catalog import (
    AssetExists,
    available_dataset_ids,
    reaction_output,
)
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork
from plasma_reactgen.infrastructure.serialization import to_plain


def write_yaml_outputs(
    output_dir: str | Path,
    case_config: CaseConfig,
    network: ReactionNetwork,
    states: list[dict],
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
    registry_context: dict[str, Any] | None = None,
    asset_exists: AssetExists | None = None,
    mechanism_coverage: dict[str, Any] | None = None,
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml(
        output_dir / "network.reactions.yaml",
        _reactions_payload(case_config, network, asset_exists),
    )
    _write_yaml(output_dir / "network.states.yaml", _states_payload(case_config, states))
    _write_yaml(output_dir / "dnt_tasks.yaml", _dnt_tasks_payload(case_config, dnt_tasks))
    _write_yaml(output_dir / "coverage_report.yaml", _coverage_payload(case_config, network))
    _write_yaml(output_dir / "missing_data.yaml", _missing_data_payload(case_config, missing_data))
    if mechanism_coverage is not None:
        _write_yaml(output_dir / "mechanism_coverage.yaml", mechanism_coverage)

    summary = build_summary(case_config, network, dnt_tasks, missing_data)
    if registry_context is not None:
        summary["registry"] = registry_context
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_yaml(
        output_dir / "quality_summary.yaml",
        build_quality_summary(case_config, network, dnt_tasks, missing_data),
    )


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _reactions_payload(
    case_config: CaseConfig,
    network: ReactionNetwork,
    asset_exists: AssetExists | None = None,
) -> dict:
    family_counts = _reaction_family_counts(network)
    numerical_data = _numerical_data_summary(network, asset_exists)
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "summary": {
            "n_species": len(network.species_nodes),
            "n_reactions": len(network.reactions),
            "n_electron_reactions": sum(r.family == "electron" for r in network.reactions),
            "n_ion_neutral_reactions": sum(r.family == "ion_neutral" for r in network.reactions),
            "reactions_by_family": family_counts,
            "numerical_data": numerical_data,
            "max_depth_reached": max((r.depth for r in network.reactions), default=0),
            "generation_complete": network.generation_complete,
            "n_truncations": len(network.truncations),
        },
        "truncations": _truncations_payload(network),
        "reactions": [_reaction_payload(reaction, asset_exists) for reaction in network.reactions],
    }


def _reaction_family_counts(network: ReactionNetwork) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reaction in network.reactions:
        counts[reaction.family] = counts.get(reaction.family, 0) + 1
    return dict(sorted(counts.items()))


def _numerical_data_summary(
    network: ReactionNetwork,
    asset_exists: AssetExists | None,
) -> dict[str, Any]:
    kinds = ("cross_section", "rate_coefficient", "mobility")
    by_kind = {
        kind: sum(
            bool(available_dataset_ids(reaction, kind, asset_exists))
            for reaction in network.reactions
        )
        for kind in kinds
    }
    with_data = sum(
        any(available_dataset_ids(reaction, kind, asset_exists) for kind in kinds)
        for reaction in network.reactions
    )
    return {
        "n_reactions_with_available_data": with_data,
        "n_reactions_without_available_data": len(network.reactions) - with_data,
        "n_reactions_by_available_dataset_kind": by_kind,
        "reaction_equations_require_numerical_data": False,
    }


def _reaction_payload(reaction, asset_exists: AssetExists | None = None) -> dict:
    return reaction_output(reaction, asset_exists)


def _states_payload(case_config: CaseConfig, states: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "species": states,
    }


def _dnt_tasks_payload(case_config: CaseConfig, dnt_tasks: list[dict]) -> dict:
    property_ready = count_dnt_status(dnt_tasks, "pair_property_readiness", "ready")
    complete_ready = count_dnt_status(dnt_tasks, "complete_readiness", "ready")
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "summary": {
            "n_dnt_pairs": len(dnt_tasks),
            "n_ready_pairs": property_ready,
            "n_property_ready_pairs": property_ready,
            "n_complete_ready_pairs": complete_ready,
            "n_ready_with_warnings_pairs": count_dnt_status(
                dnt_tasks, "complete_readiness", "ready_with_warnings"
            ),
            "n_pairs_missing_required_data": count_dnt_status(
                dnt_tasks, "complete_readiness", "missing_required_data"
            ),
            "n_pairs_without_dnt_channels": count_dnt_status(
                dnt_tasks, "complete_readiness", "no_dnt_channels"
            ),
            "n_pairs_with_missing_properties": len(dnt_tasks) - property_ready,
        },
        "dnt_tasks": dnt_tasks,
    }


def _coverage_payload(case_config: CaseConfig, network: ReactionNetwork) -> dict:
    found = [item for item in network.coverage if item.status == "found"]
    missing = [item for item in network.coverage if item.status == "missing"]
    other = [item for item in network.coverage if item.status not in {"found", "missing"}]
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "summary": {
            "n_pairs_found": len(found),
            "n_pairs_missing": len(missing),
            "n_pairs_other": len(other),
            "generation_complete": network.generation_complete,
            "n_truncations": len(network.truncations),
        },
        "truncations": _truncations_payload(network),
        "pairs": {
            "found": [to_plain(item) for item in found],
            "missing": [to_plain(item) for item in missing],
            "other": [to_plain(item) for item in other],
        },
    }


def _missing_data_payload(
    case_config: CaseConfig,
    missing_data: list[MissingDataItem],
) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "missing_data": [to_plain(item) for item in missing_data],
    }


def _truncations_payload(network: ReactionNetwork) -> list[dict[str, Any]]:
    return [to_plain(event) for event in network.truncations]
