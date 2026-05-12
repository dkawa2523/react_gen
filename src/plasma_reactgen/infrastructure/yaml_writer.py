from __future__ import annotations

from pathlib import Path
import json
import yaml

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork
from plasma_reactgen.infrastructure.serialization import to_plain


def write_yaml_outputs(
    output_dir: str | Path,
    case_config: CaseConfig,
    network: ReactionNetwork,
    states: list[dict],
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if case_config.outputs.reactions:
        _write_yaml(output_dir / "network.reactions.yaml", _reactions_payload(case_config, network))

    if case_config.outputs.states:
        _write_yaml(output_dir / "network.states.yaml", _states_payload(case_config, states))

    if case_config.outputs.dnt_tasks:
        _write_yaml(output_dir / "dnt_tasks.yaml", _dnt_tasks_payload(case_config, dnt_tasks))

    if case_config.outputs.coverage_report:
        _write_yaml(output_dir / "coverage_report.yaml", _coverage_payload(case_config, network))

    if case_config.outputs.missing_data:
        _write_yaml(output_dir / "missing_data.yaml", _missing_data_payload(case_config, missing_data))

    summary = _summary_payload(case_config, network, dnt_tasks, missing_data)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _reactions_payload(case_config: CaseConfig, network: ReactionNetwork) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "summary": {
            "n_species": len(network.species_nodes),
            "n_reactions": len(network.reactions),
            "n_electron_reactions": sum(1 for r in network.reactions if r.family == "electron"),
            "n_ion_neutral_reactions": sum(1 for r in network.reactions if r.family == "ion_neutral"),
            "max_depth_reached": max((r.depth for r in network.reactions), default=0),
        },
        "reactions": [to_plain(rxn) for rxn in network.reactions],
    }


def _states_payload(case_config: CaseConfig, states: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "species": states,
    }


def _dnt_tasks_payload(case_config: CaseConfig, dnt_tasks: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "summary": {
            "n_dnt_pairs": len(dnt_tasks),
            "n_ready_pairs": sum(1 for x in dnt_tasks if x.get("readiness", {}).get("status") == "ready"),
            "n_pairs_with_missing_properties": sum(1 for x in dnt_tasks if x.get("readiness", {}).get("status") != "ready"),
        },
        "dnt_tasks": dnt_tasks,
    }


def _coverage_payload(case_config: CaseConfig, network: ReactionNetwork) -> dict:
    found = [c for c in network.coverage if c.status == "found"]
    missing = [c for c in network.coverage if c.status == "missing"]
    other = [c for c in network.coverage if c.status not in {"found", "missing"}]
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "summary": {
            "n_pairs_found": len(found),
            "n_pairs_missing": len(missing),
            "n_pairs_other": len(other),
        },
        "pairs": {
            "found": [to_plain(x) for x in found],
            "missing": [to_plain(x) for x in missing],
            "other": [to_plain(x) for x in other],
        },
    }


def _missing_data_payload(case_config: CaseConfig, missing_data: list[MissingDataItem]) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "missing_data": [to_plain(x) for x in missing_data],
    }


def _summary_payload(
    case_config: CaseConfig,
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "n_species": len(network.species_nodes),
        "n_reactions": len(network.reactions),
        "n_pairs_found": sum(1 for c in network.coverage if c.status == "found"),
        "n_pairs_missing": sum(1 for c in network.coverage if c.status == "missing"),
        "n_dnt_tasks": len(dnt_tasks),
        "n_missing_data_items": len(missing_data),
    }
