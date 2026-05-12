from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import yaml

from plasma_reactgen.visualization.models import VisualizationDataset


def load_visualization_dataset(output_dir: str | Path) -> VisualizationDataset:
    """Load generated output files from a case output directory.

    Missing optional files are tolerated so visualization can be used on partial
    outputs. Required semantic data are simply represented as empty lists.
    """

    output_dir = Path(output_dir)

    reactions_payload = _read_yaml(output_dir / "network.reactions.yaml")
    states_payload = _read_yaml(output_dir / "network.states.yaml")
    coverage_payload = _read_yaml(output_dir / "coverage_report.yaml")
    dnt_payload = _read_yaml(output_dir / "dnt_tasks.yaml")
    missing_payload = _read_yaml(output_dir / "missing_data.yaml")
    summary_payload = _read_json(output_dir / "summary.json")

    case = (
        reactions_payload.get("case")
        or states_payload.get("case")
        or dnt_payload.get("case")
        or summary_payload.get("case")
        or {"name": output_dir.parent.name}
    )

    return VisualizationDataset(
        source_dir=output_dir,
        case=case,
        reactions=list(reactions_payload.get("reactions", [])),
        states=list(states_payload.get("species", [])),
        coverage_pairs=dict(coverage_payload.get("pairs", {})),
        dnt_tasks=list(dnt_payload.get("dnt_tasks", [])),
        missing_data=list(missing_payload.get("missing_data", [])),
        summary=dict(summary_payload),
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
