"""Enumerate the reaction channels a species could have.

Bond-breaking under conservation, nothing more. Given SiH4 this proposes
ionization, attachment, and the dissociations that breaking one bond allows.
It does not know which of them occur — that is what a source is for — so
everything it returns is a candidate.

The enumeration is bounded by chemistry, not by the registry: a molecule with no
registered fragments is exactly the case `discover` exists for. What the
registry decides is only *naming* — a fragment already registered keeps its id,
and one that is not is reported as a species to register alongside the channel.
"""

from __future__ import annotations

from dataclasses import dataclass

# How many ligands may leave at once. Two covers the dominant single-bond and
# paired-ligand channels; raising it reaches the deeper dissociative ionization
# a high-energy electron drives — SF6 gives SF3+ and SF2+ as well as SF5+ — at
# the cost of proposing channels that need a real cross section to justify.
MAX_LEAVING_ATOMS = 2

Composition = dict[str, int]
Known = dict[tuple, str]


@dataclass(frozen=True)
class Candidate:
    """One proposed channel, with the species it needs that do not exist yet."""

    type: str
    reactants: tuple[str, ...]
    products: tuple[str, ...]
    new_species: tuple[str, ...] = ()
    threshold_eV: float | None = None

    @property
    def equation(self) -> str:
        return f"{' + '.join(self.reactants)} -> {' + '.join(self.products)}"


def electron_channels(
    target: str,
    composition: Composition,
    known: Known,
    max_charge: int = 1,
    excitation: str = "none",
    electronic: bool = True,
    level_energy: dict[str, float] | None = None,
    max_leaving: int = MAX_LEAVING_ATOMS,
    binds_electron: bool = True,
) -> list[Candidate]:
    """Electron-impact channels for one neutral target.

    ``binds_electron`` gates attachment: an atom whose electron affinity is
    negative — argon's is -11.5 eV — forms no anion at all.

    ``max_charge`` admits multiply charged ions. Each further stage costs its own
    ionization energy — argon's second is 27.6 eV against 15.8 for the first — so
    it is off by default and belongs to a case that says it wants it.

    ``excitation`` chooses how excited states are written. See `excited_state`.
    """

    channels = [Candidate("elastic", ("e", target), ("e", target))]
    for stage in range(1, max_charge + 1):
        cation = _name(composition, stage, known)
        kind = "ionization" if stage == 1 else f"ionization_{stage}"
        # One electron in, stage + 1 out: the incident one plus the ones removed.
        products = ("e",) * (stage + 1) + (cation.id,)
        channels.append(Candidate(kind, ("e", target), products, cation.new))
    if binds_electron:
        # A species with a negative electron affinity has no bound anion, so
        # `e + Ar -> Ar-` is not a slow reaction but an impossible one.
        anion = _name(composition, -1, known)
        channels.append(Candidate("attachment", ("e", target), (anion.id,), anion.new))

    for excited, kind in excited_states(target, composition, excitation, electronic):
        onset = (level_energy or {}).get(kind)
        channels.append(Candidate("excitation", ("e", target), ("e", excited), (excited,), onset))
        # Superelastic: the excited partner pays, so the electron needs nothing.
        channels.append(Candidate("deexcitation", ("e", excited), ("e", target), (), 0.0))

    for heavy, light in _bonds(composition, max_leaving):
        big = _name(heavy, 0, known)
        leaving, leaving_new = _leaving_group(light, known)
        channels.append(
            Candidate(
                "dissociation",
                ("e", target),
                ("e", big.id, *leaving),
                big.new + leaving_new,
            )
        )
        charged = _name(heavy, 1, known)
        channels.append(
            Candidate(
                "dissociative_ionization",
                ("e", target),
                ("e", "e", charged.id, *leaving),
                charged.new + leaving_new,
            )
        )
    return channels


# Homonuclear diatomics that are real species; a leaving pair may recombine into
# one of these. Three or more ligands leave as separate atoms — `F3` is not a
# molecule, and writing one would put a species into the list that cannot exist.
DIATOMIC = frozenset({"H", "N", "O", "F", "Cl", "Br", "I"})


def _leaving_group(light: Composition, known: Known) -> tuple[tuple[str, ...], tuple[str, ...]]:
    element, count = next(iter(light.items()))
    if count == 2 and element in DIATOMIC:
        molecule = _name(light, 0, known)
        return ((molecule.id,), molecule.new)
    atom = _name({element: 1}, 0, known)
    return ((atom.id,) * count, atom.new)


# Ground-state shell character, which is what decides how a first excitation
# splits. Closed-shell atoms promote an electron into a new configuration whose
# manifold contains both metastable and radiating levels; open-shell atoms have
# low terms inside their own configuration, and radiation between same-parity
# terms is forbidden, so those are metastable and there is no resonant partner.
CLOSED_SHELL = frozenset({"He", "Ne", "Ar", "Kr", "Xe"})
OPEN_SHELL_ATOMS = frozenset({"C", "N", "O", "F", "S", "Cl", "Br", "Si", "P", "I"})


