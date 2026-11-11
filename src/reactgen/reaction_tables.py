"""Focused tables from a saved result. No reaction or evidence is evaluated here."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable, Mapping

from reactgen.presentation import reaction_equation, state_name

VERDICTS = ("pass", "fail", "unknown", "not_applicable")
_IDENTITY = ("equation", "family", "process", "stabilization")
_INDEX_JUDGMENTS = ("conservation", "consistency", "energy", "reaction_evidence")
_CLAIM = (
    "verdict",
    "label",
    "proposition",
    "reason",
    "scope",
    "blocking_causes",
    "basis",
    "depends_on",
    "next_steps",
)
_ENERGY_COLUMNS = (
    "collision_entrance",
    "projectile_state",
    "target_state",
    "incident_energy_eV",
    "incident_energy_frame",
    "target_at_rest",
    "relative_collision_energy_eV",
    "state_energy_difference_eV",
    "collision_energy_margin_eV",
    "collision_input",
)
_THERMOCHEMISTRY_COLUMNS = (
    "delta_h_eV",
    "delta_h_reference_temperature_K",
    "delta_h_standard_pressure_Pa",
    "delta_g_eV",
)
_KINETICS_COLUMNS = ("numerical_use", "quantity", "value", "unit", "dataset_id")
_JUDGMENT_COLUMNS = {
    "energy": _ENERGY_COLUMNS,
    "thermochemistry": _THERMOCHEMISTRY_COLUMNS,
    "reaction_evidence": ("declared_threshold_eV",),
    "kinetics": _KINETICS_COLUMNS,
}
_LEGACY_INPUT = re.compile(
    r"conditions(?:\.collision_pairs\[(\d+)\])?\."
    r"(collision_energy_eV|electron_energy_eV|ion_energy_eV)"
)


def selected_reactions(
    payload: dict,
    *,
    family: str | None = None,
    process: str | None = None,
    verdicts: Mapping[str, str] | None = None,
) -> list[dict]:
    """Intersect exact family, process and independently saved verdicts."""
    rows = payload["reactions"]
    filters = verdicts or {}
    saved = {name for row in rows for name in row["assessments"]}
    for name, verdict in filters.items():
        if name not in saved:
            raise ValueError(f"reaction judgment {name!r} is not saved")
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict: {verdict}")
    return [
        row
        for row in rows
        if (family is None or row["family"] == family)
        and (process is None or row["process"] == process)
        and all(
            row["assessments"].get(name, {}).get("verdict") == value
            for name, value in filters.items()
        )
    ]


def state_labels(payload: dict) -> dict[str, str]:
    """Disambiguate display names without changing a state's exact identity."""
    names = {state["id"]: state_name(state) for state in payload["states"]}
    counts = Counter(names.values())
    return {
        identifier: f"{name} [{identifier}]" if counts[name] > 1 else name
        for identifier, name in names.items()
    }


def energy_values(payload: dict, reaction: dict) -> dict:
    """Read the collision binding and values retained by the energy calculation."""
    calculations = reaction.get("thermochemical_calculations", {})
    margin = calculations.get("collision_energy_margin_eV", {})
    incident: dict = next((term for term in margin.get("inputs", ()) if "input" in term), {})
    incident_energy = incident.get("energy_eV")
    if "input" in incident and "energy_eV" not in incident:
        incident_energy = _archived_incident_energy(payload, incident["input"])
    entrance = None
    if "input" in incident and not all(
        incident.get(role) for role in ("projectile_state", "target_state")
    ):
        entrance = " + ".join(
            term["species"] if term["n"] == 1 else f"{term['n']:g} {term['species']}"
            for term in reaction["reactants"]
        )
    return {
        "collision_entrance": entrance,
        "projectile_state": incident.get("projectile_state"),
        "target_state": incident.get("target_state"),
        "incident_energy_eV": incident_energy,
        "incident_energy_frame": incident.get("frame"),
        "target_at_rest": incident.get("target_at_rest"),
        "relative_collision_energy_eV": margin.get("conditions", {}).get(
            "relative_collision_energy_eV"
        ),
        "state_energy_difference_eV": calculations.get("state_energy_difference_eV", {}).get(
            "value"
        ),
        "collision_energy_margin_eV": margin.get("value"),
        "collision_input": incident.get("input"),
    }


def _archived_incident_energy(payload: dict, reference: str) -> float | None:
    """Resolve the exact saved input path in archives without a copied value."""
    match = _LEGACY_INPUT.fullmatch(reference)
    if match is None:
        return None
    index, quantity = match.groups()
    conditions = payload.get("input", {}).get("conditions", {})
    if index is None:
        return conditions.get(quantity)
    pairs = conditions.get("collision_pairs", ())
    number = int(index)
    return pairs[number].get(quantity) if number < len(pairs) else None


def reaction_table(
    payload: dict,
    *,
    family: str | None = None,
    process: str | None = None,
    verdicts: Mapping[str, str] | None = None,
) -> str:
    """Provide the compact index used to find and cross-reference candidates."""
    reactions = selected_reactions(payload, family=family, process=process, verdicts=verdicts)
    columns = tuple(f"{name}_verdict" for name in _INDEX_JUDGMENTS)
    rows = (
        identity
        | {
            column: reaction["assessments"].get(name, {}).get("verdict")
            for name, column in zip(_INDEX_JUDGMENTS, columns, strict=True)
        }
        for identity, reaction in _reaction_rows(payload, reactions)
    )
    return csv_text(rows, (*_IDENTITY, *columns, "id"))


