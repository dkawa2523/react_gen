from __future__ import annotations

from plasma_reactgen.application.ports import RuleRepository
from plasma_reactgen.application.state_roles import derive_species_roles
from plasma_reactgen.domain.chemistry import has_property_value
from plasma_reactgen.domain.models import ReactionNetwork


def build_state_list(network: ReactionNetwork, rule_repo: RuleRepository) -> list[dict]:
    role_rules = rule_repo.get_role_required_properties().get("roles", {})
    roles_by_species = derive_species_roles(network)

    states: list[dict] = []
    for sid in sorted(network.species_nodes):
        node = network.species_nodes[sid]
        sp = network.species.get(sid)
        if sp is None:
            continue

        roles = roles_by_species[sid]
        required = sorted(_required_properties_for_roles(roles, role_rules))
        missing = [name for name in required if not has_property_value(sp, name)]

        states.append(
            {
                "id": sp.id,
                "charge": sp.charge,
                "composition": sp.composition,
                "classes": sorted(sp.classes),
                "depth_first_seen": node.depth_first_seen,
                "introduced_by": node.introduced_by,
                "roles": sorted(roles),
                "propagated": node.propagated,
                "required_properties": required,
                "missing_properties": sorted(missing),
                "status": sp.status,
            }
        )
    return states


def _required_properties_for_roles(roles: set[str], role_rules: dict) -> set[str]:
    required: set[str] = set()
    for role in roles:
        rule = role_rules.get(role, {})
        required.update(rule.get("required", []))
    return required
