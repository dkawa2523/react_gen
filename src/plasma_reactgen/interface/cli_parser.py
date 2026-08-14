from __future__ import annotations

import argparse
from pathlib import Path

from plasma_reactgen.interface.maintenance_parser import (
    COMMANDS as MAINTENANCE_COMMANDS,
)
from plasma_reactgen.interface.maintenance_parser import add_maintenance_commands


def parse_command(arguments: list[str]) -> tuple[argparse.Namespace, argparse.ArgumentParser]:
    parser = argparse.ArgumentParser(prog="reactgen")
    subcommands = parser.add_subparsers(dest="command", required=True)
    _add_generate_parser(subcommands)
    _add_visualize_parser(subcommands)
    _add_dev_check_parser(subcommands)
    _add_export_dnt_parser(subcommands)
    _add_template_parser(subcommands)
    if arguments and arguments[0] in MAINTENANCE_COMMANDS:
        add_maintenance_commands(subcommands)
    return parser.parse_args(arguments), parser


def _add_generate_parser(subcommands: argparse._SubParsersAction) -> None:
    parser = subcommands.add_parser(
        "generate", help="generate registry-driven network outputs from a case YAML"
    )
    parser.add_argument("input", type=Path, help="case input YAML")
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="explicit local registry root; disables automatic pack selection",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output directory; defaults to CASE_DIR/outputs",
    )


def _add_visualize_parser(subcommands: argparse._SubParsersAction) -> None:
    parser = subcommands.add_parser(
        "visualize", help="create statistical charts and Graphviz reaction-network outputs"
    )
    parser.add_argument(
        "outputs", type=Path, help="case output directory containing network.*.yaml files"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="visualization destination; defaults to OUTPUTS/visualizations",
    )
    parser.add_argument(
        "--include-self-loops",
        action="store_true",
        help="include self-loop edges such as elastic/non-changing channels",
    )
    parser.add_argument(
        "--include-non-expanding",
        action="store_true",
        help="include reactions whose non-electron species set does not change",
    )
    parser.add_argument(
        "--max-reactions",
        type=int,
        default=250,
        help="maximum reactions to draw in the Graphviz network; use -1 for all",
    )
    parser.add_argument(
        "--formats",
        default="svg,png",
        help="comma-separated Graphviz render formats, e.g. svg,png,pdf",
    )


def _add_dev_check_parser(subcommands: argparse._SubParsersAction) -> None:
    parser = subcommands.add_parser(
        "dev-check", help="check registry readability and basic references"
    )
    parser.add_argument("--registry", type=Path, default=Path("registry"))
    parser.add_argument("--strict", action="store_true")


def _add_export_dnt_parser(subcommands: argparse._SubParsersAction) -> None:
    parser = subcommands.add_parser(
        "export-dnt", help="export solver-free pair-wise DNT+/DNT+DM input YAML files"
    )
    parser.add_argument("input", type=Path, help="case input YAML")
    parser.add_argument(
        "--registry", type=Path, default=Path("registry"), help="local registry root"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output directory for dnt_manifest.yaml and dnt_inputs/",
    )


def _add_template_parser(subcommands: argparse._SubParsersAction) -> None:
    parser = subcommands.add_parser("template", help="print a registration template to stdout")
    parser.add_argument("kind", choices=["species", "electron-pair", "ion-pair"])
    parser.add_argument("args", nargs="+")
