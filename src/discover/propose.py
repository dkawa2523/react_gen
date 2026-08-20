"""Answer for the species the registry does not cover.

This is the implementation behind `reactgen.expand`'s proposer hook, and it is
what turns a single-species guess into a multi-step list: whatever it proposes
produces species, those enter the frontier, and it is asked again.

Two layers are proposed and one is deliberately not:

* **electron impact** — ligand stripping bounds it. SF6/O2 closes at 59 channels
  over 11 neutrals, so mechanical enumeration is safe here.
* **ion-neutral charge transfer** — the pair count grows as N squared, so it is
  screened first: only channels that are exothermic by ionization energy are
  proposed, which rejects about half.
* **neutral-neutral** — proposed only where formation enthalpies exist, and only
  the exothermic ones. Without that screen the layer is skipped entirely rather
  than enumerated blind, because unscreened it buries the useful list in noise.
  Run `acquire thermo` to widen it.

Everything proposed carries ``status: candidate`` and species it invents are
marked the same way, so nothing here can reach a normal generated network.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from discover import collide, fragments, screen, view
from discover.relations import Relations
from reactgen import derive, naming
from reactgen.model import ELECTRON, Property, Reaction, Species, State, Term
from reactgen.processes import Selection, select
from reactgen.registry import Registry

CANDIDATE = "candidate"

# Zero by definition rather than by measurement, so these are written rather
# than left as an acquisition gap: an elastic collision pays for no internal
# state, and a superelastic one is paid by the excited partner instead of the
# electron. Every other channel has an onset that has to come from a source.
FREE = {"elastic": 0.0, "deexcitation": 0.0}

# How far a candidate can be trusted before anyone reads a paper. The order is
# what a reviewer should work down, and it is written into every proposal.
CONFIDENCE = {
    "measured": "a source states this equation",
    "energetic": "no source seen, but the energetics say the channel is open",
    "structural": "conservation allows it; nothing says it happens",
}


@dataclass
class Proposer:
    """Proposes channels, and remembers the species it had to invent."""

    registry: Registry
    relations: Relations
    ionization: dict[str, float]
    affinity: dict[str, float]
    enthalpy: dict[str, float]
    levels: dict[str, dict[str, float]]
    vibration: dict[str, float]
    invented: dict[str, Species]
    max_ion_charge: int = 1
    excitation: str = "lumped"
    max_leaving: int = 2
    max_endothermic_eV: float = 2.0
    processes: Selection = field(default_factory=select)
    _equations: set[tuple] | None = None
    _elements: dict[str, float] | None = None

    @classmethod
    def build(
        cls,
        registry: Registry,
        ionization: dict[str, float],
        affinity: dict[str, float] | None = None,
        enthalpy: dict[str, float] | None = None,
        levels: dict[str, dict[str, float]] | None = None,
        vibration: dict[str, float] | None = None,
        max_ion_charge: int = 1,
        excitation: str = "lumped",
        max_leaving: int = 2,
        max_endothermic_eV: float = 2.0,
        processes: Selection | None = None,
    ) -> Proposer:
        return cls(
            registry,
            Relations(registry.species),
            ionization,
            affinity or {},
            enthalpy or {},
            levels or {},
            vibration or {},
            {},
            max_ion_charge,
            excitation,
            max_leaving,
            max_endothermic_eV,
            processes or select(),
        )

    def __call__(self, frontier: set[str], active: set[str]) -> list[Reaction]:
        proposed = list(self._electron(frontier))
        if self.processes.on("dissociation"):
            proposed += self._dissociative_excitation(frontier)
        if self.processes.on("vibrational_relaxation"):
            proposed += self._relaxation(frontier, active)
        if self.processes.on("heavy_particle"):
            # Two rules, not one. `_collide` rearranges atoms and moves charge;
            # Penning creates a charge out of energy already stored in a
            # metastable, which no partition of the atoms can express.
            proposed += self._collide(frontier, active)
            proposed += self._penning(frontier, active)
        return self._keep_new([item for item in proposed if self.processes.allows(item.type)])

    def _dissociative_excitation(self, frontier: set[str]) -> list[Reaction]:
        """``e + AB -> e + A + B*``: the bond breaks and a piece comes out excited.

        The energy follows from two things already held — the bond energy from
        formation enthalpies, and the level energy of the fragment — so this
        needs no cross section and no spectroscopy of the parent::

            Delta E = D0(A-B) + E(B*)

        What comes out is the *thermodynamic* limit, which is where the channel
        becomes possible, not where a measured cross section rises: oxygen's
        O(1D) channel computes to 7.13 eV against an observed 8.57, the gap
        being vertical against adiabatic. So it is recorded as ``delta_e_eV``
        and the threshold is left unknown. `reactgen.audit` then checks any
        acquired onset against it rather than being told a guess is a fact.
        """

        out = []
        for species_id in sorted(frontier):
            parent = self.registry.species.get(species_id)
            if parent is None or not parent.is_neutral or parent.state.kind != "ground":
                continue
            whole = self.enthalpy.get(species_id)
            if whole is None or sum(parent.composition.values()) < 2:
                continue
            for heavy, light in fragments._bonds(dict(parent.composition), self.max_leaving):
                out += self._excited_pieces(species_id, whole, heavy, light)
                out += self._excited_pieces(species_id, whole, light, heavy)
        return out

    def _excited_pieces(
        self, parent_id: str, whole: float, part: dict[str, int], rest: dict[str, int]
    ) -> list[Reaction]:
        """Channels where ``part`` leaves in each level the registry knows for it."""

        piece, remainder = fragments.formula(part), fragments.formula(rest)
        ground = self.enthalpy.get(piece)
        other = self.enthalpy.get(remainder)
        if ground is None or other is None:
            return []
        bond = ground + other - whole
        out = []
        for excited_id, energy in self._levels_of(part):
            out.append(
                Reaction(
                    id=f"cand_{_slug(parent_id)}_diss_{_slug(excited_id)}",
                    family="electron",
                    type="dissociation",
                    reactants=[Term(ELECTRON), Term(parent_id)],
                    products=[Term(ELECTRON), Term(remainder), Term(excited_id)],
                    delta_e_eV=bond + energy,
                    status=CANDIDATE,
                    source=_provenance(
                        "dissociation_limit",
                        "energetic",
                        f"bond energy {bond:.2f} eV plus the {energy:.2f} eV level; "
                        "the thermodynamic limit, below any measured onset",
                    ),
                )
            )
        return out

    def _levels_of(self, composition: dict[str, int]) -> list[tuple[str, float]]:
        """Registered excited states of this formula, atom or molecule alike."""

        wanted = tuple(sorted(composition.items()))
        return sorted(
            (item.id, item.state.energy_eV)
            for item in self.registry.species.values()
            if item.state.kind == "excited"
            and item.state.energy_eV is not None
            and item.charge == 0
            and tuple(sorted(item.composition.items())) == wanted
        )

    def _relaxation(self, frontier: set[str], active: set[str]) -> list[Reaction]:
        """``AB_v + M -> AB + M``: a heavy collision takes the vibration away.

        The partner is written out rather than hidden behind a generic third
        body, because which one it is decides the rate by orders of magnitude —
        an oxygen atom drains N2's vibration far faster than argon does. That is
        a number for later, but the reaction it belongs to has to be in the list
        for anyone to attach it.

        Downhill by the vibrational quantum, so no screen applies: what is
        missing is the size of the step, not whether it happens.
        """

        touching = frontier | active
        out = []
        for excited_id in sorted(touching):
            excited = self.registry.species.get(excited_id)
            if excited is None or excited.state.label != "vibrational":
                continue
            ground = self.relations.ground_of(excited_id)
            if ground is None:
                continue
            for partner in sorted(touching):
                other = self.registry.species.get(partner)
                if other is None or not other.is_neutral or partner == excited_id:
                    continue
                out.append(
                    Reaction(
                        id=f"cand_{_slug(excited_id)}_{_slug(partner)}_vt",
                        family="neutral_neutral",
                        type="vibrational_relaxation",
                        reactants=[Term(excited_id), Term(partner)],
                        products=[Term(ground), Term(partner)],
                        threshold_eV=0.0,
                        delta_e_eV=_relaxation_energy(excited),
                        status=CANDIDATE,
                        source=_provenance(
                            "vibrational_manifold",
                            "structural",
                            "a heavy collision de-excites the manifold; the rate "
                            "depends strongly on which partner it is",
                        ),
                    )
                )
        return out

    def _collide(self, frontier: set[str], active: set[str]) -> list[Reaction]:
        """Every heavy-particle channel, from one rule rather than five.

        Charge transfer, dissociative transfer, ligand transfer, association and
        neutralization used to be five generators with five energy formulas.
        `discover.collide` enumerates the recombinations and screens them all on
        one enthalpy difference, which reproduces each of those formulas exactly.

        Endothermic channels are kept. This list tells DNT+ which cross sections
        to compute, and a channel with a threshold is precisely one to compute.
        """

        touching = sorted(frontier | active)
        energies = self._energies()
        out = []
        for first in touching:
            for second in touching:
                left, right = self._partner(first), self._partner(second)
                if left is None or right is None or left.charge == 0:
                    continue
                if right.charge != 0 and left.charge * right.charge > 0:
                    continue  # like charges do not meet at thermal energy
                out += self._from_channels(left, right, energies)
        return out

    # How far uphill to carry a channel. At 400 K the thermal energy is 0.034 eV,
    # so nothing 2 eV endothermic runs in the bulk; what reaches it is an ion
    # already accelerated in the presheath. A sheath study raises this
    # deliberately rather than getting the whole ladder by default.
    def _from_channels(
        self, left: collide.Partner, right: collide.Partner, energies: collide.Energies
    ) -> list[Reaction]:
        out = []
        for channel in collide.channels(left, right, energies, self.max_leaving):
            if channel.delta_h_eV is None or channel.delta_h_eV > self.max_endothermic_eV:
                continue
            kind = collide.classify(left, right, channel)
            if kind == "elastic":
                continue  # the pair's transport, not a chemical channel
            out.append(self._collision(left, right, channel, kind, energies))
        return out

    def _collision(
        self,
        left: collide.Partner,
        right: collide.Partner,
        channel: collide.Channel,
        kind: str,
        energies: collide.Energies,
    ) -> Reaction:
        products = [energies.written(piece) for piece in channel.products]
        family = "ion_ion" if right.charge else "ion_neutral"
        return Reaction(
            id=f"cand_{_slug(left.id)}_{_slug(right.id)}_{kind[:4]}_{_slug('_'.join(products))}",
            family=family,
            type=kind,
            reactants=[Term(left.id), Term(right.id)],
            products=[Term(name) for name in products],
            dnt_class=collide.dnt_class(channel, kind),
            threshold_eV=channel.threshold_eV,
            delta_e_eV=channel.delta_h_eV,
            status=CANDIDATE,
            source=_provenance(
                "formation_enthalpy",
                "energetic",
                f"delta H = {channel.delta_h_eV:+.2f} eV from formation enthalpies, "
                "with ion enthalpies built from the ionization energy",
            ),
        )

    def _partner(self, species_id: str) -> collide.Partner | None:
        item = self.registry.species.get(species_id)
        if item is None or not item.composition or item.id == ELECTRON:
            return None
        return collide.Partner(item.id, dict(item.composition), item.charge)

    def _energies(self) -> collide.Energies:
        return collide.Energies(
            self.enthalpy,
            self.ionization,
            self.affinity,
            {(key[0], key[1]): name for key, name in view.known(self.registry).items()},
        )

    def _keep_new(self, proposed: list[Reaction]) -> list[Reaction]:
        """One proposal per process.

        A channel can be reached two ways — transferring F, or transferring F2
        the other direction — and arrive at the same equation under a different
        id. Both would be counted, so the process, not the id, is what decides.
        """

        seen = set(self._registered_equations())
        fresh = []
        for item in proposed:
            key = item.signature
            if key in seen or not self._resolvable(item):
                continue
            seen.add(key)
            fresh.append(item)
        return fresh

    def _registered_equations(self) -> set[tuple]:
        """Proposing what the registry already states would double count it."""

        if self._equations is None:
            self._equations = {
                reaction.signature
                for channels in self.registry.channels.values()
                for reaction in channels
            }
        return self._equations

    def _binds_electron(self, species_id: str) -> bool:
        """Whether an anion of this species exists at all.

        A recorded negative affinity is a statement that it does not; no record
        is not, so an unmeasured species keeps its attachment candidate.
        """

        return self.affinity.get(species_id, 1.0) > 0

    def _penning(self, frontier: set[str], active: set[str]) -> list[Reaction]:
        """``M* + X -> M + X+ + e``: a metastable spends its energy ionizing."""

        touching = frontier | active
        out = []
        for excited_id in sorted(touching):
            excited = self.registry.species.get(excited_id)
            if excited is None or excited.state.kind != "excited":
                continue
            # Without the level energy there is nothing to weigh the target's
            # ionization against, so the channel cannot be screened at all.
            carried = excited.state.energy_eV
            if carried is None:
                continue
            ground = self.relations.ground_of(excited_id)
            for target in sorted(touching):
                ion = self.relations.cations().get(target)
                if ground is None or ion is None or target == ground:
                    continue
                energy = screen.penning_energy(carried, target, self.ionization)
                if screen.neutral_verdict(energy) != "open":
                    continue
                out.append(
                    Reaction(
                        id=f"cand_{_slug(excited_id)}_{_slug(target)}_penning",
                        family="neutral_neutral",
                        type="penning_ionization",
                        reactants=[Term(excited_id), Term(target)],
                        products=[Term(ground), Term(ion), Term(ELECTRON)],
                        delta_e_eV=energy,
                        status=CANDIDATE,
                        source=_provenance(
                            "excitation_versus_ionization_energy",
                            "energetic",
                            f"the metastable carries {carried:.2f} eV, "
                            f"more than the {self.ionization.get(target, 0):.2f} eV needed",
                        ),
                    )
                )
        return out

    def _transfers(self, radical: str, partner: str) -> list[Reaction]:
        species = self.registry.species
        out = []
        for heavy, light in fragments._bonds(dict(species[partner].composition)):
            taken = fragments.formula(light)
            grown = fragments.formula(_merge(species[radical].composition, light))
            rest = fragments.formula(heavy)
            energy = screen.reaction_energy([radical, partner], [grown, rest], self.enthalpy)
            if screen.neutral_verdict(energy) != "open":
                continue
            out.append(
                Reaction(
                    id=f"cand_{_slug(radical)}_{_slug(partner)}_transfer_{_slug(taken)}",
                    family="neutral_neutral",
                    type="abstraction",
                    reactants=[Term(radical), Term(partner)],
                    products=[Term(grown), Term(rest)],
                    delta_e_eV=energy,
                    status=CANDIDATE,
                    source=_provenance(
                        "formation_enthalpy_difference",
                        "energetic",
                        f"exothermic by {abs(energy or 0):.2f} eV. Unlike an ion-molecule "
                        "reaction this may still carry an activation barrier, so open "
                        "here means possible, not fast",
                    ),
                )
            )
        return out

    # ----------------------------------------------------------------- layers

    def _electron(self, frontier: set[str]) -> list[Reaction]:
        """Every neutral on the frontier gets the channels its formula allows."""

        # One index, and it prefers the ground state. Built fresh each pass
        # because invented species join the registry as they are proposed.
        known = view.known(self.registry)
        out = []
        for species_id in sorted(frontier):
            species = self._species().get(species_id)
            if species is None or not species.is_neutral:
                continue
            for candidate in fragments.electron_channels(
                species_id,
                dict(species.composition),
                known,
                max_charge=self.max_ion_charge,
                excitation=self._excitation_for(species),
                electronic=not self.relations.has_excited(species_id),
                level_energy=self.levels.get(species_id),
                max_leaving=self.max_leaving,
                binds_electron=self._binds_electron(species_id),
            ):
                out.append(self._reaction("electron", candidate.type, candidate))
        return out

    def _excitation_for(self, species: Species) -> str:
        """How this species may be excited, if at all.

        The registry's own state is what decides, not the shape of the name:
        ``Ar_4s`` reads as a ground-state name and would otherwise be excited a
        second time into an ``Ar_4s*`` that does not exist.
        """

        return "none" if species.state.kind != "ground" else self.excitation

    def _reaction(self, family: str, kind: str, candidate: fragments.Candidate) -> Reaction:
        return Reaction(
            id=f"cand_{_slug(candidate.equation)}",
            family=family,
            type=kind,
            reactants=[Term(name) for name in candidate.reactants],
            products=[Term(name) for name in candidate.products],
            threshold_eV=candidate.threshold_eV
            if candidate.threshold_eV is not None
            else FREE.get(kind),
            status=CANDIDATE,
            source=_provenance(
                "bond_breaking",
                "structural",
                "conservation allows this channel; no source has been consulted",
            ),
        )

    def _resolvable(self, reaction: Reaction) -> bool:
        """Invent whatever species the channel needs, or drop the channel.

        An invented species goes straight into the registry the caller handed
        us, because the conservation check runs against that dictionary and a
        species it cannot see would reject its own reaction.
        """

        for term in (*reaction.reactants, *reaction.products):
            if term.species in self.registry.species:
                continue
            invented = _species_from(term.species, self._level_of(term.species))
            if invented is None:
                return False
            invented = self._inherit(invented)
            self.invented[term.species] = invented
            self.registry.species[term.species] = invented
        return True

    def _level_of(self, written: str) -> float | None:
        """The energy of an excited species this proposer is about to invent.

        It is recorded against the ground-state atom, because that is what
        existed when `acquire asd` ran, so the suffix that named the species is
        what leads back to it.
        """

        kind = _excited_kind(written)
        if kind is None:
            return None
        parent = written[: -len(SUFFIX[kind])]
        if kind == "vibrational":
            # Fitted from the parent's heat capacity, not read off a spectrum.
            return self.vibration.get(parent)
        return self.levels.get(parent, {}).get(kind)

    def _inherit(self, invented: Species) -> Species:
        """Give an invented state the properties of the substance it is a state of.

        `SF4_v` is sulfur tetrafluoride, so it has SF4's mass and size. Without
        this a proposed state reaches the output carrying nothing at all -- not
        even a mass, which no collision rate can be formed without.
        """

        carried: dict = {}
        mass = derive.mass_of(invented.composition, invented.charge, self._element_masses())
        if mass is not None:
            carried["mass_amu"] = Property(
                value=mass,
                unit="amu",
                source="sum of atomic masses in the registry, less the electron mass",
            )
        if invented.state.kind == "ground":
            return replace(invented, properties={**carried, **invented.properties})
        key = (tuple(sorted(invented.composition.items())), invented.charge)
        for candidate in self.registry.species.values():
            if candidate.state.kind != "ground":
                continue
            if (tuple(sorted(candidate.composition.items())), candidate.charge) != key:
                continue
            carried |= derive.carried_from(candidate, invented.state.energy_eV)
            break
        return replace(invented, properties={**carried, **invented.properties})

    def _element_masses(self) -> dict[str, float]:
        if self._elements is None:
            self._elements = derive.element_masses(self.registry)
        return self._elements

    def _species(self) -> dict[str, Species]:
        return self.registry.species


def _provenance(basis: str, confidence: str, why: str) -> dict[str, str]:
    """Why a candidate is being offered, and how far it can be trusted."""

    return {"source_type": basis, "confidence": confidence, "citation": why}


def _relaxation_energy(excited: Species) -> float | None:
    """Downhill by the quantum, where the level energy is known."""

    energy = excited.state.energy_eV
    return None if energy is None else -energy


def _species_from(written: str, energy_eV: float | None = None) -> Species | None:
    """A species the formula alone defines, marked as the guess it is.

    A lumped excited state declares itself as such, so `reactgen.audit` will
    refuse to let it sit beside the resolved levels it stands for.
    """

    parsed = naming.parse(written)
    if not parsed.composition:
        return None
    kind = _excited_kind(written)
    if kind is None:
        return Species(
            id=written,
            composition=dict(parsed.composition),
            charge=parsed.charge,
            classes=frozenset({CANDIDATE}),
            status=CANDIDATE,
        )
    return Species(
        id=written,
        composition=dict(parsed.composition),
        charge=parsed.charge,
        classes=frozenset({CANDIDATE, "excited", kind}),
        state=State(kind="excited", label=kind, energy_eV=energy_eV, resolution="lumped"),
        status=CANDIDATE,
    )


# The suffix each kind of invented excited species is written with. Vibrational
# is here too: `N2_v` is an excited state, and leaving it out let one be created
# as though it were a ground state.
SUFFIX = {"metastable": "_meta", "resonant": "_res", "vibrational": "_v", "lumped": "*"}


def _excited_kind(written: str) -> str | None:
    """What an invented excited species is, from the suffix that named it."""

    for kind, suffix in SUFFIX.items():
        if written.endswith(suffix):
            return kind
    return None


# Every invented excited species stands for several real levels — X* for all of
# them, X_m for the metastable ones — so none is ever state_resolved. Registering
# a real level beside one is a double count, and `reactgen.audit` says so.


def _merge(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left)
    for element, count in right.items():
        merged[element] = merged.get(element, 0) + count
    return merged


def _slug(text: str) -> str:
    for old, new in ((" -> ", "_to_"), (" + ", "_"), ("+", "p"), ("-", "m"), (" ", "")):
        text = text.replace(old, new)
    return text
