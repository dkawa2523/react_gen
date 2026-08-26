"""Generate candidate chemistry and manage its local evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from reactgen import adopt, derive, export, ingest, plan
from reactgen.balance import imbalance
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import POLICIES, run
from reactgen.registry import Registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rgen", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("generate", help="generate, assess and select candidates")
    _case_arguments(build)
    build.add_argument("--policy", choices=POLICIES, default="review")
    build.add_argument("--out", type=Path, default=None)
    build.add_argument(
        "--csv",
        action="store_true",
        help="also write compact CSV views and per-assessment summaries and SVG graphs",
    )
    build.set_defaults(run=_generate)

    verify = commands.add_parser("check", help="validate curated Registry structure")
    verify.add_argument("--registry", type=Path, required=True)
    verify.set_defaults(run=_check)

    backlog = commands.add_parser("plan", help="list unknown evidence for a case")
    _case_arguments(backlog)
    backlog.set_defaults(run=_plan)

    absorb = commands.add_parser(
        "ingest",
        help="match a local data snapshot onto a generated candidate bundle",
    )
    absorb.add_argument("snapshot", type=Path)
    absorb.add_argument("--bundle", type=Path, required=True)
    absorb.add_argument("--overlay", type=Path, default=Path("overlay.yaml"))
    absorb.set_defaults(run=_ingest)

    infer = commands.add_parser(
        "derive",
        help="derive reviewed excited-state properties in an overlay",
    )
    infer.add_argument("--registry", type=Path, required=True)
    infer.add_argument("--overlay", type=Path, default=Path("overlay.yaml"))
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


def _case_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("case", type=Path)
    parser.add_argument("--registry", type=Path, default=Path("registry"))
    parser.add_argument("--overlay", type=Path, default=None)
    parser.add_argument(
        "--known",
        type=Path,
        action="append",
        default=[],
        help="local reaction or numerical-data snapshot; repeatable",
    )


def _generate(args: argparse.Namespace) -> int:
    case = Case.load(args.case)
    catalog = EvidenceCatalog.load(
        args.registry,
        overlay=args.overlay,
        known=tuple(args.known),
    )
    result = run(case, catalog, args.policy)

    outdir = args.out or args.case.parent / "outputs"
    try:
        export.write(outdir, result, include_csv=args.csv)
    except OSError as error:
        print(f"error: cannot write bundle: {error}", file=sys.stderr)
        return 1
    mechanical_states = sum(
        state.origin == "mechanical" for state in result.candidates.states.values()
    )
    mechanical_reactions = sum(
        reaction.origin == "mechanical" for reaction in result.candidates.reactions.values()
    )
    print(outdir)
    print(f"  states       {len(result.candidates.states)} ({mechanical_states} mechanical)")
    print(f"  reactions    {len(result.candidates.reactions)} ({mechanical_reactions} mechanical)")
    print(f"  selected     {len(result.selection.reaction_ids)} ({args.policy})")
    print(f"  complete     {result.candidates.complete}")
    if not result.candidates.complete:
        print(f"  stop_reason  {result.candidates.stop_reason}")
    return 0 if result.candidates.complete else 1


def _plan(args: argparse.Namespace) -> int:
    case = Case.load(args.case)
    catalog = EvidenceCatalog.load(
        args.registry,
        overlay=args.overlay,
        known=tuple(args.known),
    )
    result = run(case, catalog, "acquisition")
    yaml.safe_dump(plan.build(result), sys.stdout, sort_keys=False, allow_unicode=True)
    return 0 if result.candidates.complete else 1


def _ingest(args: argparse.Namespace) -> int:
    report = ingest.ingest(args.snapshot, args.bundle, args.overlay)
    print(f"  accepted    {report.accepted} -> {args.overlay}")
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
    merged = derive.merged(_document(args.overlay), filled)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(merged, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
    values = sum(len(entry) for entry in filled["properties"].values())
    print(f"  states      {len(derive.parents(registry))}")
    print(f"  properties  {values}")
    print(f"  thermo      {len(filled['thermo'])}")
    print(f"  overlay     {args.out}")
    return 0


def _adopt(args: argparse.Namespace) -> int:
    report = adopt.adopt(args.overlay, args.registry, args.dry_run)
    for species_id, names in sorted(report.written.items()):
        print(f"  {species_id:14} {' '.join(names)}")
    print(f"  wrote       {report.values} entries across {len(report.written)} subjects")
    if report.held:
        print(f"  kept        {report.held} existing curated values")
    if report.unplaced:
        print(f"  no Registry record for {' '.join(report.unplaced)}")
    if args.dry_run:
        print("  dry run: nothing written")
    return 0


def _document(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


if __name__ == "__main__":
    raise SystemExit(main())
