from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .registry_admin import (
    build_registry_pack,
    import_lxcat_raw,
    import_property_snapshot,
    import_rate_snapshot,
    plan_registry_pack,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m external_data_tools.data_admin")
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan_registry_pack")
    plan.add_argument("--seed-gases", nargs="+", required=True)
    plan.add_argument("--max-depth", type=int, default=2)
    plan.add_argument("--registry", type=Path, default=Path("registry"))
    plan.add_argument("--output", type=Path, default=Path("registry_pack_plan.yaml"))

    lxcat = commands.add_parser("import_lxcat_raw")
    lxcat.add_argument("input", type=Path)
    lxcat.add_argument("--registry", type=Path, required=True)
    lxcat.add_argument("--report-dir", type=Path, default=Path("data_admin_reports"))
    lxcat.add_argument(
        "--redistribution-status",
        choices=["permitted", "internal", "site-local"],
        default="site-local",
    )

    properties = commands.add_parser("import_property_snapshot")
    properties.add_argument("input", type=Path)
    properties.add_argument("--registry", type=Path, required=True)
    properties.add_argument("--report-dir", type=Path, default=Path("data_admin_reports"))

    rates = commands.add_parser("import_rate_snapshot")
    rates.add_argument("input", type=Path)
    rates.add_argument("--registry", type=Path, required=True)
    rates.add_argument("--report-dir", type=Path, default=Path("data_admin_reports"))

    build = commands.add_parser("build_registry_pack")
    build.add_argument("--id", required=True)
    build.add_argument("--version", required=True)
    build.add_argument("--seed-gases", nargs="+", required=True)
    build.add_argument("--max-depth", type=int, default=2)
    build.add_argument("--registry", type=Path, required=True)
    build.add_argument("--packs-root", type=Path, default=Path("registry_packs"))
    build.add_argument(
        "--redistribution-status",
        choices=["permitted", "internal", "site-local"],
        default="site-local",
    )

    args = parser.parse_args(argv)
    if args.command == "plan_registry_pack":
        result = plan_registry_pack(
            seed_gases=args.seed_gases,
            max_depth=args.max_depth,
            registry_root=args.registry,
        )
        _write(args.output, result)
    elif args.command == "import_lxcat_raw":
        result = import_lxcat_raw(
            args.input,
            registry_root=args.registry,
            report_dir=args.report_dir,
            redistribution_status=args.redistribution_status,
        )
    elif args.command == "import_property_snapshot":
        result = import_property_snapshot(
            args.input,
            registry_root=args.registry,
            report_dir=args.report_dir,
        )
    elif args.command == "import_rate_snapshot":
        result = import_rate_snapshot(
            args.input,
            registry_root=args.registry,
            report_dir=args.report_dir,
        )
    else:
        result = build_registry_pack(
            pack_id=args.id,
            version=args.version,
            seed_gases=args.seed_gases,
            max_depth=args.max_depth,
            registry_root=args.registry,
            packs_root=args.packs_root,
            redistribution_status=args.redistribution_status,
        )

    print(yaml.safe_dump(result.get("summary", result), sort_keys=False, allow_unicode=True).rstrip())
    return 0 if result.get("built", True) else 1


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
