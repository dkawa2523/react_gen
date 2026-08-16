"""Public missing-data diagnostics assembled from focused collectors."""

from __future__ import annotations

from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.missing_data_collectors import (
    dnt_task_missing_items,
    reaction_missing_items,
    state_missing_items,
)
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork


def build_missing_data(
    network: ReactionNetwork,
    states: list[dict],
    dnt_tasks: list[dict] | None = None,
) -> list[MissingDataItem]:
    """Return each user-actionable gap once, independent of output format."""

    tasks = dnt_tasks if dnt_tasks is not None else build_dnt_tasks(network)
    items = [
        *network.missing_data,
        *state_missing_items(states),
        *reaction_missing_items(network.reactions),
        *dnt_task_missing_items(tasks),
    ]
    return _dedupe_missing_items(items)


def _dedupe_missing_items(
    items: list[MissingDataItem],
) -> list[MissingDataItem]:
    seen: set[tuple[str, str, str, str]] = set()
    unique = []
    for item in items:
        key = (item.subject_kind, item.subject_id, item.field, item.required_by)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


__all__ = ["build_missing_data"]
