"""Thermochemistry: NASA polynomials, and what they let us decide.

Two things follow from having a polynomial on both sides of a reaction: the
reverse coefficient, by detailed balance, and the Gibbs energy, which says
whether the forward direction is favoured at all. Both are derived, not
acquired, so neither is an entry in the acquisition backlog.
"""

from __future__ import annotations

from math import exp, log

from reactgen.model import ELECTRON, Reaction, Species, Thermo

GAS_CONSTANT = 8.314462618  # J/(mol K)
STANDARD_PRESSURE = 101325.0  # Pa
AVOGADRO = 6.02214076e23
JOULE_PER_EV = 1.602176634e-19


def formation_delta(reaction: Reaction, species: dict[str, Species]) -> float | None:
    """Reaction enthalpy from formation enthalpies, or None where one is missing.

    ``E(products) - E(reactants)``, so a positive value is endothermic. The
    electron carries none by the usual convention, which makes an electron
    impact channel the same arithmetic as any other: ``e + CF4 -> e + CF3 + F``
    costs the bond, and ``e + A -> 2e + A+`` costs the ionization energy.

    Not a screen. An electron brings whatever energy it has, so a positive value
    here says where the channel opens rather than that it is shut — but it has
    to be recorded for `audit` to check an acquired threshold against it, and
    for a reviewer to see how far uphill a channel sits.
    """

    total = 0.0
    for terms, sign in ((reaction.products, 1.0), (reaction.reactants, -1.0)):
        for term in terms:
            if term.species == ELECTRON:
                continue
            found = species.get(term.species)
            value = None if found is None else found.value("enthalpy_formation_eV")
            if value is None:
                return None
            total += sign * term.n * value
    return total


def enthalpy_RT(thermo: Thermo, temperature_K: float) -> float:
    a = thermo.coefficients(temperature_K)
    t = temperature_K
    return a[0] + a[1] * t / 2 + a[2] * t**2 / 3 + a[3] * t**3 / 4 + a[4] * t**4 / 5 + a[5] / t


def entropy_R(thermo: Thermo, temperature_K: float) -> float:
    a = thermo.coefficients(temperature_K)
    t = temperature_K
    return a[0] * log(t) + a[1] * t + a[2] * t**2 / 2 + a[3] * t**3 / 3 + a[4] * t**4 / 4 + a[6]


def deltas(
    reaction: Reaction, species: dict[str, Species], temperature_K: float
) -> tuple[float, float] | None:
    """Dimensionless reaction enthalpy and entropy, or None without polynomials."""

    delta_h = delta_s = 0.0
    for terms, sign in ((reaction.products, 1.0), (reaction.reactants, -1.0)):
        for term in terms:
            contribution = _term_thermo(term.species, species, temperature_K)
            if contribution is None:
                return None
            delta_h += sign * term.n * contribution[0]
            delta_s += sign * term.n * contribution[1]
    return (delta_h, delta_s)


def gibbs_energy_eV(
    reaction: Reaction, species: dict[str, Species], temperature_K: float
) -> float | None:
    """Delta G of the forward reaction, in eV per event."""

    found = deltas(reaction, species, temperature_K)
    if found is None:
        return None
    delta_h, delta_s = found
    return GAS_CONSTANT * temperature_K * (delta_h - delta_s) / (AVOGADRO * JOULE_PER_EV)


def equilibrium_constant(
    reaction: Reaction, species: dict[str, Species], temperature_K: float
) -> float | None:
    """Concentration-based K in m^3 units, or None without polynomials."""

    found = deltas(reaction, species, temperature_K)
    if found is None:
        return None
    delta_h, delta_s = found
    concentration = STANDARD_PRESSURE / (GAS_CONSTANT * temperature_K) * AVOGADRO
    return exp(delta_s - delta_h) * concentration**-reaction.delta_moles


def reverse_rate(
    forward: float, reaction: Reaction, species: dict[str, Species], temperature_K: float
) -> float | None:
    constant = equilibrium_constant(reaction, species, temperature_K)
    return None if not constant else forward / constant


def _term_thermo(
    species_id: str, species: dict[str, Species], temperature_K: float
) -> tuple[float, float] | None:
    """Dimensionless enthalpy and entropy; the electron carries neither."""

    if species_id == ELECTRON:
        return (0.0, 0.0)
    found = species.get(species_id)
    if found is None or found.thermo is None:
        return None
    return (enthalpy_RT(found.thermo, temperature_K), entropy_R(found.thermo, temperature_K))
