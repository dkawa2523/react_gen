"""Public Graphviz API and file-rendering adapter."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from plasma_reactgen.visualization.graphviz_options import GraphvizOptions
from plasma_reactgen.visualization.models import VisualizationDataset
from plasma_reactgen.visualization.reaction_network_dot import (
    build_reaction_network_dot,
)
from plasma_reactgen.visualization.species_lineage_dot import (
    build_species_lineage_dot,
)


def write_reaction_network_graphviz(
    dataset: VisualizationDataset,
    output_dir: str | Path,
    *,
    options: GraphvizOptions | None = None,
) -> dict[str, str | bool | list[str]]:
    """Write the full state-node reaction network."""

    selected = options or GraphvizOptions()
    return _write_graphviz(
        output_dir,
        stem="reaction_network",
        dot=build_reaction_network_dot(dataset, options=selected),
        formats=selected.render_formats,
    )


def write_species_lineage_graphviz(
    dataset: VisualizationDataset,
    output_dir: str | Path,
    *,
    options: GraphvizOptions | None = None,
) -> dict[str, str | bool | list[str]]:
    """Write the compact species-introduction graph."""

    selected = options or GraphvizOptions()
    return _write_graphviz(
        output_dir,
        stem="species_lineage",
        dot=build_species_lineage_dot(dataset, options=selected),
        formats=selected.render_formats,
    )


def _write_graphviz(
    output_dir: str | Path,
    *,
    stem: str,
    dot: str,
    formats: tuple[str, ...],
) -> dict[str, str | bool | list[str]]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    dot_path = destination / f"{stem}.dot"
    dot_path.write_text(dot, encoding="utf-8")

    executable = shutil.which("dot")
    rendered = []
    if executable is not None:
        rendered = asyncio.run(
            _render_graphviz_files(executable, dot_path, destination, stem, formats)
        )
    return {
        "dot": str(dot_path),
        "rendered": rendered,
        "graphviz_dot_available": executable is not None,
    }


async def _render_graphviz_files(
    executable: str,
    dot_path: Path,
    destination: Path,
    stem: str,
    formats: tuple[str, ...],
) -> list[str]:
    rendered = []
    for file_format in formats:
        output_path = destination / f"{stem}.{file_format}"
        process = await asyncio.create_subprocess_exec(
            executable,
            f"-T{file_format}",
            str(dot_path),
            "-o",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode:
            message = stderr.decode(errors="replace").strip()
            raise RuntimeError(f"Graphviz rendering failed: {message}")
        rendered.append(str(output_path))
    return rendered


__all__ = [
    "GraphvizOptions",
    "build_reaction_network_dot",
    "build_species_lineage_dot",
    "write_reaction_network_graphviz",
    "write_species_lineage_graphviz",
]
