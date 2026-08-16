from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from pathlib import Path

FONT_FAMILY = "Arial, Helvetica, sans-serif"
TEXT_COLOR = "#222222"
MUTED_TEXT_COLOR = "#555555"
AXIS_COLOR = "#333333"
GRID_COLOR = "#D9D9D9"
BACKGROUND_COLOR = "#FFFFFF"

DEFAULT_PALETTE = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#56B4E9",
    "#E69F00",
    "#F0E442",
    "#000000",
]


def prepare_svg_output(path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def write_svg(path: Path, parts: list[str]) -> None:
    path.write_text("\n".join([*parts, "</svg>"]) + "\n", encoding="utf-8")


def svg_header(path: Path, title: str, width: int, height: int, description: str) -> list[str]:
    chart_id = safe_svg_id(path.stem)
    return [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' role='img' "
        f"aria-labelledby='{chart_id}-title {chart_id}-desc'>",
        f"<title id='{chart_id}-title'>{escape(title)}</title>",
        f"<desc id='{chart_id}-desc'>{escape(description)}</desc>",
        f"<rect width='100%' height='100%' fill='{BACKGROUND_COLOR}'/>",
    ]


def chart_titles(title: str, subtitle: str | None) -> list[str]:
    parts = [svg_text(28, 34, title, size=21, weight="700")]
    if subtitle:
        parts.append(svg_text(28, 58, subtitle, size=12, fill=MUTED_TEXT_COLOR))
    return parts


def svg_text(
    x: float,
    y: float,
    value: str,
    *,
    size: int,
    fill: str = TEXT_COLOR,
    anchor: str = "start",
    weight: str | None = None,
) -> str:
    weight_attr = f" font-weight='{weight}'" if weight else ""
    return (
        f"<text x='{x:.2f}' y='{y:.2f}' text-anchor='{anchor}' font-size='{size}' "
        f"font-family='{FONT_FAMILY}' fill='{fill}'{weight_attr}>{escape(str(value))}</text>"
    )


def format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return f"{value:.3g}"


def color_for_label(
    label: str,
    index: int,
    color_map: Mapping[str, str] | None,
) -> str:
    if color_map and label in color_map:
        return color_map[label]
    return DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)]


def safe_svg_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return safe or "chart"
