"""NASA thermodynamic polynomials, from the data `cantera` already ships.

The registry has carried a `thermo` field since it was written and every one of
its 102 species has it empty, because the compilations that publish these
coefficients -- Burcat's tables, NASA CEA, ATcT -- are all behind a form or a
WAF. `cantera` bundles them: twenty-two mechanism files holding 862 distinct
compositions between them, `nasa_gas.yaml` alone carrying 748.

Matching is on composition and charge, never on name. A mechanism writes `AR`,
the registry writes `Ar`, and CHEMKIN convention spells the cation `AR+` while
this repository spells it `Ar+`; the atom counts are the same in every notation,
and the electron appears as an element `E` whose count is the negated charge.
That match reaches 91 of the 102 species.

It answers for ground states only. `O_1D` and `O` have the same composition and
charge, so a composition match hands the excited state the ground state's
polynomial verbatim -- and O(1D) sits 1.967 eV above O, which the enthalpy
constant has to carry. Excited states are filled by `rgen derive`, which shifts
a6 by the level energy instead.

What the coefficients are for: Cp(T)/R, H(T)/RT and S(T)/R as polynomials in T,
which is what a reverse rate constant needs. `reactgen.thermo.reverse_rate`
has been waiting for them -- an equilibrium constant cannot be formed from a
formation enthalpy alone, because the entropy term is temperature dependent.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from typing import Any

# The element cantera uses for the electron in an ionised mechanism.
ELECTRON_ELEMENT = "E"


@dataclass(frozen=True)
class Polynomial:
    """One species' thermodynamic fit, or why there is none."""

    species: str
    model: str | None = None
    temperature_ranges: list[float] = field(default_factory=list)
    coefficients: list[list[float]] = field(default_factory=list)
    listed_as: str | None = None
    origin: str | None = None
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.nasa7 != (None, None)

    @property
    def nasa7(self) -> tuple[tuple[float, ...] | None, tuple[float, ...] | None]:
        """The low and high seven-term rows, or a pair of None for anything else."""

        rows = [tuple(row) for row in self.coefficients if len(row) == 7]
        if self.model != "NASA7" or not rows or len(self.temperature_ranges) < 2:
            return None, None
        return (rows[0], rows[-1])

    @property
    def unusable(self) -> str | None:
        """Why a matched species still yields nothing, for the run to report."""

        if self.error or self.known:
            return None
        return f"{self.model or 'no'} fit, which the registry's NASA7 field cannot hold"

    @property
    def deferred(self) -> bool:
        """Left to `rgen derive` rather than absent from the compilation."""

        return bool(self.error and self.error.endswith("from the ground state"))


def available() -> bool:
    try:
        import cantera  # noqa: F401
    except ImportError:
        return False
    return True


def catalog() -> dict[tuple[tuple[tuple[str, int], ...], int], dict[str, Any]]:
    """Every bundled species that carries a fit, keyed by composition and charge.

    First file wins on a repeat. `nasa_gas.yaml` sorts before the combustion
    mechanisms, and it is the broader and more consistent compilation, so the
    ordering is worth keeping rather than leaving to chance.
    """

    import cantera as ct

    root = os.path.join(os.path.dirname(ct.__file__), "data")
    found: dict[tuple[tuple[tuple[str, int], ...], int], dict[str, Any]] = {}
    for path in sorted(glob.glob(os.path.join(root, "*.yaml"))):
        document = _document(path)
        for entry in (document or {}).get("species") or []:
            if not entry.get("thermo"):
                continue
            key = _key(entry.get("composition") or {})
            if key is not None:
                found.setdefault(key, {**entry, "origin": os.path.basename(path)})
    return found


def _document(path: str) -> dict | None:
    """One bundled file, or None where this cantera build cannot parse it."""

    import yaml

    try:
        with open(path, encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError):
        return None


def _key(composition: dict) -> tuple[tuple[tuple[str, int], ...], int] | None:
    try:
        counts = {str(k): int(v) for k, v in composition.items()}
    except (TypeError, ValueError):  # a fractional composition is not a species here
        return None
    charge = -counts.pop(ELECTRON_ELEMENT, 0)
    return tuple(sorted(counts.items())), charge


def fetch(species: list[dict]) -> list[Polynomial]:
    """One polynomial per requested species; each dict needs id, composition, charge."""

    if not available():
        return [Polynomial(str(s.get("id")), error="cantera is not installed") for s in species]
    listed = catalog()
    return [_one(item, listed) for item in species]


def _one(item: dict, listed: dict) -> Polynomial:
    name = str(item.get("id"))
    kind = str((item.get("state") or {}).get("kind", "ground"))
    if kind not in ("ground", "ion"):
        return Polynomial(
            name, error=f"{kind} state; `rgen derive` shifts it from the ground state"
        )
    composition = {str(k): int(v) for k, v in (item.get("composition") or {}).items()}
    key = (tuple(sorted(composition.items())), int(item.get("charge", 0)))
    entry = listed.get(key)
    if entry is None:
        return Polynomial(name, error="no bundled fit for this composition and charge")
    thermo = entry["thermo"]
    return Polynomial(
        species=name,
        model=str(thermo.get("model")),
        temperature_ranges=[float(t) for t in thermo.get("temperature-ranges") or []],
        coefficients=[[float(c) for c in row] for row in thermo.get("data") or []],
        listed_as=str(entry.get("name")),
        origin=str(entry.get("origin")),
    )


def records(found: list[Polynomial], citation: str) -> list[dict]:
    """Thermo records for `rgen ingest`, one per species with a usable fit.

    The registry holds a NASA 7-coefficient polynomial with a low and a high
    range, so that is what is emitted. A bundled fit with one range fills both
    from it, which is what a single-range fit means. NASA9 is left alone rather
    than truncated to seven terms -- the two forms are different functions, and
    silently dropping the T^-2 and T^-1 terms would move Cp near 300 K.
    """

    out = []
    for item in found:
        low, high = item.nasa7
        if low is None or high is None:
            continue
        boundaries = item.temperature_ranges
        out.append(
            {
                "species": item.species,
                "thermo": {
                    "low": list(low),
                    "high": list(high),
                    "t_min": boundaries[0],
                    "t_mid": boundaries[1] if len(boundaries) > 2 else boundaries[-1],
                    "t_max": boundaries[-1],
                    "source": f"{citation}, listed as {item.listed_as} in {item.origin}",
                },
            }
        )
    return out
