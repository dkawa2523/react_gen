from __future__ import annotations

from typing import Any

from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork


def build_missing_data(network: ReactionNetwork, states: list[dict], dnt_tasks: list[dict], registry) -> list[MissingDataItem]:
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
            cs = _nested_get(rxn.data, ["cross_section"])
            if not cs:
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
            else:
                path = cs.get("path")
                if not path:
                    items.append(
                        MissingDataItem(
                            subject_kind="asset",
                            subject_id=rxn.id,
                            field="data.cross_section.path",
                            required_by="electron_collision",
                            severity="warning",
                            message="Cross-section source is registered but numeric table has not been imported yet.",
                        )
                    )
                elif hasattr(registry, "asset_exists") and not registry.asset_exists(path):
                    items.append(
                        MissingDataItem(
                            subject_kind="asset",
                            subject_id=rxn.id,
                            field="data.cross_section.path",
                            required_by="electron_collision",
                            severity="warning",
                            message=f"Registered cross-section path does not exist: {path}",
                        )
                    )

        if rxn.family == "ion_neutral" and rxn.type != "elastic":
            if rxn.deltaE_products_minus_reactants_eV is None:
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

    for task in dnt_tasks:
        missing = task.get("readiness", {}).get("missing", {})
        for side, fields in missing.items():
            for field in fields:
                items.append(
                    MissingDataItem(
                        subject_kind="dnt_task",
                        subject_id=task["pair_id"],
                        field=f"{side}.{field}",
                        required_by="dnt_plus_dm",
                        severity="required",
                        message="DNT+/DNT+DM task is not ready because a required property is missing.",
                    )
                )

    return _dedupe_missing_items(items)


def _nested_get(data: dict[str, Any], path: list[str]):
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


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
