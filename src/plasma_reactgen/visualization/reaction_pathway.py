from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any

from plasma_reactgen.visualization.models import VisualizationDataset


FAMILY_COLORS = {
    "electron": ("#DBEAFE", "#2563EB"),
    "ion_neutral": ("#FEE2E2", "#DC2626"),
    "neutral_neutral": ("#D1FAE5", "#059669"),
    "ion_ion": ("#EDE9FE", "#7C3AED"),
    "electron_ion": ("#FEF3C7", "#D97706"),
}

FAMILY_LABELS = {
    "electron": "電子衝突",
    "ion_neutral": "イオン–中性",
    "neutral_neutral": "中性–中性",
    "ion_ion": "イオン–イオン",
    "electron_ion": "電子–イオン",
}

TYPE_LABELS = {
    "elastic": "弾性",
    "ionization": "電離",
    "excitation": "励起",
    "dissociation": "解離",
    "attachment": "付着",
    "charge_transfer": "電荷移行",
    "dissociative_charge_transfer": "解離性電荷移行",
    "association": "会合",
    "reactive_scattering": "反応性散乱",
    "mutual_neutralization": "相互中和",
    "dissociative_recombination": "解離性再結合",
}


def write_reaction_pathway_svg(
    dataset: VisualizationDataset,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Write a reaction-node lineage graph whose cards show equations.

    The species graph remains useful for connectivity.  This companion view
    instead uses reactions as nodes and precursor ids as directed edges, so a
    reviewer can read both the equation and the generation path.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "reaction_equation_network.svg"

    reactions = sorted(
        dataset.reactions,
        key=lambda item: (_depth(item), str(item.get("id", ""))),
    )
    by_depth: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for reaction in reactions:
        by_depth[_depth(reaction)].append(reaction)

    card_width = 340
    card_height = 94
    column_gap = 80
    row_gap = 24
    margin_x = 48
    top = 128
    depths = sorted(by_depth)
    max_rows = max((len(items) for items in by_depth.values()), default=1)
    width = max(900, margin_x * 2 + len(depths) * card_width + max(0, len(depths) - 1) * column_gap)
    height = max(620, top + max_rows * (card_height + row_gap) + 70)

    positions: dict[str, tuple[float, float]] = {}
    for column, depth in enumerate(depths):
        x = margin_x + column * (card_width + column_gap)
        for row, reaction in enumerate(by_depth[depth]):
            positions[str(reaction.get("id"))] = (x, top + row * (card_height + row_gap))

    case_name = str(dataset.case.get("name", "case"))
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<defs>",
        '<marker id="reaction-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">',
        '<path d="M0,0 L8,4 L0,8 z" fill="#64748B"/>',
        "</marker>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        _text(40, 42, f"反応経路図: {case_name}", 24, weight=700),
        _text(40, 70, "各枠は反応式、矢印は前段反応からの到達関係を示す", 13, fill="#475569"),
    ]

    for column, depth in enumerate(depths):
        x = margin_x + column * (card_width + column_gap)
        lines.append(_text(x + card_width / 2, 105, f"深さ {depth}", 15, anchor="middle", weight=700))

    reaction_by_id = {str(item.get("id")): item for item in reactions}
    edge_count = 0
    for reaction in reactions:
        reaction_id = str(reaction.get("id"))
        if reaction_id not in positions:
            continue
        target_x, target_y = positions[reaction_id]
        for precursor_id in sorted(str(value) for value in reaction.get("precursor_reaction_ids", []) or []):
            if precursor_id not in positions or precursor_id not in reaction_by_id:
                continue
            source_x, source_y = positions[precursor_id]
            x1 = source_x + card_width
            y1 = source_y + card_height / 2
            x2 = target_x
            y2 = target_y + card_height / 2
            bend = max(35, abs(x2 - x1) * 0.45)
            path_d = f"M {x1:.1f} {y1:.1f} C {x1 + bend:.1f} {y1:.1f}, {x2 - bend:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
            lines.append(
                f'<path d="{path_d}" fill="none" stroke="#64748B" stroke-width="1.5" '
                f'opacity="0.7" marker-end="url(#reaction-arrow)"><title>{escape(precursor_id)} → {escape(reaction_id)}</title></path>'
            )
            edge_count += 1

    for reaction in reactions:
        reaction_id = str(reaction.get("id"))
        x, y = positions[reaction_id]
        family = str(reaction.get("family", "unknown"))
        reaction_type = str(reaction.get("type", "unknown"))
        fill, stroke = FAMILY_COLORS.get(family, ("#F1F5F9", "#64748B"))
        equation = str(reaction.get("equation", reaction_id))
        equation_lines = _wrap_equation(equation)
        class_label = f"{FAMILY_LABELS.get(family, family)} / {TYPE_LABELS.get(reaction_type, reaction_type)}"
        tooltip = f"{reaction_id} | {equation} | {class_label}"
        lines.append(f"<g><title>{escape(tooltip)}</title>")
        lines.append(
            f'<rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" rx="10" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.7"/>'
        )
        lines.append(_text(x + 14, y + 20, _shorten(reaction_id, 46), 10, fill="#475569"))
        for offset, part in enumerate(equation_lines):
            lines.append(_text(x + 14, y + 45 + offset * 18, part, 14, weight=700))
        lines.append(
            _text(
                x + 14,
                y + 84,
                class_label,
                10,
                fill=stroke,
            )
        )
        lines.append("</g>")

    lines.extend(_legend(height))
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "svg": str(path),
        "reaction_nodes": len(reactions),
        "precursor_edges": edge_count,
        "max_depth": max(depths, default=0),
    }


def _depth(reaction: dict[str, Any]) -> int:
    try:
        return int(reaction.get("depth", 0))
    except (TypeError, ValueError):
        return 0


def _wrap_equation(equation: str, limit: int = 38) -> list[str]:
    if len(equation) <= limit:
        return [equation]
    tokens = equation.split()
    lines: list[str] = []
    current: list[str] = []
    for token in tokens:
        candidate = " ".join([*current, token])
        if current and len(candidate) > limit:
            lines.append(" ".join(current))
            current = [token]
        else:
            current.append(token)
    if current:
        lines.append(" ".join(current))
    if len(lines) <= 2:
        return lines
    return [lines[0], _shorten(" ".join(lines[1:]), limit)]


def _shorten(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _text(
    x: float,
    y: float,
    value: str,
    size: int,
    *,
    fill: str = "#0F172A",
    anchor: str = "start",
    weight: int = 400,
) -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}">{escape(value)}</text>'
    )


def _legend(height: int) -> list[str]:
    lines: list[str] = []
    x = 40
    for family, (fill, stroke) in FAMILY_COLORS.items():
        lines.append(f'<rect x="{x}" y="{height - 34}" width="16" height="12" rx="2" fill="{fill}" stroke="{stroke}"/>')
        lines.append(_text(x + 22, height - 23, FAMILY_LABELS.get(family, family), 10, fill="#334155"))
        x += 160
    return lines
