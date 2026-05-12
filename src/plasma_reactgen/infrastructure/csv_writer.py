from __future__ import annotations

from pathlib import Path
import csv

from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork


def write_csv_outputs(
    output_dir: str | Path,
    network: ReactionNetwork,
    states: list[dict],
    missing_data: list[MissingDataItem],
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_reactions_csv(output_dir / "network.reactions.csv", network)
    _write_states_csv(output_dir / "network.states.csv", states)
    _write_missing_data_csv(output_dir / "missing_data.csv", missing_data)


def _write_reactions_csv(path: Path, network: ReactionNetwork) -> None:
    fields = [
        "id",
        "depth",
        "family",
        "type",
        "equation",
        "source_pair",
        "introduced_species",
        "charge_balance",
        "element_balance",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rxn in network.reactions:
            writer.writerow(
                {
                    "id": rxn.id,
                    "depth": rxn.depth,
                    "family": rxn.family,
                    "type": rxn.type,
                    "equation": rxn.equation,
                    "source_pair": rxn.source_pair_label,
                    "introduced_species": ";".join(rxn.introduced_species),
                    "charge_balance": rxn.validation.get("charge_balance"),
                    "element_balance": rxn.validation.get("element_balance"),
                    "status": rxn.data_status.get("reaction"),
                }
            )


def _write_states_csv(path: Path, states: list[dict]) -> None:
    fields = [
        "id",
        "charge",
        "composition",
        "classes",
        "depth_first_seen",
        "roles",
        "propagated",
        "required_properties",
        "missing_properties",
        "introduced_by",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for state in states:
            writer.writerow(
                {
                    "id": state.get("id"),
                    "charge": state.get("charge"),
                    "composition": ";".join(f"{k}:{v}" for k, v in state.get("composition", {}).items()),
                    "classes": ";".join(state.get("classes", [])),
                    "depth_first_seen": state.get("depth_first_seen"),
                    "roles": ";".join(state.get("roles", [])),
                    "propagated": state.get("propagated"),
                    "required_properties": ";".join(state.get("required_properties", [])),
                    "missing_properties": ";".join(state.get("missing_properties", [])),
                    "introduced_by": ";".join(state.get("introduced_by", [])),
                    "status": state.get("status"),
                }
            )


def _write_missing_data_csv(path: Path, missing_data: list[MissingDataItem]) -> None:
    fields = ["subject_kind", "subject_id", "field", "required_by", "severity", "message"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in missing_data:
            writer.writerow(
                {
                    "subject_kind": item.subject_kind,
                    "subject_id": item.subject_id,
                    "field": item.field,
                    "required_by": item.required_by,
                    "severity": item.severity,
                    "message": item.message,
                }
            )
