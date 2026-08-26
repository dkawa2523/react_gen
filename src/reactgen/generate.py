"""Generate plasma-chemistry candidates from formulas alone.

This is the only network-growth implementation.  It has no Registry, file,
thermochemistry or kinetics dependency; those questions are answered after the
mechanical set exists.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from itertools import combinations

from reactgen import naming
from reactgen.case import Limits
from reactgen.chemistry import (
    bond_exchanges,
    bond_splits,
    candidate_state,
    electron_state,
    formula,
    is_atom,
    is_noble,
    is_noble_ligand_complex,
    leaving_products,
    ligand_transfers,
    neutral_reactive_candidate,
)
from reactgen.model import (
    ELECTRON,
    CandidateSet,
    ReactionCandidate,
    ReactionKey,
    StateCandidate,
    StateKey,
    Term,
    reaction_id,
)

EXCITED_KINDS = frozenset({"vibrational", "electronic", "metastable", "resonant"})


class _LimitReached(RuntimeError):
    pass


def candidates(
    gases: tuple[str, ...],
    limits: Limits | None = None,
) -> CandidateSet:
    """Return the deterministic mechanical closure for neutral formula seeds."""

    limits = limits or Limits()
    if not gases:
        raise ValueError("gases must list at least one neutral chemical formula")
    parsed: list[tuple[str, dict[str, int]]] = []
    for written in gases:
        if not isinstance(written, str):
            raise ValueError("every input gas must be a chemical-formula string")
        name = naming.parse(written)
        if not name.composition:
            raise ValueError(f"input gas is not a chemical formula: {written}")
        if name.charge or name.state or name.excited:
            raise ValueError(f"input gas must be a neutral ground-state formula: {written}")
        parsed.append((formula(name.composition), name.composition))
    return _Generator(limits).run(parsed)


class _Generator:
    """A small stateful frontier walk around otherwise pure template functions."""

    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.result = CandidateSet(
            limits={
                "max_depth": limits.max_depth,
                "max_species": limits.max_species,
                "max_reactions": limits.max_reactions,
                "max_charge_abs": limits.max_charge_abs,
                "max_leaving_atoms": limits.max_leaving_atoms,
            }
        )
        self._state_keys: dict[StateKey, str] = {}
        self._reaction_keys: set[ReactionKey] = set()
        self._new_states: set[str] = set()
        self.feed: set[str] = set()

    def run(self, gases: list[tuple[str, dict[str, int]]]) -> CandidateSet:
        self._add_state(electron_state())
        for _written, composition in sorted(gases):
            classes = {"feed", "neutral"}
            if neutral_reactive_candidate(composition):
                classes.add("reactive_candidate")
            state = candidate_state(
                composition,
                0,
                "ground",
                resolution="resolved",
                classes=frozenset(classes),
                introduced_by=("input",),
            )
            self.feed.add(self._add_state(state))

        active = set(self.result.states)
        frontier = set(self.feed)
        try:
            for depth in range(1, self.limits.max_depth + 1):
                if not frontier:
                    break
                self._new_states = set()
                snapshot = tuple(
                    self.result.states[state_id]
                    for state_id in sorted(active)
                    if state_id != ELECTRON
                )
                self._electron(frontier, depth)
                self._ion(frontier, snapshot, depth)
                self._neutral(frontier, snapshot, depth)
                discovered = self._new_states - active
                if not discovered:
                    frontier = set()
                    break
                active.update(discovered)
                frontier = discovered
                if depth == self.limits.max_depth:
                    self._truncate(f"max_depth={self.limits.max_depth}")
        except _LimitReached as error:
            self._truncate(str(error))
        return self.result

    def _truncate(self, reason: str) -> None:
        self.result.complete = False
        self.result.stop_reason = reason

    def _add_state(self, state: StateCandidate) -> str:
        existing = self._state_keys.get(state.key)
        if existing is not None:
            current = self.result.states[existing]
            merged = replace(
                current,
                classes=current.classes | state.classes,
                depth=min(current.depth, state.depth),
                introduced_by=tuple(sorted(set(current.introduced_by) | set(state.introduced_by))),
            )
            self.result.states[existing] = merged
            return existing
        if len(self.result.states) >= self.limits.max_species:
            raise _LimitReached(f"max_species={self.limits.max_species}")
        self.result.states[state.id] = state
        self._state_keys[state.key] = state.id
        self._new_states.add(state.id)
        return state.id

    def _state(
        self,
        composition: dict[str, int],
        charge: int,
        kind: str,
        depth: int,
        rule: str,
        *,
        label: str = "",
        resolution: str = "lumped",
        classes: frozenset[str] = frozenset(),
    ) -> str:
        if abs(charge) > self.limits.max_charge_abs:
            raise ValueError(f"charge outside generation grammar: {charge}")
        base_classes = {"neutral"} if charge == 0 else {"ion", "cation" if charge > 0 else "anion"}
        if charge == 0 and kind == "ground" and neutral_reactive_candidate(composition):
            base_classes.add("reactive_candidate")
        return self._add_state(
            candidate_state(
                composition,
                charge,
                kind,
                label=label,
                resolution=resolution,
                classes=frozenset(base_classes) | classes,
                depth=depth,
                introduced_by=(rule,),
            )
        )

    def _ground(
        self,
        composition: dict[str, int],
        charge: int,
        depth: int,
        rule: str,
        *,
        classes: frozenset[str] = frozenset(),
    ) -> str:
        return self._state(
            composition,
            charge,
            "ground",
            depth,
            rule,
            resolution="resolved",
            classes=classes,
        )

    def _reaction(
        self,
        family: str,
        process: str,
        reactants: tuple[str, ...],
        products: tuple[str, ...],
        depth: int,
        rule: str,
        *,
        third_body: str | None = None,
        kinetic_effects: tuple[str, ...] = (),
    ) -> None:
        candidate = ReactionCandidate(
            id="",
            reactants=_terms(reactants),
            products=_terms(products),
            family=family,
            process=process,
            origin="mechanical",
            generation_rule=rule,
            depth=depth,
            third_body=third_body,
            kinetic_effects=kinetic_effects,
        )
        key = candidate.key
        if key in self._reaction_keys:
            return
        if len(self.result.reactions) >= self.limits.max_reactions:
            raise _LimitReached(f"max_reactions={self.limits.max_reactions}")
        candidate = replace(candidate, id=reaction_id(key))
        self.result.reactions[candidate.id] = candidate
        self._reaction_keys.add(key)

    # Electron templates -----------------------------------------------------

    def _electron(self, frontier: set[str], depth: int) -> None:
        for state_id in sorted(frontier):
            if state_id == ELECTRON:
                continue
            target = self.result.states[state_id]
            self._reaction(
                "electron",
                "elastic",
                (ELECTRON, state_id),
                (ELECTRON, state_id),
                depth,
                "electron.elastic.v1",
                kinetic_effects=("momentum_transfer",),
            )
            if target.charge == 0:
                self._electron_neutral(target, depth)
            elif target.charge > 0:
                self._electron_cation(target, depth)
            else:
                self._electron_anion(target, depth)

    def _electron_neutral(self, target: StateCandidate, depth: int) -> None:
        inherited = target.classes & {"fragment", "rearranged"}
        cation = self._ground(
            target.composition,
            1,
            depth,
            "electron.ionization.v1",
            classes=inherited,
        )
        self._reaction(
            "electron",
            "ionization",
            (ELECTRON, target.id),
            (ELECTRON, ELECTRON, cation),
            depth,
            "electron.ionization.v1",
        )

        if target.state.kind != "ground":
            ground = self._ground(
                target.composition,
                0,
                depth,
                "electron.deexcitation.v1",
                classes=target.classes - {"excited"},
            )
            self._reaction(
                "electron",
                "deexcitation",
                (ELECTRON, target.id),
                (ELECTRON, ground),
                depth,
                "electron.deexcitation.v1",
            )
            return

        anion = self._ground(
            target.composition,
            -1,
            depth,
            "electron.attachment.v1",
            classes=inherited,
        )
        self._reaction(
            "electron",
            "attachment",
            (ELECTRON, target.id),
            (anion,),
            depth,
            "electron.attachment.v1",
        )

        if not target.classes.intersection({"fragment", "rearranged"}):
            for excited in self._excited_states(target, depth):
                self._reaction(
                    "electron",
                    "excitation",
                    (ELECTRON, target.id),
                    (ELECTRON, excited),
                    depth,
                    "electron.excitation.v1",
                )

        for heavy, leaving in bond_splits(
            target.composition,
            self.limits.max_leaving_atoms,
        ):
            neutral_products = [
                self._ground(
                    heavy,
                    0,
                    depth,
                    "electron.dissociation.v1",
                    classes=frozenset({"fragment"}),
                )
            ]
            neutral_products += [
                self._ground(
                    part,
                    0,
                    depth,
                    "electron.dissociation.v1",
                    classes=frozenset({"fragment"}),
                )
                for part in leaving_products(leaving)
            ]
            self._reaction(
                "electron",
                "dissociation",
                (ELECTRON, target.id),
                (ELECTRON, *neutral_products),
                depth,
                "electron.dissociation.v1",
            )
            self._reaction(
                "neutral",
                "three_body_association",
                tuple(neutral_products),
                (target.id,),
                depth,
                "neutral.reverse_dissociation.v1",
                third_body="M",
            )

            cation = self._ground(
                heavy,
                1,
                depth,
                "electron.dissociative_ionization.v1",
                classes=frozenset({"fragment"}),
            )
            self._reaction(
                "electron",
                "dissociative_ionization",
                (ELECTRON, target.id),
                (ELECTRON, ELECTRON, cation, *neutral_products[1:]),
                depth,
                "electron.dissociative_ionization.v1",
            )

            anion = self._ground(
                heavy,
                -1,
                depth,
                "electron.dissociative_attachment.v1",
                classes=frozenset({"fragment"}),
            )
            self._reaction(
                "electron",
                "dissociative_attachment",
                (ELECTRON, target.id),
                (anion, *neutral_products[1:]),
                depth,
                "electron.dissociative_attachment.v1",
            )
            leaving_parts = leaving_products(leaving)
            if leaving_parts:
                neutral_heavy = self._ground(
                    heavy,
                    0,
                    depth,
                    "electron.dissociative_attachment.v1",
                    classes=frozenset({"fragment"}),
                )
                leaving_anion = self._ground(
                    leaving_parts[0],
                    -1,
                    depth,
                    "electron.dissociative_attachment.v1",
                    classes=frozenset({"fragment"}),
                )
                remaining = [
                    self._ground(
                        part,
                        0,
                        depth,
                        "electron.dissociative_attachment.v1",
                        classes=frozenset({"fragment"}),
                    )
                    for part in leaving_parts[1:]
                ]
                self._reaction(
                    "electron",
                    "dissociative_attachment",
                    (ELECTRON, target.id),
                    (neutral_heavy, leaving_anion, *remaining),
                    depth,
                    "electron.dissociative_attachment.v1",
                )

    def _excited_states(self, target: StateCandidate, depth: int) -> list[str]:
        classes = target.classes - {"feed"} | {"excited"}
        if not is_atom(target.composition):
            return [
                self._state(
                    target.composition,
                    0,
                    "vibrational",
                    depth,
                    "electron.excitation.v1",
                    classes=classes,
                ),
                self._state(
                    target.composition,
                    0,
                    "electronic",
                    depth,
                    "electron.excitation.v1",
                    classes=classes,
                ),
            ]
        if is_noble(target.composition):
            return [
                self._state(
                    target.composition,
                    0,
                    "metastable",
                    depth,
                    "electron.excitation.v1",
                    classes=classes,
                ),
                self._state(
                    target.composition,
                    0,
                    "resonant",
                    depth,
                    "electron.excitation.v1",
                    classes=classes,
                ),
            ]
        return [
            self._state(
                target.composition,
                0,
                "electronic",
                depth,
                "electron.excitation.v1",
                classes=classes,
            )
        ]

    def _electron_cation(self, ion: StateCandidate, depth: int) -> None:
        if "complex_ion" not in ion.classes:
            parent = self._ground(
                ion.composition,
                0,
                depth,
                "electron.recombination.v1",
                classes=ion.classes & {"fragment", "rearranged"},
            )
            self._reaction(
                "electron",
                "recombination",
                (ELECTRON, ion.id),
                (parent,),
                depth,
                "electron.recombination.v1",
            )
        for heavy, leaving in bond_splits(ion.composition, self.limits.max_leaving_atoms):
            products = [
                self._ground(
                    heavy,
                    0,
                    depth,
                    "electron.dissociative_recombination.v1",
                    classes=frozenset({"fragment"}),
                )
            ]
            products += [
                self._ground(
                    part,
                    0,
                    depth,
                    "electron.dissociative_recombination.v1",
                    classes=frozenset({"fragment"}),
                )
                for part in leaving_products(leaving)
            ]
            self._reaction(
                "electron",
                "dissociative_recombination",
                (ELECTRON, ion.id),
                tuple(products),
                depth,
                "electron.dissociative_recombination.v1",
            )

    def _electron_anion(self, ion: StateCandidate, depth: int) -> None:
        if "complex_ion" in ion.classes:
            for heavy, leaving in bond_splits(
                ion.composition,
                self.limits.max_leaving_atoms,
            ):
                fragments = [
                    self._ground(
                        part,
                        0,
                        depth,
                        "electron.dissociative_detachment.v1",
                        classes=frozenset({"fragment"}),
                    )
                    for part in (heavy, *leaving_products(leaving))
                ]
                self._reaction(
                    "electron",
                    "dissociative_detachment",
                    (ELECTRON, ion.id),
                    (ELECTRON, ELECTRON, *fragments),
                    depth,
                    "electron.dissociative_detachment.v1",
                )
            return
        parent = self._ground(
            ion.composition,
            0,
            depth,
            "electron.detachment.v1",
            classes=ion.classes & {"fragment", "rearranged"},
        )
        self._reaction(
            "electron",
            "detachment",
            (ELECTRON, ion.id),
            (ELECTRON, ELECTRON, parent),
            depth,
            "electron.detachment.v1",
        )

    # Ion templates ----------------------------------------------------------

    def _ion(self, frontier: set[str], snapshot: tuple[StateCandidate, ...], depth: int) -> None:
        ions = [
            item
            for item in snapshot
            if item.charge and item.state.kind == "ground" and item.id != ELECTRON
        ]
        neutrals = [item for item in snapshot if item.charge == 0]
        for ion in ions:
            for neutral in neutrals:
                if ion.id not in frontier and neutral.id not in frontier:
                    continue
                if not (
                    "feed" in neutral.classes
                    or ion.composition == neutral.composition
                    or self._reactive_neutral(neutral)
                ):
                    continue
                self._ion_neutral(ion, neutral, snapshot, frontier, depth)

        for left, right in combinations(ions, 2):
            if left.id not in frontier and right.id not in frontier:
                continue
            if left.charge * right.charge >= 0:
                continue
            left_products = self._neutralized_products(left, depth)
            right_products = self._neutralized_products(right, depth)
            self._reaction(
                "ion",
                "mutual_neutralization",
                (left.id, right.id),
                (*left_products, *right_products),
                depth,
                "ion.mutual_neutralization.v1",
                kinetic_effects=("fast_product",),
            )

    def _ion_neutral(
        self,
        ion: StateCandidate,
        neutral: StateCandidate,
        snapshot: tuple[StateCandidate, ...],
        frontier: set[str],
        depth: int,
    ) -> None:
        if neutral.state.kind != "ground":
            ground = self._ground(
                neutral.composition,
                0,
                depth,
                "ion.deexcitation.v1",
                classes=neutral.classes - {"excited"},
            )
            self._reaction(
                "ion",
                "ion_induced_deexcitation",
                (ion.id, neutral.id),
                (ion.id, ground),
                depth,
                "ion.deexcitation.v1",
            )
            return

        if "complex_ion" in ion.classes:
            self._complex_ion_collision(ion, neutral, depth)
            return

        ion_parent = self._ground(
            ion.composition,
            0,
            depth,
            "ion.charge_exchange.v1",
            classes=ion.classes & {"fragment", "rearranged"},
        )
        product_ion = self._ground(
            neutral.composition,
            ion.charge,
            depth,
            "ion.charge_exchange.v1",
            classes=neutral.classes & {"fragment", "rearranged"},
        )
        resonant = ion.composition == neutral.composition
        if resonant:
            self._reaction(
                "ion",
                "resonant_charge_exchange",
                (ion.id, neutral.id),
                (ion_parent, product_ion),
                depth,
                "ion.charge_exchange.v1",
                kinetic_effects=("momentum_transfer", "fast_product"),
            )
        else:
            self._reaction(
                "ion",
                "elastic",
                (ion.id, neutral.id),
                (ion.id, neutral.id),
                depth,
                "ion.elastic.v1",
                kinetic_effects=("momentum_transfer", "fast_product"),
            )
            self._reaction(
                "ion",
                "charge_exchange",
                (ion.id, neutral.id),
                (ion_parent, product_ion),
                depth,
                "ion.charge_exchange.v1",
                kinetic_effects=("fast_product",),
            )

        for excited in snapshot:
            if (
                excited.charge == 0
                and excited.composition == neutral.composition
                and excited.state.kind in EXCITED_KINDS
            ):
                self._reaction(
                    "ion",
                    "ion_induced_excitation",
                    (ion.id, neutral.id),
                    (ion.id, excited.id),
                    depth,
                    "ion.excitation.v1",
                )

        if ion.charge < 0:
            self._reaction(
                "ion",
                "collisional_detachment",
                (ion.id, neutral.id),
                (ion_parent, neutral.id, ELECTRON),
                depth,
                "ion.detachment.v1",
            )

        self._ion_dissociation(
            ion,
            neutral,
            ion_parent,
            depth,
            split_target=neutral.id in frontier,
            split_projectile=ion.id in frontier,
        )
        if ion.id in frontier and "feed" in neutral.classes and "rearranged" not in ion.classes:
            self._ion_transfer(ion, neutral, depth)

    def _ion_dissociation(
        self,
        ion: StateCandidate,
        neutral: StateCandidate,
        ion_parent: str,
        depth: int,
        *,
        split_target: bool,
        split_projectile: bool,
    ) -> None:
        neutral_splits = (
            bond_splits(neutral.composition, self.limits.max_leaving_atoms) if split_target else []
        )
        for heavy, leaving in neutral_splits:
            neutral_fragments = [
                self._ground(
                    heavy,
                    0,
                    depth,
                    "ion.collision_induced_dissociation.v1",
                    classes=frozenset({"fragment"}),
                )
            ]
            neutral_fragments += [
                self._ground(
                    part,
                    0,
                    depth,
                    "ion.collision_induced_dissociation.v1",
                    classes=frozenset({"fragment"}),
                )
                for part in leaving_products(leaving)
            ]
            self._reaction(
                "ion",
                "collision_induced_dissociation",
                (ion.id, neutral.id),
                (ion.id, *neutral_fragments),
                depth,
                "ion.collision_induced_dissociation.v1",
                kinetic_effects=("fast_product",),
            )
            charged = self._ground(
                heavy,
                ion.charge,
                depth,
                "ion.dissociative_charge_transfer.v1",
                classes=frozenset({"fragment"}),
            )
            self._reaction(
                "ion",
                "dissociative_charge_transfer",
                (ion.id, neutral.id),
                (ion_parent, charged, *neutral_fragments[1:]),
                depth,
                "ion.dissociative_charge_transfer.v1",
                kinetic_effects=("fast_product",),
            )

        ion_splits = (
            bond_splits(ion.composition, self.limits.max_leaving_atoms) if split_projectile else []
        )
        for heavy, leaving in ion_splits:
            charged = self._ground(
                heavy,
                ion.charge,
                depth,
                "ion.projectile_dissociation.v1",
                classes=frozenset({"fragment"}),
            )
            fragments = [
                self._ground(
                    part,
                    0,
                    depth,
                    "ion.projectile_dissociation.v1",
                    classes=frozenset({"fragment"}),
                )
                for part in leaving_products(leaving)
            ]
            self._reaction(
                "ion",
                "projectile_dissociation",
                (ion.id, neutral.id),
                (charged, *fragments, neutral.id),
                depth,
                "ion.projectile_dissociation.v1",
                kinetic_effects=("fast_product",),
            )

    def _ion_transfer(
        self,
        ion: StateCandidate,
        neutral: StateCandidate,
        depth: int,
    ) -> None:
        for remainder, moved in ligand_transfers(
            neutral.composition,
            ion.composition,
            charged_acceptor=True,
        ):
            neutral_product = self._ground(
                remainder,
                0,
                depth,
                "ion.ligand_transfer.v1",
                classes=frozenset({"fragment", "rearranged"}),
            )
            ion_product = self._ground(
                moved,
                ion.charge,
                depth,
                "ion.ligand_transfer.v1",
                classes=(
                    frozenset({"rearranged", "complex_ion"})
                    if is_noble_ligand_complex(moved)
                    else frozenset({"rearranged"})
                ),
            )
            self._reaction(
                "ion",
                "ligand_transfer",
                (ion.id, neutral.id),
                (neutral_product, ion_product),
                depth,
                "ion.ligand_transfer.v1",
                kinetic_effects=("fast_product",),
            )

        for ion_composition, neutral_composition in bond_exchanges(
            ion.composition,
            neutral.composition,
        ):
            ion_product = self._ground(
                ion_composition,
                ion.charge,
                depth,
                "ion.reactive_scattering.v1",
                classes=frozenset({"rearranged"}),
            )
            neutral_product = self._ground(
                neutral_composition,
                0,
                depth,
                "ion.reactive_scattering.v1",
                classes=frozenset({"rearranged"}),
            )
            self._reaction(
                "ion",
                "reactive_scattering",
                (ion.id, neutral.id),
                (ion_product, neutral_product),
                depth,
                "ion.reactive_scattering.v1",
                kinetic_effects=("fast_product",),
            )

        for ion_remainder, moved in ligand_transfers(ion.composition, neutral.composition):
            ion_product = self._ground(
                ion_remainder,
                ion.charge,
                depth,
                "ion.ligand_transfer.v1",
                classes=frozenset({"rearranged"}),
            )
            neutral_product = self._ground(
                moved,
                0,
                depth,
                "ion.ligand_transfer.v1",
                classes=frozenset({"fragment", "rearranged"}),
            )
            self._reaction(
                "ion",
                "ligand_transfer",
                (ion.id, neutral.id),
                (ion_product, neutral_product),
                depth,
                "ion.ligand_transfer.v1",
                kinetic_effects=("fast_product",),
            )

    def _neutralized_products(self, ion: StateCandidate, depth: int) -> tuple[str, ...]:
        if "complex_ion" not in ion.classes:
            return (
                self._ground(
                    ion.composition,
                    0,
                    depth,
                    "ion.mutual_neutralization.v1",
                    classes=ion.classes & {"fragment", "rearranged"},
                ),
            )
        splits = bond_splits(ion.composition, self.limits.max_leaving_atoms)
        if not splits:
            return ()
        heavy, leaving = splits[0]
        return tuple(
            self._ground(
                part,
                0,
                depth,
                "ion.dissociative_neutralization.v1",
                classes=frozenset({"fragment"}),
            )
            for part in (heavy, *leaving_products(leaving))
        )

    def _complex_ion_collision(
        self,
        ion: StateCandidate,
        neutral: StateCandidate,
        depth: int,
    ) -> None:
        """Collide an ion complex without inventing its unbound neutral parent."""

        self._reaction(
            "ion",
            "elastic",
            (ion.id, neutral.id),
            (ion.id, neutral.id),
            depth,
            "ion.complex_elastic.v1",
            kinetic_effects=("momentum_transfer",),
        )
        for heavy, leaving in bond_splits(ion.composition, self.limits.max_leaving_atoms):
            neutral_fragments = [
                self._ground(
                    part,
                    0,
                    depth,
                    "ion.complex_dissociation.v1",
                    classes=frozenset({"fragment"}),
                )
                for part in (heavy, *leaving_products(leaving))
            ]
            product_ion = self._ground(
                neutral.composition,
                ion.charge,
                depth,
                "ion.dissociative_charge_transfer.v1",
                classes=neutral.classes & {"fragment", "rearranged"},
            )
            self._reaction(
                "ion",
                "dissociative_charge_transfer",
                (ion.id, neutral.id),
                (*neutral_fragments, product_ion),
                depth,
                "ion.dissociative_charge_transfer.v1",
                kinetic_effects=("fast_product",),
            )
            if ion.charge < 0:
                self._reaction(
                    "ion",
                    "collisional_detachment",
                    (ion.id, neutral.id),
                    (*neutral_fragments, neutral.id, ELECTRON),
                    depth,
                    "ion.complex_detachment.v1",
                )

    # Neutral templates ------------------------------------------------------

    def _neutral(
        self,
        frontier: set[str],
        snapshot: tuple[StateCandidate, ...],
        depth: int,
    ) -> None:
        neutrals = [item for item in snapshot if item.charge == 0]
        for left, right in combinations(neutrals, 2):
            if left.id not in frontier and right.id not in frontier:
                continue
            if not self._eligible_neutral_pair(left, right):
                continue
            self._neutral_pair(left, right, depth)

    def _eligible_neutral_pair(self, left: StateCandidate, right: StateCandidate) -> bool:
        if left.state.kind in EXCITED_KINDS or right.state.kind in EXCITED_KINDS:
            return True
        left_active = self._reactive_neutral(left)
        right_active = self._reactive_neutral(right)
        left_partner = bool(left.classes & {"feed", "fragment"}) or left_active
        right_partner = bool(right.classes & {"feed", "fragment"}) or right_active
        return (left_active and right_partner) or (right_active and left_partner)

    @staticmethod
    def _reactive_neutral(state: StateCandidate) -> bool:
        return "reactive_candidate" in state.classes and (
            "rearranged" not in state.classes or "fragment" in state.classes
        )

    def _neutral_pair(
        self,
        left: StateCandidate,
        right: StateCandidate,
        depth: int,
    ) -> None:
        for excited, collider in ((left, right), (right, left)):
            if excited.state.kind not in EXCITED_KINDS:
                continue
            ground = self._ground(
                excited.composition,
                0,
                depth,
                "neutral.relaxation.v1",
                classes=excited.classes - {"excited"},
            )
            process = "v_t_relaxation" if excited.state.kind == "vibrational" else "quenching"
            self._reaction(
                "neutral",
                process,
                (excited.id, collider.id),
                (ground, collider.id),
                depth,
                f"neutral.{process}.v1",
            )
            if (
                excited.state.kind in {"metastable", "electronic"}
                and collider.state.kind == "ground"
            ):
                ion = self._ground(
                    collider.composition,
                    1,
                    depth,
                    "neutral.penning_ionization.v1",
                )
                self._reaction(
                    "neutral",
                    "penning_ionization",
                    (excited.id, collider.id),
                    (ground, ion, ELECTRON),
                    depth,
                    "neutral.penning_ionization.v1",
                )

        reactive = self._reactive_neutral(left) or self._reactive_neutral(right)
        if not reactive:
            return
        for donor, acceptor in ((left, right), (right, left)):
            for remainder, moved in ligand_transfers(donor.composition, acceptor.composition):
                process = "radical_abstraction"
                first = self._ground(
                    remainder,
                    0,
                    depth,
                    f"neutral.{process}.v1",
                    classes=frozenset({"fragment", "rearranged"}),
                )
                second = self._ground(
                    moved,
                    0,
                    depth,
                    f"neutral.{process}.v1",
                    classes=frozenset({"rearranged"}),
                )
                self._reaction(
                    "neutral",
                    process,
                    (left.id, right.id),
                    (first, second),
                    depth,
                    f"neutral.{process}.v1",
                )


def _terms(species_ids: tuple[str, ...]) -> tuple[Term, ...]:
    counts = Counter(species_ids)
    return tuple(
        Term(species, float(counts[species]))
        for species in sorted(counts, key=lambda item: (item != ELECTRON, item))
    )
