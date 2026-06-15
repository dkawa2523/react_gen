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
from plasma_reactgen.data_sources.cross_section_table import import_cross_section_table
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
from plasma_reactgen.preparation.cross_section_mapping import apply_cross_section_mappings
from plasma_reactgen.preparation.enricher import enrich_case
from plasma_reactgen.preparation.input_templates import generate_missing_input_templates
from plasma_reactgen.preparation.missing_plan import write_missing_plan
from plasma_reactgen.preparation.promote import promote_reviewed_registry
from plasma_reactgen.data_sources.source_listing import build_source_list_report, format_source_list_report
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

    enrich = sub.add_parser("enrich", help="prepare and run configured local/offline enrichers into a workspace")
    enrich.add_argument("input", type=Path, help="case input YAML")
    enrich.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    enrich.add_argument("--workspace", type=Path, required=True, help="workspace for prepared_registry and reports")
    enrich.add_argument("--source-profile", default="local_only", help="source profile name or YAML path")

    dnt = sub.add_parser("export-dnt", help="export solver-free pair-wise DNT+/DNT+DM input YAML files")
    dnt.add_argument("input", type=Path, help="case input YAML")
    dnt.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    dnt.add_argument("--output", type=Path, default=None, help="output directory for dnt_manifest.yaml and dnt_inputs/")

    xsec = sub.add_parser("import-cross-sections", help="import local CSV/TSV cross-section tables into prepared_registry assets")
    xsec.add_argument("input_file", type=Path, help="CSV or TSV file with energy_eV and cross_section_m2 columns")
    xsec.add_argument("--workspace", type=Path, required=True, help="workspace containing prepared_registry/")
    xsec.add_argument("--source", choices=["lxcat_offline", "local_file"], default="local_file")
    xsec.add_argument("--reaction-id", default=None, help="prepared_registry reaction channel id to link if present")
    xsec.add_argument("--target", default=None, help="target species label used for output naming/provenance")
    xsec.add_argument("--license-note", default=None, help="license/citation note to write into metadata")

    xmap = sub.add_parser("apply-cross-section-mapping", help="apply reviewed cross-section mappings to prepared_registry electron channels")
    xmap.add_argument("mapping_file", type=Path, help="YAML file containing reviewed cross-section mappings")
    xmap.add_argument("--workspace", type=Path, required=True, help="workspace containing prepared_registry/")

    mplan = sub.add_parser("plan-missing", help="write an enrichment action plan from missing_data.yaml")
    mplan.add_argument("outputs_or_missing_data", type=Path, help="outputs directory or missing_data.yaml file")
    mplan.add_argument("--output", type=Path, default=Path("missing_plan.yaml"), help="destination missing_plan.yaml")

    tmissing = sub.add_parser("template-missing", help="write manual fill-in templates from missing_data.yaml")
    tmissing.add_argument("outputs_or_missing_data", type=Path, help="outputs directory or missing_data.yaml file")
    tmissing.add_argument("--output-dir", type=Path, default=Path("manual_inputs"), help="destination directory for templates")

    slist = sub.add_parser("source-list", help="show source-provider status for a source profile")
    slist.add_argument("--source-profile", default="local_only", help="source profile name or YAML path")
    slist.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")

    promote = sub.add_parser("promote", help="promote reviewed prepared/candidate registry items into curated registry")
    promote.add_argument("prepared_registry", type=Path, help="prepared_registry or candidate_registry root")
    promote.add_argument("--registry", type=Path, default=Path("registry"), help="curated registry root")
    promote.add_argument("--decision", type=Path, required=True, help="review decision YAML")
    promote_mode = promote.add_mutually_exclusive_group()
    promote_mode.add_argument("--dry-run", dest="apply", action="store_false", help="plan promotion without registry mutation")
    promote_mode.add_argument("--apply", dest="apply", action="store_true", help="apply accepted promotions to registry")
    promote.set_defaults(apply=False)

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
    if args.command == "enrich":
        return _cmd_enrich(args.input, args.registry, args.workspace, args.source_profile)
    if args.command == "export-dnt":
        return _cmd_export_dnt(args.input, args.registry, args.output)
    if args.command == "import-cross-sections":
        return _cmd_import_cross_sections(
            input_file=args.input_file,
            workspace=args.workspace,
            source=args.source,
            reaction_id=args.reaction_id,
            target=args.target,
            license_note=args.license_note,
        )
    if args.command == "apply-cross-section-mapping":
        return _cmd_apply_cross_section_mapping(args.mapping_file, args.workspace)
    if args.command == "plan-missing":
        return _cmd_plan_missing(args.outputs_or_missing_data, args.output)
    if args.command == "template-missing":
        return _cmd_template_missing(args.outputs_or_missing_data, args.output_dir)
    if args.command == "source-list":
        return _cmd_source_list(args.source_profile, args.registry)
    if args.command == "promote":
        return _cmd_promote(
            prepared_registry=args.prepared_registry,
            registry=args.registry,
            decision=args.decision,
            apply=args.apply,
        )
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
    print(f"  electron_reactions: {sum(1 for reaction in network.reactions if reaction.family == 'electron')}")
    print(f"  ion_neutral_reactions: {sum(1 for reaction in network.reactions if reaction.family == 'ion_neutral')}")
    print(f"  pairs_found: {sum(1 for item in network.coverage if item.status == 'found')}")
    print(f"  pairs_missing: {sum(1 for item in network.coverage if item.status == 'missing')}")
    print(f"  dnt_tasks: {len(dnt_tasks)}")
    print(f"  dnt_ready_pairs: {_count_ready_dnt_pairs(dnt_tasks)}")
    print(f"  reactions_with_cross_section_asset: {_count_reactions_with_cross_section_asset(network)}")
    print(f"  electron_reactions_missing_cross_section: {_count_electron_reactions_missing_cross_section(network)}")
    print(f"  missing_data_items: {len(missing_data)}")
    print(f"  quality_summary: {output_dir / 'quality_summary.yaml'}")
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


