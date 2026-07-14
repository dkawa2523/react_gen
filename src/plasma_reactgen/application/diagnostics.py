from __future__ import annotations

from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks, dnt_channel_missing_fields
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork
from plasma_reactgen.application.reaction_catalog import DATASET_OUTPUT_KINDS


def build_missing_data(
    network: ReactionNetwork,
    states: list[dict],
    dnt_tasks: list[dict] | None = None,
) -> list[MissingDataItem]:
    """Build user-facing gaps from the generated network and state roles.

    Builders already resolve assets and DNT channels into ``ReactionNetwork``.
    Keeping those derived representations out of this API prevents the same gap
    from being reported once per output format.
    """
    items: list[MissingDataItem] = list(network.missing_data)

    for state in states:
        for field in state.get("missing_properties", []):
            items.append(
                MissingDataItem(
                    subject_kind="species",
                    subject_id=state["id"],
                    field=field,
                    required_by=";".join(state.get("roles", [])),
                    severity="required",
                    message="Required property is missing for at least one assigned role.",
                )
            )

    for rxn in network.reactions:
        if rxn.family == "electron":
            cross_section_status = rxn.data_status.get("cross_section")
            if cross_section_status == "missing":
                items.append(
                    MissingDataItem(
                        subject_kind="reaction",
                        subject_id=rxn.id,
                        field="data.cross_section",
                        required_by="electron_collision",
                        severity="warning",
                        message="Electron-collision channel has no cross-section reference.",
                    )
                )
            elif cross_section_status in {
                "reference_only_needs_import",
                "path_registered_but_missing",
            }:
                items.append(
                    MissingDataItem(
                        subject_kind="asset",
                        subject_id=rxn.id,
                        field="data.cross_section.path",
                        required_by="electron_collision",
                        severity="warning",
                        message="Cross-section numeric data is not available locally.",
                    )
                )

        if rxn.family != "ion_neutral" or not rxn.dnt_class:
            continue
        missing_fields = dnt_channel_missing_fields(
            reaction_type=rxn.type,
            dnt_class=rxn.dnt_class,
            threshold_eV=rxn.threshold_eV,
            delta_e_eV=rxn.deltaE_products_minus_reactants_eV,
        )
        if "threshold_eV" in missing_fields:
            items.append(
                MissingDataItem(
                    subject_kind="reaction",
                    subject_id=rxn.id,
                    field="threshold_eV",
                    required_by="dnt_task",
                    severity="warning",
                    message="Non-elastic DNT channel has no registered threshold energy.",
                )
            )
        if "deltaE_products_minus_reactants_eV" in missing_fields:
            items.append(
                MissingDataItem(
                    subject_kind="reaction",
                    subject_id=rxn.id,
                    field="deltaE_products_minus_reactants_eV",
                    required_by="dnt_task",
                    severity="warning",
                    message="Reaction energy is not registered. DNT+/DNT+DM calculation may need it.",
                )
            )

    # Accept the already-built catalog from the generate workflow.  The
    # fallback keeps this public helper convenient for callers and tests.
    for task in dnt_tasks if dnt_tasks is not None else build_dnt_tasks(network):
        for side, properties in task["required_properties"].items():
            for name, prop in properties.items():
                if prop["available"]:
                    continue
                items.append(
                    MissingDataItem(
                        subject_kind="dnt_pair",
                        subject_id=task["pair_id"],
                        field=f"{side}.{name}",
                        required_by="dnt_task",
                        severity="warning",
                        message="Required DNT pair property is unavailable.",
                    )
                )
        missing_dataset_kinds = []
        for output_name, kind in DATASET_OUTPUT_KINDS.items():
            if not any(
                item["available"]
                for item in task["existing_datasets"][output_name]
            ):
                missing_dataset_kinds.append(kind)
        if missing_dataset_kinds:
            items.append(
                MissingDataItem(
                    subject_kind="dnt_pair",
                    subject_id=task["pair_id"],
                    field="data.datasets",
                    required_by="reaction_data_review",
                    severity="info",
                    message=(
                        "No available dataset is registered for: "
                        + ", ".join(missing_dataset_kinds)
                        + "."
                    ),
                )
            )

    return _dedupe_missing_items(items)


def _dedupe_missing_items(items: list[MissingDataItem]) -> list[MissingDataItem]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[MissingDataItem] = []
    for item in items:
        key = (item.subject_kind, item.subject_id, item.field, item.required_by)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
