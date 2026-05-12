from __future__ import annotations

from collections.abc import Mapping
from html import escape
from math import ceil, floor, log10
from pathlib import Path
import re


FONT_FAMILY = "Arial, Helvetica, sans-serif"
TEXT_COLOR = "#222222"
MUTED_TEXT_COLOR = "#555555"
AXIS_COLOR = "#333333"
GRID_COLOR = "#D9D9D9"
BACKGROUND_COLOR = "#FFFFFF"

# Okabe-Ito colorblind-safe palette, suitable for print and projection.
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


def write_horizontal_bar_chart(
    path: str | Path,
    title: str,
    values: Mapping[str, int | float],
    *,
    subtitle: str | None = None,
    color_map: Mapping[str, str] | None = None,
    width: int = 1120,
    min_height: int = 300,
    sort_by_value: bool = True,
    max_items: int | None = None,
) -> None:
    """Write a publication-oriented SVG horizontal bar chart.

    The chart deliberately uses vector text, explicit axes, light grid lines,
    a colorblind-safe palette, and generous margins so the output can be reused
    in manuscripts without further post-processing.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    items = [(str(k), float(v)) for k, v in values.items() if float(v) != 0.0]
    if sort_by_value:
        items.sort(key=lambda x: (-x[1], x[0]))
    else:
        items.sort(key=lambda x: x[0])

    if max_items is not None and len(items) > max_items:
        kept = items[:max_items]
        other_value = sum(v for _, v in items[max_items:])
        items = kept + [("Other", other_value)]

    if not items:
        items = [("No data", 0.0)]

    row_h = 42
    title_y = 34
    subtitle_y = 58
    plot_top = 92 if subtitle else 70
    plot_bottom = plot_top + row_h * len(items)
    bottom = 74
    left = 340
    right = 116
    height = max(min_height, plot_bottom + bottom)
    chart_w = max(160, width - left - right)
    tick_max = _tick_max(max(v for _, v in items))
    ticks = _tick_values(tick_max)
    axis_y = plot_bottom + 8

    parts = _svg_header(path, title, width, height, "Horizontal bar chart with count axis.")
    parts.append(_text(28, title_y, title, size=21, weight="700"))
    if subtitle:
        parts.append(_text(28, subtitle_y, subtitle, size=12, fill=MUTED_TEXT_COLOR))

    for tick in ticks:
        x = left + chart_w * (tick / tick_max)
        parts.append(f"<line x1='{x:.2f}' y1='{plot_top - 10}' x2='{x:.2f}' y2='{axis_y}' stroke='{GRID_COLOR}' stroke-width='1'/>")
        parts.append(_text(x, axis_y + 22, _format_number(tick), size=12, anchor="middle", fill=MUTED_TEXT_COLOR))

    axis_label_y = min(height - 22, axis_y + 50)
    parts.append(f"<line x1='{left}' y1='{axis_y}' x2='{left + chart_w}' y2='{axis_y}' stroke='{AXIS_COLOR}' stroke-width='1.2'/>")
    parts.append(_text(left + chart_w / 2, axis_label_y, "Count", size=13, anchor="middle", fill=TEXT_COLOR))

    for idx, (label, value) in enumerate(items):
        y = plot_top + idx * row_h
        bar_w = 0 if tick_max == 0 else chart_w * (value / tick_max)
        color = _color_for_label(label, idx, color_map)
        value_label = _format_number(value)
        label_y = y + 25

        parts.append(_text(left - 14, label_y, label, size=13, anchor="end"))
        parts.append(
            f"<rect x='{left}' y='{y + 7}' width='{bar_w:.2f}' height='24' "
            f"fill='{color}' stroke='#1A1A1A' stroke-width='0.4'>"
            f"<title>{escape(label)}: {escape(value_label)}</title></rect>"
        )

        value_x = left + bar_w + 9
        value_anchor = "start"
        value_fill = TEXT_COLOR
        if value_x > width - 26 and bar_w > 38:
            value_x = left + bar_w - 8
            value_anchor = "end"
            value_fill = "#FFFFFF"
        parts.append(_text(value_x, label_y, value_label, size=13, anchor=value_anchor, fill=value_fill))

    path.write_text("\n".join(parts) + "\n</svg>\n", encoding="utf-8")


def write_grouped_bar_chart(
    path: str | Path,
    title: str,
    series: Mapping[str, Mapping[str, int | float]],
    *,
    subtitle: str | None = None,
    color_map: Mapping[str, str] | None = None,
    width: int = 1080,
    min_height: int = 440,
) -> None:
    """Write a publication-oriented SVG grouped bar chart.

    ``series`` is ``group_label -> category -> value``. The chart is optimized
    for small grouped summaries such as depth x reaction-family counts.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    groups = list(series.keys())
    categories = sorted({cat for values in series.values() for cat in values.keys()})
    if not groups:
        write_horizontal_bar_chart(path, title, {}, subtitle=subtitle, color_map=color_map, width=width, min_height=min_height)
        return

    title_y = 34
    subtitle_y = 58
    plot_top = 98 if subtitle else 76
    left = 96
    right = 48
    bottom = 110
    height = max(min_height, plot_top + 260 + bottom)
    chart_h = height - plot_top - bottom
    chart_w = width - left - right
    base_y = plot_top + chart_h
    group_w = chart_w / max(len(groups), 1)
    bar_gap = 7
    inner_pad = 22
    bar_w = max(10, (group_w - inner_pad * 2) / max(len(categories), 1) - bar_gap)
    raw_max = max((float(v) for values in series.values() for v in values.values()), default=1.0)
    tick_max = _tick_max(raw_max)
    ticks = _tick_values(tick_max)

    parts = _svg_header(path, title, width, height, "Grouped bar chart with count axis.")
    parts.append(_text(28, title_y, title, size=21, weight="700"))
    if subtitle:
        parts.append(_text(28, subtitle_y, subtitle, size=12, fill=MUTED_TEXT_COLOR))

    for tick in ticks:
        y = base_y - chart_h * (tick / tick_max)
        parts.append(f"<line x1='{left}' y1='{y:.2f}' x2='{left + chart_w}' y2='{y:.2f}' stroke='{GRID_COLOR}' stroke-width='1'/>")
        parts.append(_text(left - 12, y + 4, _format_number(tick), size=12, anchor="end", fill=MUTED_TEXT_COLOR))

    parts.append(f"<line x1='{left}' y1='{plot_top}' x2='{left}' y2='{base_y}' stroke='{AXIS_COLOR}' stroke-width='1.2'/>")
    parts.append(f"<line x1='{left}' y1='{base_y}' x2='{left + chart_w}' y2='{base_y}' stroke='{AXIS_COLOR}' stroke-width='1.2'/>")
    parts.append(
        f"<text x='24' y='{plot_top + chart_h / 2:.2f}' transform='rotate(-90 24 {plot_top + chart_h / 2:.2f})' "
        f"font-size='13' font-family='{FONT_FAMILY}' fill='{TEXT_COLOR}' text-anchor='middle'>Count</text>"
    )

    for gi, group in enumerate(groups):
        group_start = left + gi * group_w
        gx = group_start + inner_pad
        group_center = group_start + group_w / 2
        parts.append(_text(group_center, base_y + 28, group, size=12, anchor="middle"))

        for ci, cat in enumerate(categories):
            value = float(series.get(group, {}).get(cat, 0.0))
            h = 0 if tick_max == 0 else chart_h * (value / tick_max)
            x = gx + ci * (bar_w + bar_gap)
            y = base_y - h
            color = _color_for_label(cat, ci, color_map)
            value_label = _format_number(value)
            parts.append(
                f"<rect x='{x:.2f}' y='{y:.2f}' width='{bar_w:.2f}' height='{h:.2f}' "
                f"fill='{color}' stroke='#1A1A1A' stroke-width='0.4'>"
                f"<title>{escape(group)} / {escape(cat)}: {escape(value_label)}</title></rect>"
            )
            if value > 0 and bar_w >= 18:
                parts.append(_text(x + bar_w / 2, y - 6, value_label, size=11, anchor="middle", fill=TEXT_COLOR))

    legend_y = height - 42
    legend_x = left
    cursor_x = legend_x
    for ci, cat in enumerate(categories):
        color = _color_for_label(cat, ci, color_map)
        label_w = 28 + max(72, len(cat) * 7)
        if cursor_x + label_w > width - right:
            legend_y += 24
            cursor_x = legend_x
        parts.append(f"<rect x='{cursor_x}' y='{legend_y - 12}' width='13' height='13' fill='{color}' stroke='#1A1A1A' stroke-width='0.4'/>")
        parts.append(_text(cursor_x + 20, legend_y - 1, cat, size=12))
        cursor_x += label_w

    path.write_text("\n".join(parts) + "\n</svg>\n", encoding="utf-8")


