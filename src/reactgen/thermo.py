"""Pure arithmetic over selected thermochemical inputs.

Source qualification and missing-input explanations belong to ``assessment``.
These functions check numerical shape and physical reference compatibility;
they do not approve a source, identify a state, or establish channel occurrence.
NASA7 calculations cover thermal gas ground states and exclude electron
channels. A computed equilibrium constant does not choose a reverse channel.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import exp, fsum, isfinite, log

from reactgen.model import ELECTRON, ReactionCandidate, stoichiometric_sum
from reactgen.records import (
    FormationReference,
    RegistryReaction,
    Species,
    StateRecord,
    Thermo,
    property_has_point_qualifier,
)
from reactgen.units import energy_eV

GAS_CONSTANT = 8.314462618  # J/(mol K)
AVOGADRO = 6.02214076e23
JOULE_PER_EV = 1.602176634e-19


ReactionLike = RegistryReaction | ReactionCandidate
ThermoEvidence = Species | StateRecord


def formation_delta(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
) -> float | None:
    """Products-minus-reactants enthalpy at one common, stated reference.

    This is neither an appearance threshold nor an occurrence or rate test.
    Values at an unspecified or incompatible reference cannot be subtracted.
    Electron formation enthalpy is zero at 0 K and in the electron convention;
    the finite-T ion convention needs its electron term when it does not cancel.
    No electron heat-capacity model or temperature correction is assumed.
    """
    coefficients = net_stoichiometry(reaction)
    if not coefficients:
        return 0.0
    reference = formation_reference(reaction, species)
    if reference is None:
        return None
    total = 0.0
    for species_id, coefficient in coefficients.items():
        if species_id == ELECTRON:
            total += coefficient * (reference.electron_enthalpy_eV or 0.0)
            continue
        found = species.get(species_id)
        prop = None if found is None else found.properties.get("enthalpy_formation_eV")
        # A free upper-limit/approximation annotation is not a point value.
        # Source review is upstream; the calculator cannot ignore its meaning.
        value = (
            energy_eV(prop.value, prop.unit)
            if prop is not None and prop.value is not None and property_has_point_qualifier(prop)
            else None
        )
        if value is None:
            return None
        total += coefficient * value
    return total if isfinite(total) else None


def formation_reference(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
) -> FormationReference | None:
    """Common elemental reference, including the ion/electron convention.

    Neutral references do not depend on the electron convention. The two ion
    conventions agree at 0 K; finite-temperature conversion is deliberately
    not inferred. Phase is supplied by the identified state, never a formula.
    """
    inputs = _formation_inputs(reaction, species)
    if inputs is None:
        return None
    references, charged_references, electron_count = inputs
    if (
        not references
        or len({(ref.temperature_K, ref.basis, ref.standard_pressure_Pa) for ref in references})
        != 1
    ):
        return None
    reference = references[0]
    if reference.temperature_K == 0:
        return FormationReference(
            0.0,
            reference.basis,
            reference.standard_pressure_Pa,
            "electron" if charged_references else None,
            0.0,
        )
    conventions = {ref.electron_convention for ref in charged_references}
    if charged_references and (None in conventions or len(conventions) != 1):
        return None
    convention = next(iter(conventions)) if conventions else None
    electron_enthalpy = 0.0
    if electron_count and convention == "ion":
        values = {ref.electron_enthalpy_eV for ref in charged_references}
        if None in values or len(values) != 1:
            return None
        declared = next(iter(values))
        if declared is None:
            return None
        electron_enthalpy = declared
    return FormationReference(
        reference.temperature_K,
        reference.basis,
        reference.standard_pressure_Pa,
        convention,
        electron_enthalpy,
    )


def _formation_inputs(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
) -> tuple[list[FormationReference], list[FormationReference], float] | None:
    """Collect references only for states contributing to the difference."""
    references = []
    charged_references = []
    for species_id in net_stoichiometry(reaction):
        if species_id == ELECTRON:
            continue
        found = species.get(species_id)
        if found is None:
            return None
        state = found.candidate if isinstance(found, StateRecord) else found
        prop = found.properties.get("enthalpy_formation_eV")
        reference = None if prop is None else prop.formation_reference
        if state.phase == "unknown" or reference is None or not reference.complete:
            return None
        references.append(reference)
        if state.charge:
            charged_references.append(reference)
    return references, charged_references, net_electron_coefficient(reaction)


def net_electron_coefficient(reaction: ReactionLike) -> float:
    """Products-minus-reactants free electrons, using common declared-coefficient arithmetic."""
    return net_stoichiometry(reaction).get(ELECTRON, 0.0)


def net_stoichiometry(reaction: ReactionLike) -> dict[str, float]:
    """Signed coefficients for thermochemical differences, retaining state identity.

    The same state on both sides cancels before demanding its physical values.
    Its role as a collision participant or catalyst remains in the reaction.
    Opposing terms use the retained decimal coefficient values for exact
    cancellation. A one-sided contribution is retained at any scale; small
    coefficients do not identify different states or approve a process.
    """
    coefficients: dict[str, list[float]] = {}
    for terms, sign in ((reaction.products, 1.0), (reaction.reactants, -1.0)):
        for term in terms:
            coefficients.setdefault(term.species, []).append(sign * term.n)
    return {
        species_id: total
        for species_id, values in sorted(coefficients.items())
        if (total := stoichiometric_sum(values)) != 0
    }


def enthalpy_RT(thermo: Thermo, temperature_K: float) -> float:
    if not valid_thermo(thermo) or not thermo.t_min <= temperature_K <= thermo.t_max:
        raise ValueError(
            "NASA7 evaluation requires finite coefficients and an in-range temperature"
        )
    a = thermo.coefficients(temperature_K)
    t = temperature_K
    return a[0] + a[1] * t / 2 + a[2] * t**2 / 3 + a[3] * t**3 / 4 + a[4] * t**4 / 5 + a[5] / t


def entropy_R(thermo: Thermo, temperature_K: float) -> float:
    if not valid_thermo(thermo) or not thermo.t_min <= temperature_K <= thermo.t_max:
        raise ValueError(
            "NASA7 evaluation requires finite coefficients and an in-range temperature"
        )
    a = thermo.coefficients(temperature_K)
    t = temperature_K
    return a[0] * log(t) + a[1] * t + a[2] * t**2 / 2 + a[3] * t**3 / 3 + a[4] * t**4 / 4 + a[6]


def deltas(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> tuple[float, float] | None:
    """Dimensionless reaction enthalpy and entropy, or None without polynomials."""

    if (
        not isfinite(temperature_K)
        or temperature_K <= 0.0
        or any(term.species == ELECTRON for term in (*reaction.reactants, *reaction.products))
    ):
        return None
    coefficients = net_stoichiometry(reaction)
    if not coefficients:
        return (0.0, 0.0)
    if reference_pressure(reaction, species) is None:
        return None
    delta_h = delta_s = 0.0
    for species_id, coefficient in coefficients.items():
        contribution = _term_thermo(species_id, species, temperature_K)
        if contribution is None:
            return None
        delta_h += coefficient * contribution[0]
        delta_s += coefficient * contribution[1]
    return (delta_h, delta_s)


def gibbs_energy_eV(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> float | None:
    """Delta G of the forward reaction, in eV per event."""

    return thermal_values(reaction, species, temperature_K)[0]


def equilibrium_constant(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> float | None:
    """Concentration-form equilibrium constant, or None without valid polynomials."""

    return thermal_values(reaction, species, temperature_K)[1]


def thermal_values(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> tuple[float | None, float | None]:
    """Standard Gibbs energy [eV/event] and number-density equilibrium ratio.

    Both values derive from one NASA7 enthalpy/entropy difference. A numerical
    overflow of one representation does not discard the other quantity.
    For the number-density ratio the dimension is ``m**(-3 * delta_nu)``.
    The ideal-gas standard concentration and Gibbs relation are described in
    https://www.cantera.org/stable/cxx/d7/dfa/classCantera_1_1IdealGasPhase.html .
    """
    found = deltas(reaction, species, temperature_K)
    if found is None:
        return None, None
    delta_h, delta_s = found
    calculated_gibbs = (
        GAS_CONSTANT * temperature_K * (delta_h - delta_s) / (AVOGADRO * JOULE_PER_EV)
    )
    gibbs = calculated_gibbs if isfinite(calculated_gibbs) else None
    if not net_stoichiometry(reaction):
        return gibbs, 1.0
    pressure = reference_pressure(reaction, species)
    if pressure is None:
        return gibbs, None
    delta_moles = fsum(net_stoichiometry(reaction).values())
    # K_n = exp(-delta_G / RT) * (p_standard / k_B T)**delta_nu.
    # Combine the factors in log space: either factor alone can overflow or
    # underflow even when the number-density equilibrium ratio is representable.
    log_concentration = fsum(
        (log(pressure), log(AVOGADRO), -log(GAS_CONSTANT), -log(temperature_K))
    )
    try:
        value = exp(fsum((delta_s, -delta_h, delta_moles * log_concentration)))
        return gibbs, value if isfinite(value) and value > 0 else None
    except OverflowError:
        return gibbs, None


def _term_thermo(
    species_id: str,
    species: Mapping[str, ThermoEvidence],
    temperature_K: float,
) -> tuple[float, float] | None:
    """Ground-state thermal H/RT and S/R; nonthermal states are not inferred."""

    if species_id == ELECTRON:
        return None
    found = species.get(species_id)
    if found is None or found.thermo is None or not valid_thermo(found.thermo):
        return None
    state_kind = found.candidate.state.kind if isinstance(found, StateRecord) else found.state.kind
    if state_kind != "ground":
        return None
    if not found.thermo.t_min <= temperature_K <= found.thermo.t_max:
        return None
    try:
        enthalpy, entropy = (
            enthalpy_RT(found.thermo, temperature_K),
            entropy_R(found.thermo, temperature_K),
        )
    except OverflowError:
        return None
    return (enthalpy, entropy) if isfinite(enthalpy) and isfinite(entropy) else None


def valid_thermo(thermo: Thermo) -> bool:
    """NASA7 shape, domain, and gas reference metadata; not source approval."""
    return (
        len(thermo.low) == len(thermo.high) == 7
        and all(
            isfinite(value)
            for value in (*thermo.low, *thermo.high, thermo.t_min, thermo.t_mid, thermo.t_max)
        )
        and 0 < thermo.t_min < thermo.t_max
        and (
            thermo.t_min < thermo.t_mid < thermo.t_max
            or (thermo.low == thermo.high and thermo.t_min <= thermo.t_mid <= thermo.t_max)
        )
        and thermo.phase == "gas"
        and thermo.standard_pressure_Pa is not None
        and isfinite(thermo.standard_pressure_Pa)
        and thermo.standard_pressure_Pa > 0
    )


def reference_pressure(
    reaction: ReactionLike,
    species: Mapping[str, ThermoEvidence],
) -> float | None:
    """Common stated reference pressure; no implicit 1 atm convention."""
    pressures = set()
    if any(term.species == ELECTRON for term in (*reaction.reactants, *reaction.products)):
        return None
    for species_id in net_stoichiometry(reaction):
        found = species.get(species_id)
        if found is None or found.thermo is None or not valid_thermo(found.thermo):
            return None
        if isinstance(found, StateRecord) and found.candidate.phase != "gas":
            return None
        if isinstance(found, Species) and found.phase != "gas":
            return None
        pressures.add(found.thermo.standard_pressure_Pa)
    return next(iter(pressures)) if len(pressures) == 1 else None
