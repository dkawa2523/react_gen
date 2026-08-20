"""Propose the channels a species could have, and say who could confirm them.

    discover channels --gas SiH4 --registry registry --out work/silane

Writes a snapshot of candidates and the route to settle each one. Candidates
carry ``status: candidate``, which no case accepts by default, so nothing here
reaches a generated network until a person promotes it.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path

import yaml

from discover import evidence, fragments, propose, screen, sources, view
from discover.relations import Relations
from reactgen import audit, export, known, layers, lock, processes, quality
from reactgen.case import Case, Limits
from reactgen.expand import expand
from reactgen.registry import Registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="discover", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    channels = commands.add_parser("channels", help="propose electron channels for a species")
    channels.add_argument("--gas", required=True, action="append", help="repeatable")
    channels.add_argument("--registry", type=Path, default=Path("registry"))
    channels.add_argument("--catalog", type=Path, default=None)
    channels.add_argument("--out", type=Path, required=True)
    channels.add_argument(
        "--known",
        type=Path,
        action="append",
        default=[],
        help="snapshot listing reactions; repeatable",
    )
    channels.add_argument("--offline", action="store_true", help="skip every network source")
    channels.set_defaults(run=_channels)

    network = commands.add_parser("network", help="grow a candidate network from input gases")
    network.add_argument("--gas", action="append", default=[], help="repeatable")
    network.add_argument(
        "--case",
        type=Path,
        default=None,
        help="a case file instead of bare gas names, so conditions, surfaces and "
        "limits apply. The same definition `rgen generate` reads, run with "
        "candidates added",
    )
    network.add_argument("--registry", type=Path, default=Path("registry"))
    network.add_argument("--out", type=Path, required=True)
    network.add_argument("--max-depth", type=int, default=4)
    network.add_argument(
        "--max-ion-charge",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help="highest charge state to propose; each stage costs its own ionization energy",
    )
    network.add_argument(
        "--excitation",
        default="lumped",
        choices=["none", "lumped", "metastable"],
        help="lumped writes X*; metastable splits an atom into X_meta and X_res. "
        "A molecule always carries X_v as well: vibrational and electronic "
        "excitation are two processes, not two resolutions of one",
    )
    network.add_argument(
        "--with",
        dest="enable",
        action="append",
        default=[],
        choices=list(processes.NAMES),
        help="turn on a collision family that is off by default",
    )
    network.add_argument(
        "--without",
        dest="disable",
        action="append",
        default=[],
        choices=list(processes.NAMES),
        help="turn off one that is on. Families:\n" + processes.describe(),
    )
    network.add_argument(
        "--max-endothermic",
        type=float,
        default=2.0,
        dest="max_endothermic",
        help="how far uphill a heavy-particle channel may sit and still be carried, in eV. "
        "Nothing above thermal runs in the bulk; raise it for sheath energies",
    )
    network.add_argument(
        "--max-leaving",
        type=int,
        default=2,
        help="ligands that may leave at once; 3 or more reaches deeper fragmentation",
    )
    network.add_argument(
        "--overlay", type=Path, default=None, help="reviewed imports, e.g. thermochemistry"
    )
    network.add_argument(
        "--known",
        type=Path,
        action="append",
        default=[],
        help="snapshot listing reactions; labels each one with who states it. "
        "A label, never a filter: silence is not evidence against a channel",
    )
    network.add_argument(
        "--layers",
        default=None,
        help="which layers of judgement to evaluate and record, comma separated: "
        + ", ".join(layers.LAYERS)
        + ". All of them by default",
    )
    network.set_defaults(run=_network)

    pairs = commands.add_parser("pairs", help="screen ion-neutral charge transfer by energy")
    pairs.add_argument("--registry", type=Path, default=Path("registry"))
    pairs.add_argument("--out", type=Path, required=True)
    pairs.set_defaults(run=_pairs)

    listing = commands.add_parser("sources", help="show which database covers what")
    listing.add_argument("--catalog", type=Path, default=None)
    listing.add_argument("--probe", action="store_true", help="ask each endpoint")
    listing.set_defaults(run=_sources)

    args = parser.parse_args(argv)
    return args.run(args)


def _channels(args) -> int:
    registry = Registry.load(args.registry)
    catalog = sources.load(args.catalog)
    registered = view.known(registry)

    candidates = []
    for gas in args.gas:
        target = registry.resolve(gas)
        if target is None:
            print(f"  unknown      {gas}  register the species first")
            continue
        composition = dict(registry.species[target].composition)
        candidates += fragments.electron_channels(target, composition, registered)

    reachable = set() if args.offline else {s.id for s in catalog if s.reachable}
    marks = evidence.gather(candidates, view.species_view(registry), reachable)
    listed = known.load(args.known, registry)

    args.out.mkdir(parents=True, exist_ok=True)
    _write(args.out / "candidates.yaml", _document(candidates, marks, listed, catalog))
    counts = Counter(item.type for item in candidates)
    for kind, number in sorted(counts.items()):
        print(f"  {kind:26} {number}")
    for label, count in _confirmation(candidates, listed).items():
        print(f"  {label:22} {count}")
    unregistered = sorted({name for item in candidates for name in item.new_species})
    if unregistered:
        print(f"  register first        {', '.join(unregistered)}")
    print(f"  candidates    {args.out / 'candidates.yaml'}")
    _print_routes(catalog, "electron")
    return 0 if candidates else 1


def _confirmation(candidates: list, listed: known.Index) -> dict[str, int]:
    """How each candidate stands: already registered, listed elsewhere, or new."""

    tally: Counter[str] = Counter()
    for item in candidates:
        sources_listing = {found.source for found in listed.lists(item.equation)}
        if "registry" in sources_listing:
            tally["already registered"] += 1
        elif sources_listing:
            tally["listed by a source"] += 1
        else:
            tally["unconfirmed"] += 1
    return dict(tally)


def _document(
    candidates: list, marks: dict, listed: known.Index, catalog: list[sources.Source]
) -> dict:
    return {
        "schema_version": 1,
        "status": "candidate",
        "note": (
            "Channels enumerated under conservation. `listed_by` is the reaction's "
            "own existence: a source states this equation. `species_evidence` is a "
            "weaker, separate question about the species, and a compound database "
            "cannot answer for a reaction."
        ),
        "reactions_indexed": len(listed),
        "index_sources": listed.sources,
        "sources_consulted": [
            {"id": item.id, "reachable": item.reachable, "blocked_by": item.blocked_by}
            for item in sources.covering(catalog, "electron")
        ],
        "candidates": [
            {
                "type": item.type,
                "reaction": item.equation,
                "status": "candidate",
                "register_first": list(item.new_species),
                "listed_by": sorted({found.source for found in listed.lists(item.equation)}),
                "species_evidence": marks.get(item.equation, []),
            }
            for item in candidates
        ],
    }


def _network(args) -> int:
    if not args.gas and args.case is None:
        print("  give --gas, or --case to run a case definition with candidates")
        return 2
    registry = Registry.load(args.registry, overlay=args.overlay)
    selection = processes.select(args.enable, args.disable)
    case = _case_of(args, selection)
    proposer = propose.Proposer.build(
        registry,
        view.ionization(registry),
        view.affinity(registry),
        view.enthalpy(registry),
        view.excitation(registry),
        view.vibration(registry),
        max_ion_charge=args.max_ion_charge,
        excitation=args.excitation,
        max_leaving=args.max_leaving,
        max_endothermic_eV=args.max_endothermic,
        processes=selection,
    )
    net, gaps = expand(registry, case, proposer)

    gaps += audit.audit(registry, net)
    gaps += quality.quality(net, case, registry)
    listed = known.load(args.known, registry) if args.known else None
    export.write(
        args.out,
        case,
        net,
        registry,
        gaps,
        lock.mechanism_id(case, registry),
        listed,
        layers.select(args.layers),
    )

    status = Counter(r.status for r in net.reactions)
    shape = selection.report()
    print(f"  processes     on {shape['on']}")
    print(f"                off {shape['off']}  not implemented {shape['not_implemented']}")
    print(f"  species       {len(net.species)}  (proposed {len(proposer.invented)})")
    print(f"  reactions     {len(net.reactions)}  {dict(net.by_family())}")
    print(f"  by status     {dict(status)}")
    blocking = _report_gaps(gaps)
    print(f"  bundle        {args.out}  (same contract as rgen generate)")
    # A blocking finding means the list is not usable as it stands, which is
    # the same contract `rgen generate` reports under.
    return 1 if blocking or not net.reactions else 0


def _case_of(args, selection) -> Case:
    """The case to grow, from a file or from bare gas names.

    A case file carries conditions, surfaces and limits that bare names cannot,
    and it is the same file `rgen generate` reads. Running one here is how a
    user asks for the curated list *plus* what has not been curated yet, which
    is most of the ion-neutral chemistry.
    """

    accept = ("curated", "literature_supported", propose.CANDIDATE)
    if args.case is not None:
        loaded = Case.load(args.case)
        return replace(
            loaded,
            accept_status=tuple(dict.fromkeys((*loaded.accept_status, *accept))),
            accept_processes=selection.active,
        )
    return Case(
        name="candidate",
        gases=tuple(args.gas),
        limits=Limits(max_depth=args.max_depth),
        accept_status=accept,
        # The same choice on both paths: what the registry contributes and what
        # the proposer may invent are restricted alike.
        accept_processes=selection.active,
    )


def _report_gaps(gaps: list) -> int:
    """Findings by severity, with the blocking ones named.

    A hundred and sixty identical `missing_threshold` lines would bury the two
    that say the mechanism is wrong, so only counts are printed per kind and
    anything blocking is spelled out.
    """

    by_severity: Counter[str] = Counter(gap.severity for gap in gaps)
    blocking = [gap for gap in gaps if gap.severity == "blocking"]
    summary = ", ".join(f"{n} {name}" for name, n in sorted(by_severity.items())) or "none"
    print(f"  findings      {summary}")
    for kind, number in sorted(Counter(g.kind for g in gaps if g.severity == "data").items()):
        print(f"    data        {kind:30} {number}")
    for gap in blocking:
        print(f"    BLOCKING    {gap.subject}  {gap.detail}")
    return len(blocking)


def _pairs(args) -> int:
    registry = Registry.load(args.registry)
    # Relations answers this, not a second copy in `view`: ionizing a metastable
    # leaves the ground-state ion, and only one of the two knew that.
    cations = Relations(registry.species).cations()
    screened = screen.charge_transfer(view.ionization(registry), cations)

    args.out.mkdir(parents=True, exist_ok=True)
    _write(
        args.out / "charge_transfer.yaml",
        {
            "schema_version": 1,
            "status": "candidate",
            "note": (
                "Delta E = IE(product neutral) - IE(reactant neutral). Open means "
                "exothermic and therefore near the capture rate; it is not a "
                "measurement, and a closed channel may still open in a sheath."
            ),
            "channels": [
                {
                    "reaction": item.equation,
                    "delta_e_eV": round(item.delta_e_eV, 4) if item.delta_e_eV else None,
                    "verdict": item.verdict,
                    "status": "candidate",
                }
                for item in screened
            ],
        },
    )
    counts = Counter(item.verdict for item in screened)
    for verdict, number in sorted(counts.items()):
        print(f"  {verdict:12} {number}")
    print(f"  channels      {args.out / 'charge_transfer.yaml'}")
    return 0 if screened else 1


def _sources(args) -> int:
    for item in sources.load(args.catalog):
        state = "reachable" if item.reachable else (item.blocked_by or "")
        print(f"  {item.id:15} {','.join(item.covers):42} {state}")
        if args.probe:
            print(f"      endpoint      {sources.probe(item)}")
        if item.applicability:
            print(f"      {item.applicability}")
    return 0


def _print_routes(catalog: list[sources.Source], family: str) -> None:
    blocked = [item for item in sources.covering(catalog, family) if not item.reachable]
    for item in blocked:
        print(f"  to confirm    {item.id}: {item.blocked_by}")


def _write(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
