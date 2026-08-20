"""Convert acquired data into snapshots `rgen ingest` can read.

    python -m acquire lxcat export.txt --out work/ar
    python -m acquire umist rate22.rates --out work/umist
    python -m acquire pubchem species.yaml --out external_data/identity

The output of either is fed to `rgen ingest`, which matches it onto registered
reactions and queues whatever is ambiguous.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import yaml

from acquire import (
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acquire", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    convert = commands.add_parser("lxcat", help="convert an LXCat export into a snapshot")
    convert.add_argument("export", type=Path)
    convert.add_argument("--out", type=Path, required=True)
    convert.add_argument("--citation", default="LXCat export, cite the contributing database")
    convert.set_defaults(run=_lxcat)

    grab = commands.add_parser("fetch", help="download the file a catalog source names")
    grab.add_argument("source", help="source id in external_data/sources.yaml")
    grab.add_argument("--catalog", type=Path, default=Path("external_data/sources.yaml"))
    grab.add_argument("--out", type=Path, required=True)
    grab.set_defaults(run=_fetch)

    rates = commands.add_parser("umist", help="convert a UMIST RATE release into a snapshot")
    rates.add_argument("release", type=Path)
    rates.add_argument("--out", type=Path, required=True)
    rates.add_argument("--citation", default="UMIST RATE release, cite the version")
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

    gas = commands.add_parser("idealgas", help="read formation enthalpy from `pyromat`")
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

    fit = commands.add_parser(
        "nasa", help="read NASA thermodynamic polynomials from `cantera` bundled data"
    )
    fit.add_argument(
        "species",
        type=Path,
        help="a bundle's species.yaml, or any list with composition and charge",
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
    return args.run(args)


def _lxcat(args) -> int:
    processes = lxcat.parse(args.export)
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
                "form": "table",
                "unit": "m2",
                "asset": asset,
                "threshold_eV": process.threshold_eV,
                "status": "imported",
                "notes": process.headers.get("COMMENT"),
            }
        )
    path = snapshot.write(
        args.out,
        "cross_section",
        {"source_type": "lxcat_export", "citation": args.citation},
        records,
    )
    print(f"  processes   {len(processes)}")
    print(f"  snapshot    {path}")
    print(f"  next        rgen ingest {path} --overlay work/overlay.yaml")
    return 0 if processes else 1


def _fetch(args) -> int:
    catalog = yaml.safe_load(args.catalog.read_text(encoding="utf-8")) or {}
    entry = next((s for s in catalog.get("sources") or [] if s["id"] == args.source), None)
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
    print(f"  fetched       {path}  sha256 {got.sha256}")
    print(f"  next          acquire {entry.get('format', 'FORMAT')} {path} --out work/")
    return 0


def _umist(args) -> int:
    rates = umist.parse(args.release)
    records = umist.records(rates)
    path = snapshot.write(
        args.out,
        "rate_coefficient",
        {"source_type": "umist", "citation": args.citation},
        records,
    )
    print(f"  reactions     {len(rates)}")
    print(f"  two-body      {len(records)}  (others need a third body the registry must name)")
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --overlay work/overlay.yaml")
    return 0 if records else 1


def _atoms(args) -> int:
    if not atoms.available():
        print('  mendeleev is not installed: python -m pip install -e ".[thermo]"')
        return 1
    citation = "mendeleev package, bundled periodic table"
    found = atoms.fetch(args.symbols)
    path = snapshot.write(
        args.out,
        "species_property",
        {"source_type": "mendeleev", "citation": citation},
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
        "species_property",
        {"source_type": "nist_asd", "citation": citation},
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
    wanted = yaml.safe_load(args.species.read_text(encoding="utf-8")) or []
    names = [item["id"] if isinstance(item, dict) else str(item) for item in _listed(wanted)]
    citation = "chemicals package bundled molecular property tables"
    found = molecular.fetch(names)
    path = snapshot.write(
        args.out,
        "species_property",
        {"source_type": "chemicals", "citation": citation},
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
    for item in _listed(yaml.safe_load(args.species.read_text(encoding="utf-8")) or []):
        named = isinstance(item, dict)
        composition = (item.get("composition") or {}) if named else {}
        key: tuple | None = (
            tuple(sorted((str(k), int(v)) for k, v in composition.items()))
            if composition
            else cccbdb.composition(str(item))
        )
        if key is not None:
            wanted.setdefault(key, str(item["id"]) if named else str(item))
    saved = args.page.read_text(encoding="utf-8") if args.page else None
    found, error = cccbdb.fetch(saved)
    if error:
        print(f"  could not read {cccbdb.LIST_URL}: {error}")
        return 1
    citation = f"NIST CCCBDB experimental polarizability list, {cccbdb.LIST_URL}"
    written = cccbdb.records(found, wanted, citation)
    path = snapshot.write(
        args.out, "species_property", {"source_type": "cccbdb", "citation": citation}, written
    )
    print(f"  {len(found)} species listed, {len(written)} of the {len(wanted)} asked for")
    missing = sorted(set(wanted.values()) - {item["species"] for item in written})
    if missing:
        print(f"  not listed: {' '.join(missing)}")
    print(f"  wrote {path}")
    return 0


def _nasa(args) -> int:
    if not nasa.available():
        print('  cantera is not installed: python -m pip install -e ".[thermo]"')
        return 1
    wanted = _listed(yaml.safe_load(args.species.read_text(encoding="utf-8")) or [])
    citation = "cantera bundled thermodynamic data"
    found = nasa.fetch([item for item in wanted if isinstance(item, dict)])
    written = nasa.records(found, citation)
    path = snapshot.write(
        args.out, "species_thermo", {"source_type": "cantera", "citation": citation}, written
    )
    for item in found:
        if item.unusable:
            print(f"  {item.species:10} skipped: {item.unusable}")
    deferred = [item.species for item in found if item.deferred]
    absent = [item.species for item in found if item.error and not item.deferred]
    print(f"  {len(written)} of {len(found)} species carry a NASA7 fit")
    if deferred:
        print(f"  left to `rgen derive`: {' '.join(sorted(deferred))}")
    if absent:
        print(f"  no bundled fit for: {' '.join(sorted(absent))}")
    print(f"  wrote {path}")
    return 0


def _listed(document) -> list:
    """The species entries of a bundle's species.yaml, or a plain list as given."""

    if isinstance(document, dict):
        return list(document.get("species") or [])
    return list(document)


