from __future__ import annotations

from typing import Any

from plasma_reactgen.application.dnt_readiness import dnt_channel_missing_fields
from plasma_reactgen.application.reaction_catalog import DATASET_OUTPUT_KINDS
from plasma_reactgen.domain.models import GeneratedReaction, MissingDataItem


def state_missing_items(states: list[dict[str, Any]]) -> list[MissingDataItem]:
    return [
        MissingDataItem(
            subject_kind="species",
            subject_id=state["id"],
            field=field,
            required_by=";".join(state.get("roles", [])),
            severity="required",
            message="Required property is missing for at least one assigned role.",
        )
        for state in states
        for field in state.get("missing_properties", [])
    ]


def reaction_missing_items(
    reactions: list[GeneratedReaction],
) -> list[MissingDataItem]:
    items = []
    for reaction in reactions:
        items.extend(_electron_cross_section_items(reaction))
        items.extend(_dnt_channel_items(reaction))
    return items


def dnt_task_missing_items(
    tasks: list[dict[str, Any]],
) -> list[MissingDataItem]:
    items = []
    for task in tasks:
        items.extend(_dnt_property_items(task))
        dataset_item = _dnt_dataset_item(task)
        if dataset_item is not None:
            items.append(dataset_item)
    return items


def _electron_cross_section_items(
    reaction: GeneratedReaction,
) -> list[MissingDataItem]:
    if reaction.family != "electron":
        return []
    status = reaction.data_status.get("cross_section")
    if status == "missing":
        return [
            _reaction_item(
                reaction.id,
                field="data.cross_section",
                required_by="electron_collision",
                message="Electron-collision channel has no cross-section reference.",
            )
        ]
    if status in {"reference_only_needs_import", "path_registered_but_missing"}:
        return [
            MissingDataItem(
                subject_kind="asset",
                subject_id=reaction.id,
                field="data.cross_section.path",
                required_by="electron_collision",
                severity="warning",
                message="Cross-section numeric data is not available locally.",
            )
        ]
    return []


def _dnt_channel_items(reaction: GeneratedReaction) -> list[MissingDataItem]:
    if reaction.family != "ion_neutral" or not reaction.dnt_class:
        return []
    missing = dnt_channel_missing_fields(
        reaction_type=reaction.type,
        dnt_class=reaction.dnt_class,
        threshold_eV=reaction.threshold_eV,
        delta_e_eV=reaction.deltaE_products_minus_reactants_eV,
    )
    items = []
    if "threshold_eV" in missing:
        items.append(
            _reaction_item(
                reaction.id,
                field="threshold_eV",
                required_by="dnt_task",
                message="Non-elastic DNT channel has no registered threshold energy.",
            )
        )
    if "deltaE_products_minus_reactants_eV" in missing:
        items.append(
            _reaction_item(
                reaction.id,
                field="deltaE_products_minus_reactants_eV",
                required_by="dnt_task",
                message=("Reaction energy is not registered. DNT+/DNT+DM calculation may need it."),
            )
        )
    return items


def _dnt_property_items(task: dict[str, Any]) -> list[MissingDataItem]:
    return [
        MissingDataItem(
            subject_kind="dnt_pair",
            subject_id=task["pair_id"],
            field=f"{side}.{name}",
            required_by="dnt_task",
            severity="warning",
            message="Required DNT pair property is unavailable.",
        )
        for side, properties in task["required_properties"].items()
        for name, prop in properties.items()
        if not prop["available"]
    ]


def _dnt_dataset_item(task: dict[str, Any]) -> MissingDataItem | None:
    missing_kinds = [
        kind
        for output_name, kind in DATASET_OUTPUT_KINDS.items()
        if not any(dataset["available"] for dataset in task["existing_datasets"][output_name])
    ]
    if not missing_kinds:
        return None
    return MissingDataItem(
        subject_kind="dnt_pair",
        subject_id=task["pair_id"],
        field="data.datasets",
        required_by="reaction_data_review",
        severity="info",
        message="No available dataset is registered for: " + ", ".join(missing_kinds) + ".",
    )


def _reaction_item(
    reaction_id: str,
    *,
    field: str,
    required_by: str,
    message: str,
) -> MissingDataItem:
    return MissingDataItem(
        subject_kind="reaction",
        subject_id=reaction_id,
        field=field,
        required_by=required_by,
        severity="warning",
        message=message,
    )


__all__ = [
    "dnt_task_missing_items",
    "reaction_missing_items",
    "state_missing_items",
]
