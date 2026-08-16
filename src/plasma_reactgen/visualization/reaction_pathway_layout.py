from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

CARD_WIDTH = 340
CARD_HEIGHT = 94
COLUMN_GAP = 80
ROW_GAP = 24
MARGIN_X = 48
TOP = 128


@dataclass(frozen=True)
class ReactionPathwayLayout:
    reactions: list[dict[str, Any]]
    depths: list[int]
    positions: dict[str, tuple[float, float]]
    width: int
    height: int


def build_reaction_pathway_layout(
    reactions: Iterable[dict[str, Any]],
) -> ReactionPathwayLayout:
    ordered = sorted(reactions, key=lambda item: (_depth(item), str(item.get("id", ""))))
    by_depth: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for reaction in ordered:
        by_depth[_depth(reaction)].append(reaction)

    depths = sorted(by_depth)
    max_rows = max((len(items) for items in by_depth.values()), default=1)
    width = max(
        900,
        MARGIN_X * 2 + len(depths) * CARD_WIDTH + max(0, len(depths) - 1) * COLUMN_GAP,
    )
    height = max(620, TOP + max_rows * (CARD_HEIGHT + ROW_GAP) + 70)
    return ReactionPathwayLayout(
        reactions=ordered,
        depths=depths,
        positions=_positions(by_depth, depths),
        width=width,
        height=height,
    )


def _positions(
    by_depth: dict[int, list[dict[str, Any]]],
    depths: list[int],
) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    for column, depth in enumerate(depths):
        x = MARGIN_X + column * (CARD_WIDTH + COLUMN_GAP)
        for row, reaction in enumerate(by_depth[depth]):
            positions[str(reaction.get("id"))] = (x, TOP + row * (CARD_HEIGHT + ROW_GAP))
    return positions


def _depth(reaction: dict[str, Any]) -> int:
    try:
        return int(reaction.get("depth", 0))
    except (TypeError, ValueError):
        return 0
