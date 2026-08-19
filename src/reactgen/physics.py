"""Quantities derived from registered values.

Nothing here solves a plasma. It evaluates the numbers a dataset already
carries at the requested conditions, and supplies two closed-form results that
need no solver: the Langevin capture rate for an ion-neutral pair, and the wall
loss frequency implied by a sticking coefficient and the chamber geometry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from math import exp, pi, sqrt

from reactgen.case import BOLTZMANN, Conditions
from reactgen.model import ELECTRON, Dataset, Reaction, Species
from reactgen.thermo import gibbs_energy_eV, reverse_rate

TableReader = Callable[[str | None], list[tuple[float, float]]]

# k_L = 2.342e-9 (alpha[A^3] / mu[amu])^(1/2) cm^3/s, expressed in SI.
LANGEVIN_COEFFICIENT = 2.342e-15
KELVIN_PER_EV = 11604.518
AMU_KG = 1.66053907e-27
# sqrt(2e/m_e): electron speed in m/s for an energy given in eV.
ELECTRON_SPEED_PER_SQRT_EV = 5.9309e5


@dataclass(frozen=True)
class Rate:
    """A rate coefficient evaluated at the case conditions."""

    value: float
    unit: str
    basis: str  # dataset | langevin_estimate | wall_loss
    dataset_id: str | None = None
    bounds: tuple[float, float] | None = None
    reverse: float | None = None


def reduced_mass_amu(a: Species, b: Species) -> float | None:
    mass_a, mass_b = a.value("mass_amu"), b.value("mass_amu")
    if not mass_a or not mass_b:
        return None
    return mass_a * mass_b / (mass_a + mass_b)


def langevin_rate(polarizability_A3: float, reduced_mass: float) -> float:
    """Capture rate for an ion approaching a non-polar neutral, in m3/s."""

    return LANGEVIN_COEFFICIENT * sqrt(polarizability_A3 / reduced_mass)


def thermal_speed(mass_amu: float, temperature_K: float) -> float:
    """Mean Maxwellian speed in m/s."""

    return sqrt(8 * BOLTZMANN * temperature_K / (pi * mass_amu * AMU_KG))


def wall_loss_frequency(sticking: float, mass_amu: float, conditions: Conditions) -> float | None:
    """Loss frequency in 1/s from gamma, thermal flux and the chamber geometry.

    ``nu = gamma * v_mean / 4 * (A / V)``. Without a geometry the sticking
    coefficient alone cannot become a rate, so this returns None.
    """

    ratio = conditions.area_to_volume
    if ratio is None or not conditions.gas_temperature_K or not mass_amu:
        return None
    return sticking * thermal_speed(mass_amu, conditions.gas_temperature_K) / 4 * ratio


def maxwellian_rate(table: list[tuple[float, float]], electron_temperature_eV: float) -> float:
    """Convolve a cross-section table with a Maxwellian electron distribution.

    ``k = <sigma v>`` for ``f(E) ~ sqrt(E) exp(-E/Te)``, integrated by trapezoid
    over the table's own energy points. This is a first estimate: a real
    discharge EEDF is not Maxwellian, and a Boltzmann solver stays out of scope.
    """

    if len(table) < 2 or electron_temperature_eV <= 0:
        return 0.0
    prefactor = 2 * ELECTRON_SPEED_PER_SQRT_EV / (sqrt(pi) * electron_temperature_eV**1.5)
    integral = 0.0
    for (e_low, s_low), (e_high, s_high) in pairwise(table):
        f_low = s_low * e_low * exp(-e_low / electron_temperature_eV)
        f_high = s_high * e_high * exp(-e_high / electron_temperature_eV)
        integral += 0.5 * (f_low + f_high) * (e_high - e_low)
    return prefactor * integral


def ion_neutral_pair(reaction: Reaction, species: dict[str, Species]) -> tuple[str, str] | None:
    ions: list[str] = []
    neutrals: list[str] = []
    for term in reaction.reactants:
        found = species.get(term.species)
        if found is None or found.id == ELECTRON:
            continue
        (neutrals if found.charge == 0 else ions).append(found.id)
    return (ions[0], neutrals[0]) if len(ions) == len(neutrals) == 1 else None


def is_resonant_charge_exchange(reaction: Reaction, species: dict[str, Species]) -> bool:
    """Symmetric charge exchange, which analytic theory handles well."""

    pair = ion_neutral_pair(reaction, species)
    if pair is None or reaction.type != "charge_transfer":
        return False
    ion, neutral = species[pair[0]], species[pair[1]]
    return ion.composition == neutral.composition


def evaluate(dataset: Dataset, conditions: Conditions) -> float | None:
    """The dataset's own number at these conditions, or None for a table."""

    if dataset.form == "constant":
        return dataset.params.get("value")
    if dataset.form == "arrhenius":
        return _arrhenius(dataset, conditions.gas_temperature_K)
    return None


