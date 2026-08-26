"""Pure thermochemical calculations over reviewed state evidence.

NASA polynomials on every thermal ground-state participant provide reaction
Gibbs energy and an equilibrium constant. A reverse coefficient additionally
needs a compatible forward rate and a channel for which detailed balance is
meaningful; that channel-level decision belongs to ``assessment``.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import exp, log

from reactgen.model import ELECTRON, ReactionCandidate
from reactgen.records import RegistryReaction, Species, StateRecord, Thermo

GAS_CONSTANT = 8.314462618  # J/(mol K)
STANDARD_PRESSURE = 101325.0  # Pa
AVOGADRO = 6.02214076e23
JOULE_PER_EV = 1.602176634e-19


ReactionLike = RegistryReaction | ReactionCandidate
ThermoEvidence = Species | StateRecord


def formation_delta(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
) -> float | None:
    """Reaction enthalpy from formation enthalpies, or None where one is missing.

    ``E(products) - E(reactants)``, so a positive value is endothermic. The
    electron carries no formation enthalpy by the usual convention. This is
    sufficient for a reaction-energy difference, but not for an equilibrium
    constant: an electron energy distribution is not a gas-temperature NASA
    species.

    Not a screen. An electron brings whatever energy it has, so a positive value
    here says where the channel opens rather than that it is shut, but it has
    to be recorded for the assessment to check an acquired threshold against it, and
    for a reviewer to see how far uphill a channel sits.
    """

    total = 0.0
    for terms, sign in ((reaction.products, 1.0), (reaction.reactants, -1.0)):
        for term in terms:
            if term.species == ELECTRON:
                continue
            found = species.get(term.species)
            prop = None if found is None else found.properties.get("enthalpy_formation_eV")
            value = prop.value if prop is not None and prop.unit in {None, "eV"} else None
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
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
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
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> float | None:
    """Delta G of the forward reaction, in eV per event."""

    found = deltas(reaction, species, temperature_K)
    if found is None:
        return None
    delta_h, delta_s = found
    return GAS_CONSTANT * temperature_K * (delta_h - delta_s) / (AVOGADRO * JOULE_PER_EV)


def equilibrium_constant(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> float | None:
    """Concentration-form equilibrium constant, or None without valid polynomials."""

    found = deltas(reaction, species, temperature_K)
    if found is None:
        return None
    delta_h, delta_s = found
    concentration = STANDARD_PRESSURE / (GAS_CONSTANT * temperature_K) * AVOGADRO
    delta_moles = sum(term.n for term in reaction.products) - sum(
        term.n for term in reaction.reactants
    )
    return exp(delta_s - delta_h) * concentration**-delta_moles


def reverse_rate(
    forward: float,
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> float | None:
    constant = equilibrium_constant(reaction, species, temperature_K)
    return None if not constant else forward / constant


def _term_thermo(
    species_id: str,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> tuple[float, float] | None:
    """Ground-state thermal H/RT and S/R; nonthermal states are not inferred."""

    if species_id == ELECTRON:
        return None
    found = species.get(species_id)
    if found is None or found.thermo is None:
        return None
    state_kind = found.candidate.state.kind if isinstance(found, StateRecord) else found.state.kind
    if state_kind != "ground":
        return None
    if not found.thermo.t_min <= temperature_K <= found.thermo.t_max:
        return None
    return (enthalpy_RT(found.thermo, temperature_K), entropy_R(found.thermo, temperature_K))
