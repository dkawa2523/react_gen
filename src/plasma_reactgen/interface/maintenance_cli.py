"""Compatibility CLI commands for registry preparation and review.

Normal users only need ``reactgen generate``.  These commands remain on the
historic CLI for compatibility, while their implementations stay outside the
generation entry point.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.data_sources.cross_section_table import import_cross_section_table
from plasma_reactgen.data_sources.source_listing import (
    build_source_list_report,
    format_source_list_report,
)
from plasma_reactgen.inference.candidate_writer import (
    build_candidate_registry,
    write_candidate_registry,
)
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.preparation.cross_section_mapping import apply_cross_section_mappings
from plasma_reactgen.preparation.enricher import enrich_case
from plasma_reactgen.preparation.input_templates import generate_missing_input_templates
from plasma_reactgen.preparation.missing_plan import write_missing_plan
from plasma_reactgen.preparation.promote import promote_reviewed_registry


COMMANDS = {
    "infer-candidates",
    "enrich",
    "import-cross-sections",
    "apply-cross-section-mapping",
    "plan-missing",
    "template-missing",
    "source-list",
    "promote",
}


def add_maintenance_commands(subparsers: Any) -> None:
    infer = subparsers.add_parser(
        "infer-candidates",
        help="developer tool: write inferred candidates for review without changing the registry",
    )
    infer.add_argument("input", type=Path, help="case input YAML")
    infer.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    infer.add_argument("--output", type=Path, default=None, help="candidate_registry output directory")

    enrich = subparsers.add_parser(
        "enrich", help="prepare and run configured local/offline enrichers into a workspace"
    )
    enrich.add_argument("input", type=Path, help="case input YAML")
    enrich.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")
    enrich.add_argument("--workspace", type=Path, required=True, help="workspace for prepared_registry and reports")
    enrich.add_argument("--source-profile", default="local_only", help="source profile name or YAML path")
    enrich.add_argument(
        "--fresh",
        action="store_true",
        help="clear enrich-owned workspace artifacts before preparing the registry",
    )

    xsec = subparsers.add_parser(
        "import-cross-sections",
        help="import local CSV/TSV cross-section tables into prepared_registry assets",
    )
    xsec.add_argument("input_file", type=Path, help="CSV or TSV file with energy_eV and cross_section_m2 columns")
    xsec.add_argument("--workspace", type=Path, required=True, help="workspace containing prepared_registry/")
    xsec.add_argument("--source", choices=["lxcat_offline", "local_file"], default="local_file")
    xsec.add_argument("--reaction-id", default=None, help="prepared_registry reaction channel id to link if present")
    xsec.add_argument("--target", default=None, help="target species label used for output naming/provenance")
    xsec.add_argument("--license-note", default=None, help="license/citation note to write into metadata")

    xmap = subparsers.add_parser(
        "apply-cross-section-mapping",
        help="apply reviewed cross-section mappings to prepared_registry electron channels",
    )
    xmap.add_argument("mapping_file", type=Path, help="YAML file containing reviewed cross-section mappings")
    xmap.add_argument("--workspace", type=Path, required=True, help="workspace containing prepared_registry/")

    mplan = subparsers.add_parser("plan-missing", help="write an enrichment action plan from missing_data.yaml")
    mplan.add_argument("outputs_or_missing_data", type=Path, help="outputs directory or missing_data.yaml file")
    mplan.add_argument("--output", type=Path, default=Path("missing_plan.yaml"), help="destination missing_plan.yaml")

    tmissing = subparsers.add_parser("template-missing", help="write manual fill-in templates from missing_data.yaml")
    tmissing.add_argument("outputs_or_missing_data", type=Path, help="outputs directory or missing_data.yaml file")
    tmissing.add_argument("--output-dir", type=Path, default=Path("manual_inputs"), help="destination directory for templates")

    slist = subparsers.add_parser("source-list", help="show source-provider status for a source profile")
    slist.add_argument("--source-profile", default="local_only", help="source profile name or YAML path")
    slist.add_argument("--registry", type=Path, default=Path("registry"), help="local registry root")

    promote = subparsers.add_parser(
        "promote", help="promote reviewed prepared/candidate registry items into curated registry"
    )
    promote.add_argument("prepared_registry", type=Path, help="prepared_registry or candidate_registry root")
    promote.add_argument("--registry", type=Path, default=Path("registry"), help="curated registry root")
    promote.add_argument("--decision", type=Path, required=True, help="review decision YAML")
    mode = promote.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="apply", action="store_false", help="plan promotion without registry mutation")
    mode.add_argument("--apply", dest="apply", action="store_true", help="apply accepted promotions to registry")
    promote.set_defaults(apply=False)


def run_maintenance_command(args: Any) -> int | None:
    if args.command not in COMMANDS:
        return None
    if args.command == "infer-candidates":
        return _infer_candidates(args.input, args.registry, args.output)
    if args.command == "enrich":
        return _enrich(args.input, args.registry, args.workspace, args.source_profile, fresh=args.fresh)
    if args.command == "import-cross-sections":
        return _import_cross_sections(
            args.input_file,
            args.workspace,
            args.source,
            args.reaction_id,
            args.target,
            args.license_note,
        )
    if args.command == "apply-cross-section-mapping":
        return _apply_cross_section_mapping(args.mapping_file, args.workspace)
    if args.command == "plan-missing":
        return _plan_missing(args.outputs_or_missing_data, args.output)
    if args.command == "template-missing":
        return _template_missing(args.outputs_or_missing_data, args.output_dir)
    if args.command == "source-list":
        return _source_list(args.source_profile, args.registry)
    return _promote(args.prepared_registry, args.registry, args.decision, args.apply)


def _infer_candidates(input_path: Path, registry_root: Path, output_dir: Path | None) -> int:
    config = load_case_config(input_path, registry_root)
    output_dir = output_dir or input_path.parent / "candidate_registry"
    candidates = build_candidate_registry(config, FileRegistry(registry_root))
    write_candidate_registry(output_dir=output_dir, candidates=candidates)
    summary = candidates["summary"]
    print(f"Generated inferred candidate registry: {output_dir}")
    print(f"  species_candidates: {summary['n_species_candidates']}")
    print(f"  reaction_candidates: {summary['n_reaction_candidates']}")
    print("  registry_mutated: false")
    return 0


def _enrich(
    input_path: Path,
    registry_root: Path,
    workspace: Path,
    source_profile: str,
    *,
    fresh: bool,
) -> int:
    report = enrich_case(input_path, registry_root, workspace, source_profile, fresh=fresh)
    summary = report["summary"]
    print(f"Enriched prepared registry: {workspace / 'prepared_registry'}")
    print(f"  source_profile: {report['source_profile']}")
    print(f"  workspace_mode: {report['workspace']['mode']}")
    if report["workspace"]["reused_existing_prepared_registry"]:
        print("  warning: existing prepared-registry overlays were preserved; use --fresh for a clean run")
    for key in (
        "species_seeded_from_reactions",
        "properties_filled",
        "properties_filled_for_seeded_species",
        "property_conflicts",
        "reaction_channels_imported",
        "cross_section_assets_registered",
        "unresolved_product_species",
        "unresolved_items",
    ):
        print(f"  {key}: {summary.get(key, 0)}")
    print(f"  prepare_report: {workspace / 'prepare_report.yaml'}")
    print(f"  enrichment_report: {workspace / 'enrichment_report.yaml'}")
    print("  registry_mutated: false")
    print("  auto_promoted: false")
    return 0


def _import_cross_sections(
    input_file: Path,
    workspace: Path,
    source: str,
    reaction_id: str | None,
    target: str | None,
    license_note: str | None,
) -> int:
    result = import_cross_section_table(
        input_file,
        workspace,
        source=source,
        reaction_id=reaction_id,
        target=target,
        license_note=license_note,
    )
    print(f"Imported cross-section table: {result.asset_path}")
    print(f"  metadata: {result.metadata_path}")
    print(f"  registry_asset_path: {result.relative_asset_path}")
    print(f"  rows: {result.row_count}")
    print("  registry_mutated: false")
    if reaction_id:
        print(f"  prepared_reaction_files_linked: {len(result.linked_reaction_files)}")
        if not result.linked_reaction_files:
            print("  link_status: reaction_id not found in prepared_registry; use apply-cross-section-mapping after review")
    return 0


def _apply_cross_section_mapping(mapping_file: Path, workspace: Path) -> int:
    report = apply_cross_section_mappings(workspace / "prepared_registry", mapping_file)
    report_path = workspace / "cross_section_mapping_report.yaml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Applied cross-section mappings: {mapping_file}")
    for key in ("n_mappings", "n_updated", "n_unresolved"):
        print(f"  {key.removeprefix('n_')}: {report['summary'][key]}")
    print(f"  report: {report_path}")
    print(f"  prepared_registry_mutated: {str(report['prepared_registry_mutated']).lower()}")
    print("  curated_registry_mutated: false")
    return 1 if report["summary"]["n_unresolved"] else 0


def _plan_missing(input_path: Path, output: Path) -> int:
    plan = write_missing_plan(input_path, output)
    print(f"Wrote missing-data enrichment plan: {output}")
    print(f"  total_missing_items: {plan['summary']['total_missing_items']}")
    print(f"  suggested_actions: {plan['summary']['suggested_actions']}")
    for action in plan.get("actions", [])[:5]:
        print(f"  action[{action['priority']}]: {action['action']} ({len(action['subjects'])} subjects)")
    print("  data_fetched: false")
    return 0


def _template_missing(input_path: Path, output_dir: Path) -> int:
    report = generate_missing_input_templates(input_path, output_dir)
    print(f"Wrote manual missing-data templates: {output_dir}")
    for key in (
        "n_missing_items",
        "n_species_property_records",
        "n_cross_section_mappings",
        "n_reaction_energetics_records",
    ):
        print(f"  {key.removeprefix('n_')}: {report['summary'][key]}")
    print("  data_fetched: false")
    print("  registry_mutated: false")
    return 0


def _source_list(source_profile: str, registry: Path) -> int:
    print(format_source_list_report(build_source_list_report(source_profile, registry)))
    return 0


def _promote(prepared_registry: Path, registry: Path, decision: Path, apply: bool) -> int:
    report = promote_reviewed_registry(prepared_registry, registry, decision, apply=apply)
    print(f"Wrote promote report: {prepared_registry.parent / 'promote_report.yaml'}")
    print(f"  mode: {'apply' if apply else 'dry_run'}")
    for key in ("n_promoted_species", "n_promoted_channels", "n_rejected", "n_conflicts"):
        print(f"  {key.removeprefix('n_')}: {report['summary'][key]}")
    print(f"  registry_mutated: {str(report['registry_mutated']).lower()}")
    return 0
