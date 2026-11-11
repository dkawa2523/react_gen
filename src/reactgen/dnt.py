"""Project saved ion-neutral candidates and their declarations for DNT preprocessing."""

from collections import defaultdict
from math import isfinite

from reactgen.reaction_tables import energy_values

_TARGET_PROPERTIES = {"polarizability_A3": "A3", "dipole_moment_D": "D", "collision_radius_A": "A"}
_JUDGMENTS = ("conservation", "consistency", "state", "energy", "reaction_evidence")


def dnt_inputs(document: dict) -> dict:
    """Retain binary candidates and saved evidence without choosing a solver model."""
    states = {row["id"]: row for row in document["states"]}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    used_states: set[str] = set()
    for reaction in document["reactions"]:
        pair = _ion_neutral_pair(reaction, states)
        if pair is None:
            continue
        groups[pair].append(_channel(document, reaction))
        used_states.update(pair)
        used_states.update(term["species"] for term in reaction["products"])

    pairs = [
        _pair(states[ion], states[target], channels)
        for (ion, target), channels in sorted(groups.items())
    ]
    metadata = document["metadata"]
    return {
        "format": "reactgen_dnt_preprocessing",
        "schema_version": 1,
        "analysis": {
            "name": document["input"].get("name"),
            "result_schema_version": metadata["schema_version"],
            "evidence_snapshot_hash": metadata.get("evidence_snapshot_hash"),
            "generation_complete": metadata["generation"]["complete"],
            "conditions": document["input"].get("conditions", {}),
        },
        "pairs": pairs,
        "states": [
            {
                key: states[state][key]
                for key in ("id", "composition", "charge", "state", "structure")
            }
            for state in sorted(used_states)
        ],
    }


def _ion_neutral_pair(reaction: dict, states: dict[str, dict]) -> tuple[str, str] | None:
    terms = reaction["reactants"]
    if (
        reaction["family"] != "ion"
        or reaction.get("surface") is not None
        or reaction.get("third_body") is not None
        or reaction.get("stabilization") not in {None, "unspecified", "isolated"}
        or len(terms) != 2
        or any(term["n"] != 1 for term in terms)
        or any(
            reaction["assessments"].get(name, {}).get("verdict") != "pass"
            for name in ("conservation", "consistency")
        )
    ):
        return None
    left, right = (states[term["species"]] for term in terms)
    products = (states[term["species"]] for term in reaction["products"])
    if any(state["phase"] != "gas" for state in (left, right, *products)):
        return None
    ion, target = (left, right) if left["charge"] else (right, left)
    return (ion["id"], target["id"]) if ion["charge"] and not target["charge"] else None


def _pair(ion: dict, target: dict, channels: list[dict]) -> dict:
    ion_mass = _property(ion, "mass_amu", "amu")
    target_mass = _property(target, "mass_amu", "amu")
    properties = {
        quantity: _property(target, quantity, unit) for quantity, unit in _TARGET_PROPERTIES.items()
    }
    m_ion, m_target = ion_mass["value"], target_mass["value"]
    dipole = properties["dipole_moment_D"]["value"]
    return {
        "projectile": {"state": ion["id"], "mass_amu": ion_mass},
        "target": {"state": target["id"], "mass_amu": target_mass, **properties},
        "reduced_mass_amu": (
            m_ion * m_target / (m_ion + m_target)
            if m_ion is not None and m_target is not None
            else None
        ),
        "neutral_dipole_model_hint": (
            None if dipole is None else ("dnt_plus" if dipole == 0 else "dnt_plus_dm")
        ),
        "channels": sorted(channels, key=lambda row: (row["process"], row["reaction_id"])),
    }


def _property(state: dict, quantity: str, unit: str) -> dict:
    declarations = []
    evidence = state["evidence"]
    for record in evidence["records"] if evidence["match"] == "exact" else ():
        prop = record["properties"].get(quantity)
        if prop is not None:
            declarations.append(
                {"record_id": record.get("record_id", record["id"])}
                | {
                    key: prop.get(key)
                    for key in (
                        "value",
                        "unit",
                        "source",
                        "status",
                        "tier",
                        "qualifier",
                        "uncertainty",
                    )
                }
            )
    values = {
        row["value"]
        for row in declarations
        if row["unit"] == unit
        and row["source"]
        and row["qualifier"] in {None, "exact"}
        and row["status"] in {"reviewed", "imported"}
        and isinstance(row["value"], int | float)
        and not isinstance(row["value"], bool)
        and isfinite(row["value"])
        and (row["value"] >= 0 if quantity == "dipole_moment_D" else row["value"] > 0)
    }
    return {
        "value": next(iter(values)) if len(values) == 1 else None,
        "unit": unit,
        "status": "declared" if len(values) == 1 else ("conflict" if values else "unavailable"),
        "declarations": sorted(declarations, key=lambda row: row["record_id"]),
    }


def _channel(document: dict, reaction: dict) -> dict:
    calculations = reaction.get("thermochemical_calculations", {})
    difference = calculations.get("state_energy_difference_eV", {})
    collision = energy_values(document, reaction)
    return {
        "reaction_id": reaction["id"],
        "process": reaction["process"],
        "stabilization": reaction.get("stabilization"),
        "products": reaction["products"],
        "judgments": {
            name: reaction["assessments"][name]["verdict"]
            for name in _JUDGMENTS
            if name in reaction["assessments"]
        },
        "endpoint_difference": {
            key: difference.get(key) for key in ("value", "unit", "status", "inputs")
        },
        "declared_threshold_eV": reaction.get("thermochemistry", {}).get("threshold_eV"),
        "threshold_records": [
            {
                "record_id": record["id"],
                "channel_scope": record.get("channel_scope"),
                "review_scope": record.get("review_scope", []),
                "source": record.get("source"),
                "quantity": {
                    key: threshold.get(key)
                    for key in ("value", "unit", "qualifier", "uncertainty", "definition", "source")
                },
            }
            for record in reaction.get("evidence", {}).get("records", ())
            if (threshold := record.get("energy_properties", {}).get("threshold_eV")) is not None
        ],
        "collision_energy_com_eV": collision["relative_collision_energy_eV"],
        "collision_input": collision["collision_input"],
    }
