"""Generate candidate chemistry and manage its local evidence."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from hashlib import sha256
from pathlib import Path

import yaml

from reactgen import adopt, derive, export, ingest, needs, yamlio
from reactgen.balance import imbalance
from reactgen.case import Case, RequestedReaction
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.presentation import analysis_overview, registered_records
from reactgen.reaction_tables import (
    VERDICTS,
    judgment_tables,
    reaction_table,
    selected_reactions,
    state_judgment_stem,
    state_judgment_tables,
)
from reactgen.registry import Registry
from reactgen.selection import SELECTABLE_QUANTITIES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rgen", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser(
        "analyze", help="investigate candidate states, channels and numerical data"
    )
    build.add_argument("gases", nargs="*", help="neutral ground-state formulas")
    build.add_argument(
        "--supply", action="append", default=[], help="explicit gas-state supply, e.g. e or Ar+"
    )
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
    backlog.add_argument(
        "--data-missing", action="store_true", help="show unresolved results that need source data"
    )
    backlog.set_defaults(run=_needs)

    inspect = commands.add_parser("records", help="inspect saved source records and numerical use")
    inspect.add_argument("result", type=Path)
    inspect.add_argument(
        "--target", required=True, help="saved state, reaction or calculation reference state ID"
    )
    inspect.add_argument("--quantity", choices=sorted(SELECTABLE_QUANTITIES))
    inspect.add_argument(
        "--detail", action="store_true", help="include complete declarations and evaluation detail"
    )
    inspect.set_defaults(run=_records)

    view = commands.add_parser("view", help="derive optional views from the saved canonical result")
    view.add_argument("result", type=Path)
    view.add_argument(
        "--kind",
        choices=("csv", "energy", "judgment", "reaction", "pathway", "network", "matrix", "dnt"),
        required=True,
    )
    view.add_argument("--out", type=Path, help="override the result directory's standard location")
    view.add_argument(
        "--judgment",
        help="saved judgment for a CSV or verdict graph, e.g. energy or conservation",
    )
    view.add_argument("--verdict", choices=VERDICTS, help="filter CSV rows of --judgment")
    view.add_argument("--family", help="exact collision family for CSV, energy or judgment graph")
    view.add_argument("--process", help="exact process key for CSV, energy or judgment graph")
    view.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="JUDGMENT=VERDICT",
        help="retain reactions matching every supplied saved verdict",
    )
    view.add_argument("--reaction", help="saved reaction ID for a single reaction diagram")
    view.add_argument("--seed", action="append", default=[])
    view.add_argument("--target", default=None)
    view.add_argument("--via", help="trace the selected saved producer reaction for --target")
    view.add_argument(
        "--checked", action="store_true", help="show paths supported by saved necessary checks"
    )
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
        help="derive nominal masses and resolved-level formation enthalpies in an overlay",
    )
    infer.add_argument("--registry", type=Path, required=True)
    infer.add_argument("--overlay", type=Path, default=None)
    infer.add_argument("--out", type=Path, required=True)
    infer.set_defaults(run=_derive)

    settle = commands.add_parser(
        "adopt",
        help="save matched overlay records in Registry, preserving their qualifications",
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
    if args.input and args.supply:
        raise ValueError("put supplies in the input file when using --input")
    case = (
        Case.load(args.input)
        if args.input
        else Case("analysis", tuple(args.gases), supplies=tuple(args.supply))
    )
    catalog = EvidenceCatalog.load_paths(tuple(args.evidence))
    result = analyze(case, catalog)
    try:
        document = export.write(args.out, result)
    except export.PartialOutputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"error: cannot save result: {error}", file=sys.stderr)
        return 1
    print("\n".join(analysis_overview(document)))
    if requested := document["input"].get("reactions"):
        print(f"Requested reactions: {len(requested)} (included in the saved assessments)")
        for row in requested[:3]:
            item = RequestedReaction(**row)
            print(f"  {item.candidate.id}  {item.equation} [{item.process}]")
    _print_result_locations(args.out, document)
    return 0 if result.candidates.complete else 1


def _print_result_locations(directory: Path, document: dict) -> None:
    print("Results:")
    for name in export.PUBLIC_FILES:
        print(f"  {directory / name}")
    if any(name.startswith("judgments/") for name in document["helper_views"]):
        print(f"  {directory / 'judgments'}")
    print("Optional graphs and source inspection:")
    print(f'  rgen view "{directory}" --kind pathway --target STATE_ID')
    if "energy" in document["summary"]["judgments"]["reactions"]:
        print(f'  rgen view "{directory}" --kind judgment --judgment energy')
    if any("collision_energy_margin_eV" in row["thermochemistry"] for row in document["reactions"]):
        print(f'  rgen view "{directory}" --kind energy')
    print(f'  rgen needs "{directory}" --detail')


def _needs(args: argparse.Namespace) -> int:
    yaml.safe_dump(
        needs.build(
            export.read(args.result), detail=args.detail, data_missing_only=args.data_missing
        ),
        sys.stdout,
        sort_keys=False,
        allow_unicode=True,
    )
    return 0


def _records(args: argparse.Namespace) -> int:
    yaml.safe_dump(
        registered_records(
            export.read(args.result), args.target, args.quantity, detail=args.detail
        ),
        sys.stdout,
        sort_keys=False,
        allow_unicode=True,
    )
    return 0


def _view(args: argparse.Namespace) -> int:
    _validate_view_options(args)
    root = args.result if args.result.is_dir() else args.result.parent
    required = _required_verdicts(args.require)
    if args.kind == "csv":
        return _csv_view(args, root, required)
    document = export.read(args.result)
    if args.kind == "dnt":
        from reactgen.dnt import dnt_inputs, dnt_tables

        destination = args.out or root / "dnt"
        name = "dnt_inputs.yaml"
        inputs = dnt_inputs(document)
        tables = dnt_tables(document, inputs)
        export.write_tables(
            destination,
            {name: yaml.safe_dump(inputs, sort_keys=False, allow_unicode=True), **tables},
        )
        print(f"{destination / name} ({len(inputs['pairs'])} ion-neutral pairs)")
        for table_name in tables:
            print(destination / table_name)
        return 0

    from reactgen.views import plot, view

    destination = args.out or root / "graphs"
    if args.kind in {"energy", "judgment", "reaction"}:
        rows = selected_reactions(
            document, family=args.family, process=args.process, verdicts=required
        )
        paths = plot(
            document,
            destination,
            args.kind,
            rows,
            judgment=args.judgment,
            reaction_id=args.reaction,
            selection=", ".join(
                ([f"family={args.family}"] if args.family else [])
                + ([f"process={args.process}"] if args.process else [])
                + [f"{name}={verdict}" for name, verdict in sorted(required.items())]
            ),
        )
        for path in paths:
            print(path)
        if not paths:
            print("No saved numerical collision margins in the selected reactions.")
            if "energy" in document["summary"]["judgments"]["reactions"]:
                print(f'  rgen view "{args.result}" --kind csv --judgment energy')
        return 0
    filename = _pathway_filename(args) if args.kind == "pathway" and not args.out else None
    path = view(
        document,
        destination,
        args.kind,
        seeds=tuple(args.seed),
        target=args.target,
        checked=args.checked,
        via=args.via,
        filename=filename,
    )
    if args.kind == "matrix" and path.suffix == ".html":
        print(f"Split matrix: open {path} to view every reaction panel")
    else:
        print(path)
    return 0


def _validate_view_options(args: argparse.Namespace) -> None:
    if (args.seed or args.target or args.checked or args.via) and args.kind not in {
        "pathway",
        "network",
    }:
        raise ValueError("--seed, --target, --checked and --via apply to pathway/network views")
    if args.judgment and args.kind not in {"csv", "judgment"}:
        raise ValueError("--judgment applies to csv/judgment views")
    if args.judgment and not re.fullmatch(r"[a-z][a-z0-9_-]*", args.judgment):
        raise ValueError("--judgment must be a saved judgment key")
    if args.verdict and (args.kind != "csv" or not args.judgment):
        raise ValueError("--verdict requires --kind csv and --judgment")
    if (args.family or args.process or args.require) and args.kind not in {
        "csv",
        "energy",
        "judgment",
    }:
        raise ValueError("--family, --process and --require apply to csv/energy/judgment views")
    if (args.kind == "reaction") != bool(args.reaction):
        raise ValueError("--kind reaction requires --reaction, which applies only to that view")
    if args.kind == "judgment" and not args.judgment:
        raise ValueError("--kind judgment requires --judgment")


def _required_verdicts(expressions: list[str]) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    for expression in expressions:
        name, _, verdict = expression.partition("=")
        if not name or verdict not in VERDICTS:
            raise ValueError(f"invalid --require {expression!r}; expected JUDGMENT=VERDICT")
        if name in verdicts and verdicts[name] != verdict:
            raise ValueError(f"conflicting --require verdicts for {name}")
        verdicts[name] = verdict
    return verdicts


def _csv_view(args: argparse.Namespace, root: Path, required: dict[str, str]) -> int:
    reaction_filter = bool(args.family or args.process or required)
    if not args.judgment and not reaction_filter:
        export.rebuild_views(args.result, args.out or root)
        print(args.out or root)
        return 0
    document = export.read(args.result)
    if args.judgment:
        tables = _selected_judgment_tables(document, args, required, reaction_filter)
    else:
        tables = {
            "reactions": reaction_table(
                document, family=args.family, process=args.process, verdicts=required
            )
        }
    filtered = bool(reaction_filter or args.verdict)
    destination = args.out or root / ("selection" if filtered else "judgments")
    files = {
        f"{name}{'.filtered' if filtered else ''}.csv": content for name, content in tables.items()
    }
    export.write_tables(destination, files)
    for name in files:
        print(destination / name)
    return 0


def _selected_judgment_tables(
    document: dict, args: argparse.Namespace, required: dict[str, str], reaction_filter: bool
) -> dict[str, str]:
    verdicts = dict(required)
    if args.verdict:
        if verdicts.get(args.judgment, args.verdict) != args.verdict:
            raise ValueError(f"--verdict conflicts with --require for {args.judgment}")
        # State-only judgments are filtered below without treating them as reaction claims.
        if args.judgment in document["summary"]["judgments"]["reactions"]:
            verdicts[args.judgment] = args.verdict
    tables = judgment_tables(
        document,
        judgment=args.judgment,
        family=args.family,
        process=args.process,
        verdicts=verdicts,
    )
    if not reaction_filter:
        tables.update(
            {
                state_judgment_stem(key): content
                for key, content in state_judgment_tables(
                    document, judgment=args.judgment, verdict=args.verdict
                ).items()
            }
        )
    if not tables:
        subjects = ("reactions",) if reaction_filter else ("reactions", "states")
        summary = document["summary"]["judgments"]
        available = sorted({key for subject in subjects for key in summary[subject]})
        raise ValueError(
            f"judgment {args.judgment!r} is not saved; available judgments: "
            f"{', '.join(available) or 'none'}"
        )
    return tables


def _pathway_filename(args: argparse.Namespace) -> str:
    if not (args.target or args.seed or args.checked or args.via):
        return "pathway.png"
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", args.target or "default").strip("-")[:48]
    query = repr((args.target, tuple(sorted(set(args.seed))), args.checked, args.via))
    return f"pathway-{name or 'state'}-{sha256(query.encode()).hexdigest()[:10]}.png"


def _ingest(args: argparse.Namespace) -> int:
    report = ingest.ingest(args.snapshot, args.result, args.overlay)
    print(f"  matched     {report.accepted} -> {args.overlay} (matching does not approve evidence)")
    print(
        f"  review      {len(report.review)} in this import; {report.pending_total} pending total"
        f" -> {args.overlay.with_name('review_queue.yaml')}"
    )
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
    acquired = (
        derive.relocated_assets(_document(args.overlay), args.overlay.parent, args.out.parent)
        if args.overlay
        else {}
    )
    merged = derive.merged(acquired, filled)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(merged, sort_keys=True, allow_unicode=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=args.out.parent,
            prefix=f".{args.out.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        EvidenceCatalog.load(None, overlay=temporary)
        os.replace(temporary, args.out)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
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
