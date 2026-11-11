"""Readable names for tables and figures derived from canonical result records."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any

from reactgen.chemistry import charged_formula
from reactgen.model import (
    EXACT_STATE_RELATION_OPERATIONS,
    THIRD_BODY,
    Term,
    numerical_requirements,
    side_key,
)
from reactgen.records import calculation_record_reference
from reactgen.selection import NUMERICAL_QUANTITIES

CalculationRecordIndex = dict[tuple[str, str], dict[str, dict]]


def state_name(state: dict) -> str:
    """Label a state for display; its canonical ID remains the exact identity."""
    if state["id"] == "e":
        return "e"
    name = charged_formula(state["composition"], state["charge"])
    kind, label = state["state"]["kind"], state["state"]["label"]
    if label:
        name += f"({label})"
    elif kind != "ground":
        suffix = {"vibrational": "v", "electronic": "*", "metastable": "m", "resonant": "r"}
        name += f"({suffix.get(kind, kind)})"
    if state["phase"] != "gas":
        name += f" [{state['phase']}]"
    if state["structure"] is not None:
        name += f" [{state['structure']}]"
    return name


def state_meaning(state: dict) -> str:
    """Explain the declared representation without assessing its physical support."""
    return (
        f"{state['phase']}; {state['state']['kind']}; "
        f"{state['state']['resolution']}; structure={state['structure'] or 'unspecified'}"
    )


def reaction_equation(reaction: dict, names: Mapping[str, str]) -> str:
    """Show stoichiometry with readable state names and explicit environment terms."""
    left = _reaction_side(reaction, "reactants", names)
    right = _reaction_side(reaction, "products", names)
    return f"{left} → {right}"


def diagram_terms(reaction: dict, side: str) -> tuple[Term, ...]:
    """Stoichiometric participants of a drawn side, including the unchanged third body."""
    terms = tuple(Term(**term) for term in reaction[side])
    combined = tuple(Term(*term) for term in side_key(terms))
    return (*combined, Term(THIRD_BODY)) if reaction.get("third_body") else combined


def _reaction_side(reaction: dict, side: str, names: Mapping[str, str]) -> str:
    terms = [
        str(Term(names.get(term["species"], term["species"]), term["n"])) for term in reaction[side]
    ]
    if reaction.get("third_body"):
        terms.append(THIRD_BODY)
    if side == "reactants" and reaction.get("surface"):
        terms.append(f"[{reaction['surface']}]")
    return " + ".join(terms) if terms else "∅"


def requirement_summary(
    inputs: Sequence[str], transforms: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    """Read historical string requirements through their single boundary adapter."""
    assigned = numerical_requirements(inputs, transforms, "historical result", "")
    return _requirement_groups(
        {"responsibility": item.responsibility, "quantity": item.quantity} for item in assigned
    )


def saved_requirement_summary(result: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Display saved work responsibilities; no scientific meaning is inferred here."""
    if "requirements" not in result:
        return requirement_summary(
            result.get("required_inputs", ()), result.get("required_transforms", ())
        )
    return _requirement_groups(result["requirements"])


def _requirement_groups(requirements: Iterable[Mapping[str, str]]) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {
        "user_inputs": [],
        "source_information": [],
        "source_selection": [],
        "external_models": [],
        "unsupported_inputs": [],
        "transforms": [],
    }
    for requirement in requirements:
        result.setdefault(requirement["responsibility"], []).append(requirement["quantity"])
    return {name: tuple(sorted(set(values))) for name, values in result.items()}


def numerical_records(reaction: dict) -> list[dict]:
    """Return saved offered records, preserving competing declarations and sources."""
    evidence = reaction.get("evidence", {})
    return [
        *evidence.get("overlay_datasets", []),
        *(
            dataset
            for record in evidence.get("records", [])
            for dataset in record.get("datasets", [])
        ),
    ]


