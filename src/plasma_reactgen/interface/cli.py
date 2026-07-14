from __future__ import annotations

from pathlib import Path
import argparse
import sys

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_input_builder import READY_STATUSES, build_dnt_inputs
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.application.network_metrics import (
    count_dnt_status,
    count_electron_reactions_missing_cross_section,
    count_reactions_with_cross_section_asset,
)
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.interface.registration_templates import render_registration_template
from plasma_reactgen.interface.maintenance_cli import (
    COMMANDS as MAINTENANCE_COMMANDS,
    add_maintenance_commands,
    run_maintenance_command,
)
from plasma_reactgen.domain.models import MissingDataItem
from plasma_reactgen.inference.provider import (
    CompositeReactionProvider,
    InferredReactionProvider,
    RegisteredReactionProvider,
)
from plasma_reactgen.infrastructure.csv_writer import write_csv_outputs
from plasma_reactgen.infrastructure.dnt_writer import write_dnt_inputs
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.infrastructure.registry_pack import resolve_registry
from plasma_reactgen.infrastructure.indexer import (
    check_registry_details,
    format_registry_check,
)
from plasma_reactgen.infrastructure.yaml_writer import write_yaml_outputs
from plasma_reactgen.visualization.network import GraphvizOptions
from plasma_reactgen.visualization.writer import write_visualizations


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="reactgen")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate registry-driven network outputs from a case YAML")
    gen.add_argument("input", type=Path, help="case input YAML")
    gen.add_argument("--registry", type=Path, default=None, help="explicit local registry root; disables automatic pack selection")
    gen.add_argument("--output", type=Path, default=None, help="output directory; defaults to CASE_DIR/outputs")

    vis = sub.add_parser("visualize", help="create statistical charts and Graphviz reaction-network outputs")
    vis.add_argument("outputs", type=Path, help="case output directory containing network.*.yaml files")
    vis.add_argument("--output", type=Path, default=None, help="visualization destination; defaults to OUTPUTS/visualizations")
    vis.add_argument("--include-self-loops", action="store_true", help="include self-loop edges such as elastic/non-changing channels")
    vis.add_argument("--include-non-expanding", action="store_true", help="include reactions whose non-electron species set does not change")
    vis.add_argument("--max-reactions", type=int, default=250, help="maximum reactions to draw in the Graphviz network; use -1 for all")
    vis.add_argument("--formats", default="svg,png", help="comma-separated Graphviz render formats, e.g. svg,png,pdf")

    chk = sub.add_parser("dev-check", help="check registry readability and basic references")
    chk.add_argument("--registry", type=Path, default=Path("registry"))
    chk.add_argument("--strict", action="store_true")

    dnt = sub.add_parser("export-dnt", help="export solver-free pair-wise DNT+/DNT+DM input YAML files")
    dnt.add_argument("input", type=Path, help="case input YAML")
    dnt.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    dnt.add_argument("--output", type=Path, default=None, help="output directory for dnt_manifest.yaml and dnt_inputs/")

    # Keep historic maintenance invocations working without advertising them
    # as part of the normal gases -> generate workflow.
    if arguments and arguments[0] in MAINTENANCE_COMMANDS:
        add_maintenance_commands(sub)

    tmpl = sub.add_parser("template", help="print a registration template to stdout")
    tmpl.add_argument("kind", choices=["species", "electron-pair", "ion-pair"])
    tmpl.add_argument("args", nargs="+")

    args = parser.parse_args(arguments)

    if args.command == "generate":
        return _cmd_generate(
            args.input,
            args.registry,
            args.output,
        )
    if args.command == "visualize":
        return _cmd_visualize(
            outputs=args.outputs,
            output=args.output,
            include_self_loops=args.include_self_loops,
            include_non_expanding=args.include_non_expanding,
            max_reactions=args.max_reactions,
            formats=args.formats,
        )
    if args.command == "dev-check":
        details = check_registry_details(args.registry, strict=args.strict)
        print(format_registry_check(details))
        return 1 if details["errors"] else 0
    if args.command == "export-dnt":
        return _cmd_export_dnt(args.input, args.registry, args.output)
    if args.command == "template":
        print(render_registration_template(args.kind, args.args))
        return 0

    maintenance_result = run_maintenance_command(args)
    if maintenance_result is not None:
        return maintenance_result

    parser.print_help()
    return 1


