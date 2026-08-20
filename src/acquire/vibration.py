"""Effective vibrational quantum, from the heat capacity a species already has.

A vibrational manifold `X_v` needs one number before anything can be said about
it: how far above the ground state it sits. That number is a spectroscopic
measurement, and spectroscopy is the least available data in this repository —
but it is also already present in the heat capacity, because vibration is what
makes Cp rise with temperature at all.

Split the ideal-gas heat capacity into the parts that carry it::

    Cp(T) = R + C_trans + C_rot + C_vib(T)
    C_trans = (3/2) R
    C_rot   = (1/2) R * f,  f = 2 (linear) or 3 (non-linear)

Everything left over is vibrational, and for a single Einstein mode::

    C_vib(T) = R * x^2 * e^x / (e^x - 1)^2,   x = theta / T

A molecule of ``n`` atoms has ``3n - 6`` modes (``3n - 5`` if linear), and at
high temperature each contributes R, so the residual has to be divided by that
count before one mode is fitted to it. Skipping the division makes the fit
lower ``theta`` until a single mode carries the heat capacity of many, which is
how every polyatomic came back at the bottom of the search range.

Fitting one effective ``theta`` to the per-mode residual gives a quantum that
stands for the whole manifold. That is the right resolution for the list: `X_v`
is one lumped level, so a mode-by-mode spectrum would be more than it can
carry, and the fit is an average over modes rather than the lowest of them.

The fit is over 300-1500 K, where the correlation is valid and the vibrational
term is large enough to see. Below that Cp is nearly all translation and
rotation, and the residual is noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp

GAS_CONSTANT = 8.314462618  # J/(mol K)
KELVIN_PER_EV = 11604.518
FIT_RANGE = (300.0, 1500.0)
POINTS = 25
# A quantum outside this is not a molecular vibration; the fit failed instead.
PLAUSIBLE_EV = (0.02, 0.60)


@dataclass(frozen=True)
class Quantum:
    """One species' effective vibrational level, or why there is none."""

    species: str
    energy_eV: float | None = None
    theta_K: float | None = None
    fit_note: str | None = None
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.energy_eV is not None


def available() -> bool:
    try:
        import chemicals  # noqa: F401
    except ImportError:
        return False
    return True


def fetch(
    species: list[str],
    linear: dict[str, bool] | None = None,
    atoms: dict[str, int] | None = None,
) -> list[Quantum]:
    if not available():
        return [Quantum(name, error="chemicals is not installed") for name in species]
    shapes, counts = linear or {}, atoms or {}
    return [_one(name, shapes.get(name, False), counts.get(name, 2)) for name in species]


def _one(name: str, linear: bool, atoms: int) -> Quantum:
    from chemicals import heat_capacity as hc
    from chemicals.identifiers import CAS_from_any

    try:
        cas = CAS_from_any(name)
    except Exception as error:  # chemicals raises bare exceptions for an unknown name
        return Quantum(name, error=f"{type(error).__name__}: {str(error)[:50]}")

    hc._load_Cp_data()
    if cas not in hc.TRC_gas_data.index:
        return Quantum(name, error="no gas heat capacity tabulated")
    row = hc.TRC_gas_data.loc[cas]
    coefficients = [row[key] for key in ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7")]

    low, high = max(FIT_RANGE[0], float(row["Tmin"])), min(FIT_RANGE[1], float(row["Tmax"]))
    if high - low < 200:
        return Quantum(name, error="validity range too narrow to fit")

    modes = max(1, 3 * atoms - (5 if linear else 6))
    temperatures = [low + (high - low) * i / (POINTS - 1) for i in range(POINTS)]
    residual = []
    for temperature in temperatures:
        try:
            total = hc.TRCCp(temperature, *coefficients)
        except Exception as error:
            return Quantum(name, error=f"{type(error).__name__}: {str(error)[:50]}")
        classical = GAS_CONSTANT * (1 + 1.5 + (1.0 if linear else 1.5))
        residual.append((total - classical) / GAS_CONSTANT / modes)

    theta, note = _fit(temperatures, residual)
    if theta is None:
        return Quantum(name, error=note)
    energy = theta / KELVIN_PER_EV
    if not PLAUSIBLE_EV[0] <= energy <= PLAUSIBLE_EV[1]:
        return Quantum(name, error=f"fitted {energy:.3f} eV is not a molecular vibration")
    return Quantum(name, round(energy, 4), round(theta, 1), f"{modes} modes, {note}")


def _fit(temperatures: list[float], residual: list[float]) -> tuple[float | None, str | None]:
    """One Einstein temperature that best reproduces the vibrational residual.

    A scan rather than a solver: the function is smooth and one-dimensional over
    a known range, so stepping it is both enough and easy to check by hand.
    """

    if max(residual) <= 0.05:
        return None, "no vibrational contribution to fit"

    best, best_error = None, float("inf")
    for step in range(200, 7000, 10):
        theta = float(step)
        error = sum(
            (_einstein(theta, temperature) - value) ** 2
            for temperature, value in zip(temperatures, residual, strict=True)
        )
        if error < best_error:
            best, best_error = theta, error
    if best is None:
        return None, "fit did not converge"
    return best, f"rms {(best_error / len(residual)) ** 0.5:.3f} in Cp/R"


def _einstein(theta: float, temperature: float) -> float:
    """Heat capacity of one harmonic mode, in units of R."""

    x = theta / temperature
    if x > 60:  # frozen out; exp overflows before it matters
        return 0.0
    growth = exp(x)
    return x * x * growth / (growth - 1.0) ** 2


def records(found: list[Quantum], citation: str) -> list[dict]:
    """Property records for `rgen ingest`, one per quantum that could be fitted."""

    return [
        {
            "species": item.species,
            "property": "vibrational_quantum_eV",
            "value": item.energy_eV,
            "unit": "eV",
            "source": {"citation": f"{citation}; effective Einstein mode, {item.fit_note}"},
        }
        for item in found
        if item.known
    ]
