"""Convert acquired data into snapshots `rgen ingest` can read.

    python -m acquire.cli lxcat export.txt --out work/ar
    python -m acquire.cli umist rate22.rates --out work/umist
    python -m acquire.cli pubchem result.yaml --out external_data/identity

The output of either is fed to `rgen ingest --result result`, which matches it
onto canonical candidates and queues whatever is ambiguous.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path

import yaml

from acquire import (
    additivity,
    asd,
    atoms,
    cccbdb,
    collisiondb,
    download,
    ideal_gas,
    lxcat,
    molecular,
    nasa,
    pubchem,
    snapshot,
    targets,
    thermo,
    umist,
    vibration,
    webbook,
)
from reactgen import yamlio
from reactgen.chemistry import parse_state_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acquire", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    convert = commands.add_parser("lxcat", help="convert an LXCat export into a snapshot")
    convert.add_argument("export", type=Path)
    convert.add_argument("--out", type=Path, required=True)
    convert.add_argument("--citation", default="LXCat export, cite the contributing database")
    convert.set_defaults(run=_lxcat)

    grab = commands.add_parser("fetch", help="download the file a catalog source names")
    grab.add_argument("source", help="source id in external_data/source_catalog.yaml")
    grab.add_argument("--catalog", type=Path, default=Path("external_data/source_catalog.yaml"))
    grab.add_argument("--out", type=Path, required=True)
    grab.set_defaults(run=_fetch)

    sources = commands.add_parser(
        "sources", help="show local source capabilities and access routes"
    )
    sources.add_argument("--catalog", type=Path, default=Path("external_data/source_catalog.yaml"))
    sources.set_defaults(run=_sources)

    rates = commands.add_parser("umist", help="convert a UMIST RATE release into a snapshot")
    rates.add_argument("release", type=Path)
    rates.add_argument("--out", type=Path, required=True)
    rates.add_argument("--citation", default="UMIST RATE release, cite the version")
    rates.add_argument(
        "--format-version",
        choices=("RATE12", "RATE22"),
        help="declare the fit layout when automatic detection is ambiguous",
    )
    rates.set_defaults(run=_umist)

    table = commands.add_parser("atoms", help="read atomic IE and EA from `mendeleev`")
    table.add_argument("symbols", nargs="+", help="element symbols")
    table.add_argument("--out", type=Path, required=True)
    table.set_defaults(run=_atoms)

    levels = commands.add_parser("asd", help="read atomic excitation levels from NIST ASD")
    levels.add_argument("symbols", nargs="+", help="element symbols")
    levels.add_argument("--out", type=Path, required=True)
    levels.set_defaults(run=_asd)

    vibrate = commands.add_parser(
        "vibration", help="fit an effective vibrational quantum from heat capacity"
    )
    vibrate.add_argument("species", type=Path, help="YAML list of species names")
    vibrate.add_argument("--out", type=Path, required=True)
    vibrate.set_defaults(run=_vibration)

    gas = commands.add_parser("idealgas", help="read ideal-gas enthalpy h(T) from `pyromat`")
    gas.add_argument("species", type=Path, help="YAML list of species")
    gas.add_argument("--out", type=Path, required=True)
    gas.set_defaults(run=_ideal_gas)

    bulk = commands.add_parser(
        "molecular", help="read dipole moment and Lennard-Jones size from `chemicals`"
    )
    bulk.add_argument("species", type=Path, help="YAML list of species names")
    bulk.add_argument("--out", type=Path, required=True)
    bulk.set_defaults(run=_molecular)

    polar = commands.add_parser(
        "cccbdb", help="read experimental polarizability from the NIST CCCBDB list page"
    )
    polar.add_argument("species", type=Path, help="YAML list of species names")
    polar.add_argument("--out", type=Path, required=True)
    polar.add_argument("--page", type=Path, help="a saved copy of the page, instead of fetching")
    polar.set_defaults(run=_cccbdb)

    book = commands.add_parser("webbook", help="read Hf and IE/EA from one identified NIST page")
    book.add_argument("species", type=Path, help="species list with explicit CAS/WebBook query IDs")
    book.add_argument("--out", type=Path, required=True)
    book.add_argument("--page", type=Path, help="saved HTML for a single requested species")
    book.set_defaults(run=_webbook)

    collision = commands.add_parser("collisiondb", help="convert a CollisionDB downloaded table")
    collision.add_argument("export", type=Path)
    collision.add_argument("--out", type=Path, required=True)
    collision.add_argument(
        "--reaction", help="explicit canonical mapping of the stateful source reaction"
    )
    collision.add_argument(
        "--type", help="canonical process; omitted declarations are queued for review"
    )
    collision.add_argument(
        "--independent-variable", choices=("electron_energy", "collision_energy", "ion_energy")
    )
    collision.add_argument(
        "--observable",
        choices=("reaction", "elastic", "momentum_transfer", "effective_momentum_transfer"),
    )
    collision.add_argument(
        "--channel-scope",
        choices=("product_resolved", "total", "total_process", "unknown"),
        default="unknown",
    )
    collision.set_defaults(run=_collisiondb)

    guess = commands.add_parser(
        "additivity",
        help="estimate polarizability for species no compilation holds (marked estimated)",
    )
    guess.add_argument("species", type=Path, help="an analysis result's result.yaml")
    guess.add_argument("--out", type=Path, required=True)
    guess.add_argument("--page", type=Path, help="a saved CCCBDB list page, instead of fetching")
    guess.set_defaults(run=_additivity)

    fit = commands.add_parser(
        "nasa", help="read NASA thermodynamic polynomials from `cantera` bundled data"
    )
    fit.add_argument(
        "species",
        type=Path,
        help="an analysis result's result.yaml, or any list with composition and charge",
    )
    fit.add_argument("--out", type=Path, required=True)
    fit.set_defaults(run=_nasa)

    heat = commands.add_parser("thermo", help="read formation enthalpy from `chemicals`")
    heat.add_argument("species", type=Path, help="YAML list of species names")
    heat.add_argument("--out", type=Path, required=True)
    heat.set_defaults(run=_thermo)

    identity = commands.add_parser("pubchem", help="fetch species identity from PubChem")
    identity.add_argument("species", type=Path, help="YAML list of species names, or a file of ids")
    identity.add_argument("--out", type=Path, required=True)
    identity.set_defaults(run=_pubchem)

    args = parser.parse_args(argv)
    try:
        return int(args.run(args))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


def _lxcat(args) -> int:
    snapshot.input_acquisition(args.export)
    processes = lxcat.parse(args.export)
    scopes = [lxcat.channel_scope(process) for process in processes]
    records = []
    for index, process in enumerate(processes):
        asset = snapshot.write_table(
            args.out,
            f"{process.label}_{index}",
            process.table,
            "energy_eV,cross_section_m2",
        )
        records.append(
            {
                "reaction": process.equation or None,
                "type": lxcat.process_type(process.kind),
                "form": "table",
                "unit": "m2",
                "independent_variable": "electron_energy",
                "observable": lxcat.observable(process.kind, process.headers),
                "channel_scope": scopes[index],
                "asset": asset,
                "threshold_eV": process.threshold_eV,
                "status": "imported",
                "notes": process.headers.get("COMMENT"),
                "source_declaration": {
                    "kind": process.kind,
                    "target": process.target,
                    "headers": dict(process.headers),
                },
            }
        )
    path = snapshot.write(
        args.out,
        "cross_section",
        {"source_type": "lxcat_export", "provider": "lxcat", "citation": args.citation},
        records,
        input_path=args.export,
    )
    print(f"  processes   {len(processes)}")
    print(f"  snapshot    {path}")
    print(f"  next        rgen ingest {path} --result result --overlay work/overlay.yaml")
    return 0 if processes else 1


def _fetch(args) -> int:
    catalog = _source_catalog(args.catalog)
    entry = next(
        (s for s in catalog.get("sources") or [] if s.get("source_id", s.get("id")) == args.source),
        None,
    )
    if entry is None or not entry.get("file"):
        print(f"  {args.source}: the catalog names no direct file for this source")
        return 1

    got = download.fetch(entry["file"], entry.get("format"))
    if not got.ok:
        print(f"  refused       {got.error}")
        print(f"  get it from   {entry.get('endpoint', '')}")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / Path(entry["file"]).name
    path.write_bytes(got.body or b"")
    (args.out / "acquisition.yaml").write_text(
        yaml.safe_dump(
            {
                "source_id": args.source,
                **{
                    name: entry[name]
                    for name in ("provider", "collection", "release")
                    if entry.get(name) is not None
                },
                "requested_url": entry["file"],
                "final_url": got.url,
                "sha256": got.sha256,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "format": entry.get("format"),
                "format_version": entry.get("format_version"),
                "file": path.name,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"  fetched       {path}  sha256 {got.sha256}")
    print(f"  next          acquire {entry.get('format', 'FORMAT')} {path} --out work/")
    return 0


def _webbook(args) -> int:
    requested = _ground_requests(args.species)
    if args.page is not None and len(requested) != 1:
        raise ValueError("a saved WebBook page requires exactly one requested species")
    records = []
    for index, request in enumerate(requested):
        source_url = webbook.url(request.query)
        if args.page is not None:
            raw_path = args.page
            raw, _ = snapshot.input_acquisition(raw_path)
        else:
            got = download.fetch(source_url, expect="html")
            if not got.ok or got.body is None:
                print(f"  unavailable   {request.target.id}: {got.error}")
                return 1
            raw = got.body
            # Parse and match before creating converted output.
            webbook.records(webbook.parse(raw.decode("utf-8")), request, source_url)
            raw_dir = args.out / f"source-{index}"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_path = raw_dir / "webbook.html"
            raw_path.write_bytes(raw)
            (raw_dir / "acquisition.yaml").write_text(
                yaml.safe_dump(
                    {
                        "provider": "nist_webbook",
                        "collection": "SRD69",
                        "requested_url": source_url,
                        "final_url": got.url,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                        "file": raw_path.name,
                        "sha256": got.sha256,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
        converted = webbook.records(webbook.parse(raw.decode("utf-8")), request, source_url)
        # Each independent raw page keeps its own input hash and manifest, so
        # several species do not acquire the last page's provenance.
        _, acquisition = snapshot.input_acquisition(raw_path)
        for record in converted:
            record["source_declaration"]["acquisition"] = acquisition
        records.extend(converted)
        destination = args.out / "raw" / f"webbook-{index}.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        for record in converted:
            record["source_declaration"]["acquisition"]["raw_path"] = f"raw/{destination.name}"
    path = snapshot.write(
        args.out,
        "state_property",
        {
            "provider": "nist_webbook",
            "collection": "SRD69",
            "citation": "NIST Chemistry WebBook, SRD 69",
        },
        records,
    )
    print(f"  properties    {len(records)}")
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --result result --overlay work/overlay.yaml")
    return 0 if records else 1


def _collisiondb(args) -> int:
    snapshot.input_acquisition(args.export)
    converted = collisiondb.record(
        collisiondb.parse(args.export),
        args.out,
        reaction=args.reaction,
        process_type=args.type,
        independent_variable=args.independent_variable,
        observable=args.observable,
        channel_scope=args.channel_scope,
    )
    path = snapshot.write(
        args.out,
        "cross_section",
        {
            "provider": "iaea_collisiondb",
            "collection": "CollisionDB",
            "citation": "CollisionDB; cite the original dataset references",
        },
        [converted],
        input_path=args.export,
    )
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --result result --overlay work/overlay.yaml")
    return 0


def _sources(args) -> int:
    catalog = _source_catalog(args.catalog)
    print(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True).rstrip())
    return 0


def _source_catalog(path: Path) -> dict:
    catalog = yamlio.load(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or not isinstance(catalog.get("sources"), list):
        raise ValueError("source catalog must contain a sources list")
    identifiers = set()
    for entry in catalog["sources"]:
        identifier = _catalog_identifier(entry)
        if identifier in identifiers:
            raise ValueError(f"source catalog repeats source_id: {identifier}")
        identifiers.add(identifier)
    return catalog


def _catalog_identifier(entry: object) -> str:
    if not isinstance(entry, dict):
        raise ValueError("source catalog entries must be mappings")
    identifier = entry.get("source_id", entry.get("id"))
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("source catalog entries require a nonempty source_id")
    for name in ("provider", "collection", "release", "file", "format", "format_version"):
        value = entry.get(name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"source catalog {identifier}: {name} must be nonempty text")
    return identifier


def _umist(args) -> int:
    rates = umist.parse(args.release, args.format_version)
    records = umist.records(rates)
    path = snapshot.write(
        args.out,
        "rate_coefficient",
        {"source_type": "umist", "provider": "umist", "citation": args.citation},
        records,
        input_path=args.release,
    )
    print(f"  reactions     {len(rates)}")
    print(f"  two-body      {len(records)}  (others need a third body the registry must name)")
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --result result --overlay work/overlay.yaml")
    return 0 if records else 1


def _atoms(args) -> int:
    if not atoms.available():
        print('  mendeleev is not installed: python -m pip install -e ".[thermo]"')
        return 1
    citation = "mendeleev package, bundled periodic table"
    found = atoms.fetch(args.symbols)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "mendeleev", "provider": "mendeleev", "citation": citation},
        atoms.records(found, citation),
    )
    for atom in found:
        signs = {True: "nominal EA > 0", False: "nominal EA <= 0", None: "finite EA unavailable"}
        print(
            f"  {atom.symbol:4} IE={atom.ionization_eV}  EA={atom.affinity_eV}"
            f"  {signs[atom.nominal_ea_positive]}"
        )
    print(f"  snapshot      {path}")
    return 0


def _asd(args) -> int:
    citation = "NIST Atomic Spectra Database, energy levels"
    found = asd.fetch(args.symbols)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "nist_asd", "provider": "nist_asd", "citation": citation},
        asd.records(found, citation),
    )
    for item in found:
        if item.error:
            print(f"  {item.symbol:4} {item.error}")
            continue
        print(
            f"  {item.symbol:4} lowest {item.lowest_eV:8.4f} eV"
            f"   no lower E1 candidate {_eV(item.no_lower_e1_candidate_eV)}"
            f"   ground E1 candidate {_eV(item.ground_e1_candidate_eV)}"
        )
    print(
        "  E1 candidates: returned-level parity/J constraints; no transition strength or lifetime"
    )
    print(f"  snapshot      {path}")
    return 0 if any(item.known for item in found) else 1


def _eV(value: float | None) -> str:
    return "     none" if value is None else f"{value:8.4f} eV"


def _molecular(args) -> int:
    if not molecular.available():
        print('  chemicals is not installed: python -m pip install -e ".[thermo]"')
        return 1
    citation = "chemicals package bundled molecular property tables"
    requested = _ground_requests(args.species)
    found, written = _ground_values(requested, molecular.fetch, molecular.records, citation)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "chemicals", "provider": "chemicals", "citation": citation},
        written,
    )
    for item in found:
        if item.known:
            print(
                f"  {item.species:10} dipole {item.dipole_D!s:>6}  D"
                f"   radius {item.collision_radius_A!s:>7} A"
                f"   well {item.well_depth_K!s:>7} K"
            )
    missing = [item.species for item in found if not item.known]
    print(f"  {len(found) - len(missing)} of {len(found)} answered; {len(missing)} unresolved")
    for item in found:
        if item.error:
            print(f"    unresolved  {item.species}  {item.error}")
    print(f"  wrote {path}")
    return 0


def _cccbdb(args) -> int:
    requested = _ground_requests(args.species)
    saved = args.page.read_text(encoding="utf-8") if args.page else None
    found, error = cccbdb.fetch(saved)
    if error:
        print(f"  could not read {cccbdb.LIST_URL}: {error}")
        return 1
    citation = f"NIST CCCBDB experimental polarizability list, {cccbdb.LIST_URL}"
    written = []
    for request in requested:
        key = tuple(sorted(request.target.composition.items()))
        identity = (
            request.declared.get("source_species")
            or request.declared.get("query")
            or request.target.structure
        )
        records = cccbdb.records(
            found,
            {key: request.target.id},
            citation,
            {key: identity} if identity else None,
        )
        written.extend(targets.records_for(request, records))
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "cccbdb", "provider": "nist_cccbdb", "citation": citation},
        written,
    )
    print(f"  {len(found)} species listed, {len(written)} of the {len(requested)} asked for")
    missing = sorted({item.target.id for item in requested} - {item["species"] for item in written})
    if missing:
        print(f"  not listed: {' '.join(missing)}")
    print(f"  wrote {path}")
    return 0


def _additivity(args) -> int:
    saved = args.page.read_text(encoding="utf-8") if args.page else None
    listed, error = cccbdb.fetch(saved)
    if error:
        print(f"  could not read the training set: {error}")
        return 1
    training = [
        (dict(key), item.polarizability_A3)
        for item in listed
        if (key := cccbdb.composition(item.formula)) is not None
    ]
    targets = [
        item
        for item in _listed(yamlio.load(args.species.read_text(encoding="utf-8")) or [])
        if isinstance(item, dict)
        and item.get("composition")
        and not item.get("charge")
        and (item.get("state") or {}).get("kind", "ground") == "ground"
    ]
    wanted = [
        (str(item["id"]), dict(item["composition"]))
        for item in targets
        if item.get("phase") == "gas"
    ]
    found = additivity.estimate(wanted, training)
    found.extend(
        additivity.Estimate(
            str(item["id"]),
            0.0,
            len(training),
            "gas phase must be explicit; other phases are outside this model",
        )
        for item in targets
        if item.get("phase") != "gas"
    )
    citation = f"NIST CCCBDB experimental polarizability list, {cccbdb.LIST_URL}"
    written = additivity.records(found, citation)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "additivity_fit", "provider": "internal_additivity", "citation": citation},
        written,
    )
    for item in found:
        if item.known:
            print(f"  {item.species:10} {item.polarizability_A3:6.3f} A3   estimated")
        else:
            print(f"  {item.species:10} not estimated: {item.error}")
    print(f"  fitted on {len(training)} species; {len(written)} estimates written to {path}")
    print("  estimated gas polarizability; structure dependence is omitted; no rates calculated")
    return 0


def _nasa(args) -> int:
    if not nasa.available():
        print('  cantera is not installed: python -m pip install -e ".[thermo]"')
        return 1
    wanted = _listed(yamlio.load(args.species.read_text(encoding="utf-8")) or [])
    citation = "cantera bundled thermodynamic data"
    found = nasa.fetch([item for item in wanted if isinstance(item, dict)])
    written = nasa.records(found, citation)
    path = snapshot.write(
        args.out,
        "state_thermochemistry",
        {"source_type": "cantera", "provider": "cantera", "citation": citation},
        written,
    )
    for item in found:
        if item.unusable:
            print(f"  {item.species:10} skipped: {item.unusable}")
    absent = [item.species for item in found if item.error]
    print(f"  {len(written)} of {len(found)} species carry a NASA7 fit")
    if absent:
        print(f"  no bundled fit for: {' '.join(sorted(absent))}")
    print(f"  wrote {path}")
    return 0


def _listed(document) -> list:
    """The states of an analysis result, or an explicit species list."""

    if isinstance(document, dict):
        document = document.get("states")
    if not isinstance(document, list):
        raise ValueError("species input must be a list or a result with a states list")
    return document


def _ground_requests(path: Path) -> list[targets.GroundRequest]:
    document = yamlio.load(path.read_text(encoding="utf-8"))
    requested, excluded = targets.requests(_listed(document))
    for name, reason in excluded:
        print(f"    excluded    {name}  {reason}")
    return requested


def _ground_values(requested, reader, record_maker, citation) -> tuple[list, list[dict]]:
    """Acquire once per lookup, then preserve each requested physical target."""
    composition: dict[str, dict[str, int]] = {}
    for request in requested:
        held = composition.get(request.query)
        if held is not None and held != request.target.composition:
            raise ValueError("the same source query is assigned to different compositions")
        composition[request.query] = request.target.composition
    found = reader(list(composition), composition)
    by_query = {item.species: item for item in found}
    displayed, written = [], []
    for request in requested:
        item = by_query[request.query]
        records = targets.records_for(request, record_maker([item], citation))
        displayed.append(
            replace(item, species=records[0]["species"] if records else request.target.id)
        )
        written.extend(records)
    return displayed, written


def _vibration(args) -> int:
    if not vibration.available():
        print('  chemicals is not installed: python -m pip install -e ".[thermo]"')
        return 1
    requested = _ground_requests(args.species)
    citation = "chemicals TRC gas heat capacity, effective Einstein mode fitted 300-1500 K"
    found: list[vibration.Quantum] = []
    written: list[dict] = []
    for request in requested:
        linear = request.declared.get("linear")
        atom_count = sum(request.target.composition.values())
        declared_atoms = request.declared.get("atoms", atom_count)
        if type(declared_atoms) is not int or declared_atoms != atom_count:
            raise ValueError("vibration.atoms must agree with the requested composition")
        acquired = vibration.fetch(
            [request.query],
            {request.query: linear} if linear is not None else None,
            {request.query: atom_count},
            {request.query: request.target.composition},
        )
        found.extend(replace(item, species=request.target.id) for item in acquired)
        written.extend(targets.records_for(request, vibration.records(acquired, citation)))
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "chemicals_cp_fit", "provider": "internal_vibration", "citation": citation},
        written,
    )
    for item in found:
        if item.known:
            print(f"  {item.species:10} {item.energy_eV:7.4f} eV   theta {item.theta_K:6.0f} K")
        else:
            print(f"  {item.species:10} {item.error}")
    print(f"  snapshot      {path}")
    return 0 if any(item.known for item in found) else 1


def _ideal_gas(args) -> int:
    if not ideal_gas.available():
        print('  pyromat is not installed: python -m pip install -e ".[thermo]"')
        return 1
    requested = _ground_requests(args.species)
    citation = "PyroMat ideal-gas model, enthalpy at the declared temperature and reference"
    found, written = _ground_values(requested, ideal_gas.fetch, ideal_gas.records, citation)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "pyromat", "provider": "pyromat", "citation": citation},
        written,
    )
    print(f"  resolved      {sum(1 for f in found if f.known)} / {len(found)}")
    for item in found:
        if not item.known:
            print(f"    unresolved  {item.species:8} {item.error}")
    print(f"  snapshot      {path}")
    return 0


def _thermo(args) -> int:
    if not thermo.available():
        print('  chemicals is not installed: python -m pip install -e ".[thermo]"')
        return 1
    requested = _ground_requests(args.species)
    citation = "chemicals package, bundled thermodynamic tables"
    found, written = _ground_values(requested, thermo.fetch, thermo.records, citation)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "chemicals", "provider": "chemicals", "citation": citation},
        written,
    )
    print(f"  resolved      {sum(1 for item in found if item.known)} / {len(found)}")
    for item in found:
        if not item.known:
            print(f"    unresolved  {item.species}  {item.error or 'no enthalpy tabulated'}")
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --result result --overlay work/overlay.yaml")
    return 0


def _pubchem(args) -> int:
    wanted = _listed(yamlio.load(args.species.read_text(encoding="utf-8")))
    requested, report = _identity_queries(wanted)
    queries = list(dict.fromkeys(query for _, _, query in requested))
    found = dict(zip(queries, pubchem.fetch(queries), strict=True))
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    for entry, request, query in requested:
        summary, values = _identity_result(entry, request, found[query])
        report.append(summary)
        records.extend(values)

    (args.out / "identity.yaml").write_text(
        yaml.safe_dump({"identity": report}, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    path = snapshot.write(
        args.out,
        "state_property",
        {
            "source_type": "pubchem",
            "provider": "pubchem",
            "citation": "PubChem PUG REST, identity only",
        },
        records,
    )

    counts = Counter(item["verdict"] for item in report)
    for verdict, number in sorted(counts.items()):
        print(f"  {verdict:12} {number}")
    print(f"  identity     {args.out / 'identity.yaml'}")
    print(f"  snapshot     {path}")
    return 1 if counts.get("differs") else 0


def _identity_queries(items: list) -> tuple[list, list[dict]]:
    """Native aliases can be looked up without inventing their physical target."""
    queries: list[tuple[dict, targets.GroundRequest | None, str]] = []
    excluded: list[dict] = []
    for item in items:
        entry = item if isinstance(item, dict) else {"id": item}
        requested, reasons = targets.requests([entry])
        if requested:
            request = requested[0]
            queries.append((entry, request, request.query))
        elif parse_state_id(str(entry["id"])) is None:
            query = entry.get("query") or entry["id"]
            if not isinstance(query, str) or not query.strip():
                raise ValueError("PubChem query must be nonempty text")
            queries.append((entry, None, query))
        else:
            excluded.append(
                {"species": entry["id"], "verdict": "not_applicable", "error": reasons[0][1]}
            )
    return queries, excluded


def _identity_result(
    entry: dict, request: targets.GroundRequest | None, identity: pubchem.Identity
) -> tuple[dict, list[dict]]:
    summary = asdict(identity) | {
        "species": request.target.id if request is not None else entry["id"],
        "source_query": identity.species,
    }
    if request is None:
        return summary | {"verdict": "identity_only" if identity.resolved else "unresolved"}, []
    source_identity = {
        "molecularFormula": identity.formula,
        "inChI": identity.inchi,
        "inchikey": identity.inchikey,
        "smiles": identity.smiles,
        "connectivity_smiles": identity.connectivity_smiles,
        "other_names": identity.synonyms,
        "name": next(iter(identity.synonyms), None),
    }
    if identity.resolved:
        try:
            targets.source_structure(source_identity, request)
        except ValueError as error:
            # Physical identity precedes mass comparison. An existing or absent
            # auxiliary mass cannot change whether an isomer has been identified.
            wrong_compound = (
                pubchem.compare(identity, request.target.composition) == "wrong_compound"
            )
            return summary | {
                "verdict": "wrong_compound" if wrong_compound else "unresolved",
                "error": str(error),
            }, []
    verdict = pubchem.compare(identity, request.target.composition, entry.get("mass_amu"))
    summary["verdict"] = verdict
    if verdict != "fills_gap" or identity.mass_amu is None:
        return summary, []
    records = targets.records_for(
        request,
        [
            {
                "property": "mass_amu",
                "value": identity.mass_amu,
                "unit": "amu",
                "status": "imported",
                "source": {"citation": f"PubChem PUG REST compound identity, CID {identity.cid}"},
                "source_declaration": asdict(identity),
            }
        ],
        identity=source_identity,
    )
    summary["identified_target"] = records[0]["species"]
    return summary, records


if __name__ == "__main__":
    raise SystemExit(main())
