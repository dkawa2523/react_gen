from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from plasma_reactgen.visualization.models import VisualizationDataset
from plasma_reactgen.visualization.svg_charts import write_grouped_bar_chart, write_horizontal_bar_chart


ChartBuilder = Callable[[VisualizationDataset, Path], Path | None]


FAMILY_COLORS = {
    "electron": "#0072B2",
    "ion_neutral": "#D55E00",
    "unknown": "#777777",
}

CHARGE_COLORS = {
    "0": "#7A7A7A",
    "+1": "#0072B2",
    "-1": "#D55E00",
    "unknown": "#999999",
}

CLASS_COLORS = {
    "neutral": "#7A7A7A",
    "radical": "#009E73",
    "positive_ion": "#0072B2",
    "negative_ion": "#D55E00",
    "atom": "#C9C9C9",
    "molecule": "#BDBDBD",
    "molecular_ion": "#A6A6A6",
}

STATUS_COLORS = {
    "found": "#009E73",
    "missing": "#D55E00",
    "other": "#999999",
    "unknown": "#999999",
}

READINESS_COLORS = {
    "ready": "#009E73",
    "missing_properties": "#D55E00",
    "unknown": "#999999",
}

MISSING_SEVERITY_COLORS = {
    "required": "#D55E00",
    "warning": "#E69F00",
    "error": "#CC0000",
    "unknown": "#999999",
}


@dataclass(frozen=True)
class ChartSpec:
    """A single statistical chart definition.

    Add or remove plots by editing ``default_chart_specs``; each builder is a
    small function that consumes ``VisualizationDataset`` and writes one file.
    """

    name: str
    description: str
    builder: ChartBuilder


def default_chart_specs() -> list[ChartSpec]:
    return [
        ChartSpec("reaction_family_counts", "Reaction count split by collision family", _chart_reaction_family_counts),
        ChartSpec("reaction_type_counts", "Reaction count split by reaction type", _chart_reaction_type_counts),
        ChartSpec("reaction_depth_by_family", "Reaction expansion depth grouped by family", _chart_reaction_depth_by_family),
        ChartSpec("species_charge_counts", "Species count split by charge", _chart_species_charge_counts),
        ChartSpec("species_class_counts", "Species count split by species class", _chart_species_class_counts),
        ChartSpec("species_depth_counts", "Species first-seen depth distribution", _chart_species_depth_counts),
        ChartSpec("coverage_status_counts", "Candidate pair coverage by status/family", _chart_coverage_status_counts),
        ChartSpec("dnt_readiness_counts", "DNT+/DNT+DM task readiness", _chart_dnt_readiness_counts),
        ChartSpec("missing_data_counts", "Missing data count by subject/severity", _chart_missing_data_counts),
    ]


def write_statistical_charts(dataset: VisualizationDataset, output_dir: str | Path) -> list[dict[str, str]]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[dict[str, str]] = []
    for spec in default_chart_specs():
        path = spec.builder(dataset, output_dir)
        if path is not None:
            written.append({"name": spec.name, "description": spec.description, "path": str(path)})
    return written


def _chart_reaction_family_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts = Counter(str(r.get("family", "unknown")) for r in dataset.reactions)
    path = output_dir / "reaction_family_counts.svg"
    write_horizontal_bar_chart(
        path,
        "Reaction counts by family",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=FAMILY_COLORS,
        sort_by_value=False,
    )
    return path


def _chart_reaction_type_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts = Counter(f"{r.get('family', 'unknown')}:{r.get('type', 'unknown')}" for r in dataset.reactions)
    path = output_dir / "reaction_type_counts.svg"
    write_horizontal_bar_chart(
        path,
        "Reaction counts by type",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=_prefix_color_map(counts, FAMILY_COLORS),
        max_items=18,
    )
    return path