def judgment_tables(
    payload: dict,
    *,
    family: str | None = None,
    process: str | None = None,
    verdicts: Mapping[str, str] | None = None,
    judgment: str | None = None,
) -> dict[str, str]:
    """One reaction table per recorded judgment, with its own values and work."""
    reactions = selected_reactions(payload, family=family, process=process, verdicts=verdicts)
    rows = _reaction_rows(payload, reactions)
    names = _judgment_names(payload["reactions"], judgment)
    return {
        name: csv_text(
            (
                identity | _claim_fields(claim) | _judgment_values(payload, reaction, name)
                for identity, reaction in rows
                if (claim := reaction["assessments"].get(name)) is not None
            ),
            (*_IDENTITY, *_CLAIM[:3], *_JUDGMENT_COLUMNS.get(name, ()), *_CLAIM[3:], "id"),
        )
        for name in names
    }


def state_table(payload: dict) -> str:
    """List the exact represented species and levels available in the result."""
    labels, states = _state_rows(payload)
    rows = (
        {
            "state": labels[state["id"]],
            "phase": state["phase"],
            "kind": state["state"]["kind"],
            "resolution": state["state"]["resolution"],
            "structure": state["structure"],
            "id": state["id"],
        }
        for state in states
    )
    return csv_text(rows, ("state", "phase", "kind", "resolution", "structure", "id"))


def state_judgment_tables(
    payload: dict, *, judgment: str | None = None, verdict: str | None = None
) -> dict[str, str]:
    """Keep individual state claims separate from claims about reactions."""
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"unknown verdict: {verdict}")
    labels, states = _state_rows(payload)
    names = _judgment_names(states, judgment)
    return {
        name: csv_text(
            (
                {"state": labels[state["id"]], "id": state["id"]} | _claim_fields(claim)
                for state in states
                if (claim := state["assessments"].get(name)) is not None
                and (verdict is None or claim["verdict"] == verdict)
            ),
            ("state", *_CLAIM, "id"),
        )
        for name in names
    }


def state_judgment_stem(judgment: str) -> str:
    return "state-support" if judgment == "state" else f"state-{judgment}"


def _judgment_names(subjects: Iterable[dict], judgment: str | None) -> list[str]:
    names = {name for subject in subjects for name in subject["assessments"]}
    if judgment is None:
        return sorted(names)
    return [judgment] if judgment in names else []


def _state_rows(payload: dict) -> tuple[dict[str, str], list[dict]]:
    labels = state_labels(payload)
    states = sorted(payload["states"], key=lambda state: (labels[state["id"]], state["id"]))
    return labels, states


def _reaction_rows(payload: dict, reactions: Iterable[dict]) -> list[tuple[dict, dict]]:
    names = state_labels(payload)
    rows = [
        (
            {name: reaction.get(name) for name in (*_IDENTITY[1:], "id")}
            | {"equation": reaction_equation(reaction, names)},
            reaction,
        )
        for reaction in reactions
    ]
    return sorted(
        rows,
        key=lambda row: (row[0]["family"], row[0]["process"], row[0]["equation"], row[0]["id"]),
    )


def _claim_fields(claim: dict) -> dict:
    return {
        "verdict": claim["verdict"],
        "label": claim.get("label"),
        "proposition": claim.get("proposition"),
        "reason": claim.get("message"),
        "scope": claim.get("scope"),
        "blocking_causes": " | ".join(claim.get("blocking_causes", ())),
        "basis": " | ".join(claim.get("basis", ())),
        "depends_on": " | ".join(
            f"{state} / {judgment}" for state, judgment in claim.get("dependencies", ())
        ),
        "next_steps": _requirement_text(claim.get("requirements", ())),
    }


def _requirement_text(requirements: Iterable[dict]) -> str:
    return " | ".join(
        " · ".join(
            part
            for part in (
                f"{work['quantity']} ({work['target']})",
                work["responsibility"],
                work.get("reason"),
            )
            if part
        )
        for work in requirements
    )


def _judgment_values(payload: dict, reaction: dict, name: str) -> dict:
    if name == "energy":
        return energy_values(payload, reaction)
    thermal = reaction.get("thermochemistry", {})
    if name == "thermochemistry":
        return {quantity: thermal.get(quantity) for quantity in _THERMOCHEMISTRY_COLUMNS}
    if name == "reaction_evidence":
        return {"declared_threshold_eV": thermal.get("threshold_eV")}
    if name == "kinetics":
        use = reaction["data_use"]
        return {
            "numerical_use": use.get("status"),
            "quantity": use.get("kind"),
            "value": use.get("value"),
            "unit": use.get("unit"),
            "dataset_id": use.get("dataset_id"),
            "next_steps": _requirement_text(use.get("requirements", ())),
        }
    return {}


def csv_text(rows: Iterable[dict], columns: tuple[str, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
