from __future__ import annotations

from pathlib import Path

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.application.dnt_input_builder import READY_STATUSES, build_dnt_inputs
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import ReactionNetworkBuilder
from plasma_reactgen.domain.models import ReactionNetwork
from plasma_reactgen.infrastructure.dnt_writer import write_dnt_inputs
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.interface.network_dependencies import build_network_dependencies


def run_export_dnt(
    input_path: Path,
    registry_root: Path,
    output_dir: Path | None,
) -> int:
    config = load_case_config(input_path, registry_root)
    output_dir = output_dir or input_path.parent / "outputs"
    registry = FileRegistry(registry_root)
    network = ReactionNetworkBuilder(build_network_dependencies(registry, config)).generate(config)
    dnt_tasks = build_dnt_tasks(network, asset_exists=registry.asset_exists)
    dnt_inputs = write_network_dnt_inputs(output_dir, network, dnt_tasks=dnt_tasks)
    print_dnt_input_summary(output_dir, dnt_inputs, include_statuses=True)
    return 0


def write_network_dnt_inputs(
    output_dir: Path,
    network: ReactionNetwork,
    *,
    dnt_tasks: list[dict] | None = None,
) -> dict:
    dnt_inputs = build_dnt_inputs(network, dnt_tasks=dnt_tasks)
    write_dnt_inputs(output_dir=output_dir, dnt_inputs=dnt_inputs)
    return dnt_inputs


def print_dnt_input_summary(
    output_dir: Path | None,
    dnt_inputs: dict,
    *,
    include_statuses: bool = False,
) -> None:
    summary = dnt_inputs["summary"]
    print(f"Generated DNT pair inputs: {output_dir}")
    print(f"  dnt_pairs: {summary['total_pairs']}")
    if include_statuses:
        for status in READY_STATUSES:
            print(f"  {status}: {summary[status]}")