def _chart_reaction_depth_by_family(dataset: VisualizationDataset, output_dir: Path) -> Path:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in dataset.reactions:
        grouped[f"depth {r.get('depth', 'unknown')}"][str(r.get("family", "unknown"))] += 1
    path = output_dir / "reaction_depth_by_family.svg"
    write_grouped_bar_chart(
        path,
        "Reaction counts by depth and family",
        dict(grouped),
        subtitle=_case_subtitle(dataset),
        color_map=FAMILY_COLORS,
    )
    return path


def _chart_species_charge_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts = Counter(_charge_label(s.get("charge")) for s in dataset.states)
    path = output_dir / "species_charge_counts.svg"
    write_horizontal_bar_chart(
        path,
        "Species counts by charge",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=CHARGE_COLORS,
        sort_by_value=False,
    )
    return path


def _chart_species_class_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts: Counter[str] = Counter()
    for state in dataset.states:
        for cls in state.get("classes", []) or []:
            counts[str(cls)] += 1
    path = output_dir / "species_class_counts.svg"
    write_horizontal_bar_chart(
        path,
        "Species counts by class",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=CLASS_COLORS,
        max_items=18,
    )
    return path


def _chart_species_depth_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts = Counter(f"depth {s.get('depth_first_seen', 'unknown')}" for s in dataset.states)
    path = output_dir / "species_depth_counts.svg"
    write_horizontal_bar_chart(
        path,
        "Species first-seen depth",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=_depth_color_map(counts),
        sort_by_value=False,
    )
    return path


def _chart_coverage_status_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for status, pairs in dataset.coverage_pairs.items():
        for p in pairs or []:
            grouped[str(p.get("family", "unknown"))][str(status)] += 1
    path = output_dir / "coverage_status_counts.svg"
    write_grouped_bar_chart(
        path,
        "Candidate pair coverage",
        dict(grouped),
        subtitle=_case_subtitle(dataset),
        color_map=STATUS_COLORS,
    )
    return path


def _chart_dnt_readiness_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts = Counter(str(t.get("readiness", {}).get("status", "unknown")) for t in dataset.dnt_tasks)
    path = output_dir / "dnt_readiness_counts.svg"
    write_horizontal_bar_chart(
        path,
        "DNT+/DNT+DM task readiness",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=READINESS_COLORS,
        sort_by_value=False,
    )
    return path


def _chart_missing_data_counts(dataset: VisualizationDataset, output_dir: Path) -> Path:
    counts = Counter(f"{m.get('severity', 'unknown')}:{m.get('subject_kind', 'unknown')}" for m in dataset.missing_data)
    path = output_dir / "missing_data_counts.svg"
    write_horizontal_bar_chart(
        path,
        "Missing data by severity and subject",
        counts,
        subtitle=_case_subtitle(dataset),
        color_map=_prefix_color_map(counts, MISSING_SEVERITY_COLORS),
        max_items=18,
    )
    return path


def _case_subtitle(dataset: VisualizationDataset) -> str:
    case_name = dataset.case.get("name", "case")
    n_species = len(dataset.states)
    n_reactions = len(dataset.reactions)
    return f"case={case_name} / species={n_species} / reactions={n_reactions}"


def _charge_label(charge) -> str:
    if charge is None:
        return "unknown"
    try:
        charge_i = int(charge)
    except (TypeError, ValueError):
        return str(charge)
    if charge_i > 0:
        return f"+{charge_i}"
    return str(charge_i)


def _prefix_color_map(labels: Counter[str], colors: dict[str, str]) -> dict[str, str]:
    return {label: colors.get(label.split(":", 1)[0], colors.get("unknown", "#999999")) for label in labels}


def _depth_color_map(labels: Counter[str]) -> dict[str, str]:
    shades = ["#D9EAF7", "#9ECAE1", "#4292C6", "#08519C"]
    sorted_labels = sorted(labels)
    return {label: shades[min(idx, len(shades) - 1)] for idx, label in enumerate(sorted_labels)}
