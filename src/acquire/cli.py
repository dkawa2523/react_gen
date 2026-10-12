"""Convert acquired data into snapshots `rgen ingest` can read.

    python -m acquire lxcat export.txt --out work/ar
    python -m acquire umist rate22.rates --out work/umist
    python -m acquire pubchem result.yaml --out external_data/identity

The output of either is fed to `rgen ingest --result result`, which matches it
onto canonical candidates and queues whatever is ambiguous.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from acquire import (
    additivity,
    asd,
    atoms,
    cccbdb,
    download,
    ideal_gas,
    lxcat,
    molecular,
    nasa,
    pubchem,
    snapshot,
    thermo,
    umist,
    vibration,
)
from reactgen import yamlio


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
        binds = {True: "binds an electron", False: "does not bind an electron", None: "unknown"}
        print(
            f"  {atom.symbol:4} IE={atom.ionization_eV}  EA={atom.affinity_eV}"
            f"  {binds[atom.binds_electron]}"
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
            f"   metastable {_eV(item.metastable_eV)}   resonant {_eV(item.resonant_eV)}"
        )
    print(f"  snapshot      {path}")
    return 0 if any(item.known for item in found) else 1


def _eV(value: float | None) -> str:
    return "     none" if value is None else f"{value:8.4f} eV"


def _molecular(args) -> int:
    if not molecular.available():
        print('  chemicals is not installed: python -m pip install -e ".[thermo]"')
        return 1
    wanted = yamlio.load(args.species.read_text(encoding="utf-8")) or []
    items = _listed(wanted)
    names = [
        _query_name(item)
        for item in items
        if not isinstance(item, dict)
        or (not item.get("charge") and (item.get("state") or {}).get("kind", "ground") == "ground")
    ]
    composition = {
        _query_name(item): item["composition"]
        for item in items
        if isinstance(item, dict) and item.get("composition")
    }
    citation = "chemicals package bundled molecular property tables"
    found = molecular.fetch(names, composition)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "chemicals", "provider": "chemicals", "citation": citation},
        molecular.records(found, citation),
    )
    for item in found:
        if item.known:
            print(
                f"  {item.species:10} dipole {item.dipole_D!s:>6}  D"
                f"   radius {item.collision_radius_A!s:>7} A"
                f"   well {item.well_depth_K!s:>7} K"
            )
    missing = [item.species for item in found if not item.known]
    print(f"  {len(found) - len(missing)} of {len(found)} answered; {len(missing)} not tabulated")
    print(f"  wrote {path}")
    return 0


def _cccbdb(args) -> int:
    wanted: dict[tuple, str] = {}
    identities: dict[tuple, str] = {}
    for item in _listed(yamlio.load(args.species.read_text(encoding="utf-8")) or []):
        named = isinstance(item, dict)
        if named and (
            item.get("charge")
            or (item.get("state") or {}).get("kind", "ground") != "ground"
            or item.get("phase", "gas") != "gas"
        ):
            continue
        composition = (item.get("composition") or {}) if named else {}
        key: tuple | None = (
            tuple(sorted((str(k), int(v)) for k, v in composition.items()))
            if composition
            else cccbdb.composition(str(item))
        )
        if key is not None:
            wanted.setdefault(key, str(item["id"]) if named else str(item))
            if named and (identity := item.get("source_species") or item.get("structure")):
                identities[key] = str(identity)
    saved = args.page.read_text(encoding="utf-8") if args.page else None
    found, error = cccbdb.fetch(saved)
    if error:
        print(f"  could not read {cccbdb.LIST_URL}: {error}")
        return 1
    citation = f"NIST CCCBDB experimental polarizability list, {cccbdb.LIST_URL}"
    written = cccbdb.records(found, wanted, citation, identities)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "cccbdb", "provider": "nist_cccbdb", "citation": citation},
        written,
    )
    print(f"  {len(found)} species listed, {len(written)} of the {len(wanted)} asked for")
    missing = sorted(set(wanted.values()) - {item["species"] for item in written})
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
        return list(document.get("states") or [])
    return list(document)


def _query_name(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    return str(item.get("query") or item.get("id") or "").partition("@")[0]


def _vibration(args) -> int:
    if not vibration.available():
        print('  chemicals is not installed: python -m pip install -e ".[thermo]"')
        return 1
    wanted = _listed(yamlio.load(args.species.read_text(encoding="utf-8")) or [])
    names = [_query_name(item) for item in wanted]
    linear = {_query_name(n): n.get("linear", False) for n in wanted if isinstance(n, dict)}
    atoms_of = {_query_name(n): n.get("atoms", 2) for n in wanted if isinstance(n, dict)}
    citation = "chemicals TRC gas heat capacity, effective Einstein mode fitted 300-1500 K"
    found = vibration.fetch(names, linear, atoms_of)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "chemicals_cp_fit", "provider": "internal_vibration", "citation": citation},
        vibration.records(found, citation),
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
    requested = yamlio.load(args.species.read_text(encoding="utf-8")) or {}
    wanted = _listed(requested)
    names = [_query_name(item) for item in wanted]
    composition = {
        _query_name(item): item["composition"]
        for item in wanted
        if isinstance(item, dict) and item.get("composition")
    }
    citation = "PyroMat ideal-gas model, enthalpy at the declared temperature and reference"
    found = ideal_gas.fetch(names, composition)
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "pyromat", "provider": "pyromat", "citation": citation},
        ideal_gas.records(found, citation),
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
    requested = yamlio.load(args.species.read_text(encoding="utf-8")) or {}
    wanted = _listed(requested)
    names = [_query_name(item) for item in wanted]
    composition = {
        _query_name(item): item["composition"]
        for item in wanted
        if isinstance(item, dict) and item.get("composition")
    }

    found = thermo.fetch(names, composition)
    citation = "chemicals package, bundled thermodynamic tables"
    path = snapshot.write(
        args.out,
        "state_property",
        {"source_type": "chemicals", "provider": "chemicals", "citation": citation},
        thermo.records(found, citation),
    )
    print(f"  resolved      {sum(1 for item in found if item.known)} / {len(found)}")
    for item in found:
        if not item.known:
            print(f"    unresolved  {item.species}  {item.error or 'no enthalpy tabulated'}")
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --result result --overlay work/overlay.yaml")
    return 0


def _pubchem(args) -> int:
    requested = yamlio.load(args.species.read_text(encoding="utf-8")) or {}
    wanted = _listed(requested)
    names = [_query_name(item) for item in wanted]
    registered = {_query_name(item): item for item in wanted if isinstance(item, dict)}

    found = pubchem.fetch(names)
    args.out.mkdir(parents=True, exist_ok=True)
    records, report = [], []
    for name, identity in zip(names, found, strict=True):
        entry = registered.get(name, {})
        verdict = pubchem.compare(identity, entry.get("composition"), entry.get("mass_amu"))
        report.append({**asdict(identity), "verdict": verdict})
        if verdict == "fills_gap" and identity.mass_amu is not None:
            records.append(
                {
                    "species": name,
                    "property": "mass_amu",
                    "value": identity.mass_amu,
                    "unit": "amu",
                }
            )

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


if __name__ == "__main__":
    raise SystemExit(main())
