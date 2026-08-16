from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from plasma_reactgen.visualization.svg_chart_scale import tick_max, tick_values


@dataclass(frozen=True)
class HorizontalBarLayout:
    items: list[tuple[str, float]]
    width: int
    height: int
    plot_top: int
    plot_bottom: int
    left: int
    chart_width: int
    row_height: int
    tick_max: float
    ticks: list[float]
    axis_y: int


@dataclass(frozen=True)
class GroupedBarLayout:
    groups: list[str]
    categories: list[str]
    width: int
    height: int
    plot_top: int
    left: int
    right: int
    chart_height: int
    chart_width: int
    base_y: int
    group_width: float
    bar_width: float
    bar_gap: int
    inner_padding: int
    tick_max: float
    ticks: list[float]


def build_horizontal_bar_layout(
    values: Mapping[str, int | float],
    *,
    has_subtitle: bool,
    width: int,
    min_height: int,
    sort_by_value: bool,
    max_items: int | None,
) -> HorizontalBarLayout:
    items = _horizontal_items(values, sort_by_value, max_items)
    row_height = 42
    plot_top = 92 if has_subtitle else 70
    plot_bottom = plot_top + row_height * len(items)
    left = 340
    right = 116
    maximum = tick_max(max(value for _, value in items))
    return HorizontalBarLayout(
        items=items,
        width=width,
        height=max(min_height, plot_bottom + 74),
        plot_top=plot_top,
        plot_bottom=plot_bottom,
        left=left,
        chart_width=max(160, width - left - right),
        row_height=row_height,
        tick_max=maximum,
        ticks=tick_values(maximum),
        axis_y=plot_bottom + 8,
    )


def build_grouped_bar_layout(
    series: Mapping[str, Mapping[str, int | float]],
    *,
    has_subtitle: bool,
    width: int,
    min_height: int,
) -> GroupedBarLayout:
    groups = list(series)
    categories = sorted({category for values in series.values() for category in values})
    plot_top = 98 if has_subtitle else 76
    left = 96
    right = 48
    bottom = 110
    height = max(min_height, plot_top + 260 + bottom)
    chart_height = height - plot_top - bottom
    chart_width = width - left - right
    group_width = chart_width / max(len(groups), 1)
    bar_gap = 7
    inner_padding = 22
    bar_width = max(
        10,
        (group_width - inner_padding * 2) / max(len(categories), 1) - bar_gap,
    )
    maximum = tick_max(
        max((float(value) for values in series.values() for value in values.values()), default=1.0)
    )
    return GroupedBarLayout(
        groups=groups,
        categories=categories,
        width=width,
        height=height,
        plot_top=plot_top,
        left=left,
        right=right,
        chart_height=chart_height,
        chart_width=chart_width,
        base_y=plot_top + chart_height,
        group_width=group_width,
        bar_width=bar_width,
        bar_gap=bar_gap,
        inner_padding=inner_padding,
        tick_max=maximum,
        ticks=tick_values(maximum),
    )


def _horizontal_items(
    values: Mapping[str, int | float],
    sort_by_value: bool,
    max_items: int | None,
) -> list[tuple[str, float]]:
    items = [(str(label), float(value)) for label, value in values.items() if float(value)]
    items.sort(key=(lambda item: (-item[1], item[0])) if sort_by_value else lambda item: item[0])
    if max_items is not None and len(items) > max_items:
        items = [*items[:max_items], ("Other", sum(value for _, value in items[max_items:]))]
    return items or [("No data", 0.0)]
