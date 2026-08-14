"""CLI and stable public API for local LXCat cross-section imports."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from external_data_tools.lxcat_import_workflow import import_lxcat_raw_file
from external_data_tools.lxcat_parser import ParsedCrossSection, parse_lxcat_raw_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize manually downloaded LXCat/BOLSIG-style raw files."
    )
    parser.add_argument("raw_file", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", default="lxcat_manual")
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=Path("external_data/lxcat/mappings.yaml"),
    )
    parser.add_argument("--reaction-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = import_lxcat_raw_file(
        args.raw_file,
        workspace=args.workspace,
        target=args.target,
        source=args.source,
        mapping_file=args.mapping_file,
        reaction_id=args.reaction_id,
        dry_run=args.dry_run,
    )
    report_path = args.workspace / "lxcat_import_report.yaml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        "lxcat raw import: "
        f"assets={report['summary']['n_assets_imported']} "
        f"mapped={report['summary']['n_mapped']} "
        f"unresolved={report['summary']['n_unresolved']} "
        f"report={report_path}"
    )
    return 1 if report["summary"]["n_unresolved"] else 0


__all__ = ["ParsedCrossSection", "import_lxcat_raw_file", "main", "parse_lxcat_raw_file"]


if __name__ == "__main__":
    raise SystemExit(main())
