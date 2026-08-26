"""Pure target-centred reachability over reaction hypergraphs."""

from __future__ import annotations

from dataclasses import dataclass

_EPSILON = 1.0e-12


@dataclass(frozen=True)
class Reachability:
    """Minimum AND-hypergraph distance from the feed states."""

    seeds: tuple[str, ...]
    state_layers: dict[str, int]
    reaction_layers: dict[str, int]


@dataclass(frozen=True)
class Pathway:
    """One deterministic shortest support hyperpath for a target state."""

    target: str | None
    state_ids: tuple[str, ...]
    reaction_ids: tuple[str, ...]
    supported_by: dict[str, str]
    related_reaction_ids: tuple[str, ...]


def feed_state_ids(states: list[dict]) -> tuple[str, ...]:
    """Return electron and explicitly marked input-gas states."""

    return tuple(
        sorted(
            state["id"]
            for state in states
            if state["id"] == "e" or "feed" in state.get("classes", [])
        )
    )


def reaction_reachability(states: list[dict], reactions: list[dict]) -> Reachability:
    """Compute minimum production layers without using candidate generation depth.

    A reaction is reachable only after every explicit reactant is reachable. Only
    positive net products introduce a new state, so elastic and identity-preserving
    collisions cannot manufacture a pathway.
    """

    state_ids = {state["id"] for state in states}
    seeds = feed_state_ids(states)
    state_layers = dict.fromkeys(seeds, 0)
    reaction_layers: dict[str, int] = {}
    ordered = sorted(reactions, key=lambda reaction: reaction["id"])

    for _ in range(max(1, len(states) + 1)):
        changed = False
        for reaction in ordered:
            reactants = {term["species"] for term in reaction["reactants"]}
            if not reactants.issubset(state_layers):
                continue
            layer = 1 + max((state_layers[state_id] for state_id in reactants), default=0)
            previous = reaction_layers.get(reaction["id"])
            if previous is None or layer < previous:
                reaction_layers[reaction["id"]] = layer
            for state_id in _positive_products(reaction):
                if state_id not in state_ids:
                    continue
                old_layer = state_layers.get(state_id)
                if old_layer is None or layer < old_layer:
                    state_layers[state_id] = layer
                    changed = True
        if not changed:
            break
    return Reachability(seeds, state_layers, reaction_layers)


def choose_pathway_target(
    states: list[dict], reactions: list[dict], reachability: Reachability | None = None
) -> str | None:
    """Choose a useful deterministic example target for the static PNG."""

    reachability = reachability or reaction_reachability(states, reactions)
    state_by_id = {state["id"]: state for state in states}
    candidates = [
        state_id
        for state_id, layer in reachability.state_layers.items()
        if layer > 0 and _shortest_producers(state_id, reactions, reachability)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda state_id: (
            _target_priority(state_by_id[state_id]),
            reachability.state_layers[state_id],
            state_id,
        ),
    )


def select_pathway(
    states: list[dict],
    reactions: list[dict],
    *,
    target: str | None = None,
    reachability: Reachability | None = None,
) -> Pathway:
    """Select one evidence-aware tie-break among equally short producer routes."""

    reachability = reachability or reaction_reachability(states, reactions)
    target = target or choose_pathway_target(states, reactions, reachability)
    if target is None or target not in reachability.state_layers:
        return Pathway(None, (), (), {}, ())

    states_on_path: set[str] = set()
    reactions_on_path: set[str] = set()
    supported_by: dict[str, str] = {}

    def visit(state_id: str) -> None:
        if state_id in states_on_path:
            return
        states_on_path.add(state_id)
        if state_id in reachability.seeds:
            return
        producers = _shortest_producers(state_id, reactions, reachability)
        if not producers:
            return
        reaction = min(producers, key=_producer_key)
        reactions_on_path.add(reaction["id"])
        supported_by[state_id] = reaction["id"]
        state_layer = reachability.state_layers[state_id]
        for term in reaction["reactants"]:
            reactant = term["species"]
            if reachability.state_layers.get(reactant, state_layer) < state_layer:
                visit(reactant)

    visit(target)
    related = _related_reactions(
        reactions,
        reactions_on_path,
        states_on_path.difference(reachability.seeds),
        target,
    )
    return Pathway(
        target,
        tuple(sorted(states_on_path)),
        tuple(sorted(reactions_on_path)),
        supported_by,
        tuple(related),
    )


def _related_reactions(
    reactions: list[dict],
    path_reactions: set[str],
    non_seed_path_states: set[str],
    target: str,
) -> list[str]:
    related = []
    for reaction in reactions:
        if reaction["id"] in path_reactions:
            continue
        produces_support = bool(_positive_products(reaction).intersection(non_seed_path_states))
        target_delta = _net_stoichiometry(reaction, target)
        mentions_target = target in {
            term["species"] for term in (*reaction["reactants"], *reaction["products"])
        }
        if (
            produces_support
            or target_delta < -_EPSILON
            or (mentions_target and abs(target_delta) <= _EPSILON)
        ):
            related.append(reaction["id"])
    return sorted(related)


def _shortest_producers(
    state_id: str, reactions: list[dict], reachability: Reachability
) -> list[dict]:
    state_layer = reachability.state_layers.get(state_id)
    if state_layer is None:
        return []
    return [
        reaction
        for reaction in reactions
        if state_id in _positive_products(reaction)
        and reachability.reaction_layers.get(reaction["id"]) == state_layer
    ]


def _producer_key(reaction: dict) -> tuple:
    assessments = reaction.get("assessments", {})
    verdict_score = {"pass": 0, "not_applicable": 1, "unknown": 2, "fail": 3}
    return (
        tuple(
            verdict_score.get(assessments.get(layer, {}).get("verdict", "unknown"), 2)
            for layer in (
                "consistency",
                "state",
                "thermochemistry",
                "reaction_evidence",
                "kinetics",
            )
        ),
        reaction["id"],
    )


def _target_priority(state: dict) -> int:
    if state["id"] == "e" or "feed" in state.get("classes", []):
        return 0
    if int(state["charge"]) == 0 and state["state"]["kind"] == "ground":
        classes = {str(value).lower() for value in state.get("classes", [])}
        atom_count = sum(int(value) for value in state.get("composition", {}).values())
        return 3 if "radical" in classes or atom_count == 1 else 4
    if int(state["charge"]) != 0:
        return 2
    return 1


def _positive_products(reaction: dict) -> set[str]:
    species = {term["species"] for term in reaction["products"]}
    return {state_id for state_id in species if _net_stoichiometry(reaction, state_id) > _EPSILON}


def _net_stoichiometry(reaction: dict, state_id: str) -> float:
    products = sum(float(term["n"]) for term in reaction["products"] if term["species"] == state_id)
    reactants = sum(
        float(term["n"]) for term in reaction["reactants"] if term["species"] == state_id
    )
    return products - reactants