def conditions_text(conditions: Mapping[str, object]) -> str:
    """Show declared conditions; missing conditions are never silently supplied."""
    labels = {
        "gas_temperature_K": ("gas temperature", "K"),
        "electron_temperature_eV": ("electron temperature", "eV"),
        "reduced_field_Td": ("reduced field", "Td"),
        "ion_energy_eV": ("ion energy", "eV"),
        "ion_temperature_K": ("ion temperature", "K"),
        "surface_temperature_K": ("surface temperature", "K"),
        "electron_energy_eV": ("electron energy", "eV"),
        "collision_energy_eV": ("collision energy", "eV"),
    }
    roles = {
        "collision_energy_frame": "collision frame",
        "projectile_state": "projectile",
        "target_state": "target",
        "target_at_rest": "stationary target",
    }
    descriptions = [
        f"{labels[key][0]} = {value:g} {labels[key][1]}"
        if key in labels and isinstance(value, int | float)
        else f"{roles.get(key, key)} = {value}"
        for key, value in sorted(conditions.items())
        if key != "collision_pairs" and value is not None
    ]
    pairs = conditions.get("collision_pairs")
    if isinstance(pairs, list) and pairs:
        descriptions.extend(
            f"{pair['projectile_state']} on {pair['target_state']} at "
            f"{pair['collision_energy_eV']:g} eV ({pair['collision_energy_frame']})"
            for pair in pairs[:3]
        )
        if len(pairs) > 3:
            descriptions.append(f"{len(pairs) - 3} more pairs in saved conditions")
    return "; ".join(descriptions) or "none supplied"


def exploration_status_text(generation: Mapping[str, object]) -> str:
    """Describe saved generation scope separately from pathway eligibility."""
    limits = generation.get("limits")
    focused = isinstance(limits, Mapping) and limits.get("expand_unresolved_states") is False
    scope = (
        " Mechanical expansion uses resolved states and explicit gas supplies." if focused else ""
    )
    if generation.get("complete") is False:
        reasons: dict[str, None] = {}
        reason = generation.get("stop_reason")
        if isinstance(reason, str) and reason and reason != "closure":
            reasons[reason] = None
        tasks = generation.get("unexpanded")
        if isinstance(tasks, list | tuple):
            for task in tasks:
                if reason := task.get("reason"):
                    reasons[reason] = None
        if generation.get("gaps") and not any("generation gaps" in reason for reason in reasons):
            reasons["mechanical operations unavailable; see generation gaps"] = None
        if len(reasons) > 1:
            reason_text = ", ".join(reasons)
            return f"Partial candidate exploration. Recorded limits and gaps: {reason_text}.{scope}"
        reason = next(iter(reasons), "reason not recorded")
        return f"Partial candidate exploration. Recorded stop reason: {reason}.{scope}"
    if generation.get("complete") is True:
        return f"Candidate exploration completed within the configured scope.{scope}"
    return f"Candidate exploration status was not recorded.{scope}"


def missing_collision_state_notes(document: dict) -> list[str]:
    """Identify declared pairs that cannot be represented by the saved state inventory."""
    conditions = document["input"].get("conditions", {})
    pairs = conditions.get("collision_pairs") or [conditions]
    state_ids = {state["id"] for state in document["states"]}
    notes = []
    for pair in pairs:
        projectile, target = pair.get("projectile_state"), pair.get("target_state")
        if projectile is None or target is None:
            continue
        if missing := sorted({projectile, target} - state_ids):
            notes.append(
                f"Collision pair {projectile} on {target} has no saved state for "
                f"{', '.join(missing)}."
            )
    return notes


def analysis_overview(document: dict) -> list[str]:
    """Show the analysis scope and a few saved outcomes before inspection commands."""
    summary = document["summary"]
    generation = document["metadata"]["generation"]
    lines = [
        f"Targets: {', '.join(document['input']['gases'])}",
        f"Conditions: {conditions_text(document['input'].get('conditions', {}))}",
        f"Candidates: {summary['state_count']} states; {summary['reaction_count']} reactions",
        f"Usable coefficients: {summary['data_use'].get('coefficient', 0)} "
        f"of {summary['reaction_count']} candidate reactions",
    ]
    energy = summary["judgments"]["reactions"].get("energy")
    if energy is not None:
        counts = (
            f"{energy.get(verdict, 0)} {label}"
            for verdict, label in (
                ("pass", "pass"),
                ("fail", "fail"),
                ("unknown", "unknown"),
                ("not_applicable", "outside scope"),
            )
        )
        lines.append("Collision-energy check: " + ", ".join(counts))
    conditions = document["input"].get("conditions", {})
    if (
        (
            conditions.get("collision_pairs")
            or (conditions.get("projectile_state") and conditions.get("target_state"))
        )
        and energy is not None
        and energy.get("not_applicable", 0) == summary["reaction_count"]
    ):
        lines.append("No saved reaction received a collision-energy check for these conditions.")
    if missing_states := missing_collision_state_notes(document):
        lines.extend(missing_states[:3])
        if len(missing_states) > 3:
            lines.append(f"{len(missing_states) - 3} more pairs lack saved states.")
    lines.extend(_pathway_overview(document))
    if not generation["complete"] or generation["limits"].get("expand_unresolved_states") is False:
        lines.append(exploration_status_text(generation))
    if gaps := generation.get("gaps", []):
        gap = gaps[0]
        lines.extend(
            (
                f"Generation operations with recorded limitations: {len(gaps)}",
                f"  {gap['operation']}: {gap['target']}; {gap['reason']}",
            )
        )
    return lines


