"""Readable names for tables and figures derived from canonical result records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from reactgen.chemistry import charged_formula
from reactgen.model import CONDITION_INPUT_FIELDS, THIRD_BODY, Term


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
    """Map saved numerical requirements to actual input fields or separate work.

    This describes the input boundary; it never assesses a dataset. Source
    declarations, selection, and distribution models are not scalar conditions.
    Unrecognized requirements stay explicitly unsupported by the current input.
    """
    result: dict[str, list[str]] = {
        "user_inputs": [],
        "source_information": [],
        "source_selection": [],
        "external_models": [],
        "unsupported_inputs": [],
        "transforms": list(transforms),
    }
    for quantity in inputs:
        if field := CONDITION_INPUT_FIELDS.get(quantity):
            result["user_inputs"].append(f"conditions.{field}")
        elif quantity in {"dataset_applicability_conditions", "dataset_independent_variable"}:
            result["source_information"].append(quantity)
        elif quantity == "rate_law_selection":
            result["source_selection"].append("data_selection")
        elif quantity in {
            "electron_energy_distribution",
            "collision_energy_distribution",
            "surface_incident_flux_model",
        }:
            result["external_models"].append(quantity)
        else:
            result["unsupported_inputs"].append(quantity)
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
    lines.extend(_value_examples(reactions, usable, names))
    lines.extend(_work_examples(work))
    summary = document["summary"]
    lines.append(
        f"Candidates: {summary['state_count']} states; {summary['reaction_count']} reactions"
    )
    generation = document["metadata"]["generation"]
    if not generation["complete"]:
        lines.append(
            f"Generation stopped: {generation['stop_reason']} (within the declared bounds)"
        )
    lines.append(f"Scope: {summary['interpretation']}")
    return lines


def _value_examples(
    reactions: list[dict], usable: list[dict], names: Mapping[str, str]
) -> list[str]:
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
    if not usable:
        energies = [item for item in reactions if item.get("thermochemistry")]
        for reaction in energies[:3]:
            values = ", ".join(
                f"{key} = {value}" for key, value in reaction["thermochemistry"].items()
            )
            lines.append(
                f"  Saved energy quantities for {reaction_equation(reaction, names)}: {values}"
            )
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
