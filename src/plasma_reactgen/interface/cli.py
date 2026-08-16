from __future__ import annotations

import argparse
import sys

from plasma_reactgen.infrastructure.indexer import (
    check_registry_details,
    format_registry_check,
)
from plasma_reactgen.interface.cli_parser import parse_command
from plasma_reactgen.interface.dnt_command import run_export_dnt
from plasma_reactgen.interface.generate_command import run_generate
from plasma_reactgen.interface.maintenance_commands import run_maintenance_command
from plasma_reactgen.interface.registration_templates import render_registration_template
from plasma_reactgen.interface.visualize_command import run_visualize


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args, parser = parse_command(arguments)
    return _dispatch_command(args, parser)


def _dispatch_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "generate":
        return run_generate(args.input, args.registry, args.output)
    if args.command == "visualize":
        return run_visualize(
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
        return int(bool(details["errors"]))
    if args.command == "export-dnt":
        return run_export_dnt(args.input, args.registry, args.output)
    if args.command == "template":
        print(render_registration_template(args.kind, args.args))
        return 0

    maintenance_result = run_maintenance_command(args)
    if maintenance_result is not None:
        return maintenance_result
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
