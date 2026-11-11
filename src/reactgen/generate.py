"""Bounded reaction hypotheses over one shared particle-state worklist.

Inventory operations do not assert structures or mechanisms. Explicit SMILES
use the optional graph recipes; evidence selection and energetic judgements
remain downstream. Added source states return through the same worklist.
"""

from __future__ import annotations

from collections import ChainMap, Counter, deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from heapq import heappop, heappush
from itertools import product

from reactgen.balance import conservation, declares_nuclides, retained_nuclide_correspondence
from reactgen.case import Case, Limits, RequestedReaction
from reactgen.chemistry import (
    candidate_state,
    composition_groups,
    composition_partitions,
    electron_partition_process,
    electron_state,
    is_atom,
    is_noble,
    merge,
    subtract,
)
from reactgen.model import (
    ELECTRON,
    CandidateSet,
    ReactionCandidate,
    StateCandidate,
    StateKey,
    Term,
    combine_transformations,
    reaction_id,
)
from reactgen.structure import (
    StructureUnavailable,
    charge_target_correspondence,
    fragment_edits,
    pair_edits,
    physical_state_key,
    resonant_charge_correspondence,
    structure_key,
)


@dataclass(frozen=True)
class _Proposal:
    family: str
    process: str
    reactants: tuple[str, ...]
    products: tuple[StateCandidate, ...]
    depth: int
    transformation: dict
    stabilization: str | None = None


class _LimitReached(RuntimeError):
    pass


SourceChannel = tuple[ReactionCandidate, dict[str, StateCandidate]]


def candidates(
    gases: tuple[str, ...],
    limits: Limits | None = None,
    *,
    supplies: tuple[str, ...] = (),
    structures: dict[str, str] | None = None,
    known_states: tuple[StateCandidate, ...] = (),
    source_channels: tuple[SourceChannel, ...] = (),
) -> CandidateSet:
    """Generate finite hypotheses; supplied particles alone are marked feed.

    ``known_states`` offers actual finite state alternatives without declaring
    them supplied or approving their properties.
    """
    case = Case(
        "analysis", gases, limits=limits or Limits(), supplies=supplies, structures=structures or {}
    )
    supplied, gaps, _ = case.input_particles()
    return expand(
        supplied, case.limits, gaps, known_states=known_states, source_channels=source_channels
    )


def expand(
    supplied: tuple[StateCandidate, ...],
    limits: Limits,
    gaps: list[dict],
    *,
    known_states: tuple[StateCandidate, ...] = (),
    source_channels: tuple[SourceChannel, ...] = (),
    requested: tuple[RequestedReaction, ...] = (),
) -> CandidateSet:
    """Expand supplied particles and reactant-ready declared channels."""
    nominations = tuple(
        (
            item.candidate,
            {
                state.id: replace(state, origin="requested", introduced_by=("input.reactions",))
                for state in item.states
            },
        )
        for item in requested
    )
    return _Generator(limits, gaps, known_states, source_channels, nominations).run(supplied)


def _can_extend_search(reaction: ReactionCandidate, states: Mapping[str, StateCandidate]) -> bool:
    """A refuted gas inventory cannot introduce an exploration frontier."""
    if reaction.surface is not None or any(
        (state := states.get(term.species)) is None or state.phase != "gas"
        for term in (*reaction.reactants, *reaction.products)
    ):
        return True
    balance = conservation(reaction.reactants, reaction.products, states)
    return balance.elements_conserved and balance.charge_conserved and not balance.isotope_conflicts


