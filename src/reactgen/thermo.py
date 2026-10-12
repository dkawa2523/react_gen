"""Pure thermochemical calculations over reviewed state evidence.

NASA polynomials on every thermal ground-state participant provide reaction
Gibbs energy and an equilibrium constant. A reverse coefficient additionally
needs a compatible forward rate and a channel for which detailed balance is
meaningful; that channel-level decision belongs to ``assessment``.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import exp, fsum, isfinite, log

from reactgen.model import ELECTRON, STOICHIOMETRY_TOLERANCE, ReactionCandidate
from reactgen.records import FormationReference, RegistryReaction, Species, StateRecord, Thermo
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
    reference = formation_reference(reaction, species)
    if reference is None:
        return None
    total = 0.0
    for terms, sign in ((reaction.products, 1.0), (reaction.reactants, -1.0)):
        for term in terms:
            if term.species == ELECTRON:
                total += sign * term.n * (reference.electron_enthalpy_eV or 0.0)
                continue
            found = species.get(term.species)
            prop = None if found is None else found.properties.get("enthalpy_formation_eV")
            value = (
                energy_eV(prop.value, prop.unit)
                if prop is not None and prop.value is not None
                else None
            )
            if value is None:
                return None
            total += sign * term.n * value
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
    """Collect explicit participant references and the net electron coefficient."""
    references = []
    charged_references = []
    for terms in (reaction.products, reaction.reactants):
        for term in terms:
            if term.species == ELECTRON:
                continue
            found = species.get(term.species)
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
    """Products-minus-reactants free electrons, using the common balance tolerance."""
    count = fsum(
        sign * term.n
        for terms, sign in ((reaction.products, 1.0), (reaction.reactants, -1.0))
        for term in terms
        if term.species == ELECTRON
    )
    return 0.0 if abs(count) <= STOICHIOMETRY_TOLERANCE else count


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
        or reference_pressure(reaction, species) is None
    ):
        return None
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
    value = GAS_CONSTANT * temperature_K * (delta_h - delta_s) / (AVOGADRO * JOULE_PER_EV)
    return value if isfinite(value) else None


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
    pressure = reference_pressure(reaction, species)
    if pressure is None:
        return None
    concentration = pressure / (GAS_CONSTANT * temperature_K) * AVOGADRO
    delta_moles = sum(term.n for term in reaction.products) - sum(
        term.n for term in reaction.reactants
    )
    try:
        value = exp(delta_s - delta_h) * concentration**delta_moles
        return value if isfinite(value) and value > 0 else None
    except OverflowError:
        return None


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
        and 0 < thermo.t_min < thermo.t_mid < thermo.t_max
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
    for term in (*reaction.reactants, *reaction.products):
        found = species.get(term.species)
        if found is None or found.thermo is None or not valid_thermo(found.thermo):
            return None
        if isinstance(found, StateRecord) and found.candidate.phase != "gas":
            return None
        if isinstance(found, Species) and found.phase != "gas":
            return None
        pressures.add(found.thermo.standard_pressure_Pa)
    return next(iter(pressures)) if len(pressures) == 1 else None
