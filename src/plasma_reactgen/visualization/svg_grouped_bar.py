from __future__ import annotations

from collections.abc import Mapping
from html import escape
from pathlib import Path

from plasma_reactgen.visualization.svg_chart_layout import GroupedBarLayout
from plasma_reactgen.visualization.svg_chart_primitives import (
    AXIS_COLOR,
    FONT_FAMILY,
    GRID_COLOR,
    MUTED_TEXT_COLOR,
    TEXT_COLOR,
    chart_titles,
    color_for_label,
    format_number,
    svg_header,
    svg_text,
)


def render_grouped_bar_chart(
    path: Path,
    title: str,
    subtitle: str | None,
    layout: GroupedBarLayout,
    series: Mapping[str, Mapping[str, int | float]],
    color_map: Mapping[str, str] | None,
) -> list[str]:
    parts = svg_header(
        path,
        title,
        layout.width,
        layout.height,
        "Grouped bar chart with count axis.",
    )
    parts.extend(chart_titles(title, subtitle))
    parts.extend(_grid_and_axes(layout))
    parts.extend(_bars(layout, series, color_map))
    parts.extend(_legend(layout, color_map))
    return parts


def _grid_and_axes(layout: GroupedBarLayout) -> list[str]:
    parts = []
    for tick in layout.ticks:
        y = layout.base_y - layout.chart_height * (tick / layout.tick_max)
        parts.extend(
            [
                f"<line x1='{layout.left}' y1='{y:.2f}' "
                f"x2='{layout.left + layout.chart_width}' y2='{y:.2f}' "
                f"stroke='{GRID_COLOR}' stroke-width='1'/>",
                svg_text(
                    layout.left - 12,
                    y + 4,
                    format_number(tick),
                    size=12,
                    anchor="end",
                    fill=MUTED_TEXT_COLOR,
                ),
            ]
        )
    return [*parts, *_axes(layout)]


def _axes(layout: GroupedBarLayout) -> list[str]:
    middle_y = layout.plot_top + layout.chart_height / 2
    return [
        f"<line x1='{layout.left}' y1='{layout.plot_top}' x2='{layout.left}' "
        f"y2='{layout.base_y}' stroke='{AXIS_COLOR}' stroke-width='1.2'/>",
        f"<line x1='{layout.left}' y1='{layout.base_y}' "
        f"x2='{layout.left + layout.chart_width}' y2='{layout.base_y}' "
        f"stroke='{AXIS_COLOR}' stroke-width='1.2'/>",
        f"<text x='24' y='{middle_y:.2f}' transform='rotate(-90 24 {middle_y:.2f})' "
        f"font-size='13' font-family='{FONT_FAMILY}' fill='{TEXT_COLOR}' "
        "text-anchor='middle'>Count</text>",
    ]


def _bars(
    layout: GroupedBarLayout,
    series: Mapping[str, Mapping[str, int | float]],
    color_map: Mapping[str, str] | None,
) -> list[str]:
    parts = []
    for group_index, group in enumerate(layout.groups):
        group_start = layout.left + group_index * layout.group_width
        parts.append(
            svg_text(
                group_start + layout.group_width / 2,
                layout.base_y + 28,
                group,
                size=12,
                anchor="middle",
            )
        )
        for category_index, category in enumerate(layout.categories):
            parts.extend(
                _bar(
                    layout,
                    group,
                    category,
                    category_index,
                    float(series.get(group, {}).get(category, 0.0)),
                    group_start,
                    color_map,
                )
            )
    return parts


def _bar(
    layout: GroupedBarLayout,
    group: str,
    category: str,
    category_index: int,
    value: float,
    group_start: float,
    color_map: Mapping[str, str] | None,
) -> list[str]:
    height = layout.chart_height * (value / layout.tick_max)
    x = group_start + layout.inner_padding + category_index * (layout.bar_width + layout.bar_gap)
    y = layout.base_y - height
    value_label = format_number(value)
    parts = [
        f"<rect x='{x:.2f}' y='{y:.2f}' width='{layout.bar_width:.2f}' "
        f"height='{height:.2f}' fill='{color_for_label(category, category_index, color_map)}' "
        f"stroke='#1A1A1A' stroke-width='0.4'><title>{escape(group)} / "
        f"{escape(category)}: {escape(value_label)}</title></rect>"
    ]
    if value > 0 and layout.bar_width >= 18:
        parts.append(
            svg_text(
                x + layout.bar_width / 2,
                y - 6,
                value_label,
                size=11,
                anchor="middle",
            )
        )
    return parts


def _legend(
    layout: GroupedBarLayout,
    color_map: Mapping[str, str] | None,
) -> list[str]:
    parts = []
    cursor_x = layout.left
    legend_y = layout.height - 42
    for index, category in enumerate(layout.categories):
        label_width = 28 + max(72, len(category) * 7)
        if cursor_x + label_width > layout.width - layout.right:
            legend_y += 24
            cursor_x = layout.left
        color = color_for_label(category, index, color_map)
        parts.extend(
            [
                f"<rect x='{cursor_x}' y='{legend_y - 12}' width='13' height='13' "
                f"fill='{color}' stroke='#1A1A1A' stroke-width='0.4'/>",
                svg_text(cursor_x + 20, legend_y - 1, category, size=12),
            ]
        )
        cursor_x += label_width
    return parts
