"""Pure target-centred reachability over reaction hypergraphs."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from heapq import heappop, heappush

from reactgen.model import VERIFIED_STRUCTURE_BASIS, stoichiometric_sum

PATHWAY_POLICY_FORMAT = 9
_PROCESS_CHECK_FORMAT = 8
_OPAQUE_IDENTITY_FORMAT = 9
MINIMUM_DEPTH_ALTERNATIVE = "minimum-depth alternative support"
LATER_PRODUCER_CONTEXT = "later reachable producer / possible return"


@dataclass(frozen=True)
class Reachability:
    """Minimum AND-hypergraph distance from explicitly available states."""

    seeds: tuple[str, ...]
    state_layers: dict[str, int]
    reaction_layers: dict[str, int]


@dataclass(frozen=True)
class Pathway:
    """One deterministic support hyperpath for a target state."""

    target: str | None
    state_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    supported_by: dict[str, str]
    related_reactions: dict[str, str]


@dataclass(frozen=True)
class ProducerPathway:
    """One selected producer with independently reachable reactants."""

    producer: str
    pathway: Pathway
    reachability: Reachability
    equation_and_energy_checks_pass: bool


def feed_state_ids(states: list[dict]) -> tuple[str, ...]:
    """Return explicitly marked particle supplies; seed electrons are not assumed."""

    return tuple(sorted(state["id"] for state in states if "feed" in state.get("classes", [])))


def reaction_reachability(
    states: list[dict],
    reactions: list[dict],
    *,
    seeds: Iterable[str] | None = None,
) -> Reachability:
    """Compute minimum production layers without using candidate generation depth.

    A reaction is reachable only after every explicit reactant is reachable. Only
    positive net products introduce a new state, so elastic and identity-preserving
    collisions cannot manufacture a pathway.
    """

    state_ids = {state["id"] for state in states}
    selected_seeds = feed_state_ids(states) if seeds is None else tuple(sorted(set(seeds)))
    unknown = set(selected_seeds) - state_ids
    if unknown:
        raise ValueError("unknown pathway seed states: " + ", ".join(sorted(unknown)))
    return _indexed_reachability(state_ids, reactions, selected_seeds)


def _indexed_reachability(
    state_ids: set[str], reactions: list[dict], seeds: tuple[str, ...]
) -> Reachability:
    """Settle each state once; an edge waits for every explicit reactant.

    Unit hyperedge cost and max-reactant depth are monotone, so a priority queue
    settles minimum AND depth without repeatedly scanning the complete network.
    """
    by_id = {reaction["id"]: reaction for reaction in reactions}
    remaining = {
        reaction["id"]: {term["species"] for term in reaction["reactants"]}
        for reaction in reactions
    }
    consumers: dict[str, list[str]] = {}
    for reaction_id, reactants in remaining.items():
        for state_id in reactants:
            consumers.setdefault(state_id, []).append(reaction_id)
    state_layers = dict.fromkeys(seeds, 0)
    reaction_layers: dict[str, int] = {}
    pending = [(0, state_id) for state_id in seeds]
    settled: set[str] = set()

    for reaction_id, reactants in remaining.items():
        if not reactants:
            _activate_reaction(
                by_id[reaction_id], state_ids, state_layers, reaction_layers, pending
            )
    while pending:
        layer, state_id = heappop(pending)
        if state_id in settled or layer != state_layers[state_id]:
            continue
        settled.add(state_id)
        for reaction_id in consumers.get(state_id, ()):
            remaining[reaction_id].discard(state_id)
            if not remaining[reaction_id]:
                _activate_reaction(
                    by_id[reaction_id], state_ids, state_layers, reaction_layers, pending
                )
    return Reachability(seeds, state_layers, reaction_layers)


def _activate_reaction(
    reaction: dict,
    state_ids: set[str],
    state_layers: dict[str, int],
    reaction_layers: dict[str, int],
    pending: list[tuple[int, str]],
) -> None:
    layer = _reaction_layer(reaction, state_layers)
    reaction_layers[reaction["id"]] = layer
    for product in _positive_products(reaction).intersection(state_ids):
        if product not in state_layers or layer < state_layers[product]:
            state_layers[product] = layer
            heappush(pending, (layer, product))


def _reaction_layer(reaction: dict, state_layers: dict[str, int]) -> int:
    return 1 + max((state_layers[term["species"]] for term in reaction["reactants"]), default=0)


def analyze_pathways(
    states: list[dict],
    reactions: list[dict],
    *,
    seeds: Iterable[str] | None = None,
    conditions: dict | None = None,
    format_version: int = PATHWAY_POLICY_FORMAT,
) -> dict:
    """Project saved propositions into two explicit candidate hypergraphs.

    No source or numerical quantity is evaluated here. Conservation falsifies
    an equation; the named collision-energy proposition falsifies only its
    saved state/condition model. Conditioned paths also exclude refuted
    equation/process declarations. Unknown comparisons remain candidates.
    """
    supplied = feed_state_ids(states) if seeds is None else tuple(sorted(set(seeds)))
    candidate_excluded = _excluded_assessments(reactions, "candidate", format_version)
    conditioned_excluded = _excluded_assessments(reactions, "conditioned", format_version)
    unconfirmed_states = _unconfirmed_states(states, format_version)
    return {
        "seeds": list(supplied),
        "conditions": conditions or {},
        "scope": (
            "Candidate AND reachability, not rates, time order, dominant flux or jointly "
            "realizable collision conditions. Unknown comparisons and unidentified "
            "intermediate connections remain explicit."
        ),
        "unconfirmed_states": unconfirmed_states,
        "candidate": _pathway_mode(states, reactions, supplied, candidate_excluded),
        "conditioned": _pathway_mode(
            states, reactions, supplied, conditioned_excluded, unconfirmed_states=unconfirmed_states
        ),
    }


def checked_pathway_query(states: list[dict], reactions: list[dict], analysis: dict) -> dict:
    """Require saved equation and energy checks without assuming state existence."""
    conditioned = analysis["conditioned"]
    unconfirmed = analysis["unconfirmed_states"]
    refuted = _state_claim_references(states, "fail")
    excluded = conditioned["excluded"] | _checked_exclusions(
        [reaction for reaction in reactions if reaction["id"] not in conditioned["excluded"]],
        conditioned["unresolved"],
        unconfirmed,
        refuted,
    )
    excluded_seeds = {
        state: notes
        for state in analysis["seeds"]
        if (notes := _participant_blockers({state}, unconfirmed, refuted))
    }
    seeds = tuple(state for state in analysis["seeds"] if state not in excluded_seeds)
    checked = _pathway_mode(
        states,
        reactions,
        seeds,
        excluded,
        participant_notes=_state_claim_references(states, "unknown"),
    )
    return analysis | {"checked": checked | {"excluded_seeds": excluded_seeds}}


def _checked_exclusions(
    reactions: list[dict],
    unresolved: dict[str, list[dict]],
    unconfirmed: Collection[str],
    refuted: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    excluded = {}
    for reaction in reactions:
        key = reaction["id"]
        notes = list(unresolved.get(key, ()))
        if not notes and not _passes_equation_and_energy(reaction):
            notes.append({"condition": "necessary_conditions_not_confirmed"})
        notes.extend(_participant_blockers(_participants(reaction), unconfirmed, refuted))
        if notes:
            excluded[key] = notes
    return excluded


def _participant_blockers(
    participants: set[str], unconfirmed: Collection[str], refuted: dict[str, list[dict]]
) -> list[dict]:
    notes = _participant_references(participants, refuted)
    if unknown := participants.intersection(unconfirmed):
        notes.append({"condition": "unconfirmed_participant_states", "states": sorted(unknown)})
    return notes


def _participant_references(
    participants: set[str], references: dict[str, list[dict]]
) -> list[dict]:
    return [
        note for state in sorted(participants & references.keys()) for note in references[state]
    ]


def _state_claim_references(states: list[dict], verdict: str) -> dict[str, list[dict]]:
    """Project state claims separately from stoichiometric cancellation and energy checks."""
    return {
        state["id"]: references
        for state in states
        if (
            references := [
                {"state": state["id"], "assessment": name, "proposition": claim["proposition"]}
                for name, claim in sorted(state.get("assessments", {}).items())
                if claim.get("verdict") == verdict
                and claim.get("proposition")
                in {"state_existence_support", "ground_anion_electron_binding"}
            ]
        )
    }


def pathway_state_claims(states: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """Index unresolved and refuted state claims independently of edge eligibility."""
    return {verdict: _state_claim_references(states, verdict) for verdict in ("fail", "unknown")}


def pathway_participant_claims(
    states: list[dict], participants: Collection[str]
) -> dict[str, list[dict]]:
    """Retain claims about all selected reaction participants, including coproducts."""
    ordered = sorted(participants)
    return {
        verdict: [reference for state in ordered for reference in claims.get(state, ())]
        for verdict, claims in pathway_state_claims(states).items()
    }


def pathway_participants(path_states: Iterable[str], path_reactions: list[dict]) -> set[str]:
    participants = set(path_states)
    for reaction in path_reactions:
        participants.update(_participants(reaction))
    return participants


def validate_saved_pathway_graph(
    states: list[dict],
    reactions: list[dict],
    analysis: dict,
    *,
    format_version: int = PATHWAY_POLICY_FORMAT,
) -> None:
    """Check the saved AND distances without selecting another representative view."""
    if not _same_notes(analysis["unconfirmed_states"], _unconfirmed_states(states, format_version)):
        raise ValueError("pathway state-connection notes contradict the saved identities")
    for mode in ("candidate", "conditioned"):
        if not _valid_pathway_mode(
            reactions, analysis[mode], analysis["seeds"], mode, format_version
        ):
            raise ValueError(f"saved pathway index contradicts its edge set and supply: {mode}")


def _valid_pathway_mode(
    reactions: list[dict], saved: dict, seeds: list[str], mode: str, format_version: int
) -> bool:
    excluded = _excluded_assessments(reactions, mode, format_version)
    if not _same_notes(saved["excluded"], excluded):
        return False
    state_layers = dict.fromkeys(seeds, 0)
    reaction_layers: dict[str, int] = {}
    producers: dict[str, list[str]] = {}
    unresolved = {}
    for reaction in reactions:
        reaction_id = reaction["id"]
        if reaction_id in excluded:
            continue
        if notes := _unresolved_edge(reaction):
            unresolved[reaction_id] = notes
        if not all(term["species"] in saved["state_layers"] for term in reaction["reactants"]):
            continue
        layer = _reaction_layer(reaction, saved["state_layers"])
        reaction_layers[reaction_id] = layer
        for state_id in _positive_products(reaction):
            producers.setdefault(state_id, []).append(reaction_id)
            state_layers[state_id] = min(state_layers.get(state_id, layer), layer)
    # A non-seed's minimum producer must depend on strictly earlier states.
    # This rules out self-supporting cycles without running another traversal.
    if (
        saved["state_layers"] != state_layers
        or saved["reaction_layers"] != reaction_layers
        or saved["producer_ids"] != {state: sorted(ids) for state, ids in producers.items()}
        or not _same_notes(saved["unresolved"], unresolved)
    ):
        return False
    primary = saved["primary_producer"]
    if primary.keys() != producers.keys() or not all(
        reaction in ids and reaction_layers[reaction] == min(reaction_layers[item] for item in ids)
        for state, ids in producers.items()
        for reaction in (primary[state],)
    ):
        return False
    default = saved["default_target"]
    targets = {state for state in producers if state_layers[state] > 0}
    return default in targets if targets else default is None


def _same_notes(saved: dict, expected: dict) -> bool:
    return saved.keys() == expected.keys() and all(
        len(saved[key]) == len(items) and all(item in saved[key] for item in items)
        for key, items in expected.items()
    )


def _excluded_assessments(
    reactions: list[dict], mode: str, format_version: int
) -> dict[str, list[dict]]:
    propositions = {"element_charge_conservation"}
    if mode == "conditioned":
        propositions.add("collision_energy_necessary_condition")
        if format_version >= _PROCESS_CHECK_FORMAT:
            propositions.add("equation_consistency")
    excluded: dict[str, list[dict]] = {}
    for reaction in reactions:
        references = [
            {"assessment": name, "proposition": assessment["proposition"]}
            for name, assessment in reaction.get("assessments", {}).items()
            if assessment.get("proposition") in propositions and assessment.get("verdict") == "fail"
        ]
        if references:
            excluded[reaction["id"]] = references
    return excluded


def _pathway_mode(
    states: list[dict],
    reactions: list[dict],
    seeds: tuple[str, ...],
    excluded: dict[str, list[dict]],
    *,
    unconfirmed_states: Collection[str] | None = None,
    participant_notes: dict[str, list[dict]] | None = None,
) -> dict:
    eligible = [reaction for reaction in reactions if reaction["id"] not in excluded]
    reachability = reaction_reachability(states, eligible, seeds=seeds)
    producers = _producer_index(eligible, reachability)
    unresolved: dict[str, list[dict]] = {}
    for reaction in eligible:
        reaction_id = reaction["id"]
        notes = _unresolved_edge(reaction)
        if participant_notes:
            notes.extend(_participant_references(_participants(reaction), participant_notes))
        if notes:
            unresolved[reaction_id] = notes
    preference_exclusions = (
        _checked_exclusions(
            eligible, unresolved, unconfirmed_states, _state_claim_references(states, "fail")
        )
        if unconfirmed_states is not None
        else None
    )
    primary = _primary_producers(producers, reachability, eligible, preference_exclusions)
    return {
        "state_layers": dict(sorted(reachability.state_layers.items())),
        "reaction_layers": dict(sorted(reachability.reaction_layers.items())),
        "producer_ids": {key: sorted(value) for key, value in sorted(producers.items())},
        "primary_producer": dict(sorted(primary.items())),
        "default_target": _indexed_target(states, reachability, producers),
        "excluded": dict(sorted(excluded.items())),
        "unresolved": dict(sorted(unresolved.items())),
    }


def _unresolved_edge(reaction: dict) -> list[dict]:
    notes = [
        {"assessment": name, "proposition": assessment["proposition"]}
        for name, assessment in reaction.get("assessments", {}).items()
        if assessment.get("proposition")
        in {"element_charge_conservation", "collision_energy_necessary_condition"}
        and assessment.get("verdict") == "unknown"
    ]
    propositions = {
        assessment.get("proposition") for assessment in reaction.get("assessments", {}).values()
    }
    consistency = reaction.get("assessments", {}).get("consistency", {})
    if consistency.get("proposition") and consistency.get("verdict") in {"fail", "unknown"}:
        notes.append({"assessment": "consistency", "proposition": consistency["proposition"]})
    energy = reaction.get("assessments", {}).get("energy", {})
    if (
        energy.get("proposition") == "collision_energy_necessary_condition"
        and energy.get("verdict") == "not_applicable"
    ):
        notes.append(
            {
                "assessment": "energy",
                "proposition": energy["proposition"],
                "condition": "energy_condition_not_applied",
            }
        )
    if "element_charge_conservation" not in propositions:
        notes.append({"condition": "conservation_assessment_not_recorded"})
    if "collision_energy_necessary_condition" not in propositions:
        notes.append({"condition": "energy_assessment_not_recorded"})
    if reaction.get("third_body"):
        notes.append({"condition": "third_body_supply_and_energy_exchange"})
    if reaction.get("surface"):
        notes.append({"condition": "surface_exchange_outside_gas_model"})
    return notes


def _unconfirmed_states(states: list[dict], format_version: int) -> dict[str, list[str]]:
    out = {}
    for state in states:
        reasons = []
        kind = state["state"]["kind"]
        if kind == "composition":
            reasons.append("composition_hypothesis_not_identified_state")
        elif state["state"].get("resolution") == "lumped":
            reasons.append("unresolved_internal_state")
        structure = state.get("structure") or ""
        if sum(state.get("composition", {}).values()) > 2 and not structure:
            reasons.append("molecular_structure_unidentified")
        if structure and _unverified_structure(state, structure, format_version):
            reasons.append("structure_unverified")
        if reasons:
            out[state["id"]] = reasons
    return out


def _unverified_structure(state: dict, structure: str, format_version: int) -> bool:
    claims = state.get("assessments", {})
    if structure.startswith("smiles:") and format_version >= _PROCESS_CHECK_FORMAT:
        claim = claims.get("consistency", {})
        return (
            claim.get("proposition") != "state_representation_consistency"
            or claim.get("verdict") != "pass"
            or VERIFIED_STRUCTURE_BASIS not in claim.get("basis", ())
        )
    if format_version >= _OPAQUE_IDENTITY_FORMAT:
        # An opaque identifier needs reviewed evidence for that exact state.
        # A correctly parsed label or an independent binding claim is insufficient.
        claim = claims.get("state", {})
        return (
            state.get("evidence", {}).get("match") != "exact"
            or claim.get("proposition") != "state_existence_support"
            or claim.get("verdict") != "pass"
        )
    return False


def saved_reachability(analysis: dict, mode: str = "conditioned") -> Reachability:
    """Read an already computed graph index; no judgments are recomputed."""
    selected = analysis[mode]
    return Reachability(
        tuple(
            state for state in analysis["seeds"] if state not in selected.get("excluded_seeds", {})
        ),
        selected["state_layers"],
        selected["reaction_layers"],
    )


def saved_pathway(
    reactions: list[dict],
    analysis: dict,
    *,
    target: str | None = None,
    mode: str = "conditioned",
) -> Pathway:
    """Select a target projection from a saved eligible graph."""
    selected = analysis[mode]
    reachability = saved_reachability(analysis, mode)
    target = target or selected["default_target"]
    if target is None or target not in reachability.state_layers:
        return Pathway(None, (), (), {}, {})
    by_id = {reaction["id"]: reaction for reaction in reactions}
    states_on_path, supported_by = primary_support(
        by_id, target, reachability.seeds, selected["primary_producer"]
    )
    reactions_on_path = set(supported_by.values())
    non_seed_states = states_on_path.difference(reachability.seeds)
    related = _related_producer_context(by_id, non_seed_states, reachability.seeds, selected)
    context = pathway_context(reactions)
    excluded = selected["excluded"]
    for state in non_seed_states:
        for reaction in context["potential_producers"].get(state, ()):
            if reaction not in excluded and reaction not in reachability.reaction_layers:
                related.setdefault(reaction, "unreachable potential producer")
    for reaction, category in context["target_neighbors"].get(target, {}).items():
        if reaction not in excluded:
            if reaction not in reachability.reaction_layers:
                category = f"{category} (unreachable)"
            related.setdefault(reaction, category)
    return Pathway(
        target,
        tuple(sorted(states_on_path)),
        tuple(sorted(reactions_on_path)),
        supported_by,
        {reaction: related[reaction] for reaction in sorted(related.keys() - reactions_on_path)},
    )


def producer_pathway(
    states: list[dict], reactions: list[dict], analysis: dict, *, target: str, via: str, mode: str
) -> ProducerPathway:
    """Trace one terminal producer while withholding its target from upstream supply."""
    by_id = {reaction["id"]: reaction for reaction in reactions}
    producer = by_id.get(via)
    if producer is None:
        raise ValueError(f"unknown saved producer reaction: {via}")
    if net_stoichiometry(producer, target) <= 0:
        raise ValueError(f"{via} does not produce {target} in net stoichiometry")
    excluded = analysis[mode]["excluded"]
    if via in excluded:
        reasons = ", ".join(
            dict.fromkeys(note.get("proposition") or note["condition"] for note in excluded[via])
        )
        raise ValueError(f"{via} is excluded in the {mode} pathway scope ({reasons})")

    upstream_states = {state["id"] for state in states} - {target}
    seeds = tuple(state for state in saved_reachability(analysis, mode).seeds if state != target)
    eligible = [reaction for reaction in reactions if reaction["id"] not in excluded]
    preference_exclusions = None
    if mode == "conditioned":
        eligible, reachability, preference_exclusions = _conditioned_producer_support(
            states,
            eligible,
            analysis,
            producer,
            upstream_states,
            seeds,
        )
    else:
        reachability = _indexed_reachability(upstream_states, eligible, seeds)
    if via not in reachability.reaction_layers:
        missing = sorted(
            {term["species"] for term in producer["reactants"]} - reachability.state_layers.keys()
        )
        raise ValueError(
            f"{via} cannot produce {target} independently in the {mode} scope. "
            f"With {target} withheld upstream, unreachable reactants: {', '.join(missing)}"
        )

    producers = _producer_index(eligible, reachability)
    primary = _primary_producers(producers, reachability, eligible, preference_exclusions)
    primary[target] = via
    path_states, supported_by = primary_support(by_id, target, seeds, primary)
    path_reactions = set(supported_by.values())
    return ProducerPathway(
        via,
        Pathway(
            target, tuple(sorted(path_states)), tuple(sorted(path_reactions)), supported_by, {}
        ),
        Reachability(
            seeds,
            {
                state: (
                    reachability.reaction_layers[via]
                    if state == target
                    else reachability.state_layers[state]
                )
                for state in sorted(path_states)
            },
            {
                reaction: reachability.reaction_layers[reaction]
                for reaction in sorted(path_reactions)
            },
        ),
        all(_passes_equation_and_energy(by_id[reaction]) for reaction in path_reactions),
    )


def _conditioned_producer_support(
    states: list[dict],
    eligible: list[dict],
    analysis: dict,
    producer: dict,
    upstream_states: set[str],
    seeds: tuple[str, ...],
) -> tuple[list[dict], Reachability, dict[str, list[dict]]]:
    preference_exclusions = _checked_exclusions(
        eligible,
        analysis["conditioned"]["unresolved"],
        analysis["unconfirmed_states"],
        _state_claim_references(states, "fail"),
    )
    # The terminal is fixed by the query. Prefer support that does not depend
    # on any earlier branch with a refuted participant.
    nonrefuted = [
        reaction
        for reaction in eligible
        if reaction is producer
        or not _has_refuted_participant(preference_exclusions.get(reaction["id"], ()))
    ]
    if _passes_equation_and_energy(producer):
        supported = [reaction for reaction in nonrefuted if _passes_equation_and_energy(reaction)]
        if len(supported) < len(nonrefuted):
            reachability = _indexed_reachability(upstream_states, supported, seeds)
            if producer["id"] in reachability.reaction_layers:
                return supported, reachability, preference_exclusions
    if len(nonrefuted) < len(eligible):
        reachability = _indexed_reachability(upstream_states, nonrefuted, seeds)
        if producer["id"] in reachability.reaction_layers:
            return nonrefuted, reachability, preference_exclusions
    return eligible, _indexed_reachability(upstream_states, eligible, seeds), preference_exclusions


def _indexed_target(
    states: list[dict], reachability: Reachability, produced_states: Collection[str]
) -> str | None:
    possible = [
        state
        for state in states
        if reachability.state_layers.get(state["id"], 0) > 0 and state["id"] in produced_states
    ]
    if not possible:
        return None
    return max(
        possible,
        key=lambda state: (
            _target_priority(state),
            reachability.state_layers[state["id"]],
            state["id"],
        ),
    )["id"]


def _producer_index(reactions: list[dict], reachability: Reachability) -> dict[str, list[str]]:
    producers: dict[str, list[str]] = {}
    for reaction in reactions:
        if reaction["id"] in reachability.reaction_layers:
            for state_id in _positive_products(reaction):
                if state_id in reachability.state_layers:
                    producers.setdefault(state_id, []).append(reaction["id"])
    return producers


def _primary_producers(
    producers: dict[str, list[str]],
    reachability: Reachability,
    reactions: list[dict],
    preference_exclusions: dict[str, list[dict]] | None,
) -> dict[str, str]:
    primary = {
        state_id: min(ids, key=lambda item: (reachability.reaction_layers[item], item))
        for state_id, ids in producers.items()
    }
    if preference_exclusions is not None:
        _prefer_supported_paths(primary, producers, reachability, reactions, preference_exclusions)
    return primary


def _has_refuted_participant(notes: Iterable[dict]) -> bool:
    return any("state" in note for note in notes)


def _prefer_supported_paths(
    primary: dict[str, str],
    producers: dict[str, list[str]],
    reachability: Reachability,
    reactions: list[dict],
    excluded: dict[str, list[dict]],
) -> None:
    """Within minimum depth, rank a path by its least supported step."""
    quality = {}
    for reaction in reactions:
        reasons = excluded.get(reaction["id"], ())
        if not reasons:
            strength = 2
        elif _has_refuted_participant(reasons):
            strength = -1
        else:
            strength = int(_passes_equation_and_energy(reaction))
        quality[reaction["id"]] = strength
    reactants = {
        reaction["id"]: {term["species"] for term in reaction["reactants"]}
        for reaction in reactions
    }
    supported = dict.fromkeys(reachability.seeds, 2)
    for state in sorted(producers, key=reachability.state_layers.__getitem__):
        if state in supported:
            continue
        rank, best = min(
            (
                -min(
                    quality[reaction], min((supported[s] for s in reactants[reaction]), default=2)
                ),
                reaction,
            )
            for reaction in producers[state]
            if reachability.reaction_layers[reaction] == reachability.state_layers[state]
        )
        primary[state] = best
        supported[state] = -rank


def _passes_equation_and_energy(reaction: dict) -> bool:
    assessments = reaction.get("assessments", {})
    return all(
        assessments.get(name, {}).get("verdict") == "pass"
        and assessments[name].get("proposition") == proposition
        for name, proposition in (
            ("conservation", "element_charge_conservation"),
            ("consistency", "equation_consistency"),
            ("energy", "collision_energy_necessary_condition"),
        )
    )


def primary_support(
    by_id: dict[str, dict], target: str, seeds: Collection[str], primary: dict[str, str]
) -> tuple[set[str], dict[str, str]]:
    """Follow selected producers back to supply for a reachable target."""
    states_on_path: set[str] = set()
    supported_by: dict[str, str] = {}
    pending = [target]
    while pending:
        state_id = pending.pop()
        if state_id in states_on_path:
            continue
        states_on_path.add(state_id)
        if state_id in seeds:
            continue
        producer = primary.get(state_id)
        if producer is None:
            continue
        supported_by[state_id] = producer
        pending.extend(term["species"] for term in by_id[producer]["reactants"])
    return states_on_path, supported_by


def pathway_context(reactions: list[dict]) -> dict:
    """Index producer and neighbor roles once for all saved pathway scopes."""
    potential_producers: dict[str, list[str]] = {}
    target_neighbors: dict[str, dict[str, str]] = {}
    for reaction in reactions:
        reaction_id = reaction["id"]
        for state in sorted(_participants(reaction)):
            delta = net_stoichiometry(reaction, state)
            if delta > 0:
                potential_producers.setdefault(state, []).append(reaction_id)
            else:
                target_neighbors.setdefault(state, {})[reaction_id] = (
                    "target consumer / return" if delta < 0 else "target-preserving / cycle context"
                )
    return {"potential_producers": potential_producers, "target_neighbors": target_neighbors}


def minimum_pathway_producers(selected: dict) -> dict[str, list[str]]:
    """Find producers whose reactants have strictly earlier minimum layers."""
    return {
        state: [
            reaction
            for reaction in producers
            if selected["reaction_layers"][reaction] == selected["state_layers"][state]
        ]
        for state, producers in selected["producer_ids"].items()
    }


def _related_producer_context(
    by_id: dict[str, dict],
    state_ids: set[str],
    seeds: tuple[str, ...],
    selected: dict,
) -> dict[str, str]:
    """Follow minimum producers upstream, keeping later producers as local context."""
    minimum_producers = minimum_pathway_producers(selected)
    producers = selected["producer_ids"]
    pending = list(state_ids)
    visited = set(seeds)
    related: dict[str, str] = {}
    while pending:
        state_id = pending.pop()
        if state_id in visited:
            continue
        visited.add(state_id)
        for reaction_id in producers.get(state_id, ()):
            related.setdefault(reaction_id, LATER_PRODUCER_CONTEXT)
        for reaction_id in minimum_producers.get(state_id, ()):
            if related.get(reaction_id) != MINIMUM_DEPTH_ALTERNATIVE:
                related[reaction_id] = MINIMUM_DEPTH_ALTERNATIVE
                pending.extend(term["species"] for term in by_id[reaction_id]["reactants"])
    return related


def _target_priority(state: dict) -> int:
    if state["id"] == "e" or "feed" in state.get("classes", []):
        return 0
    if int(state["charge"]) == 0 and state["state"]["kind"] == "ground":
        atom_count = sum(int(value) for value in state.get("composition", {}).values())
        return 3 if atom_count == 1 else 4
    if int(state["charge"]) != 0:
        return 2
    return 1


def _positive_products(reaction: dict) -> set[str]:
    species = {term["species"] for term in reaction["products"]}
    return {state_id for state_id in species if net_stoichiometry(reaction, state_id) > 0}


def _participants(reaction: dict) -> set[str]:
    return {term["species"] for term in (*reaction["reactants"], *reaction["products"])}


def net_stoichiometry(reaction: dict, state_id: str) -> float:
    """Project saved coefficients using the common declared-count arithmetic."""
    return stoichiometric_sum(
        sign * float(term["n"])
        for side, sign in (("products", 1), ("reactants", -1))
        for term in reaction[side]
        if term["species"] == state_id
    )
