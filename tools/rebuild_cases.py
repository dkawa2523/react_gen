"""Rebuild every case in `cases/`, both bundles, and draw them.

The two bundles answer different questions and are not two settings of one
run. `outputs/` is the registry alone: every reaction in it is one a source
states, which is what a locked mechanism has to be. `candidates/` adds the
proposed channels, which is where the ion collisions live -- almost none of
them are in any database, and deciding what DNT+ should compute is the job.

Neither run needs a `--known` snapshot: `discover network` always matches its
candidates against the registry, so the attestation layer already says which of
the proposed reactions a curated channel covers. A snapshot goes on top of that
when a published list is at hand.

    python tools/rebuild_cases.py            # all four
    python tools/rebuild_cases.py ar_cf4     # one
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

# One lumped X* per species. `metastable` splits an atom into X_meta and X_res,
# which is the right resolution once the levels are wanted separately, but it
# only reaches atoms the registry has no levels for -- Ar and C already carry
# real terms from NIST ASD, so in these cases it would rename F alone.
EXCITATION = "lumped"


def rebuild(case: Path) -> None:
    import visualize

    import discover.cli
    import reactgen.cli

    outputs, candidates = case / "outputs", case / "candidates"
    steps = [
        (reactgen.cli.main, ["generate", str(case / "case.yaml"), "--out", str(outputs)]),
        (
            discover.cli.main,
            [
                "network",
                "--case",
                str(case / "case.yaml"),
                "--out",
                str(candidates),
                "--excitation",
                EXCITATION,
                "--known",
                str(outputs / "reactions.yaml"),
            ],
        ),
        (visualize.main, [str(outputs), str(candidates)]),
    ]
    for step, arguments in steps:
        # `discover network` exits 1 on a blocking finding, which is a report
        # about the data rather than a failure to produce the bundle.
        step(arguments)


def main(argv: list[str]) -> int:
    wanted = set(argv)
    cases = sorted(p for p in (ROOT / "cases").iterdir() if (p / "case.yaml").exists())
    for case in cases:
        if wanted and case.name not in wanted:
            continue
        print(f"\n=== {case.name} ===")
        rebuild(case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
