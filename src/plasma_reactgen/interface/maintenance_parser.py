"""Register compatibility commands for registry preparation and review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
    infer.add_argument(
        "--registry", type=Path, default=Path("registry"), help="local registry root"
    )
    infer.add_argument(
        "--output", type=Path, default=None, help="candidate_registry output directory"
    )

    enrich = subparsers.add_parser(
        "enrich", help="prepare and run configured local/offline enrichers into a workspace"
    )
    enrich.add_argument("input", type=Path, help="case input YAML")
    enrich.add_argument(
        "--registry", type=Path, default=Path("registry"), help="local registry root"
    )
    enrich.add_argument(
        "--workspace", type=Path, required=True, help="workspace for prepared_registry and reports"
    )
    enrich.add_argument(
        "--source-profile", default="local_only", help="source profile name or YAML path"
    )
    enrich.add_argument(
        "--fresh",
        action="store_true",
        help="clear enrich-owned workspace artifacts before preparing the registry",
    )

    xsec = subparsers.add_parser(
        "import-cross-sections",
        help="import local CSV/TSV cross-section tables into prepared_registry assets",
    )
    xsec.add_argument(
        "input_file", type=Path, help="CSV or TSV file with energy_eV and cross_section_m2 columns"
    )
    xsec.add_argument(
        "--workspace", type=Path, required=True, help="workspace containing prepared_registry/"
    )
    xsec.add_argument("--source", choices=["lxcat_offline", "local_file"], default="local_file")
    xsec.add_argument(
        "--reaction-id",
        default=None,
        help="prepared_registry reaction channel id to link if present",
    )
    xsec.add_argument(
        "--target", default=None, help="target species label used for output naming/provenance"
    )
    xsec.add_argument(
        "--license-note", default=None, help="license/citation note to write into metadata"
    )

    xmap = subparsers.add_parser(
        "apply-cross-section-mapping",
        help="apply reviewed cross-section mappings to prepared_registry electron channels",
    )
    xmap.add_argument(
        "mapping_file", type=Path, help="YAML file containing reviewed cross-section mappings"
    )
    xmap.add_argument(
        "--workspace", type=Path, required=True, help="workspace containing prepared_registry/"
    )

    mplan = subparsers.add_parser(
        "plan-missing", help="write an enrichment action plan from missing_data.yaml"
    )
    mplan.add_argument(
        "outputs_or_missing_data", type=Path, help="outputs directory or missing_data.yaml file"
    )
    mplan.add_argument(
        "--output",
        type=Path,
        default=Path("missing_plan.yaml"),
        help="destination missing_plan.yaml",
    )

    tmissing = subparsers.add_parser(
        "template-missing", help="write manual fill-in templates from missing_data.yaml"
    )
    tmissing.add_argument(
        "outputs_or_missing_data", type=Path, help="outputs directory or missing_data.yaml file"
    )
    tmissing.add_argument(
        "--output-dir",
        type=Path,
        default=Path("manual_inputs"),
        help="destination directory for templates",
    )

    slist = subparsers.add_parser(
        "source-list", help="show source-provider status for a source profile"
    )
    slist.add_argument(
        "--source-profile", default="local_only", help="source profile name or YAML path"
    )
    slist.add_argument(
        "--registry", type=Path, default=Path("registry"), help="local registry root"
    )

    promote = subparsers.add_parser(
        "promote", help="promote reviewed prepared/candidate registry items into curated registry"
    )
    promote.add_argument(
        "prepared_registry", type=Path, help="prepared_registry or candidate_registry root"
    )
    promote.add_argument(
        "--registry", type=Path, default=Path("registry"), help="curated registry root"
    )
    promote.add_argument("--decision", type=Path, required=True, help="review decision YAML")
    mode = promote.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="apply",
        action="store_false",
        help="plan promotion without registry mutation",
    )
    mode.add_argument(
        "--apply", dest="apply", action="store_true", help="apply accepted promotions to registry"
    )
    promote.set_defaults(apply=False)


__all__ = ["COMMANDS", "add_maintenance_commands"]
