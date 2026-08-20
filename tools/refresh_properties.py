"""Refill every species property the installed packages can answer for.

The four acquirers answer different questions and none of them overlaps:

    atoms      mendeleev  ionization energy, electron affinity, and the only
                          polarizability that can be looked up anywhere here
    molecular  chemicals  dipole moment and Lennard-Jones size for molecules
    nasa       cantera    thermodynamic polynomials, ground states only
    derive     -          what an excited state inherits from its ground state

then `rgen adopt` writes the result into the registry, keeping every curated
value that is already there. Re-running is safe and changes nothing on a
registry that is already full.

    python tools/refresh_properties.py            # write
    python tools/refresh_properties.py --dry-run  # report only
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str]) -> int:
    from acquire.cli import main as acquire
    from reactgen.cli import main as rgen
    from reactgen.registry import Registry

    registry = Registry.load(ROOT / "registry")
    work = Path(tempfile.mkdtemp(prefix="properties-"))
    overlay = work / "overlay.yaml"

    elements = sorted({element for s in registry.species.values() for element in s.composition})
    listing = work / "species.yaml"
    listing.write_text(
        yaml.safe_dump(
            {
                "species": [
                    {
                        "id": s.id,
                        "composition": s.composition,
                        "charge": s.charge,
                        "state": {"kind": s.state.kind},
                    }
                    for s in registry.species.values()
                ]
            }
        ),
        encoding="utf-8",
    )
    # chemicals resolves a name, so only substances it can name are asked for.
    neutrals = work / "neutrals.yaml"
    neutrals.write_text(
        yaml.safe_dump(
            [s.id for s in registry.species.values() if s.charge == 0 and s.state.kind == "ground"]
        ),
        encoding="utf-8",
    )

    steps = [
        ("atoms", ["atoms", *elements, "--out", str(work / "atoms")]),
        ("molecular", ["molecular", str(neutrals), "--out", str(work / "molecular")]),
        ("nasa", ["nasa", str(listing), "--out", str(work / "nasa")]),
    ]
    for name, arguments in steps:
        print(f"\n=== acquire {name} ===")
        acquire(arguments)
        rgen(["ingest", str(work / name / "snapshot.yaml"), "--overlay", str(overlay)])

    print("\n=== rgen derive ===")
    rgen(["derive", "--overlay", str(overlay), "--out", str(overlay)])

    print("\n=== rgen adopt ===")
    return rgen(["adopt", str(overlay), *(["--dry-run"] if "--dry-run" in argv else [])])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
