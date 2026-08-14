from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from plasma_reactgen.visualization.models import VisualizationDataset
from plasma_reactgen.visualization.reaction_pathway_layout import (
    CARD_HEIGHT,
    CARD_WIDTH,
    COLUMN_GAP,
    MARGIN_X,
    ReactionPathwayLayout,
    build_reaction_pathway_layout,
)

FAMILY_COLORS = {
    "electron": ("#DBEAFE", "#2563EB"),
    "ion_neutral": ("#FEE2E2", "#DC2626"),
    "neutral_neutral": ("#D1FAE5", "#059669"),
    "ion_ion": ("#EDE9FE", "#7C3AED"),
    "electron_ion": ("#FEF3C7", "#D97706"),
}

FAMILY_LABELS = {
    "electron": "電子衝突",
    "ion_neutral": "イオン・中性",
    "neutral_neutral": "中性・中性",
    "ion_ion": "イオン・イオン",
    "electron_ion": "電子・イオン",
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

    layout = build_reaction_pathway_layout(dataset.reactions)
    lines = _document_header(layout, str(dataset.case.get("name", "case")))
    lines.extend(_depth_headers(layout))
    edge_lines, edge_count = _render_edges(layout)
    lines.extend(edge_lines)
    lines.extend(_render_cards(layout))
    lines.extend(_legend(layout.height))
    lines.append("</svg>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "svg": str(path),
        "reaction_nodes": len(layout.reactions),
        "precursor_edges": edge_count,
        "max_depth": max(layout.depths, default=0),
    }


def _document_header(layout: ReactionPathwayLayout, case_name: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" '
        f'height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}">',
        "<defs>",
        '<marker id="reaction-arrow" markerWidth="8" markerHeight="8" '
        'refX="7" refY="4" orient="auto">',
        '<path d="M0,0 L8,4 L0,8 z" fill="#64748B"/>',
        "</marker>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        _text(40, 42, f"反応経路図: {case_name}", 24, weight=700),
        _text(40, 70, "各枠は反応式、矢印は前段反応からの到達関係を示す", 13, fill="#475569"),
    ]


def _depth_headers(layout: ReactionPathwayLayout) -> list[str]:
    return [
        _text(
            MARGIN_X + column * (CARD_WIDTH + COLUMN_GAP) + CARD_WIDTH / 2,
            105,
            f"深さ {depth}",
            15,
            anchor="middle",
            weight=700,
        )
        for column, depth in enumerate(layout.depths)
    ]


def _render_edges(layout: ReactionPathwayLayout) -> tuple[list[str], int]:
    lines = []
    for reaction in layout.reactions:
        reaction_id = str(reaction.get("id"))
        for precursor_id in _precursor_ids(reaction):
            if precursor_id not in layout.positions:
                continue
            lines.append(_edge_svg(precursor_id, reaction_id, layout.positions))
    return lines, len(lines)


def _precursor_ids(reaction: dict[str, Any]) -> list[str]:
    return sorted(str(value) for value in reaction.get("precursor_reaction_ids", []) or [])


def _edge_svg(
    precursor_id: str,
    reaction_id: str,
    positions: dict[str, tuple[float, float]],
) -> str:
    source_x, source_y = positions[precursor_id]
    target_x, target_y = positions[reaction_id]
    x1 = source_x + CARD_WIDTH
    y1 = source_y + CARD_HEIGHT / 2
    x2 = target_x
    y2 = target_y + CARD_HEIGHT / 2
    bend = max(35, abs(x2 - x1) * 0.45)
    path_d = (
        f"M {x1:.1f} {y1:.1f} C {x1 + bend:.1f} {y1:.1f}, "
        f"{x2 - bend:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
    )
    return (
        f'<path d="{path_d}" fill="none" stroke="#64748B" stroke-width="1.5" '
        f'opacity="0.7" marker-end="url(#reaction-arrow)"><title>'
        f"{escape(precursor_id)} → {escape(reaction_id)}</title></path>"
    )


def _render_cards(layout: ReactionPathwayLayout) -> list[str]:
    lines = []
    for reaction in layout.reactions:
        reaction_id = str(reaction.get("id"))
        lines.extend(_card_svg(reaction, layout.positions[reaction_id]))
    return lines


def _card_svg(
    reaction: dict[str, Any],
    position: tuple[float, float],
) -> list[str]:
    reaction_id = str(reaction.get("id"))
    family = str(reaction.get("family", "unknown"))
    reaction_type = str(reaction.get("type", "unknown"))
    fill, stroke = FAMILY_COLORS.get(family, ("#F1F5F9", "#64748B"))
    equation = str(reaction.get("equation", reaction_id))
    class_label = (
        f"{FAMILY_LABELS.get(family, family)} / {TYPE_LABELS.get(reaction_type, reaction_type)}"
    )
    x, y = position
    lines = [
        f"<g><title>{escape(f'{reaction_id} | {equation} | {class_label}')}</title>",
        f'<rect x="{x}" y="{y}" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" rx="10" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.7"/>',
        _text(x + 14, y + 20, _shorten(reaction_id, 46), 10, fill="#475569"),
    ]
    lines.extend(
        _text(x + 14, y + 45 + offset * 18, part, 14, weight=700)
        for offset, part in enumerate(_wrap_equation(equation))
    )
    lines.extend([_text(x + 14, y + 84, class_label, 10, fill=stroke), "</g>"])
    return lines


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
        lines.append(
            f'<rect x="{x}" y="{height - 34}" width="16" height="12" rx="2" '
            f'fill="{fill}" stroke="{stroke}"/>'
        )
        lines.append(
            _text(x + 22, height - 23, FAMILY_LABELS.get(family, family), 10, fill="#334155")
        )
        x += 160
    return lines