def _pathway_overview(document: dict) -> list[str]:
    pathways = document.get("pathways")
    if pathways is None:
        return []
    names = {state["id"]: state_name(state) for state in document["states"]}
    seeds = set(pathways["seeds"])
    conditioned = pathways["conditioned"]
    reached = set(conditioned["state_layers"]) - seeds
    lines = [
        "Supplied particles: " + ", ".join(names[state_id] for state_id in sorted(seeds)),
        f"Conditioned pathways: {len(reached)} additional states reachable; "
        f"{len(conditioned['excluded'])} reactions excluded by saved necessary checks.",
    ]
    if (
        not reached
        and "e" not in seeds
        and any(item["family"] == "electron" for item in document["reactions"])
    ):
        lines.append(
            "For an electron feed, use --supply e or supplies: [e]. "
            "Otherwise electron paths need a preceding electron-producing reaction."
        )
    return lines


def registered_records(
    document: dict, target: str, quantity: str | None = None, *, detail: bool = False
) -> dict:
    """Show source records and any saved evaluations for source selection."""
    candidates = (*document["states"], *document["reactions"])
    found = next((item for item in candidates if item["id"] == target), None)
    context: dict[str, Any] = {}
    if found is None:
        archived = [
            record
            for record in document.get("scientific_records", {}).values()
            if record.get("calculation_target") == target
        ]
        if not archived and target not in document.get("metadata", {}).get(
            "calculation_reference_state_ids", ()
        ):
            raise ValueError(f"target is absent from the saved result: {target}")
        context["target_scope"] = "calculation_reference"
        records = _state_quantity_records(
            [record | {"record_ref": calculation_record_reference(record)} for record in archived],
            quantity,
        )
    elif "data_use" in found:
        use = found["data_use"]
        records = numerical_records(found)
        if quantity is not None:
            records = [record for record in records if record.get("kind") == quantity]
        if records or quantity is None or quantity in NUMERICAL_QUANTITIES:
            assessed = {item["dataset_id"]: item for item in use["datasets"]}
            records = [
                record | {"native_evaluation": assessed[record["id"]]}
                if record.get("id") in assessed
                else record
                for record in records
            ]
            fields: tuple[str, ...] = ("status", "reason", "dataset_id", "kind", "scope")
            if use["status"] == "coefficient":
                fields += ("value", "unit")
            if detail:
                fields += ("selection", "disagreements", "requirements")
            context["coefficient_use"] = {key: use[key] for key in fields if key in use}
        records += reaction_calculation_records(calculation_record_index(document), found, quantity)
    else:
        evidence = found["evidence"]
        records = [
            record | {"target_match": evidence.get("match", "unknown")}
            for record in evidence.get("records", [])
        ] + [record | {"target_match": "related"} for record in evidence.get("related_records", [])]
        records = _state_quantity_records(
            [record | {"record_ref": calculation_record_reference(record)} for record in records],
            quantity,
        )
    if found is not None:
        _append_assessment_record_sources(document, found, quantity, records)
    if not detail:
        records = [_compact_record(record) for record in records]
    return {
        "target": target,
        "quantity": quantity,
        **context,
        "records": records,
        "interpretation": (
            "These are saved source declarations. Use record_ref for an exact state or direct "
            "energy declaration, or a dataset id, with data_selection.targets. Direct endpoint "
            "relations can use the source direction or its reversal. An energy_role of "
            "derived traces a calculation input; declaration identifies a matching record "
            "without a saved calculation use. Listing does not qualify a record. "
            "State target_match distinguishes exact, compatible and related identities; "
            "selection does not make a related target applicable to the requested state."
        )
        + (
            " Native evaluation refers to the source quantity. Coefficient use is the "
            "saved decision for the channel and can refer to another quantity than requested."
            if "coefficient_use" in context
            else ""
        ),
    }


