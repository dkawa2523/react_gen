from __future__ import annotations

from plasma_reactgen.application.ports import RuleRepository
from plasma_reactgen.domain.chemistry import has_property_value
from plasma_reactgen.domain.models import ReactionNetwork, Species


def build_state_list(network: ReactionNetwork, rule_repo: RuleRepository) -> list[dict]:
    role_rules = rule_repo.get_role_required_properties().get("roles", {})
    _assign_roles_from_reactions(network)

    states: list[dict] = []
    for sid in sorted(network.species_nodes):
        node = network.species_nodes[sid]
        sp = network.species.get(sid)
        if sp is None:
            continue

        required = sorted(_required_properties_for_roles(node.roles, role_rules))
        missing = [name for name in required if not has_property_value(sp, name)]

        states.append(
            {
                "id": sp.id,
                "charge": sp.charge,
                "composition": sp.composition,
                "classes": sorted(sp.classes),
                "depth_first_seen": node.depth_first_seen,
                "introduced_by": node.introduced_by,
                "roles": sorted(node.roles),
                "propagated": node.propagated,
                "required_properties": required,
                "missing_properties": sorted(missing),
                "status": sp.status,
            }
        )
    return states


def _assign_roles_from_reactions(network: ReactionNetwork) -> None:
    for rxn in network.reactions:
        if rxn.family == "electron":
            for amount in rxn.reactants:
                if amount.species != "e" and amount.species in network.species_nodes:
                    network.species_nodes[amount.species].roles.add("electron_target")

        if rxn.family == "ion_neutral":
            for amount in rxn.reactants:
                sid = amount.species
                if sid == "e" or sid not in network.species_nodes or sid not in network.species:
                    continue
                sp = network.species[sid]
                if sp.charge == 0:
                    network.species_nodes[sid].roles.update({"ion_neutral_target", "dnt_neutral"})
                else:
                    network.species_nodes[sid].roles.update({"ion_neutral_projectile", "dnt_ion"})


def _required_properties_for_roles(roles: set[str], role_rules: dict) -> set[str]:
    required: set[str] = set()
    for role in roles:
        rule = role_rules.get(role, {})
        required.update(rule.get("required", []))
    return required