def _cmd_enrich(input_path: Path, registry_root: Path, workspace: Path, source_profile: str) -> int:
    report = enrich_case(
        input_path=input_path,
        registry_root=registry_root,
        workspace=workspace,
        source_profile=source_profile,
    )
    print(f"Enriched prepared registry: {workspace / 'prepared_registry'}")
    print(f"  source_profile: {report['source_profile']}")
    print(f"  species_seeded_from_reactions: {report['summary'].get('species_seeded_from_reactions', 0)}")
    print(f"  properties_filled: {report['summary']['properties_filled']}")
    print(f"  properties_filled_for_seeded_species: {report['summary'].get('properties_filled_for_seeded_species', 0)}")
    print(f"  property_conflicts: {report['summary']['property_conflicts']}")
    print(f"  reaction_channels_imported: {report['summary']['reaction_channels_imported']}")
    print(f"  cross_section_assets_registered: {report['summary']['cross_section_assets_registered']}")
    print(f"  unresolved_product_species: {report['summary'].get('unresolved_product_species', 0)}")
    print(f"  unresolved_items: {report['summary']['unresolved_items']}")
    print(f"  prepare_report: {workspace / 'prepare_report.yaml'}")
    print(f"  enrichment_report: {workspace / 'enrichment_report.yaml'}")
    print("  registry_mutated: false")
    print("  auto_promoted: false")
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


def _cmd_import_cross_sections(
    input_file: Path,
    workspace: Path,
    source: str,
    reaction_id: str | None,
    target: str | None,
    license_note: str | None,
) -> int:
    result = import_cross_section_table(
        input_file=input_file,
        workspace=workspace,
        source=source,
        reaction_id=reaction_id,
        target=target,
        license_note=license_note,
    )
    print(f"Imported cross-section table: {result.asset_path}")
    print(f"  metadata: {result.metadata_path}")
    print(f"  registry_asset_path: {result.relative_asset_path}")
    print(f"  rows: {result.row_count}")
    print(f"  registry_mutated: false")
    if reaction_id:
        print(f"  prepared_reaction_files_linked: {len(result.linked_reaction_files)}")
        if not result.linked_reaction_files:
            print("  link_status: reaction_id not found in prepared_registry; use apply-cross-section-mapping after review")
    return 0


