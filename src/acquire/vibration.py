"""Effective vibrational quantum, from the heat capacity a species already has.

This approximation fits heat-capacity contributions to one effective Einstein
mode. It does not identify a spectroscopic level, a state population or an
excitation threshold. Molecular geometry and atom count are model inputs;
polyatomic geometry is never silently guessed.

Split the ideal-gas heat capacity into the parts that carry it::

    Cp(T) = R + C_trans + C_rot + C_vib(T)
    C_trans = (3/2) R
    C_rot   = (1/2) R * f,  f = 2 (linear) or 3 (non-linear)

Everything left over is vibrational, and for a single Einstein mode::

    C_vib(T) = R * x^2 * e^x / (e^x - 1)^2,   x = theta / T

A molecule of ``n`` atoms has ``3n - 6`` modes (``3n - 5`` if linear), and at
high temperature each contributes R, so the residual has to be divided by that
count before one mode is fitted to it.

Fitting one effective ``theta`` to the per-mode residual gives a model average,
not the lowest mode or the energy of an identified lumped state. Contributions
outside this vibrational approximation require their own model.

The fit is over 300-1500 K, where the correlation is valid and the vibrational
term is large enough to see. Below that Cp is nearly all translation and
rotation, and the residual is noise.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import exp

from acquire.targets import chemical_identity, ground_problem
from reactgen.naming import parse_formula

GAS_CONSTANT = 8.314462618  # J/(mol K)
KELVIN_PER_EV = 11604.518
FIT_RANGE = (300.0, 1500.0)
POINTS = 25
# Bounds of this approximation, not a universal limit on molecular vibration.
MODEL_ENERGY_RANGE_EV = (0.02, 0.60)


@dataclass(frozen=True)
class Quantum:
    """One species' effective vibrational level, or why there is none."""

    species: str
    energy_eV: float | None = None
    theta_K: float | None = None
    fit_note: str | None = None
    error: str | None = None
    source_record: dict = field(default_factory=dict)
    fit_temperature_range_K: tuple[float, float] | None = None
    modes: int | None = None

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
    composition: dict[str, dict[str, int]] | None = None,
) -> list[Quantum]:
    if not available():
        return [Quantum(name, error="chemicals is not installed") for name in species]
    shapes, counts = linear or {}, atoms or {}
    return [
        _one(name, shapes.get(name), counts.get(name), (composition or {}).get(name))
        for name in species
    ]


def _one(
    name: str,
    linear: bool | None,
    atoms: int | None,
    wanted: dict[str, int] | None = None,
) -> Quantum:
    if problem := ground_problem(name):
        return Quantum(name, error=problem)
    from chemicals.identifiers import CAS_from_any, search_chemical

    try:
        cas = CAS_from_any(name)
        metadata = search_chemical(cas)
        formula = metadata.formula
    except Exception as error:  # chemicals raises bare exceptions for an unknown name
        if type(error) is not Exception and not isinstance(error, ValueError | LookupError):
            raise
        return Quantum(name, error=f"{type(error).__name__}: {str(error)[:50]}")
    source_composition = parse_formula(formula)
    requested_composition = wanted or parse_formula(name)
    if not source_composition or (
        requested_composition and requested_composition != source_composition
    ):
        return Quantum(name, error="source formula does not identify the requested composition")
    actual_atoms = sum(source_composition.values())
    geometry = _geometry(linear, atoms, actual_atoms)
    if actual_atoms < 2:
        return Quantum(name, error="an atom has no molecular vibrational modes")
    if geometry is None:
        return Quantum(
            name, error="linear geometry is required for this effective-mode calculation"
        )
    result = _calculate(name, cas, formula, geometry, actual_atoms)
    return replace(
        result,
        source_record=result.source_record | {"identity": chemical_identity(metadata, cas)},
    )


def _geometry(linear: bool | None, declared_atoms: int | None, actual_atoms: int) -> bool | None:
    """The mode count uses identified atom counts and declared molecular geometry."""
    if linear is not None and type(linear) is not bool:
        raise ValueError("vibration.linear must be a boolean")
    if declared_atoms is not None and (
        type(declared_atoms) is not int or declared_atoms != actual_atoms
    ):
        raise ValueError("vibration.atoms must agree with the identified source formula")
    if actual_atoms == 2:
        if linear is False:
            raise ValueError("a diatomic molecule is linear")
        return True
    return linear


def _calculate(name: str, cas: str, formula: str, linear: bool, atoms: int) -> Quantum:
    """Fit an effective mode only after identity and geometry are resolved."""
    from chemicals import heat_capacity as hc

    hc._load_Cp_data()
    if cas not in hc.TRC_gas_data.index:
        return Quantum(name, error="no gas heat capacity tabulated")
    row = hc.TRC_gas_data.loc[cas]
    coefficients = [row[key] for key in ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7")]

    low, high = max(FIT_RANGE[0], float(row["Tmin"])), min(FIT_RANGE[1], float(row["Tmax"]))
    if high - low < 200:
        return Quantum(name, error="validity range too narrow to fit")

    modes = 3 * atoms - (5 if linear else 6)
    temperatures = [low + (high - low) * i / (POINTS - 1) for i in range(POINTS)]
    residual = []
    for temperature in temperatures:
        try:
            total = hc.TRCCp(temperature, *coefficients)
        except (ValueError, ArithmeticError) as error:
            return Quantum(name, error=f"{type(error).__name__}: {str(error)[:50]}")
        classical = GAS_CONSTANT * (1 + 1.5 + (1.0 if linear else 1.5))
        residual.append((total - classical) / GAS_CONSTANT / modes)

    theta, note = _fit(temperatures, residual)
    if theta is None:
        return Quantum(name, error=note)
    energy = theta / KELVIN_PER_EV
    if not MODEL_ENERGY_RANGE_EV[0] <= energy <= MODEL_ENERGY_RANGE_EV[1]:
        return Quantum(
            name,
            error=f"fitted {energy:.3f} eV is outside the supported effective-mode approximation",
        )
    return Quantum(
        name,
        round(energy, 4),
        round(theta, 1),
        f"{modes} modes, {note}",
        source_record={
            "cas": cas,
            "formula": formula,
            "TRC_coefficients": [float(value) for value in coefficients],
            "source_temperature_range_K": [float(row["Tmin"]), float(row["Tmax"])],
        },
        fit_temperature_range_K=(low, high),
        modes=modes,
    )


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
            "phase": "gas",
            "quantity": "effective_vibrational_quantum",
            "method": "estimated",
            "status": "estimated",
            "quality": "estimated",
            "qualifier": (
                "effective Einstein-mode fit; no resolved vibrational level is established"
            ),
            "fit_temperature_range_K": item.fit_temperature_range_K,
            "modes": item.modes,
            "source_record": item.source_record,
            "source_identity": item.source_record.get("identity"),
            "source": {"citation": f"{citation}; effective Einstein mode, {item.fit_note}"},
        }
        for item in found
        if item.known
    ]
