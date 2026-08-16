from __future__ import annotations

import argparse
from pathlib import Path

from external_data_tools.source_setup import run_source_setup
from external_data_tools.source_setup_report import format_source_setup_summary


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report, exit_code = run_source_setup(
        args.config,
        check=args.check,
        install_chemicals=args.install_chemicals,
        download_explicit_data=args.download_explicit_data,
        write_report=args.write_report,
    )
    print(format_source_setup_summary(report))
    return exit_code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check external source acquisition setup.")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="source access profile YAML",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate setup without installing or downloading",
    )
    parser.add_argument(
        "--install-chemicals",
        action="store_true",
        help="explicitly install optional chemicals package requirements",
    )
    parser.add_argument(
        "--download-explicit-data",
        action="store_true",
        help="download explicit URL manifests when policy allows it",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        default=None,
        help="optional report path override",
    )
    return parser
