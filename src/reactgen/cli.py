"""Generate candidate chemistry and manage its local evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from reactgen import adopt, derive, export, ingest, needs, yamlio
from reactgen.balance import imbalance
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.presentation import analysis_overview
from reactgen.registry import Registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rgen", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "analyze", help="investigate candidate states, channels and numerical data"
    )
    build.add_argument("gases", nargs="*", help="neutral ground-state formulas")
    build.add_argument(
        "--input", type=Path, help="validated physical input YAML, instead of gas arguments"
    )
    build.add_argument(
        "--evidence",
        type=Path,
        action="append",
        default=[],
        help="local Registry directory or snapshot/overlay file; repeatable",
    )
    build.add_argument("--out", type=Path, default=Path("result"))
    build.set_defaults(run=_analyze)

    verify = commands.add_parser("check", help="validate curated Registry structure")
    verify.add_argument("--registry", type=Path, required=True)
    verify.set_defaults(run=_check)

    backlog = commands.add_parser(
        "needs", help="summarize conclusions and next work from a saved result"
    )
    backlog.add_argument("result", type=Path)
    backlog.add_argument(
        "--detail", action="store_true", help="include every affected target and saved reason"
    )
    backlog.set_defaults(run=_needs)

    view = commands.add_parser("view", help="derive optional views from the saved canonical result")
    view.add_argument("result", type=Path)
    view.add_argument("--kind", choices=("csv", "network", "matrix", "pathway"), required=True)
    view.add_argument("--out", type=Path, required=True)
    view.add_argument("--seed", action="append", default=[])
    view.add_argument("--target", default=None)
    view.set_defaults(run=_view)

    absorb = commands.add_parser(
        "ingest",
        help="match a local data snapshot onto canonical candidate identities",
    )
    absorb.add_argument("snapshot", type=Path)
    absorb.add_argument("--result", type=Path, required=True)
    absorb.add_argument("--overlay", type=Path, default=Path("overlay.yaml"))
    absorb.set_defaults(run=_ingest)

    infer = commands.add_parser(
        "derive",
        help="derive reviewed excited-state properties in an overlay",
    )
    infer.add_argument("--registry", type=Path, required=True)
    infer.add_argument("--overlay", type=Path, default=None)
    infer.add_argument("--out", type=Path, required=True)
    infer.set_defaults(run=_derive)

    settle = commands.add_parser(
        "adopt",
        help="promote a reviewed overlay into curated Registry files",
    )
    settle.add_argument("overlay", type=Path)
    settle.add_argument("--registry", type=Path, required=True)
    settle.add_argument("--dry-run", action="store_true")
    settle.set_defaults(run=_adopt)

    args = parser.parse_args(argv)
    try:
        return int(args.run(args))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _analyze(args: argparse.Namespace) -> int:
    if bool(args.input) == bool(args.gases):
        raise ValueError("provide gas formulas or --input, exactly one")
    case = Case.load(args.input) if args.input else Case("analysis", tuple(args.gases))
    catalog = EvidenceCatalog.load_paths(tuple(args.evidence))
    result = analyze(case, catalog)
    try:
        export.write(args.out, result)
    except export.PartialOutputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: cannot save result: {error}", file=sys.stderr)
        return 1
    # Read the committed source of truth: success output describes the same
    # values and conclusions as the persisted result and every later view.
    document = export.read(args.out)
    print("\n".join(analysis_overview(document, needs.build(document))))
    print(f'Next work details: rgen needs "{args.out}" --detail')
    print("Results:")
    for name in export.PUBLIC_FILES:
        print(f"  {args.out / name}")
    return 0 if result.candidates.complete else 1


def _needs(args: argparse.Namespace) -> int:
    yaml.safe_dump(
        needs.build(export.read(args.result), detail=args.detail),
        sys.stdout,
        sort_keys=False,
        allow_unicode=True,
    )
    return 0


def _view(args: argparse.Namespace) -> int:
    document = export.read(args.result)
    if args.kind == "csv":
        if args.seed or args.target:
            raise ValueError("--seed and --target apply to pathway/network views")
        export.rebuild_views(document, args.out)
    else:
        from reactgen.views import view

        path = view(document, args.out, args.kind, seeds=tuple(args.seed), target=args.target)
        if args.kind == "matrix" and path.suffix == ".html":
            print(f"Split matrix: open {path} to view every reaction panel")
        else:
            print(path)
        return 0
    print(args.out)
    return 0


def _ingest(args: argparse.Namespace) -> int:
    report = ingest.ingest(args.snapshot, args.result, args.overlay)
    print(f"  matched     {report.accepted} -> {args.overlay} (matching does not approve evidence)")
    print(f"  review      {len(report.review)} -> {args.overlay.with_name('review_queue.yaml')}")
    for item in report.review[:10]:
        print(f"    {item['reason']:18} {item['wrote']}")
    return 0


def _check(args: argparse.Namespace) -> int:
    registry = Registry.load(args.registry)
    issues = []
    for reaction in (reaction for channels in registry.channels.values() for reaction in channels):
        if reason := imbalance(reaction, registry.species):
            issues.append((reaction.id, reason))
    for reaction_id, reason in issues:
        print(f"  fail  {reaction_id}  {reason}")
    print(
        f"{len(registry.species)} species, "
        f"{sum(len(group) for group in registry.channels.values())} reactions, "
        f"{len(issues)} structural failures"
    )
    return 1 if issues else 0


def _derive(args: argparse.Namespace) -> int:
    registry = Registry.load(args.registry)
    filled = derive.overlay(registry)
    merged = derive.merged(_document(args.overlay) if args.overlay else {}, filled)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(merged, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    values = sum(len(entry) for entry in filled["properties"].values())
    print(f"  derived     {values} property values across {len(filled['properties'])} states")
    print(f"  overlay     {args.out}")
    print(
        "  scope       mass and resolved-level formation enthalpy; "
        "missing prerequisites remain unresolved"
    )
    return 0


def _adopt(args: argparse.Namespace) -> int:
    report = adopt.adopt(args.overlay, args.registry, args.dry_run)
    for species_id, names in sorted(report.written.items()):
        print(f"  {species_id:14} {' '.join(names)}")
    print(f"  wrote       {report.values} entries across {len(report.written)} subjects")
    if report.held:
        print(f"  kept        {report.held} existing entries")
    if report.unplaced:
        print(f"  no Registry record for {' '.join(report.unplaced)}")
    if args.dry_run:
        print("  dry run: nothing written")
    return 0


def _document(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    document = yamlio.load(path.read_text(encoding="utf-8"))
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ValueError("overlay must be a mapping")
    return document


if __name__ == "__main__":
    raise SystemExit(main())