def _append_assessment_record_sources(
    document: dict, subject: dict, quantity: str | None, records: list[dict]
) -> None:
    uses = [
        (layer, assessment["proposition"], term)
        for layer, assessment in subject.get("assessments", {}).items()
        for term in assessment.get("record_inputs", ())
        if quantity is None or term["quantity"] == quantity
    ]
    if not uses:
        return
    index = calculation_record_index(document)
    by_ref = {record["record_ref"]: record for record in records if "record_ref" in record}
    for layer, proposition, term in uses:
        ref = term["record_ref"]
        if ref not in by_ref:
            source = calculation_source(index, term)
            if source is None:
                continue
            record = source | {"record_ref": ref}
            if quantity is not None:
                for collection in ("properties", "energy_properties"):
                    if quantity in record.get(collection, {}):
                        record[collection] = {quantity: record[collection][quantity]}
            records.append(record)
            by_ref[ref] = record
        by_ref[ref].setdefault("assessment_uses", []).append(
            {
                "layer": layer,
                "proposition": proposition,
                "target": term["target"],
                "quantity": term["quantity"],
            }
        )


def calculation_record_index(document: dict) -> CalculationRecordIndex:
    """Index records against the target under which a calculation could cite them."""
    sources: CalculationRecordIndex = {}

    def add(target: str, record_id: str, record: dict) -> None:
        if record.get("properties") or record.get("energy_properties") or record.get("thermo"):
            sources.setdefault((target, record_id), {}).setdefault(
                calculation_record_reference(record), record
            )

    for state in document["states"]:
        for record in state.get("evidence", {}).get("records", ()):
            add(state["id"], record.get("record_id", record.get("id")), record)
    for reaction in document["reactions"]:
        for record in reaction.get("evidence", {}).get("records", ()):
            add(record["id"], record["id"], record)
    for record in document.get("scientific_records", {}).values():
        target = record.get("calculation_target")
        if isinstance(target, str):
            add(target, record["record_id"], record)
        elif (record_id := record.get("id")) is not None:
            add(record_id, record_id, record)
    return sources


def _calculation_quantity(record: dict, quantity: str) -> dict | None:
    if quantity == "thermochemical_model":
        value = record.get("thermo")
    else:
        value = record.get("properties", {}).get(quantity) or record.get(
            "energy_properties", {}
        ).get(quantity)
    return value if isinstance(value, dict) else None


def calculation_source_offers(index: CalculationRecordIndex, term: dict) -> dict[str, dict]:
    """Find archived declarations for the specified target, portable ID and quantity."""
    quantity = term.get("quantity", "")
    offered = index.get((term.get("target", ""), term.get("record_id", "")), {})
    return {
        ref: record
        for ref, record in offered.items()
        if _calculation_quantity(record, quantity) is not None
    }


def calculation_source(index: CalculationRecordIndex, term: dict) -> dict | None:
    """Resolve the exact record, with a unique evidence-based fallback for older results."""
    offered = calculation_source_offers(index, term)
    fields = {"source_value": "value", "source_unit": "unit"}
    matched = [
        record
        for ref, record in offered.items()
        if ("record_ref" not in term or term["record_ref"] == ref)
        and (quantity := _calculation_quantity(record, term["quantity"])) is not None
        and all(term[key] == quantity.get(field) for key, field in fields.items() if key in term)
        and all(
            term[key] == (quantity.get("provenance") or {}).get(key)
            for key in ("provider", "collection")
            if term.get(key) is not None
        )
    ]
    return matched[0] if len(matched) == 1 else None