def _svg_header(path: Path, title: str, width: int, height: int, desc: str) -> list[str]:
    chart_id = _safe_id(path.stem)
    return [
        (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
            f"viewBox='0 0 {width} {height}' role='img' aria-labelledby='{chart_id}-title {chart_id}-desc'>"
        ),
        f"<title id='{chart_id}-title'>{escape(title)}</title>",
        f"<desc id='{chart_id}-desc'>{escape(desc)}</desc>",
        f"<rect width='100%' height='100%' fill='{BACKGROUND_COLOR}'/>",
    ]


def _text(
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


def _tick_max(value: float) -> float:
    if value <= 0:
        return 1.0
    step = _nice_number(value / 4, round_to_nearest=True)
    return step * ceil(value / step)


def _tick_values(tick_max: float) -> list[float]:
    step = _nice_number(tick_max / 4, round_to_nearest=True)
    ticks: list[float] = []
    current = 0.0
    while current <= tick_max + step * 0.5:
        ticks.append(round(current, 10))
        current += step
    if ticks[-1] < tick_max:
        ticks.append(tick_max)
    return ticks


def _nice_number(value: float, *, round_to_nearest: bool) -> float:
    if value <= 0:
        return 1.0
    exponent = floor(log10(value))
    fraction = value / (10**exponent)
    if round_to_nearest:
        if fraction < 1.5:
            nice_fraction = 1
        elif fraction < 3:
            nice_fraction = 2
        elif fraction < 7:
            nice_fraction = 5
        else:
            nice_fraction = 10
    else:
        if fraction <= 1:
            nice_fraction = 1
        elif fraction <= 2:
            nice_fraction = 2
        elif fraction <= 5:
            nice_fraction = 5
        else:
            nice_fraction = 10
    return nice_fraction * (10**exponent)


def _format_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.3g}"


def _color_for_label(label: str, idx: int, color_map: Mapping[str, str] | None) -> str:
    if color_map and label in color_map:
        return color_map[label]
    return DEFAULT_PALETTE[idx % len(DEFAULT_PALETTE)]


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return safe or "chart"