def excited_states(
    target: str, composition: Composition, mode: str, electronic: bool = True
) -> list[tuple[str, str]]:
    """Excited species to carry, as ``(id, kind)`` pairs.

    Three resolutions, and what each can be defended with:

    ``lumped`` — one effective level, ``Ar*``. What a swarm calculation lumps
    its excitation cross sections into, and enough for a power balance.

    ``metastable`` — the split a plasma model actually needs: ``Ar_meta`` lives
    long enough to accumulate and drive stepwise ionization and Penning
    transfer, while ``Ar_res`` radiates away. The suffixes are spelled out
    because ``_m`` is already how this repository writes a *negative ion*, and
    ``Ar_m`` would parse as the anion rather than the metastable. Which levels fall on which side
    follows from selection rules on the ground configuration, so this needs no
    spectroscopy — only the shell the atom starts from.

    The mode chooses the resolution of an *atom*. A molecule always carries
    two, because they are two processes rather than two resolutions of one:
    ``N2_v`` sits a few tenths of an eV up and takes most of the electron
    energy at low Te, while ``N2*`` is several eV. One ``N2*`` for both would
    give the list a single threshold where the physics has two.

    ``electronic`` is dropped where the registry already resolves this species
    into named levels, so a lumped ``O2*`` is not carried beside ``O2_a1Delta``.
    The vibrational manifold survives that: no registry here names one, and it
    is a different process rather than a coarser view of the same one.

    Energies are not derivable at any resolution. The species are proposed
    without one, and their thresholds stay an acquisition gap. Resolving the
    manifold into levels needs vibrational constants, which is why it is
    carried whole.
    """

    if mode == "none" or target.endswith(("*", "_meta", "_res", "_v")):
        return []
    if sum(composition.values()) != 1:
        levels = [(f"{target}_v", "vibrational")]
        if electronic:
            levels.append((f"{target}*", "lumped"))
        return levels
    if not electronic:
        return []
    if mode == "lumped":
        return [(f"{target}*", "lumped")]

    element = next(iter(composition))
    if element in CLOSED_SHELL:
        # p6 -> p5 s: the manifold holds both metastable and radiating levels.
        return [(f"{target}_meta", "metastable"), (f"{target}_res", "resonant")]
    if element in OPEN_SHELL_ATOMS:
        # Low terms sit in the ground configuration; radiation to it is forbidden.
        return [(f"{target}_meta", "metastable")]
    return [(f"{target}*", "lumped")]


def _bonds(
    composition: Composition, max_leaving: int = MAX_LEAVING_ATOMS
) -> list[tuple[Composition, Composition]]:
    """Ways one bond can break: the ligand leaves, singly or in a pair.

    The ligand is the most numerous element — F in SF6, H in SiH4 — because that
    is what a bond to the central atom holds. Stripping anything else invents
    fragments like ``H4`` that do not exist. Breaking several bonds at once is a
    higher-order process whose channels belong to a source, not to a formula.
    """

    ligand = max(composition, key=lambda element: (composition[element], element))
    found = []
    for count in range(1, min(max_leaving, composition[ligand]) + 1):
        heavy = {**composition, ligand: composition[ligand] - count}
        heavy = {element: number for element, number in heavy.items() if number}
        if heavy:
            found.append((heavy, {ligand: count}))
    return found


@dataclass(frozen=True)
class _Named:
    id: str
    new: tuple[str, ...]


def _name(composition: Composition, charge: int, known: Known) -> _Named:
    """The registered id for this formula and charge, or the formula itself."""

    registered = known.get((tuple(sorted(composition.items())), charge))
    if registered:
        return _Named(registered, ())
    written = formula(composition) + _charge_suffix(charge)
    return _Named(written, (written,))


def _charge_suffix(charge: int) -> str:
    """``+`` for a single charge, ``2+`` beyond that, ``-`` for an anion."""

    if charge == 0:
        return ""
    sign = "+" if charge > 0 else "-"
    return sign if abs(charge) == 1 else f"{abs(charge)}{sign}"


# Pauling electronegativity for the elements this domain uses. Formulas are
# written least electronegative first, which is what gives SiH4 and SF6 rather
# than the alphabetical H4Si and F6S.
ELECTRONEGATIVITY = {
    "Cu": 1.90,
    "Si": 1.90,
    "B": 2.04,
    "H": 2.20,
    "P": 2.19,
    "C": 2.55,
    "S": 2.58,
    "I": 2.66,
    "Br": 2.96,
    "N": 3.04,
    "Cl": 3.16,
    "O": 3.44,
    "F": 3.98,
}


def formula(composition: Composition) -> str:
    """``{"Si": 1, "H": 4}`` written as ``SiH4``."""

    order = sorted(composition, key=lambda element: (ELECTRONEGATIVITY.get(element, 2.0), element))
    return "".join(f"{e}{composition[e] if composition[e] > 1 else ''}" for e in order)
