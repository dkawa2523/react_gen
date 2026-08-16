from __future__ import annotations

from pathlib import Path

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.mechanism_coverage import build_mechanism_coverage
from plasma_reactgen.application.network_builder import ReactionNetworkBuilder
from plasma_reactgen.application.network_metrics import (
    count_dnt_status,
    count_electron_reactions_missing_cross_section,
    count_reactions_with_cross_section_asset,
)
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork
from plasma_reactgen.infrastructure.csv_writer import write_csv_outputs
from plasma_reactgen.infrastructure.registry_pack import resolve_registry
from plasma_reactgen.infrastructure.yaml_writer import write_yaml_outputs
from plasma_reactgen.interface.dnt_command import (
    print_dnt_input_summary,
    write_network_dnt_inputs,
)
from plasma_reactgen.interface.network_dependencies import build_network_dependencies


def run_generate(
    input_path: Path,
    registry_root: Path | None,
    output_dir: Path | None,
) -> int:
    base_registry = Path("registry")
    config = load_case_config(input_path, registry_root or base_registry)
    output_dir = output_dir or input_path.parent / "outputs"
    resolution = resolve_registry(
        gases=config.gases,
        base_registry=base_registry,
        explicit_registry=registry_root,
    )
    registry = resolution.registry
    network = ReactionNetworkBuilder(build_network_dependencies(registry, config)).generate(config)
    states = build_state_list(network=network, rule_repo=registry)
    dnt_tasks = build_dnt_tasks(network=network, asset_exists=registry.asset_exists)
    diagnostic_dnt_tasks = dnt_tasks if config.outputs.dnt_inputs else []
    missing_data = build_missing_data(
        network=network,
        states=states,
        dnt_tasks=diagnostic_dnt_tasks,
    )
    mechanism_coverage = build_mechanism_coverage(config.gases, network, registry.root)
    _write_generation_outputs(
        output_dir,
        config,
        network,
        states,
        dnt_tasks,
        missing_data,
        resolution.context,
        registry.asset_exists,
        mechanism_coverage,
    )
    dnt_inputs = (
        write_network_dnt_inputs(output_dir, network, dnt_tasks=dnt_tasks)
        if config.outputs.dnt_inputs
        else None
    )
    _print_generation_summary(output_dir, network, dnt_tasks, missing_data)
    if dnt_inputs is not None:
        print_dnt_input_summary(output_dir, dnt_inputs)
    return 0


def _write_generation_outputs(
    output_dir: Path,
    config,
    network: ReactionNetwork,
    states: list[dict],
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
    registry_context: dict,
    asset_exists,
    mechanism_coverage: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml_outputs(
        output_dir=output_dir,
        case_config=config,
        network=network,
        states=states,
        dnt_tasks=dnt_tasks,
        missing_data=missing_data,
        registry_context=registry_context,
        asset_exists=asset_exists,
        mechanism_coverage=mechanism_coverage,
    )
    write_csv_outputs(
        output_dir=output_dir,
        network=network,
        states=states,
        missing_data=missing_data,
        asset_exists=asset_exists,
    )


def _print_generation_summary(
    output_dir: Path,
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> None:
    reaction_counts: dict[str, int] = {}
    for reaction in network.reactions:
        reaction_counts[reaction.family] = reaction_counts.get(reaction.family, 0) + 1
    coverage_counts = {
        status: sum(item.status == status for item in network.coverage)
        for status in ("found", "missing")
    }
    print(f"Generated outputs: {output_dir}")
    print(f"  species: {len(network.species_nodes)}")
    print(f"  reactions: {len(network.reactions)}")
    for family, count in sorted(reaction_counts.items()):
        print(f"  {family}_reactions: {count}")
    print(f"  pairs_found: {coverage_counts['found']}")
    print(f"  pairs_missing: {coverage_counts['missing']}")
    print(f"  generation_complete: {str(network.generation_complete).lower()}")
    print(f"  truncations: {len(network.truncations)}")
    print(f"  dnt_tasks: {len(dnt_tasks)}")
    print(
        "  dnt_property_ready_pairs: "
        f"{count_dnt_status(dnt_tasks, 'pair_property_readiness', 'ready')}"
    )
    print(
        f"  dnt_complete_ready_pairs: {count_dnt_status(dnt_tasks, 'complete_readiness', 'ready')}"
    )
    print(
        f"  reactions_with_cross_section_asset: {count_reactions_with_cross_section_asset(network)}"
    )
    print(
        "  electron_reactions_missing_cross_section: "
        f"{count_electron_reactions_missing_cross_section(network)}"
    )
    print(f"  missing_data_items: {len(missing_data)}")
    print(f"  mechanism_coverage: {output_dir / 'mechanism_coverage.yaml'}")
    print(f"  quality_summary: {output_dir / 'quality_summary.yaml'}")
