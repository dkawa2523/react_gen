from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VisualizationDataset:
    """Parsed case outputs used by visualization builders.

    The fields mirror output YAML files rather than internal domain objects so
    visualization remains a post-processing layer.
    """

    source_dir: Path
    case: dict[str, Any]
    reactions: list[dict[str, Any]] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    coverage_pairs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    dnt_tasks: list[dict[str, Any]] = field(default_factory=list)
    missing_data: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