def _cmd_generate(
    input_path: Path,
    registry_root: Path | None,
    output_dir: Path | None,
) -> int:
    base_registry = Path("registry")
    config = load_case_config(input_path, registry_root or base_registry)
    if output_dir is None:
        output_dir = input_path.parent / "outputs"

    resolution = resolve_registry(
        gases=config.gases,
        base_registry=base_registry,
        explicit_registry=registry_root,
    )
    registry = resolution.registry
    deps = _build_network_dependencies(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)
    states = build_state_list(network=network, rule_repo=registry)
    dnt_tasks = build_dnt_tasks(network=network, asset_exists=registry.asset_exists)
    missing_data = build_missing_data(
        network=network,
        states=states,
        dnt_tasks=dnt_tasks,
    )
    if resolution.context.get("coverage_gap"):
        missing_data.append(
            MissingDataItem(
                subject_kind="registry_pack",
                subject_id="+".join(sorted(config.gases)),
                field="registry_pack.coverage",
                required_by="registry_pack_resolver",
                severity="warning",
                message="No matching registry pack was found; generation used the base registry only.",
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml_outputs(
        output_dir=output_dir,
        case_config=config,
        network=network,
        states=states,
        dnt_tasks=dnt_tasks,
        missing_data=missing_data,
        registry_context=resolution.context,
        asset_exists=registry.asset_exists,
    )
    write_csv_outputs(
        output_dir=output_dir,
        network=network,
        states=states,
        missing_data=missing_data,
        asset_exists=registry.asset_exists,
    )

    dnt_output_dir = None
    dnt_inputs = None
    if config.outputs.dnt_inputs:
        dnt_output_dir = output_dir
        dnt_inputs = _write_dnt_inputs_for_network(
            dnt_output_dir, network, dnt_tasks=dnt_tasks
        )

    print(f"Generated outputs: {output_dir}")
    print(f"  species: {len(network.species_nodes)}")
    print(f"  reactions: {len(network.reactions)}")
    print(f"  electron_reactions: {sum(1 for reaction in network.reactions if reaction.family == 'electron')}")
    print(f"  ion_neutral_reactions: {sum(1 for reaction in network.reactions if reaction.family == 'ion_neutral')}")
    print(f"  pairs_found: {sum(1 for item in network.coverage if item.status == 'found')}")
    print(f"  pairs_missing: {sum(1 for item in network.coverage if item.status == 'missing')}")
    print(f"  generation_complete: {str(network.generation_complete).lower()}")
    print(f"  truncations: {len(network.truncations)}")
    print(f"  dnt_tasks: {len(dnt_tasks)}")
    print(
        "  dnt_property_ready_pairs: "
        f"{count_dnt_status(dnt_tasks, 'pair_property_readiness', 'ready')}"
    )
    print(
        "  dnt_complete_ready_pairs: "
        f"{count_dnt_status(dnt_tasks, 'complete_readiness', 'ready')}"
    )
    print(f"  reactions_with_cross_section_asset: {count_reactions_with_cross_section_asset(network)}")
    print(f"  electron_reactions_missing_cross_section: {count_electron_reactions_missing_cross_section(network)}")
    print(f"  missing_data_items: {len(missing_data)}")
    print(f"  quality_summary: {output_dir / 'quality_summary.yaml'}")
    if dnt_inputs is not None:
        _print_dnt_input_summary(dnt_output_dir, dnt_inputs)

    return 0


def _cmd_export_dnt(input_path: Path, registry_root: Path, output_dir: Path | None) -> int:
    config = load_case_config(input_path, registry_root)
    if output_dir is None:
        output_dir = input_path.parent / "outputs"

    registry = FileRegistry(registry_root)
    deps = _build_network_dependencies(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)
    dnt_tasks = build_dnt_tasks(network, asset_exists=registry.asset_exists)
    dnt_inputs = _write_dnt_inputs_for_network(
        output_dir, network, dnt_tasks=dnt_tasks
    )

    _print_dnt_input_summary(output_dir, dnt_inputs, include_statuses=True)
    return 0


def _write_dnt_inputs_for_network(
    output_dir: Path,
    network,
    *,
    dnt_tasks: list[dict] | None = None,
) -> dict:
    dnt_inputs = build_dnt_inputs(network, dnt_tasks=dnt_tasks)
    write_dnt_inputs(output_dir=output_dir, dnt_inputs=dnt_inputs)
    return dnt_inputs


def _print_dnt_input_summary(
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


def _build_network_dependencies(registry: FileRegistry, config) -> NetworkBuilderDependencies:
    if not (config.inference.enabled and config.inference.include_inferred_reactions):
        return NetworkBuilderDependencies(
            species_repo=registry,
            reaction_repo=registry,
            rule_repo=registry,
        )

    registered = RegisteredReactionProvider(registry)
    inferred = InferredReactionProvider(species_repo=registry)
    composite = CompositeReactionProvider(
        registered=registered,
        inferred=inferred,
        config=config,
    )
    return NetworkBuilderDependencies(
        species_repo=composite,
        reaction_repo=composite,
        rule_repo=registry,
    )


def _cmd_visualize(
    outputs: Path,
    output: Path | None,
    include_self_loops: bool,
    include_non_expanding: bool,
    max_reactions: int,
    formats: str,
) -> int:
    render_formats = tuple(x.strip() for x in formats.split(",") if x.strip())
    max_reactions_value = None if max_reactions < 0 else max_reactions
    manifest = write_visualizations(
        outputs,
        output,
        graphviz_options=GraphvizOptions(
            include_self_loops=include_self_loops,
            include_non_expanding=include_non_expanding,
            max_reactions=max_reactions_value,
            render_formats=render_formats,
        ),
    )
    print(f"Generated visualizations: {manifest['visualization_dir']}")
    print(f"  statistical_charts: {len(manifest['statistics'])}")
    print(f"  graphviz_network_dot: {manifest['network']['dot']}")
    if 'lineage' in manifest:
        print(f"  graphviz_lineage_dot: {manifest['lineage']['dot']}")
    rendered = manifest['network'].get('rendered', [])
    lineage_rendered = manifest.get('lineage', {}).get('rendered', [])
    if rendered or lineage_rendered:
        all_rendered = [*rendered, *lineage_rendered]
        print("  graphviz_rendered: " + ", ".join(all_rendered))
    else:
        print("  graphviz_rendered: not available; install Graphviz 'dot' to render")
    return 0


if __name__ == "__main__":
    sys.exit(main())