def _cmd_apply_cross_section_mapping(mapping_file: Path, workspace: Path) -> int:
    report = apply_cross_section_mappings(
        prepared_registry=workspace / "prepared_registry",
        mapping_file=mapping_file,
    )
    print(f"Applied cross-section mappings: {mapping_file}")
    print(f"  mappings: {report['summary']['n_mappings']}")
    print(f"  updated: {report['summary']['n_updated']}")
    print(f"  unresolved: {report['summary']['n_unresolved']}")
    print("  registry_mutated: false")
    return 0


def _cmd_plan_missing(outputs_or_missing_data: Path, output: Path) -> int:
    plan = write_missing_plan(outputs_or_missing_data, output)
    print(f"Wrote missing-data enrichment plan: {output}")
    print(f"  total_missing_items: {plan['summary']['total_missing_items']}")
    print(f"  suggested_actions: {plan['summary']['suggested_actions']}")
    for action in plan.get("actions", [])[:5]:
        print(f"  action[{action['priority']}]: {action['action']} ({len(action['subjects'])} subjects)")
    print("  data_fetched: false")
    return 0


def _cmd_template_missing(outputs_or_missing_data: Path, output_dir: Path) -> int:
    report = generate_missing_input_templates(outputs_or_missing_data, output_dir)
    print(f"Wrote manual missing-data templates: {output_dir}")
    print(f"  missing_items: {report['summary']['n_missing_items']}")
    print(f"  species_property_records: {report['summary']['n_species_property_records']}")
    print(f"  cross_section_mappings: {report['summary']['n_cross_section_mappings']}")
    print(f"  reaction_energetics_records: {report['summary']['n_reaction_energetics_records']}")
    print("  data_fetched: false")
    print("  registry_mutated: false")
    return 0


def _cmd_source_list(source_profile: str, registry: Path) -> int:
    report = build_source_list_report(source_profile, registry)
    print(format_source_list_report(report))
    return 0


def _cmd_promote(prepared_registry: Path, registry: Path, decision: Path, apply: bool) -> int:
    report = promote_reviewed_registry(
        prepared_registry=prepared_registry,
        registry=registry,
        decision_file=decision,
        apply=apply,
    )
    report_path = prepared_registry.parent / "promote_report.yaml"
    print(f"Wrote promote report: {report_path}")
    print(f"  mode: {'apply' if apply else 'dry_run'}")
    print(f"  promoted_species: {report['summary']['n_promoted_species']}")
    print(f"  promoted_channels: {report['summary']['n_promoted_channels']}")
    print(f"  rejected: {report['summary']['n_rejected']}")
    print(f"  conflicts: {report['summary']['n_conflicts']}")
    print(f"  registry_mutated: {str(report['registry_mutated']).lower()}")
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


def _count_ready_dnt_pairs(dnt_tasks: list[dict]) -> int:
    return sum(1 for task in dnt_tasks if task.get("readiness", {}).get("status") == "ready")


def _count_reactions_with_cross_section_asset(network) -> int:
    return sum(1 for reaction in network.reactions if _has_cross_section_asset(reaction.data))


def _count_electron_reactions_missing_cross_section(network) -> int:
    return sum(
        1
        for reaction in network.reactions
        if reaction.family == "electron" and not _has_cross_section_asset(reaction.data)
    )


def _has_cross_section_asset(data: dict) -> bool:
    cross_section = data.get("cross_section") if isinstance(data, dict) else None
    return isinstance(cross_section, dict) and bool(cross_section.get("path"))


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