def _arrhenius(dataset: Dataset, temperature_K: float | None) -> float | None:
    prefactor = dataset.params.get("A")
    if prefactor is None or temperature_K is None:
        return None
    reference = dataset.params.get("T_ref", 300.0)
    exponent = dataset.params.get("n", 0.0)
    activation_eV = dataset.params.get("Ea_eV", 0.0)
    return (
        prefactor
        * (temperature_K / reference) ** exponent
        * exp(-activation_eV * KELVIN_PER_EV / temperature_K)
    )


def rate_of(
    reaction: Reaction,
    species: dict[str, Species],
    conditions: Conditions,
    table_of: TableReader | None = None,
) -> Rate | None:
    """The best coefficient available for this reaction, measured or derived."""

    if reaction.surface:
        return _wall_rate(reaction, species, conditions)
    if reaction.rate_form == "cross_section":
        return _convolved(reaction, conditions, table_of)
    measured = _dataset_rate(reaction, species, conditions)
    return measured if measured is not None else _langevin(reaction, species)


def _convolved(
    reaction: Reaction, conditions: Conditions, table_of: TableReader | None
) -> Rate | None:
    """An electron rate is only meaningful once a cross section and Te exist."""

    dataset = reaction.best("cross_section")
    if dataset is None or table_of is None or not conditions.electron_temperature_eV:
        return None
    table = table_of(dataset.asset)
    if not table:
        return None
    value = maxwellian_rate(table, conditions.electron_temperature_eV)
    return Rate(value, "m3/s", "maxwellian_estimate", dataset.id)


def _dataset_rate(
    reaction: Reaction, species: dict[str, Species], conditions: Conditions
) -> Rate | None:
    dataset = reaction.best("rate_coefficient")
    if dataset is None:
        return None
    value = evaluate(dataset, conditions)
    if value is None:
        return None
    bounds = dataset.uncertainty.bounds(value) if dataset.uncertainty else None
    backward = None
    if reaction.reverse == "from_equilibrium" and conditions.gas_temperature_K:
        backward = reverse_rate(value, reaction, species, conditions.gas_temperature_K)
    return Rate(value, dataset.unit or "m3/s", "dataset", dataset.id, bounds, backward)


def _langevin(reaction: Reaction, species: dict[str, Species]) -> Rate | None:
    """A capture upper bound, offered only when a pair has no measurement."""

    if reaction.family != "ion_neutral":
        return None
    pair = ion_neutral_pair(reaction, species)
    if pair is None:
        return None
    ion, neutral = species[pair[0]], species[pair[1]]
    polarizability = neutral.value("polarizability_A3")
    reduced = reduced_mass_amu(ion, neutral)
    if not polarizability or not reduced:
        return None
    return Rate(langevin_rate(polarizability, reduced), "m3/s", "langevin_estimate")


def _wall_rate(
    reaction: Reaction, species: dict[str, Species], conditions: Conditions
) -> Rate | None:
    dataset = reaction.best("sticking_coefficient")
    reactant = species.get(reaction.reactants[0].species) if reaction.reactants else None
    if dataset is None or reactant is None:
        return None
    sticking = evaluate(dataset, conditions)
    mass = reactant.value("mass_amu")
    if sticking is None or mass is None:
        return None
    frequency = wall_loss_frequency(sticking, mass, conditions)
    if frequency is None:
        return None
    return Rate(frequency, "1/s", "wall_loss", dataset.id)


def energy_cost_eV(reaction: Reaction) -> float | None:
    """Electron energy removed from the swarm by one event of this reaction.

    Inelastic electron collisions pay their threshold; elastic ones lose only the
    small mass-ratio fraction, which a swarm calculation handles, not this table.
    """

    if reaction.family != "electron" or reaction.type in {"elastic", "effective"}:
        return None
    if reaction.threshold_eV is not None:
        return reaction.threshold_eV
    return None if reaction.delta_e_eV is None else -reaction.delta_e_eV


def feasibility(
    reaction: Reaction, species: dict[str, Species], conditions: Conditions
) -> dict | None:
    """Gibbs energy of the forward reaction, when the thermochemistry allows it.

    This is the entropy-aware check: a strongly positive Delta G means the
    forward direction is thermodynamically disfavoured at these conditions. It
    annotates, it never removes a registered reaction.
    """

    if not conditions.gas_temperature_K:
        return None
    delta_g = gibbs_energy_eV(reaction, species, conditions.gas_temperature_K)
    if delta_g is None:
        return None
    return {"delta_g_eV": delta_g, "favourable": delta_g < 0}


def applicability(dataset: Dataset, conditions: Conditions) -> str:
    """Whether the case conditions fall inside the dataset's declared range."""

    if dataset.validity is None:
        return "undeclared"
    covers = dataset.validity.covers(conditions.value_of(dataset.validity.quantity))
    if covers is None:
        return "unknown"
    return "in_range" if covers else "out_of_range"