def _vibration(args) -> int:
    if not vibration.available():
        print('  chemicals is not installed: python -m pip install -e ".[thermo]"')
        return 1
    wanted = yaml.safe_load(args.species.read_text(encoding="utf-8")) or []
    names = [item["id"] if isinstance(item, dict) else str(item) for item in wanted]
    linear = {n["id"]: n.get("linear", False) for n in wanted if isinstance(n, dict)}
    atoms_of = {n["id"]: n.get("atoms", 2) for n in wanted if isinstance(n, dict)}
    citation = "chemicals TRC gas heat capacity, effective Einstein mode fitted 300-1500 K"
    found = vibration.fetch(names, linear, atoms_of)
    path = snapshot.write(
        args.out,
        "species_property",
        {"source_type": "chemicals_cp_fit", "citation": citation},
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
    requested = yaml.safe_load(args.species.read_text(encoding="utf-8")) or {}
    wanted = requested if isinstance(requested, list) else requested.get("species") or []
    names = [item if isinstance(item, str) else item["query"] for item in wanted]
    composition = {
        item["query"]: item["composition"]
        for item in wanted
        if isinstance(item, dict) and item.get("composition")
    }
    citation = "pyromat, NASA Glenn ideal-gas tables"
    found = ideal_gas.fetch(names, composition)
    path = snapshot.write(
        args.out,
        "species_property",
        {"source_type": "pyromat", "citation": citation},
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
    requested = yaml.safe_load(args.species.read_text(encoding="utf-8")) or {}
    wanted = requested if isinstance(requested, list) else requested.get("species") or []
    names = [item if isinstance(item, str) else item["query"] for item in wanted]
    composition = {
        item["query"]: item["composition"]
        for item in wanted
        if isinstance(item, dict) and item.get("composition")
    }

    found = thermo.fetch(names, composition)
    citation = "chemicals package, bundled thermodynamic tables"
    path = snapshot.write(
        args.out,
        "species_property",
        {"source_type": "chemicals", "citation": citation},
        thermo.records(found, citation),
    )
    print(f"  resolved      {sum(1 for item in found if item.known)} / {len(found)}")
    for item in found:
        if not item.known:
            print(f"    unresolved  {item.species}  {item.error or 'no enthalpy tabulated'}")
    print(f"  snapshot      {path}")
    print(f"  next          rgen ingest {path} --overlay work/overlay.yaml")
    return 0


def _pubchem(args) -> int:
    requested = yaml.safe_load(args.species.read_text(encoding="utf-8")) or {}
    wanted = requested if isinstance(requested, list) else requested.get("species") or []
    names = [item if isinstance(item, str) else item["query"] for item in wanted]
    registered = {
        item["query"]: item for item in wanted if isinstance(item, dict) and item.get("query")
    }

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
        "species_property",
        {"source_type": "pubchem", "citation": "PubChem PUG REST, identity only"},
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
