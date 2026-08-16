from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path

from plasma_reactgen.visualization.svg_chart_layout import HorizontalBarLayout
from plasma_reactgen.visualization.svg_chart_primitives import (
    AXIS_COLOR,
    GRID_COLOR,
    MUTED_TEXT_COLOR,
    TEXT_COLOR,
    chart_titles,
    color_for_label,
    format_number,
    svg_header,
    svg_text,
)


def render_horizontal_bar_chart(
    path: Path,
    title: str,
    subtitle: str | None,
    layout: HorizontalBarLayout,
    color_map: Mapping[str, str] | None,
) -> list[str]:
    parts = svg_header(
        path,
        title,
        layout.width,
        layout.height,
        "Horizontal bar chart with count axis.",
    )
    parts.extend(chart_titles(title, subtitle))
    parts.extend(_grid(layout))
    parts.extend(_axes(layout))
    for index, (label, value) in enumerate(layout.items):
        parts.extend(_bar(layout, index, label, value, color_map))
    return parts


def _grid(layout: HorizontalBarLayout) -> list[str]:
    parts = []
    for tick in layout.ticks:
        x = layout.left + layout.chart_width * (tick / layout.tick_max)
        parts.extend(
            [
                f"<line x1='{x:.2f}' y1='{layout.plot_top - 10}' x2='{x:.2f}' "
                f"y2='{layout.axis_y}' stroke='{GRID_COLOR}' stroke-width='1'/>",
                svg_text(
                    x,
                    layout.axis_y + 22,
                    format_number(tick),
                    size=12,
                    anchor="middle",
                    fill=MUTED_TEXT_COLOR,
                ),
            ]
        )
    return parts


def _axes(layout: HorizontalBarLayout) -> list[str]:
    return [
        f"<line x1='{layout.left}' y1='{layout.axis_y}' "
        f"x2='{layout.left + layout.chart_width}' y2='{layout.axis_y}' "
        f"stroke='{AXIS_COLOR}' stroke-width='1.2'/>",
        svg_text(
            layout.left + layout.chart_width / 2,
            min(layout.height - 22, layout.axis_y + 50),
            "Count",
            size=13,
            anchor="middle",
        ),
    ]


def _bar(
    layout: HorizontalBarLayout,
    index: int,
    label: str,
    value: float,
    color_map: Mapping[str, str] | None,
) -> list[str]:
    y = layout.plot_top + index * layout.row_height
    bar_width = layout.chart_width * (value / layout.tick_max)
    value_label = format_number(value)
    value_x, value_anchor, value_fill = _value_label_style(layout, bar_width)
    return [
        svg_text(layout.left - 14, y + 25, label, size=13, anchor="end"),
        f"<rect x='{layout.left}' y='{y + 7}' width='{bar_width:.2f}' height='24' "
        f"fill='{color_for_label(label, index, color_map)}' stroke='#1A1A1A' "
        f"stroke-width='0.4'><title>{escape(label)}: "
        f"{escape(value_label)}</title></rect>",
        svg_text(
            value_x,
            y + 25,
            value_label,
            size=13,
            anchor=value_anchor,
            fill=value_fill,
        ),
    ]


def _value_label_style(
    layout: HorizontalBarLayout,
    bar_width: float,
) -> tuple[float, str, str]:
    outside_x = layout.left + bar_width + 9
    if outside_x > layout.width - 26 and bar_width > 38:
        return layout.left + bar_width - 8, "end", "#FFFFFF"
    return outside_x, "start", TEXT_COLOR
