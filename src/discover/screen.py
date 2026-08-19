"""Decide which ion-neutral channels are thermodynamically open.

Ion-molecule chemistry is the family with almost no queryable database, and it
is also the family that needs one least. Charge transfer

    A+ + B -> A + B+        Delta E = IE(B) - IE(A)

is exothermic exactly when B is easier to ionize than A, and an exothermic
ion-molecule reaction proceeds at close to the capture rate. So the question
"does this channel exist" reduces to a thermochemical lookup, and the rate that
follows is the Langevin value `reactgen.physics` already computes.

This screens; it does not confirm. An open channel may still be slow for
reasons a table of energies cannot see, and a closed one is genuinely closed at
thermal energy but may open in a sheath.
"""

from __future__ import annotations

from dataclasses import dataclass

# How far past thermoneutral a channel may sit and still be reached. At a few
# hundred kelvin this is a handful of kT, and it is also about the accuracy the
# ionization energies are known to, so a difference smaller than this settles
# nothing either way.
RESONANCE_EV = 0.1


@dataclass(frozen=True)
class Screened:
    ion: str
    neutral: str
    products: tuple[str, str]
    delta_e_eV: float | None
    verdict: str  # open | closed | unknown

    @property
    def equation(self) -> str:
        return f"{self.ion} + {self.neutral} -> {self.products[0]} + {self.products[1]}"


def charge_transfer(
    ionization: dict[str, float],
    cations: dict[str, str],
) -> list[Screened]:
    """Every ``A+ + B`` pair the registry can name, with its energy verdict.

    ``ionization`` maps a neutral onto its ionization energy; ``cations`` maps a
    neutral onto the id of its singly charged ion.
    """

    out = []
    for parent, ion in sorted(cations.items()):
        for neutral in sorted(ionization):
            if neutral == parent or parent not in ionization:
                continue
            product_ion = cations.get(neutral)
            if product_ion is None:
                continue
            delta = ionization[neutral] - ionization[parent]
            products = (parent, product_ion)
            out.append(Screened(ion, neutral, products, delta, transfer_verdict(delta)))
    return out


def dissociative_transfer_energy(
    ion_parent: str,
    fragment: str,
    rest: str,
    target: str,
    ionization: dict[str, float],
    enthalpy: dict[str, float],
) -> float | None:
    """Delta E of ``A+ + BC -> A + B+ + C``, in eV.

    Writing the ion enthalpy as ``Hf(X) + IE(X)`` the parent terms cancel and

        Delta E = IE(B) - IE(A) + D(B-C)

    where the bond energy ``D = Hf(B) + Hf(C) - Hf(BC)``. So the channel opens
    when the fragment is easier to ionize than the projectile by more than the
    bond costs — which is why an ion can break a molecule that plain charge
    transfer would leave whole.
    """

    if ion_parent not in ionization or fragment not in ionization:
        return None
    bond = reaction_energy([target], [fragment, rest], enthalpy)
    if bond is None:
        return None
    return ionization[fragment] - ionization[ion_parent] + bond


def penning_energy(
    excitation_eV: float | None, target: str, ionization: dict[str, float]
) -> float | None:
    """Delta E of ``M* + X -> M + X+ + e``, in eV.

    A metastable carries its excitation energy until something takes it. When
    that exceeds the partner's ionization energy the collision ionizes, which in
    a rare-gas-diluted discharge is often the dominant electron source.
    """

    if excitation_eV is None or target not in ionization:
        return None
    return ionization[target] - excitation_eV


def neutralization_energy(
    ion_parent: str,
    anion_parent: str,
    ionization: dict[str, float],
    affinity: dict[str, float],
) -> float | None:
    """Delta E of ``A+ + B- -> A + B``, in eV.

    The electron falls from the anion back onto the cation, releasing
    ``IE(A) - EA(B)``. Ionization energies run far above electron affinities, so
    mutual neutralization is open for essentially every pair — which is why it
    is the dominant ion loss in an electronegative discharge, and why the screen
    here is a sanity check rather than a filter.
    """

    if ion_parent not in ionization or anion_parent not in affinity:
        return None
    return affinity[anion_parent] - ionization[ion_parent]


def reaction_energy(
    reactants: list[str],
    products: list[str],
    enthalpy: dict[str, float],
) -> float | None:
    """Delta H of the forward reaction in eV, or None if any species is missing.

    Formation enthalpies alone settle whether a neutral-neutral channel runs
    downhill. The entropy term matters near equilibrium, but a channel that is
    endothermic by more than a fraction of an eV is closed at a gas temperature
    of a few hundred kelvin whatever the entropy does.
    """

    total = 0.0
    for names, sign in ((products, 1.0), (reactants, -1.0)):
        for name in names:
            if name not in enthalpy:
                return None
            total += sign * enthalpy[name]
    return total


def neutral_verdict(delta_h: float | None, tolerance_eV: float = 0.25) -> str:
    """Whether a neutral-neutral channel runs downhill far enough to happen.

    The tolerance is several kT at a few hundred kelvin, and it stands in for
    the activation barrier this has no way to see: an abstraction that is only
    just exothermic usually still has one. Undecided in the middle band, which
    is honest — unlike a charge transfer, the sign alone does not settle it.

    Deliberately stricter than `transfer_verdict`, and for a different reason.
    That one asks whether an ion-molecule channel is energetically reachable,
    where near resonance means fast; this one asks whether a barrier is likely
    to close a channel the energetics leave open.
    """

    if delta_h is None:
        return "unknown"
    if delta_h < -tolerance_eV:
        return "open"
    return "closed" if delta_h > tolerance_eV else "unknown"


def transfer_verdict(delta_e: float | None) -> str:
    """Whether a charge transfer channel is reachable at thermal energy.

    Exothermic and near-resonant channels are open. Near resonance is where
    charge transfer is *fastest*, not where it is doubtful: a channel within
    ``RESONANCE_EV`` of thermoneutral runs close to the capture rate, and the
    sign of a difference that small sits inside the uncertainty of the two
    ionization energies anyway. Treating it as undecided dropped the quickest
    channels in the set, so only a clearly endothermic one is closed.

    This is a different question from `neutral_verdict`, which asks whether a
    neutral-neutral channel runs downhill far enough to beat its barrier.
    """

    if delta_e is None:
        return "unknown"
    return "open" if delta_e < RESONANCE_EV else "closed"
