from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from external_data_tools.chemical_identity_fetch import fetch_chemical_identity
from external_data_tools.chemical_identity_sources import PROVIDERS


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = fetch_chemical_identity(
            args.species_list,
            output_root=args.output_root,
            snapshot_path=args.snapshot,
            provider=args.provider,
            dry_run=args.dry_run,
            local_snapshot=args.local_snapshot,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"chemical identity fetch: {exc}")
        return 1
    print(_result_summary(args, result))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build local chemical identity snapshots from optional external identity providers."
        )
    )
    parser.add_argument("species_list", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("external_data/raw/chemical_identity"),
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("external_data/snapshots/chemical_identity.yaml"),
    )
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default="chebi")
    parser.add_argument("--local-snapshot", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _result_summary(args: argparse.Namespace, result: dict[str, Any]) -> str:
    if args.dry_run:
        return (
            "chemical identity fetch dry-run: "
            f"provider={args.provider} planned={result['summary']['planned']}"
        )
    return (
        "chemical identity fetch: "
        f"provider={args.provider} records={len(result.get('records', []))} "
        f"unresolved={len(result.get('unresolved', []))} snapshot={args.snapshot}"
    )