class _Generator:
    def __init__(
        self,
        limits: Limits,
        gaps: list[dict],
        known_states: tuple[StateCandidate, ...],
        source_channels: tuple[SourceChannel, ...],
        nominations: tuple[SourceChannel, ...],
    ) -> None:
        self.limits = limits
        self._max_atoms = limits.max_atoms or 2
        self.result = CandidateSet(
            limits=limits.document(),
            completion={"mechanical": True, "attested": True},
            generation_gaps=list(gaps),
        )
        self.feed: set[str] = set()
        self._state_keys: dict[StateKey, str] = {}
        self._inventory: dict[tuple, set[str]] = {}
        self._new_states: set[str] = set()
        self._tasks: list[tuple[int, int, Iterator[_Proposal | None], dict]] = []
        self._active: dict | None = None
        self._first_state_limit: dict | None = None
        self._task_order = 0
        self._scheduled: set[str] = set()
        self._known: dict[tuple, dict[str, StateCandidate]] = {}
        self._graph_keys: dict[str, str | None] = {}
        for state in known_states:
            if state.phase == "gas" and state.id != ELECTRON:
                self._known.setdefault(self._inventory_key(state), {})[state.id] = state
        self._declared_channels = tuple(
            sorted(
                (*source_channels, *nominations),
                key=lambda channel: (channel[0].origin == "requested", channel[0].id),
            )
        )
        self._inspect_only = {reaction.id: (reaction, states) for reaction, states in nominations}
        self._declared_waiting: dict[str, list[int]] = {}
        self._declared_unmet: list[int] = []
        self._declared_ready: list[tuple[int, int]] = []
        for index, (reaction, _) in enumerate(self._declared_channels):
            required = {term.species for term in reaction.reactants}
            self._declared_unmet.append(len(required))
            for identifier in required:
                self._declared_waiting.setdefault(identifier, []).append(index)
            if not required:
                heappush(self._declared_ready, (1, index))

    @staticmethod
    def _inventory_key(state: StateCandidate) -> tuple:
        return tuple(sorted(state.composition.items())), state.charge

    def run(self, supplied: tuple[StateCandidate, ...]) -> CandidateSet:
        initial = (electron_state(), *supplied)
        needed = len({state.key for state in initial})
        if needed > self.limits.max_species:
            raise ValueError(
                f"max_species cannot retain the input particles; use at least {needed}"
            )
        if any(sum(state.composition.values()) > self._max_atoms for state in supplied):
            raise ValueError("max_atoms cannot retain an input particle; increase max_atoms")
        for state in initial:
            self._add_state(state)
        self.feed = {state.id for state in self.result.states.values() if "feed" in state.classes}
        try:
            self._schedule_new()
            self._run_worklist()
        except _LimitReached as error:
            self.result.completion["mechanical"] = False
            self.result.stop_reason = str(error)
            self._record_unexpanded(str(error))
            while self._declared_ready:
                self._include_declared(cut_reason=str(error))
        if self.result.generation_gaps:
            self.result.completion["mechanical"] = False
            if self.result.stop_reason == "closure":
                self.result.stop_reason = "mechanical operations unavailable; see generation gaps"
        if self._first_state_limit is not None:
            self.result.unexpanded.append(self._first_state_limit)
        self._retain_for_inspection()
        self.result.complete = all(self.result.completion.values())
        return self.result

    def _retain_for_inspection(self) -> None:
        # Direct requests and refuted source equations remain assessable. The
        # inspection inventory is separate from the bounded discovery frontier.
        for reaction, states in self._inspect_only.values():
            for term in (*reaction.reactants, *reaction.products):
                if (state := states.get(term.species)) is not None:
                    self.result.states.setdefault(
                        state.id, replace(state, classes=state.classes - {"feed"})
                    )
            self.result.reactions.setdefault(reaction.id, reaction)

    def _add_state(self, state: StateCandidate) -> str:
        existing = self._state_keys.get(state.key)
        if existing is not None:
            current = self.result.states[existing]
            self.result.states[existing] = replace(
                current,
                classes=current.classes | state.classes,
                depth=min(current.depth, state.depth),
                introduced_by=tuple(sorted(set(current.introduced_by) | set(state.introduced_by))),
            )
            return existing
        self.result.states[state.id] = state
        self._state_keys[state.key] = state.id
        self._inventory.setdefault(self._inventory_key(state), set()).add(state.id)
        self._new_states.add(state.id)
        for index in self._declared_waiting.pop(state.id, ()):
            self._declared_unmet[index] -= 1
            if not self._declared_unmet[index]:
                reaction, _ = self._declared_channels[index]
                depth = 1 + max(
                    self.result.states[term.species].depth for term in reaction.reactants
                )
                heappush(self._declared_ready, (depth, index))
        return state.id

    def _gap(self, target: str, operation: str, reason: str) -> None:
        item = {"target": target, "operation": operation, "reason": reason}
        if item not in self.result.generation_gaps:
            self.result.generation_gaps.append(item)

    def _schedule_new(self) -> None:
        pending = sorted(self._new_states)
        self._new_states.clear()
        for state_id in pending:
            state = self.result.states[state_id]
            if state_id == ELECTRON or state.phase != "gas":
                continue
            # The state remains a candidate product and can satisfy a declared
            # channel. This scope only controls the mechanical worklist.
            if (
                not self.limits.expand_unresolved_states
                and state_id not in self.feed
                and (state.state.kind == "composition" or state.state.resolution != "resolved")
            ):
                continue
            if state.depth >= self.limits.max_depth:
                self.result.completion["mechanical"] = False
                reason = f"max_depth={self.limits.max_depth}"
                if self.result.stop_reason == "closure":
                    self.result.stop_reason = reason
                self.result.unexpanded.append(
                    {
                        "depth": state.depth + 1,
                        "category": "gas",
                        "operation": "state_expansion",
                        "participants": [state_id],
                        "progress": "depth_limited",
                        "reason": reason,
                    }
                )
                continue
            self._scheduled.add(state_id)
            self._enqueue(
                state.depth + 1,
                self._electron(state, state.depth + 1),
                {
                    "depth": state.depth + 1,
                    "category": "electron",
                    "operation": "electron_transformations",
                    "participants": [ELECTRON, state_id],
                },
            )
            for other_id in sorted(self._scheduled):
                other = self.result.states[other_id]
                pair = (min(state_id, other_id), max(state_id, other_id))
                depth = max(state.depth, other.depth) + 1
                iterator = (
                    self._ion_pair(state, other, depth)
                    if state.charge or other.charge
                    else self._neutral_pair(state, other, depth)
                )
                self._enqueue(
                    depth,
                    iterator,
                    {
                        "depth": depth,
                        "category": "ion" if state.charge or other.charge else "neutral",
                        "operation": "heavy_pair_transformations",
                        "participants": list(pair),
                    },
                )

    def _enqueue(self, depth: int, iterator: Iterator[_Proposal | None], descriptor: dict) -> None:
        self._task_order += 1
        heappush(self._tasks, (depth, self._task_order, iterator, descriptor))

    def _run_worklist(self) -> None:
        # A deeper declared path must not register a state before a shallower
        # mechanical proposal has a chance to introduce and schedule it.
        while self._tasks or self._declared_ready:
            if self._declared_precedes_next_task():
                self._include_declared()
                self._schedule_new()
                continue
            depth, _, iterator, descriptor = heappop(self._tasks)
            self._active = {**descriptor, "progress": "active"}
            try:
                proposal = next(iterator)
            except StopIteration:
                continue
            self._enqueue(depth, iterator, descriptor)
            if proposal is not None:
                self._active["next_process"] = proposal.process
            if self.result.trials >= self.limits.max_candidate_trials:
                raise _LimitReached(f"max_candidate_trials={self.limits.max_candidate_trials}")
            self.result.trials += 1
            if proposal is not None:
                self._offer(proposal)
            self._schedule_new()
        self._active = None

    def _declared_precedes_next_task(self) -> bool:
        if not self._declared_ready:
            return False
        if not self._tasks:
            return True
        depth, index = self._declared_ready[0]
        task_depth = self._tasks[0][0]
        # At equal depth, preserve existing source precedence and give the
        # mechanical grammar the chance to discover a nominated duplicate.
        return depth < task_depth or (
            depth == task_depth and self._declared_channels[index][0].origin != "requested"
        )

    def _include_declared(self, *, cut_reason: str | None = None) -> None:
        depth, index = heappop(self._declared_ready)
        reaction, states = self._declared_channels[index]
        existing = self.result.reactions.get(reaction.id)
        if existing is not None:
            self._merge_transformation(existing, reaction.transformation)
            return
        if not _can_extend_search(reaction, ChainMap(self.result.states, states)):
            self._inspect_only[reaction.id] = (reaction, states)
            return
        if cut_reason is not None:
            self._record_declared_limit(reaction, depth, cut_reason)
            return
        if depth > self.limits.max_depth:
            self._record_declared_limit(reaction, depth, f"max_depth={self.limits.max_depth}")
            return
        products = tuple(
            replace(state, classes=state.classes - {"feed"}, depth=depth)
            for term in reaction.products
            if (state := states.get(term.species)) is not None and state.key not in self._state_keys
        )
        if capacity := self._capacity_limit(products):
            limit, maximum = capacity
            self._record_declared_limit(reaction, depth, f"{limit}={maximum}")
            return
        for state in products:
            self._add_state(state)
        self.result.reactions[reaction.id] = replace(reaction, depth=depth)

    def _record_declared_limit(self, reaction: ReactionCandidate, depth: int, reason: str) -> None:
        requested = reaction.origin == "requested"
        self.result.completion["mechanical" if requested else "attested"] = False
        if self.result.stop_reason == "closure":
            self.result.stop_reason = reason
        self.result.unexpanded.append(
            {
                "depth": depth,
                "operation": "requested_channel_addition"
                if requested
                else "source_channel_addition",
                "reaction": reaction.id,
                "participants": [term.species for term in reaction.reactants],
                "reason": reason,
            }
        )

    def _record_unexpanded(self, reason: str) -> None:
        """Expose remaining owned tasks, without serialising iterators or a resume checkpoint."""
        pending = [
            {**entry[3], "progress": "pending", "reason": reason}
            for entry in sorted(self._tasks, key=lambda entry: entry[:2])
        ]
        if self._active is not None:
            pending.append({**self._active, "reason": reason})
        for state_id in sorted(self._new_states - {ELECTRON}):
            state = self.result.states[state_id]
            if state.phase == "gas":
                pending.append(
                    {
                        "depth": state.depth + 1,
                        "category": "gas",
                        "operation": "state_expansion",
                        "participants": [state_id],
                        "progress": "pending",
                        "reason": reason,
                    }
                )
        tasks = {}
        for task in (*self.result.unexpanded, *pending):
            key = (
                task.get("depth"),
                task.get("category"),
                task.get("operation"),
                task.get("reaction"),
                tuple(task.get("participants", ())),
            )
            tasks[key] = task
        self.result.unexpanded = list(tasks.values())

    def _offer(self, proposal: _Proposal) -> None:
        if any(sum(state.composition.values()) > self._max_atoms for state in proposal.products):
            return
        transformation = proposal.transformation
        if self._unresolved_nuclides(proposal):
            transformation = {**transformation, "unresolved_nuclides": True}
        reaction = ReactionCandidate(
            "",
            _terms(proposal.reactants),
            _terms(tuple(state.id for state in proposal.products)),
            proposal.family,
            proposal.process,
            "mechanical",
            "bounded." + proposal.process,
            proposal.depth,
            stabilization=proposal.stabilization,
            transformation=transformation,
        )
        if reaction.reactants == reaction.products and proposal.process not in {
            "elastic",
            "resonant_charge_exchange",
        }:
            return
        reaction = replace(reaction, id=reaction_id(reaction.key))
        existing = self.result.reactions.get(reaction.id)
        if existing is not None:
            self._merge_transformation(existing, reaction.transformation)
            return
        if capacity := self._capacity_limit(proposal.products):
            limit, maximum = capacity
            reason = f"{limit}={maximum}"
            if limit == "max_reactions":
                raise _LimitReached(reason)
            self._record_state_limit(proposal, reason)
            return
        for state in proposal.products:
            self._add_state(state)
        self.result.reactions[reaction.id] = reaction

    def _record_state_limit(self, proposal: _Proposal, reason: str) -> None:
        """Retain the first skipped registration while exploring existing states."""
        self.result.completion["mechanical"] = False
        if self.result.stop_reason == "closure":
            self.result.stop_reason = reason
        if self._first_state_limit is None:
            self._first_state_limit = {
                "depth": proposal.depth,
                "category": proposal.family,
                "operation": "mechanical_state_registration",
                "participants": sorted(proposal.reactants),
                "next_process": proposal.process,
                "progress": "capacity_limited",
                "reason": reason,
            }

    def _capacity_limit(self, products: tuple[StateCandidate, ...]) -> tuple[str, int] | None:
        additions = {state.key for state in products if state.key not in self._state_keys}
        if len(self.result.states) + len(additions) > self.limits.max_species:
            return "max_species", self.limits.max_species
        if len(self.result.reactions) >= self.limits.max_reactions:
            return "max_reactions", self.limits.max_reactions
        return None

    def _unresolved_nuclides(self, proposal: _Proposal) -> bool:
        transformation = proposal.transformation
        kind = transformation["kind"]
        if kind in {
            "charge_transfer",
            "group_exchange",
            "group_transfer",
            "graph_edit",
            "internal_identity",
            "level_transition",
            "two_level_transition",
        }:
            return False
        projected = proposal.reactants
        if kind in {"collision_partition", "collision_ionization", "detachment"}:
            collider = self.result.states[transformation["collider"]]
            final_id = transformation.get("collider_product", collider.id)
            if any(
                state.id == final_id and state.structure == collider.structure
                for state in proposal.products
            ):
                # The exact nuclear structure of the mapped partner is retained.
                projected = (transformation["parent"],)
                if kind == "collision_partition":
                    parent = self.result.states[projected[0]]
                    if not declares_nuclides(parent):
                        return False
                    fragments = tuple(Term(name) for name in transformation["fragments"])
                    inventory = {parent.id: parent, **{s.id: s for s in proposal.products}}
                    balance = conservation((Term(parent.id),), fragments, inventory)
                    return bool(balance.isotope_unresolved)
        return any(declares_nuclides(self.result.states[state]) for state in projected)

    def _merge_transformation(self, reaction: ReactionCandidate, offered: dict) -> None:
        combined = combine_transformations((reaction.transformation, offered))
        if combined != reaction.transformation:
            self.result.reactions[reaction.id] = replace(reaction, transformation=combined)

    def _variants(
        self, composition: dict[str, int], charge: int, depth: int
    ) -> tuple[StateCandidate, ...]:
        key = tuple(sorted(composition.items())), charge
        kind = "ground" if is_atom(composition) else "composition"
        base = candidate_state(
            composition,
            charge,
            kind,
            resolution="lumped" if kind == "composition" else "resolved",
            depth=depth,
            introduced_by=("inventory_hypothesis",),
        )
        found = {base.id: base}
        for identifier in self._inventory.get(key, ()):
            existing = self.result.states[identifier]
            if existing.phase == "gas" and existing.state.kind != "composition":
                found[existing.id] = replace(
                    existing, depth=depth, classes=existing.classes - {"feed"}
                )
        for known in self._known.get(key, {}).values():
            found[known.id] = replace(
                known,
                depth=depth,
                classes=known.classes - {"feed"},
                introduced_by=("known_state_alternative",),
            )
        return tuple(found[k] for k in sorted(found))

    def _products(
        self,
        parts: tuple[dict[str, int], ...],
        charges: tuple[int, ...],
        depth: int,
    ) -> Iterator[tuple[StateCandidate, ...]]:
        yield from product(
            *(
                self._variants(part, charge, depth)
                for part, charge in zip(parts, charges, strict=False)
            )
        )

    def _electron(self, target: StateCandidate, depth: int) -> Iterator[_Proposal | None]:
        reactants = (ELECTRON, target.id)
        yield _Proposal(
            "electron",
            "elastic",
            reactants,
            (electron_state(), target),
            depth,
            {"kind": "internal_identity", "target": target.id},
        )
        iterators = [
            self._electron_charge(target, depth),
            self._level_transitions(target, depth),
            self._electron_partitions(target, depth),
        ]
        if target.structure:
            iterators.append(self._electron_graphs(target, depth))
        yield from _interleave(iterators)

    def _electron_charge(self, target: StateCandidate, depth: int) -> Iterator[_Proposal]:
        reactants = (ELECTRON, target.id)
        for delta, nout in ((1, 2), (-1, 0)):
            charge = target.charge + delta
            if abs(charge) > self.limits.max_charge_abs:
                continue
            process = (
                ("detachment" if target.charge < 0 else "ionization")
                if delta > 0
                else ("recombination" if target.charge > 0 else "attachment")
            )
            for state in self._variants(target.composition, charge, depth):
                yield _Proposal(
                    "electron",
                    process,
                    reactants,
                    (electron_state(),) * nout + (state,),
                    depth,
                    {
                        "kind": "charge_change",
                        "parent": target.id,
                        "product": state.id,
                        "outgoing_electrons": nout,
                    },
                )

    def _electron_partitions(
        self, target: StateCandidate, depth: int
    ) -> Iterator[_Proposal | None]:
        reactants = (ELECTRON, target.id)
        for count in (2, 3):
            for parts in composition_partitions(target.composition, count):
                for charges in product((-1, 0, 1), repeat=count):
                    nout = _outgoing_electrons(1, target.charge, sum(charges))
                    if nout not in {0, 1, 2}:
                        yield None
                        continue
                    process = electron_partition_process(target.charge, nout, charges)
                    for fragments in self._products(parts, charges, depth):
                        yield _Proposal(
                            "electron",
                            process,
                            reactants,
                            (electron_state(),) * nout + fragments,
                            depth,
                            {
                                "kind": "electron_partition",
                                "resolution": "inventory",
                                "parent": target.id,
                                "fragments": [state.id for state in fragments],
                                "outgoing_electrons": nout,
                            },
                        )

    def _electron_graphs(self, target: StateCandidate, depth: int) -> Iterator[_Proposal | None]:
        for branch in self._fragment_graphs(target, depth):
            if branch is None:
                yield None
                continue
            products, transformation = branch
            yield _Proposal(
                "electron",
                electron_partition_process(target.charge, 1, (state.charge for state in products)),
                (ELECTRON, target.id),
                (electron_state(), *products),
                depth,
                {**transformation, "parent": target.id},
            )

    def _fragment_graphs(
        self, target: StateCandidate, depth: int, *, max_fragments: int = 3
    ) -> Iterator[tuple[tuple[StateCandidate, ...], dict] | None]:
        try:
            for edit in fragment_edits(target, depth):
                if edit is None or len(edit.products) > max_fragments:
                    yield None
                    continue
                yield from self._graph_products(edit.products, edit.transformation, depth)
        except StructureUnavailable as error:
            self._gap(target.id, "graph_fragmentation", str(error))

    def _levels(self, target: StateCandidate, depth: int) -> tuple[StateCandidate, ...]:
        if target.state.kind == "composition":
            return ()
        found = dict(self._known.get(self._inventory_key(target), {}))
        if target.state.kind != "ground" and is_atom(target.composition):
            # An atomic ground hypothesis preserves the declared nuclear identity.
            ground = candidate_state(
                target.composition, target.charge, structure=target.structure, phase=target.phase
            )
            found.setdefault(ground.id, ground)
        if target.state.kind == "ground" and target.id in self.feed and target.structure is None:
            kinds = (
                ("metastable", "resonant")
                if is_noble(target.composition)
                else (
                    ("electronic",)
                    if is_atom(target.composition)
                    else ("vibrational", "electronic")
                )
            )
            for kind in kinds:
                state = candidate_state(
                    target.composition,
                    target.charge,
                    kind,
                    depth=depth,
                    classes=frozenset({"excited"}),
                    introduced_by=("unresolved_excitation_hypothesis",),
                )
                found[state.id] = state
        found.update(
            (identifier, self.result.states[identifier])
            for identifier in self._inventory.get(self._inventory_key(target), ())
        )
        target_structure = physical_state_key(target)[-1]
        return tuple(
            replace(state, depth=depth, classes=state.classes - {"feed"})
            for state in sorted(found.values(), key=lambda state: state.id)
            if state.state != target.state
            and state.state.kind != "composition"
            and state.phase == target.phase
            and physical_state_key(state)[-1] == target_structure
        )

    def _level_transitions(self, target: StateCandidate, depth: int) -> Iterator[_Proposal]:
        for state in self._levels(target, depth):
            if target.state.kind == "ground":
                process = "excitation"
            elif state.state.kind == "ground":
                process = "deexcitation"
            else:
                process = "level_transfer"
            yield _Proposal(
                "electron",
                process,
                (ELECTRON, target.id),
                (electron_state(), state),
                depth,
                {"kind": "level_transition", "initial": target.id, "final": state.id},
            )

    def _ion_pair(
        self, left: StateCandidate, right: StateCandidate, depth: int
    ) -> Iterator[_Proposal | None]:
        reactants = (left.id, right.id)
        yield _Proposal(
            "ion", "elastic", reactants, (left, right), depth, {"kind": "internal_identity"}
        )
        iterators = [
            self._charge_exchange(left, right, depth),
            self._transfers(left, right, depth, "ion"),
            self._heavy_partitions(left, right, depth, "ion"),
            self._association(left, right, depth, "ion"),
            self._heavy_levels(left, right, depth, "ion"),
            self._heavy_electron_release(left, right, depth, "ion"),
        ]
        if left.structure and right.structure:
            iterators.append(self._graphs(left, right, depth, "ion"))
        yield from _interleave(iterators)

    def _charge_exchange(
        self, left: StateCandidate, right: StateCandidate, depth: int
    ) -> Iterator[_Proposal]:
        reactants = (left.id, right.id)
        for delta in (-1, 1):
            charges = left.charge + delta, right.charge - delta
            if any(abs(q) > self.limits.max_charge_abs for q in charges):
                continue
            if left.charge * right.charge < 0 and charges == (0, 0):
                process = "mutual_neutralization"
            else:
                process = "charge_exchange"
            for products in self._products((left.composition, right.composition), charges, depth):
                correspondence = tuple(
                    charge_target_correspondence(initial, final)
                    for initial, final in zip((left, right), products, strict=True)
                )
                if False in correspondence:
                    continue
                actual_process = process
                if process == "charge_exchange" and {p.id for p in products} == set(reactants):
                    if left.charge * right.charge != 0 or (
                        resonant_charge_correspondence(left, right) is False
                    ):
                        continue
                    actual_process = "resonant_charge_exchange"
                transformation = {
                    "kind": "charge_transfer",
                    "partners": list(reactants),
                    "partner_products": [state.id for state in products],
                    "charge_change": delta,
                }
                if None in correspondence:
                    transformation["unresolved_nuclides"] = True
                yield _Proposal(
                    "ion",
                    actual_process,
                    reactants,
                    products,
                    depth,
                    transformation,
                )

    def _neutral_pair(
        self, left: StateCandidate, right: StateCandidate, depth: int
    ) -> Iterator[_Proposal | None]:
        yield _Proposal(
            "neutral",
            "elastic",
            (left.id, right.id),
            (left, right),
            depth,
            {"kind": "internal_identity"},
        )
        iterators = [
            self._transfers(left, right, depth, "neutral"),
            self._association(left, right, depth, "neutral"),
            self._heavy_partitions(left, right, depth, "neutral"),
            self._heavy_levels(left, right, depth, "neutral"),
            self._heavy_electron_release(left, right, depth, "neutral"),
        ]
        if left.structure and right.structure:
            iterators.append(self._graphs(left, right, depth, "neutral"))
        yield from _interleave(iterators)

    def _transfers(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        yield from _interleave(
            [
                self._transfer_from(left, right, depth, family),
                self._transfer_from(right, left, depth, family),
                self._exchanges(left, right, depth, family),
            ]
        )

    def _transfer_from(
        self, donor: StateCandidate, acceptor: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        for group in composition_groups(donor.composition, self.limits.max_leaving_atoms):
            remainder = subtract(donor.composition, group)
            if not remainder:
                continue
            for qgroup in (-1, 0, 1) if family == "ion" else (0,):
                charges = donor.charge - qgroup, acceptor.charge + qgroup
                if any(abs(q) > self.limits.max_charge_abs for q in charges):
                    yield None
                    continue
                parts = remainder, merge(acceptor.composition, group)
                if parts == (acceptor.composition, donor.composition):
                    yield None
                    continue
                for products in self._products(parts, charges, depth):
                    donor_product, acceptor_product = products
                    correspondence = retained_nuclide_correspondence(
                        (donor, donor_product, donor_product.composition),
                        (acceptor, acceptor_product, acceptor.composition),
                    )
                    if correspondence is False:
                        yield None
                        continue
                    transformation = {
                        "kind": "group_transfer",
                        "resolution": "inventory",
                        "donor": donor.id,
                        "acceptor": acceptor.id,
                        "group": group,
                        "group_charge": qgroup,
                        "donor_product": donor_product.id,
                        "acceptor_product": acceptor_product.id,
                    }
                    if correspondence is None:
                        transformation["unresolved_nuclides"] = True
                    yield _Proposal(
                        family,
                        "net_group_transfer",
                        (donor.id, acceptor.id),
                        products,
                        depth,
                        transformation,
                    )

    def _exchanges(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        for a in composition_groups(left.composition, self.limits.max_leaving_atoms):
            for b in composition_groups(right.composition, self.limits.max_leaving_atoms):
                cores = subtract(left.composition, a), subtract(right.composition, b)
                if not all(cores) or a == b:
                    continue
                parts = merge(cores[0], b), merge(cores[1], a)
                if parts == (right.composition, left.composition):
                    # Same ordered inventories already require a == b. A
                    # reversal also leaves the net elemental partition intact.
                    yield None
                    continue
                for products in self._products(parts, (left.charge, right.charge), depth):
                    correspondence = retained_nuclide_correspondence(
                        (left, products[0], cores[0]), (right, products[1], cores[1])
                    )
                    if correspondence is False:
                        yield None
                        continue
                    transformation: dict[str, object] = {
                        "kind": "group_exchange",
                        "resolution": "inventory",
                        "partners": [left.id, right.id],
                        "partner_products": [state.id for state in products],
                        "groups": [a, b],
                    }
                    if correspondence is None:
                        transformation["unresolved_nuclides"] = True
                    yield _Proposal(
                        family,
                        "net_group_exchange",
                        (left.id, right.id),
                        products,
                        depth,
                        transformation,
                    )

    def _association(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        composition = merge(left.composition, right.composition)
        charge = left.charge + right.charge
        if abs(charge) <= self.limits.max_charge_abs:
            for state in self._variants(composition, charge, depth):
                yield _Proposal(
                    family,
                    "net_association",
                    (left.id, right.id),
                    (state,),
                    depth,
                    {"kind": "association", "resolution": "inventory"},
                    "unspecified",
                )
        if family == "ion" and (left.charge < 0 or right.charge < 0) and abs(charge + 1) <= 1:
            for state in self._variants(composition, charge + 1, depth):
                yield _Proposal(
                    family,
                    "associative_detachment",
                    (left.id, right.id),
                    (state, electron_state()),
                    depth,
                    {"kind": "associative_detachment", "resolution": "inventory"},
                )
        if family == "neutral":
            for state in self._variants(composition, 1, depth):
                yield _Proposal(
                    family,
                    "associative_ionization",
                    (left.id, right.id),
                    (state, electron_state()),
                    depth,
                    {"kind": "associative_ionization", "resolution": "inventory"},
                )
        for leaving in composition_groups(composition, self.limits.max_leaving_atoms):
            core = subtract(composition, leaving)
            if (
                not core
                or abs(charge) > self.limits.max_charge_abs
                or (core, leaving)
                in ((left.composition, right.composition), (right.composition, left.composition))
            ):
                continue
            for products in self._products((core, leaving), (charge, 0), depth):
                yield _Proposal(
                    family,
                    "net_association_loss",
                    (left.id, right.id),
                    products,
                    depth,
                    {
                        "kind": "association_loss",
                        "resolution": "inventory",
                        "leaving_group": leaving,
                    },
                )

    def _heavy_partitions(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        parts = [self._heavy_inventory_partitions(left, right, depth, family)]
        for parent, collider in ((left, right), (right, left)):
            if parent.structure and not is_atom(parent.composition):
                parts.append(self._heavy_fragment_graphs(parent, collider, depth, family))
        yield from _interleave(parts)

    def _heavy_inventory_partitions(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        charge_options = (-1, 0, 1) if family == "ion" else (0,)
        for parent, collider in ((left, right), (right, left)):
            if is_atom(parent.composition):
                continue
            changed_colliders = self._excited_partner_exits(collider, depth)
            for parts in composition_partitions(parent.composition):
                for charges in product(charge_options, repeat=2):
                    fragment_charge = sum(charges)
                    counterparts = tuple(
                        self._partition_counterparts(
                            parent, collider, changed_colliders, fragment_charge, depth
                        )
                    )
                    if not counterparts:
                        yield None
                        continue
                    for fragments in self._products(parts, charges, depth):
                        for process, counterpart in counterparts:
                            nout = _outgoing_electrons(
                                0,
                                parent.charge + collider.charge,
                                fragment_charge + counterpart.charge,
                            )
                            yield _Proposal(
                                family,
                                process,
                                (parent.id, collider.id),
                                (*fragments, counterpart) + (electron_state(),) * nout,
                                depth,
                                {
                                    "kind": "collision_partition",
                                    "resolution": "inventory",
                                    "parent": parent.id,
                                    "collider": collider.id,
                                    "fragments": sorted(state.id for state in fragments),
                                    "collider_product": counterpart.id,
                                    "outgoing_electrons": nout,
                                },
                            )

    def _heavy_fragment_graphs(
        self, parent: StateCandidate, collider: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        exits = tuple(
            self._partition_counterparts(
                parent, collider, self._excited_partner_exits(collider, depth), parent.charge, depth
            )
        )
        for branch in self._fragment_graphs(parent, depth, max_fragments=2):
            if branch is None:
                yield None
                continue
            fragments, transformation = branch
            for process, counterpart in exits:
                yield _Proposal(
                    family,
                    process,
                    (parent.id, collider.id),
                    (*fragments, counterpart),
                    depth,
                    {
                        **transformation,
                        "parent": parent.id,
                        "collider": collider.id,
                        "fragments": sorted(state.id for state in fragments),
                        "collider_product": counterpart.id,
                    },
                )

    def _partition_counterparts(
        self,
        parent: StateCandidate,
        collider: StateCandidate,
        changed_colliders: tuple[StateCandidate, ...],
        fragment_charge: int,
        depth: int,
    ) -> Iterator[tuple[str, StateCandidate]]:
        """Assign the collider's exit for a finite fragment charge partition."""
        delta = fragment_charge - parent.charge
        if delta == 0:
            yield "collision_induced_dissociation", collider
            for counterpart in changed_colliders:
                yield "dissociation_with_level_transfer", counterpart
            return
        qcollider = collider.charge - delta
        if abs(qcollider) <= self.limits.max_charge_abs:
            for counterpart in self._variants(collider.composition, qcollider, depth):
                yield "dissociative_charge_transfer", counterpart
        if parent.charge < 0 and delta == 1:
            yield "dissociative_detachment", collider

    def _excited_partner_exits(
        self, collider: StateCandidate, depth: int
    ) -> tuple[StateCandidate, ...]:
        if collider.state.kind in {"ground", "composition"}:
            return ()
        # A level change is a candidate even when its direction cannot yet be evaluated.
        return self._levels(collider, depth)

    def _heavy_levels(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        for parent, collider in ((left, right), (right, left)):
            for state in self._levels(parent, depth):
                yield _Proposal(
                    family,
                    "level_transfer",
                    (parent.id, collider.id),
                    (state, collider),
                    depth,
                    {
                        "kind": "level_transition",
                        "initial": parent.id,
                        "final": state.id,
                        "collider": collider.id,
                    },
                )
                for final_collider in self._levels(collider, depth):
                    yield _Proposal(
                        family,
                        "level_transfer",
                        (parent.id, collider.id),
                        (state, final_collider),
                        depth,
                        {
                            "kind": "two_level_transition",
                            "initial": [parent.id, collider.id],
                            "final": [state.id, final_collider.id],
                        },
                    )

    def _heavy_electron_release(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal]:
        for target, collider in ((left, right), (right, left)):
            charge = target.charge + 1
            if abs(charge) > self.limits.max_charge_abs:
                continue
            detachment = target.charge < 0
            counterparts: tuple[StateCandidate, ...] = (collider,)
            if not detachment:
                counterparts += self._excited_partner_exits(collider, depth)
            for final_target in self._variants(target.composition, charge, depth):
                for counterpart in counterparts:
                    transformation = {
                        "kind": "detachment" if detachment else "collision_ionization",
                        "parent": target.id,
                        "product": final_target.id,
                        "collider": collider.id,
                    }
                    process = "collisional_detachment" if detachment else "collision_ionization"
                    if counterpart.id != collider.id:
                        transformation["collider_product"] = counterpart.id
                        if (
                            family == "neutral"
                            and collider.state.manifold == "electronic"
                            and counterpart.state.kind == "ground"
                        ):
                            process = "penning_ionization"
                    yield _Proposal(
                        family,
                        process,
                        (target.id, collider.id),
                        (final_target, counterpart, electron_state()),
                        depth,
                        transformation,
                    )

    def _graphs(
        self, left: StateCandidate, right: StateCandidate, depth: int, family: str
    ) -> Iterator[_Proposal | None]:
        try:
            for edit in pair_edits(left, right, depth):
                if edit is None:
                    yield None
                    continue
                for products, transformation in self._graph_products(
                    edit.products, edit.transformation, depth
                ):
                    yield _Proposal(
                        family,
                        edit.process,
                        (left.id, right.id),
                        products,
                        depth,
                        {**transformation, "reactants": [left.id, right.id]},
                    )
        except StructureUnavailable as error:
            self._gap(left.id + " + " + right.id, "graph_pair_edits", str(error))

    def _graph_products(
        self,
        products: tuple[StateCandidate, ...],
        transformation: dict,
        depth: int,
    ) -> Iterator[tuple[tuple[StateCandidate, ...], dict]]:
        """Keep the graph hypothesis and identified state alternatives as separate branches."""
        alternatives = [self._graph_states(state, depth) for state in products]
        for selected in product(*alternatives):
            mapped = [
                {**entry, "state": state.id}
                for state, entry in zip(selected, transformation["products"], strict=True)
            ]
            yield selected, {**transformation, "products": mapped}

    def _graph_states(self, state: StateCandidate, depth: int) -> tuple[StateCandidate, ...]:
        found = {state.id: state}
        key = self._graph_key(state)
        inventory = self._inventory_key(state)
        offered = {
            identifier: item
            for identifier in self._inventory.get(inventory, ())
            if (item := self.result.states[identifier]).state.kind != "composition"
        }
        offered.update(self._known.get(inventory, {}))
        for known in offered.values():
            same = key is not None and self._graph_key(known) == key
            atom = (
                is_atom(state.composition)
                and known.structure is None
                and not declares_nuclides(state)
            )
            if known.phase == state.phase and (same or atom):
                found[known.id] = replace(known, depth=depth, classes=known.classes - {"feed"})
        return tuple(found[name] for name in sorted(found))

    def _graph_key(self, state: StateCandidate) -> str | None:
        if state.id not in self._graph_keys:
            self._graph_keys[state.id] = structure_key(state)
        return self._graph_keys[state.id]


def _outgoing_electrons(incident: int, heavy_in_charge: int, heavy_out_charge: int) -> int:
    """Conserve total charge, including the incident and emitted free electrons."""
    return incident + heavy_out_charge - heavy_in_charge


def _interleave(iterators: list[Iterator[_Proposal | None]]) -> Iterator[_Proposal | None]:
    pending = deque(iterators)
    while pending:
        iterator = pending.popleft()
        try:
            yield next(iterator)
        except StopIteration:
            continue
        pending.append(iterator)


def _terms(species_ids: tuple[str, ...]) -> tuple[Term, ...]:
    counts = Counter(species_ids)
    return tuple(
        Term(state, float(counts[state]))
        for state in sorted(counts, key=lambda item: (item != ELECTRON, item))
    )
