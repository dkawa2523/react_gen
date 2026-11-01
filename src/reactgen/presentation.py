"""Readable names for tables and figures derived from canonical result records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from reactgen.chemistry import charged_formula
from reactgen.model import THIRD_BODY, Term, numerical_requirements


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
    return (
        "; ".join(
            f"{labels[key][0]} = {value} {labels[key][1]}" if key in labels else f"{key} = {value}"
            for key, value in sorted(conditions.items())
            if value is not None
        )
        or "none supplied"
    )


def analysis_overview(document: dict, work: dict) -> list[str]:
    """Describe saved conclusions before counts, internal history, and file paths.

    The short examples are bounded display samples of saved usable coefficients,
    not a selected mechanism or a new judgment of reaction occurrence.
    """
    names = {state["id"]: state_name(state) for state in document["states"]}
    reactions = sorted(document["reactions"], key=lambda item: item["id"])
    usable = [item for item in reactions if item["data_use"]["status"] == "coefficient"]
    lines = [
        f"Targets: {', '.join(document['input']['gases'])}",
        f"Conditions: {conditions_text(document['input'].get('conditions', {}))}",
        f"Usable coefficients: {len(usable)} of {len(reactions)} saved candidate reactions",
    ]
    generation = document["metadata"]["generation"]
    unsupported = [
        gas
        for gas, scope in sorted(generation.get("input_scope", {}).items())
        if scope == "formula_only"
    ]
    if unsupported:
        lines.append(
            "Mechanical bond splitting is outside the supported formula grammar for: "
            + ", ".join(unsupported)
            + ". Product-resolved source channels or a structural generation method are needed."
        )
    lines.extend(_value_examples(usable, names))
    calculations = [
        (reaction, quantity, result)
        for reaction in reactions
        for quantity, result in sorted(reaction.get("thermochemical_calculations", {}).items())
    ]
    if calculations:
        completed = [row for row in calculations if row[2]["status"] == "computed"]
        lines.append(
            f"Thermochemical calculations: {len(completed)} computed quantity results; "
            f"{len(calculations) - len(completed)} have separately recorded limitations."
        )
        examples = sorted(completed, key=_calculation_example_key)
        for reaction, quantity, result in examples[:2]:
            lines.append(
                f"  {reaction_equation(reaction, names)}: {quantity} = "
                f"{result['value']:.6g} {result['unit']}; "
                f"conditions = {dict(result['conditions'])}"
            )
    lines.extend(_work_examples(work))
    summary = document["summary"]
    lines.extend(_coverage_lines(summary.get("coverage", {})))
    lines.append(
        f"Candidates: {summary['state_count']} states; {summary['reaction_count']} reactions"
    )
    if not generation["complete"]:
        lines.append(
            f"Generation stopped: {generation['stop_reason']} (within the declared bounds)"
        )
    lines.append(f"Scope: {summary['interpretation']}")
    return lines


def _calculation_example_key(row: tuple[dict, str, dict]) -> tuple:
    reaction, quantity, _result = row
    assessments = reaction["assessments"]
    return (
        assessments["thermochemistry"].get("proposition") == "elastic_internal_energy_identity",
        assessments["reaction_evidence"]["verdict"] != "pass",
        {"delta_h_eV": 0, "delta_g_eV": 1}.get(quantity, 2),
        reaction["id"],
    )


def _coverage_lines(coverage: dict) -> list[str]:
    """Each percentage has its own proposition/calculation denominator."""
    if not coverage:
        return []
    lines = ["Unresolved because source data are missing (separate from proposition rejection):"]
    for subject, domains in coverage["judgments"].items():
        for name, counts in domains.items():
            rejected = counts["by_label"].get("not_satisfied", 0)
            lines.append(
                _coverage_line(f"{subject}.{name}", counts) + f"; not satisfied: {rejected}"
            )
    for name, counts in coverage["thermochemical_calculations"].items():
        lines.append(_coverage_line(f"calculation.{name}", counts))
    lines.append(
        "Other unresolved causes and individual propositions: summary.coverage in result.yaml"
    )
    return lines


def _coverage_line(name: str, counts: dict) -> str:
    fraction = counts["data_missing_fraction"]
    percentage = f" ({fraction:.1%})" if fraction is not None else " (no applicable results)"
    return f"  {name}: {counts['data_missing']}/{counts['applicable']}" + percentage


def registered_records(
    document: dict, target: str, quantity: str | None = None, *, detail: bool = False
) -> dict:
    """Inspect saved source records for registration/selection, without evaluation."""
    candidates = (*document["states"], *document["reactions"])
    found = next((item for item in candidates if item["id"] == target), None)
    if found is None:
        raise ValueError(f"target is absent from the saved result: {target}")
    if "data_use" in found:
        records = numerical_records(found)
        if quantity is not None:
            records = [record for record in records if record.get("kind") == quantity]
    else:
        evidence = found["evidence"]
        records = [
            record | {"target_match": evidence.get("match", "unknown")}
            for record in evidence.get("records", [])
        ] + [record | {"target_match": "related"} for record in evidence.get("related_records", [])]
        records = _state_quantity_records(records, quantity)
    if not detail:
        records = [_compact_record(record) for record in records]
    return {
        "target": target,
        "quantity": quantity,
        "records": records,
        "interpretation": (
            "These are saved source declarations. State record_id or dataset id may be used "
            "with data_selection.targets; listing does not qualify a record or approve its use. "
            "State target_match distinguishes exact, compatible and related identities; "
            "selection does not make a related target applicable to the requested state."
        ),
    }


def _compact_record(record: dict) -> dict:
    """Show selectable identity, content and qualification before raw history."""
    names = (
        "record_id",
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
    )
    output = {name: record[name] for name in names if name in record and record[name] is not None}
    if candidate := record.get("candidate"):
        output.update(
            record_target=candidate["id"],
            phase=candidate["phase"],
            structure=candidate.get("structure"),
            state=candidate["state"],
        )
    if "properties" in record:
        output["properties"] = {
            name: {
                key: value
                for key, value in prop.items()
                if key != "source_declaration" and value is not None
            }
            for name, prop in record["properties"].items()
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


def _value_examples(usable: list[dict], names: Mapping[str, str]) -> list[str]:
    lines = []
    for reaction in usable[:3]:
        use = reaction["data_use"]
        label = str(use["kind"]).replace("_", " ")
        lines.append(
            f"  {reaction_equation(reaction, names)}: {label} = "
            f"{use['value']:.6g} {use['unit']}" + (" (estimated)" if use.get("estimated") else "")
        )
        selected = [item for item in numerical_records(reaction) if item["id"] == use["dataset_id"]]
        if selected and (validity := selected[0].get("validity")):
            lines.append(
                f"    declared applicability: {validity['quantity']} "
                f"[{validity['minimum']}, {validity['maximum']}] {validity['unit']}"
            )
    if len(usable) > 3:
        lines.append("  More saved values and their conditions: reactions.csv / result.yaml")
    return lines


def _work_examples(work: dict) -> list[str]:
    priority = {"user_inputs": 0, "source_selection": 1, "source_information": 2, "identity": 3}
    groups = sorted(
        work["work"],
        key=lambda item: (
            priority.get(item["responsibility"], 4),
            -item["target_tasks"],
            item["quantity"],
        ),
    )
    summary = work["summary"]
    lines = [
        f"Next work: {summary['known_prerequisites']} distinct known target/quantity prerequisites"
    ]
    for group in groups[:3]:
        responsibility = group["responsibility"]
        task = work["responsibilities"].get(responsibility, responsibility.replace("_", " "))
        lines.append(f"  {task}")
        lines.append(
            f"    needed: {group['quantity']}; "
            f"{group['target_tasks']} target-specific prerequisites"
        )
        examples = group.get("target_examples", [])
        if examples:
            lines.append(f"    target examples: {'; '.join(examples)}")
    lines.append(
        f"Other saved findings: {summary['findings_without_prerequisites']} "
        "without classified prerequisites; "
        f"{summary['derived_findings']} refer to other saved results."
    )
    return lines
