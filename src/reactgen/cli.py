"""Command line: generate a bundle, check a registry, plan and ingest data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from reactgen import (
    adopt,
    audit,
    derive,
    export,
    ingest,
    known,
    layers,
    lock,
    plan,
    quality,
)
from reactgen.case import Case
from reactgen.expand import expand
from reactgen.registry import Registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rgen", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("generate", help="build the reaction and dataset bundle")
    build.add_argument("case", type=Path)
    build.add_argument("--registry", type=Path, default=Path("registry"))
    build.add_argument("--overlay", type=Path, default=None, help="reviewed imports to merge in")
    build.add_argument("--out", type=Path, default=None)
    build.add_argument(
        "--known",
        type=Path,
        action="append",
        default=[],
        help="snapshot a source published; repeatable. Confirms a reaction exists.",
    )
    build.add_argument(
        "--layers",
        default=None,
        help="which layers of judgement to evaluate and record, comma separated: "
        + ", ".join(layers.LAYERS)
        + ". All of them by default",
    )
    build.add_argument(
        "--show-unreferenced",
        action="store_true",
        help="list the reactions no source states, once --known is given",
    )
    build.set_defaults(run=_generate)

    verify = commands.add_parser("check", help="validate the registry on its own")
    verify.add_argument("--registry", type=Path, default=Path("registry"))
    verify.set_defaults(run=_check)

    backlog = commands.add_parser("plan", help="group a case's gaps into an acquisition plan")
    backlog.add_argument("case", type=Path)
    backlog.add_argument("--registry", type=Path, default=Path("registry"))
    backlog.set_defaults(run=_plan)

    absorb = commands.add_parser("ingest", help="match a data snapshot onto registered reactions")
    absorb.add_argument("snapshot", type=Path)
    absorb.add_argument("--registry", type=Path, default=Path("registry"))
    absorb.add_argument("--overlay", type=Path, default=Path("overlay.yaml"))
    absorb.set_defaults(run=_ingest)

    infer = commands.add_parser(
        "derive", help="fill excited-state properties from the ground state they belong to"
    )
    infer.add_argument("--registry", type=Path, default=Path("registry"))
    infer.add_argument("--overlay", type=Path, default=Path("overlay.yaml"))
    infer.add_argument("--out", type=Path, required=True)
    infer.set_defaults(run=_derive)

    settle = commands.add_parser(
        "adopt", help="write a reviewed overlay into the registry files it belongs to"
    )
    settle.add_argument("overlay", type=Path)
    settle.add_argument("--registry", type=Path, default=Path("registry"))
    settle.add_argument("--dry-run", action="store_true", help="report without writing")
    settle.set_defaults(run=_adopt)

    args = parser.parse_args(argv)
    return args.run(args)


def _derive(args) -> int:
    registry = Registry.load(args.registry, overlay=args.overlay)
    filled = derive.overlay(registry)
    # Written as one overlay rather than a second one to chain, because
    # `Registry.load` takes a single file. Derived entries only ever fill a gap,
    # so merging cannot overwrite what the acquired overlay already said.
    merged = derive.merged(_document(args.overlay), filled)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        yaml.safe_dump(merged, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )
    values = sum(len(entry) for entry in filled["properties"].values())
    print(f"  states      {len(derive.parents(registry))} with a ground state to inherit from")
    print(f"  properties  {values} filled across {len(filled['properties'])} states")
    print(f"  thermo      {len(filled['thermo'])} polynomials shifted by their level energy")
    print(f"  overlay     {args.out}")
    return 0


def _adopt(args) -> int:
    report = adopt.adopt(_document(args.overlay), args.registry, args.dry_run)
    for species_id, names in sorted(report.written.items()):
        print(f"  {species_id:14} {' '.join(names)}")
    print(f"  wrote       {report.values} values across {len(report.written)} species")
    if report.held:
        print(f"  kept        {report.held} the registry already answered for")
    if report.unplaced:
        print(f"  no file for {' '.join(report.unplaced)}")
    if args.dry_run:
        print("  dry run: nothing written")
    return 0


def _document(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _generate(args) -> int:
    case = Case.load(args.case)
    registry = Registry.load(args.registry, overlay=args.overlay)
    network, gaps = expand(registry, case)
    gaps += audit.audit(registry, network)
    gaps += quality.quality(network, case, registry)
    listed = known.load(args.known) if args.known else None
    gaps += _references(network, args.known, args.show_unreferenced)

    outdir = args.out or args.case.parent / "outputs"
    identifier = lock.mechanism_id(case, registry)
    export.write(
        outdir, case, network, registry, gaps, identifier, listed, layers.select(args.layers)
    )
    lock.write(outdir / "lock.yaml", lock.build(case, network, registry))

    blocking = sum(gap.severity == "blocking" for gap in gaps)
    print(f"{outdir}")
    print(f"  mechanism   {identifier}")
    print(f"  species     {len(network.species)}")
    print(f"  reactions   {len(network.reactions)}  {network.by_family()}")
    print(f"  complete    {not network.truncated}")
    print(f"  gaps        {blocking} blocking, {len(gaps) - blocking} other")
    return 1 if blocking else 0


def _references(network, paths: list[Path], show: bool) -> list:
    """Which reactions a source states, and optionally which none does.

    Confirming against a source is opt-in because it needs files the user
    fetched; listing what stays unreferenced is a second choice, because a long
    list of the unconfirmed is noise until someone means to work through it.
    """

    from reactgen.model import Gap

    if not paths:
        return []
    # External sources only. Indexing the registry would confirm every reaction
    # against itself and answer nothing.
    listed = known.load(paths)
    missing = [r for r in network.reactions if not listed.lists(r.equation)]
    summary = [
        Gap(
            "references",
            "sources",
            f"{len(listed)} equations indexed from {listed.sources}",
            "info",
        )
    ]
    if not show:
        detail = f"{len(missing)} of {len(network.reactions)} reactions are unreferenced"
        return [*summary, Gap("unreferenced", "reactions", detail, "info")]
    return summary + [Gap("unreferenced", item.id, item.equation, "info") for item in missing]


def _check(args) -> int:
    registry = Registry.load(args.registry)
    gaps = audit.audit(registry)
    for gap in gaps:
        print(f"  {gap.severity:8} {gap.kind:22} {gap.subject}  {gap.detail}")
    blocking = sum(gap.severity == "blocking" for gap in gaps)
    print(f"{len(registry.species)} species, {len(registry.channels)} pairs, {blocking} blocking")
    return 1 if blocking else 0


def _plan(args) -> int:
    case = Case.load(args.case)
    registry = Registry.load(args.registry)
    network, gaps = expand(registry, case)
    gaps += audit.audit(registry, network)
    gaps += quality.quality(network, case, registry)
    yaml.safe_dump(plan.build(gaps), sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


def _ingest(args) -> int:
    registry = Registry.load(args.registry)
    report = ingest.ingest(args.snapshot, registry, args.overlay)
    print(f"  accepted    {report.accepted} -> {args.overlay}")
    print(f"  review      {len(report.review)} -> {args.overlay.with_name('review_queue.yaml')}")
    for item in report.review[:10]:
        print(f"    {item['reason']:15} {item['wrote']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
