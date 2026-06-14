from __future__ import annotations

from pathlib import Path
import argparse
import sys
import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_input_builder import READY_STATUSES, build_dnt_inputs
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.identifiers import pair_filename, to_file_key
from plasma_reactgen.inference.candidate_writer import (
    build_candidate_registry,
    write_candidate_registry,
)
from plasma_reactgen.inference.provider import (
    CompositeReactionProvider,
    InferredReactionProvider,
    RegisteredReactionProvider,
)
from plasma_reactgen.infrastructure.csv_writer import write_csv_outputs
from plasma_reactgen.infrastructure.dnt_writer import write_dnt_inputs
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.infrastructure.indexer import build_indexes, check_registry
from plasma_reactgen.infrastructure.yaml_writer import write_yaml_outputs
from plasma_reactgen.visualization.network import GraphvizOptions
from plasma_reactgen.visualization.writer import write_visualizations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reactgen")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate registry-driven network outputs from a case YAML")
    gen.add_argument("input", type=Path, help="case input YAML")
    gen.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    gen.add_argument("--output", type=Path, default=None, help="output directory; defaults to CASE_DIR/outputs")
    gen.add_argument("--visualize", action="store_true", help="also create visualization files after generation")
    gen.add_argument("--visualization-output", type=Path, default=None, help="destination for visualization files when --visualize is used")
    gen.add_argument("--export-dnt-inputs", action="store_true", help="also write solver-free pair-wise DNT input files")
    gen.add_argument("--dnt-input-output", type=Path, default=None, help="destination for pair-wise DNT input files")

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

    idx = sub.add_parser("dev-index", help="build registry index files")
    idx.add_argument("--registry", type=Path, default=Path("registry"))

    infer = sub.add_parser(
        "infer-candidates",
        help="developer tool: write inferred candidates for review without changing the registry",
    )
    infer.add_argument("input", type=Path, help="case input YAML")
    infer.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    infer.add_argument("--output", type=Path, default=None, help="candidate_registry output directory")

    dnt = sub.add_parser("export-dnt", help="export solver-free pair-wise DNT+/DNT+DM input YAML files")
    dnt.add_argument("input", type=Path, help="case input YAML")
    dnt.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    dnt.add_argument("--output", type=Path, default=None, help="output directory for dnt_manifest.yaml and dnt_inputs/")

    tmpl = sub.add_parser("template", help="print a registration template to stdout")
    tmpl.add_argument("kind", choices=["species", "electron-pair", "ion-pair"])
    tmpl.add_argument("args", nargs="+")

    args = parser.parse_args(argv)

    if args.command == "generate":
        return _cmd_generate(
            args.input,
            args.registry,
            args.output,
            args.visualize,
            args.visualization_output,
            args.export_dnt_inputs,
            args.dnt_input_output,
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
        print(check_registry(args.registry, strict=args.strict))
        return 0
    if args.command == "dev-index":
        build_indexes(args.registry)
        print("Registry indexes updated.")
        return 0
    if args.command == "infer-candidates":
        return _cmd_infer_candidates(args.input, args.registry, args.output)
    if args.command == "export-dnt":
        return _cmd_export_dnt(args.input, args.registry, args.output)
    if args.command == "template":
        print(_template(args.kind, args.args))
        return 0

    parser.print_help()
    return 1


def _cmd_generate(
    input_path: Path,
    registry_root: Path,
    output_dir: Path | None,
    visualize: bool = False,
    visualization_output: Path | None = None,
    export_dnt_inputs: bool = False,
    dnt_input_output: Path | None = None,
) -> int:
    config = load_case_config(input_path, registry_root)
    if output_dir is None:
        output_dir = input_path.parent / "outputs"

    registry = FileRegistry(registry_root)
    deps = _build_network_dependencies(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)
    states = build_state_list(network=network, rule_repo=registry)
    dnt_tasks = build_dnt_tasks(network=network)
    missing_data = build_missing_data(
        network=network,
        states=states,
        dnt_tasks=dnt_tasks,
        registry=registry,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml_outputs(
        output_dir=output_dir,
        case_config=config,
        network=network,
        states=states,
        dnt_tasks=dnt_tasks,
        missing_data=missing_data,
    )
    if config.outputs.csv_summary:
        write_csv_outputs(output_dir=output_dir, network=network, states=states, missing_data=missing_data)

    dnt_output_dir = None
    dnt_inputs = None
    if export_dnt_inputs or config.outputs.dnt_inputs:
        dnt_output_dir = dnt_input_output or output_dir
        dnt_inputs = _write_dnt_inputs_for_network(dnt_output_dir, network)

    print(f"Generated outputs: {output_dir}")
    print(f"  species: {len(network.species_nodes)}")
    print(f"  reactions: {len(network.reactions)}")
    print(f"  dnt_tasks: {len(dnt_tasks)}")
    print(f"  missing_data_items: {len(missing_data)}")
    if dnt_inputs is not None:
        _print_dnt_input_summary(dnt_output_dir, dnt_inputs)

    if visualize:
        manifest = write_visualizations(output_dir, visualization_output)
        print(f"Generated visualizations: {manifest['visualization_dir']}")

    return 0


def _cmd_infer_candidates(input_path: Path, registry_root: Path, output_dir: Path | None) -> int:
    config = load_case_config(input_path, registry_root)
    if output_dir is None:
        output_dir = input_path.parent / "candidate_registry"

    registry = FileRegistry(registry_root)
    candidates = build_candidate_registry(config, registry)
    write_candidate_registry(output_dir=output_dir, candidates=candidates)

    summary = candidates["summary"]
    print(f"Generated inferred candidate registry: {output_dir}")
    print(f"  species_candidates: {summary['n_species_candidates']}")
    print(f"  reaction_candidates: {summary['n_reaction_candidates']}")
    print("  registry_mutated: false")
    return 0


def _cmd_export_dnt(input_path: Path, registry_root: Path, output_dir: Path | None) -> int:
    config = load_case_config(input_path, registry_root)
    if output_dir is None:
        output_dir = input_path.parent / "outputs"

    registry = FileRegistry(registry_root)
    deps = _build_network_dependencies(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)
    dnt_inputs = _write_dnt_inputs_for_network(output_dir, network)

    _print_dnt_input_summary(output_dir, dnt_inputs, include_statuses=True)
    return 0


def _write_dnt_inputs_for_network(output_dir: Path, network) -> dict:
    dnt_inputs = build_dnt_inputs(network)
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


def _template(kind: str, args: list[str]) -> str:
    if kind == "species":
        if len(args) != 1:
            raise SystemExit("template species requires: SPECIES_ID")
        species_id = args[0]
        data = {
            "schema_version": 1,
            "id": species_id,
            "display_name": species_id,
            "composition": {},
            "charge": 0,
            "classes": ["neutral"],
            "state": {"kind": "ground", "label": "X", "excitation_energy_eV": 0.0},
            "properties": {
                "mass_amu": {"value": None, "unit": "amu", "source": None},
                "polarizability_A3": {"value": None, "unit": "A3", "source": None},
                "dipole_moment_D": {"value": None, "unit": "D", "source": None},
                "collision_radius_A": {"value": None, "unit": "A", "source": None},
                "enthalpy_formation_eV": {"value": None, "unit": "eV", "source": None},
                "ionization_energy_eV": {"value": None, "unit": "eV", "source": None},
                "electron_affinity_eV": {"value": None, "unit": "eV", "source": None},
            },
            "metadata": {"status": "draft", "notes": []},
            "suggested_filename": f"{to_file_key(species_id)}.yaml",
        }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    if kind == "electron-pair":
        if len(args) != 2:
            raise SystemExit("template electron-pair requires: e TARGET")
        projectile, target = args
        data = {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": projectile, "target": target},
            "channels": [
                {
                    "id": f"e_{to_file_key(target)}_elastic",
                    "type": "elastic",
                    "products": [{"species": projectile, "n": 1}, {"species": target, "n": 1}],
                    "threshold_eV": 0.0,
                    "data": {"cross_section": {"path": None, "format": "csv_energy_eV_sigma_m2"}},
                    "status": "draft",
                }
            ],
            "suggested_filename": pair_filename(projectile, target),
        }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    if kind == "ion-pair":
        if len(args) != 2:
            raise SystemExit("template ion-pair requires: ION NEUTRAL")
        projectile, target = args
        data = {
            "schema_version": 1,
            "pair": {"family": "ion_neutral", "projectile": projectile, "target": target},
            "channels": [
                {
                    "id": f"{to_file_key(projectile)}_{to_file_key(target)}_elastic",
                    "type": "elastic",
                    "dnt_class": "elastic",
                    "products": [{"species": projectile, "n": 1}, {"species": target, "n": 1}],
                    "deltaE_products_minus_reactants_eV": 0.0,
                    "status": "draft",
                }
            ],
            "suggested_filename": pair_filename(projectile, target),
        }
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

    raise SystemExit(f"unknown template kind: {kind}")


if __name__ == "__main__":
    sys.exit(main())