def reaction_calculation_records(
    index: CalculationRecordIndex, reaction: dict, quantity: str | None = None
) -> list[dict]:
    """Project saved calculation inputs and matching direct channel declarations."""
    declarations = {
        (record["id"], calculation_record_reference(record)): record
        for record in reaction.get("evidence", {}).get("records", ())
        if (
            (quantity is None and record.get("energy_properties"))
            or quantity in record.get("energy_properties", {})
        )
    }
    records = declarations.copy()
    uses: dict[tuple[str, str], list[dict]] = {}
    for term, use in calculation_uses(reaction):
        if (
            quantity is not None
            and quantity not in {use["quantity"], use["calculation"]}
            and not (
                quantity == "delta_e_eV"
                and (
                    use["calculation"] == "state_energy_difference_eV"
                    or use["calculation"].startswith("level_gap_")
                )
            )
        ):
            continue
        source = calculation_source(index, term)
        if source is None:
            continue
        key = (term["target"], term.get("record_ref") or calculation_record_reference(source))
        records.setdefault(key, source)
        recorded = uses.setdefault(key, [])
        if use not in recorded:
            recorded.append(use)

    output = []
    for key, record in records.items():
        recorded = uses.get(key, [])
        roles = {use["role"] for use in recorded}
        role = next((name for name in ("direct", "derived") if name in roles), "declaration")
        quantities = {use["quantity"] for use in recorded}
        if key in declarations:
            offered = record["energy_properties"].keys()
            quantities.update(offered if quantity is None else offered & {quantity})
        projected = record | {"record_ref": key[1], "energy_role": role, "energy_uses": recorded}
        for collection in ("properties", "energy_properties"):
            if collection in projected:
                projected[collection] = {
                    name: value
                    for name, value in projected[collection].items()
                    if name in quantities
                }
        if "thermochemical_model" not in quantities:
            projected.pop("thermo", None)
        output.append(projected)
    return output


def calculation_uses(reaction: dict) -> Iterator[tuple[dict, dict]]:
    """Yield saved selected and alternative uses, without resolving new sources."""
    for name, result in reaction.get("thermochemical_calculations", {}).items():
        selected = (("selected", result),) if result.get("status") == "computed" else ()
        alternatives = (("alternative", item) for item in result.get("alternatives", ()))
        for status, offer in (*selected, *alternatives):
            operation = offer.get("operation")
            for term in offer.get("inputs", ()):
                if "record_id" not in term:
                    continue
                role = (
                    "direct"
                    if name == "state_energy_difference_eV"
                    and operation in EXACT_STATE_RELATION_OPERATIONS
                    else "derived"
                )
                yield (
                    term,
                    {
                        "calculation": name,
                        "operation": operation,
                        "status": status,
                        "role": role,
                        "target": term.get("target"),
                        "quantity": term["quantity"],
                        "coefficient": term.get("coefficient"),
                    },
                )


def _compact_record(record: dict) -> dict:
    """Show selectable identity, content and qualification before raw history."""
    names = (
        "record_id",
        "record_ref",
        "calculation_target",
        "target_match",
        "id",
        "kind",
        "observable",
        "channel_scope",
        "form",
        "unit",
        "params",
        "parameters",
        "reaction_order",
        "validity",
        "provenance",
        "method",
        "status",
        "tier",
        "review_scope",
        "equation_key",
        "energy_role",
        "energy_uses",
        "assessment_uses",
    )
    output = {name: record[name] for name in names if name in record and record[name] is not None}
    if native := record.get("native_evaluation"):
        output["native_evaluation"] = {
            key: native[key]
            for key in ("status", "reason", "value", "unit", "scope")
            if key in native and native[key] is not None
        }
    if candidate := record.get("candidate"):
        output.update(
            record_target=candidate["id"],
            phase=candidate["phase"],
            structure=candidate.get("structure"),
            state=candidate["state"],
        )
    for collection in ("properties", "energy_properties"):
        if collection not in record:
            continue
        output[collection] = {
            name: {
                key: value
                for key, value in prop.items()
                if key != "source_declaration" and value is not None
            }
            for name, prop in record[collection].items()
        }
    if model := record.get("thermo"):
        output["thermochemical_model"] = {
            name: model[name]
            for name in (
                "t_min",
                "t_mid",
                "t_max",
                "phase",
                "standard_pressure_Pa",
                "method",
                "tier",
                "status",
                "review_scope",
                "provenance",
            )
            if name in model
        }
    return output


def _state_quantity_records(records: list[dict], quantity: str | None) -> list[dict]:
    if quantity is None:
        return records
    if quantity == "thermochemical_model":
        return [record for record in records if record.get("thermo") is not None]
    return [
        record | {"properties": {quantity: record["properties"][quantity]}}
        for record in records
        if quantity in record.get("properties", {})
    ]
