"""Serialize one evaluated candidate set into YAML and optional flat CSV views."""

from __future__ import annotations

import csv
import io
from dataclasses import asdict
from pathlib import Path

import yaml

from reactgen.chemistry import electronic_character, formula, formula_scope
from reactgen.evidence import ReactionEvidence, StateEvidence
from reactgen.model import (
    Assessment,
    ReactionCandidate,
    StateCandidate,
    Term,
    canonical_state_label,
    state_excitation,
    state_lifetime_class,
)
from reactgen.network_matrix import network_matrix_png
from reactgen.network_view import network_explorer_html
from reactgen.pathway import choose_pathway_target, reaction_reachability
from reactgen.pathway_view import pathway_png
from reactgen.pipeline import PipelineResult
from reactgen.records import NumericDataset, ReactionRecord, StateRecord, dataset_payload
from reactgen.visualize import (
    composition_svg,
    reaction_family_rows,
    reaction_family_svg,
    screening_retention_svg,
    statistics_rows,
    statistics_svg,
    summary_rows,
    verdict_counts_svg,
)

YAML_FILES = ("states.yaml", "reactions.yaml", "selected.yaml")
ASSESSMENT_NAMES = (
    "consistency",
    "state",
    "thermochemistry",
    "reaction_evidence",
    "kinetics",
)
STATE_ASSESSMENT_NAMES = ("consistency", "state", "thermochemistry")
REACTION_ONLY_ASSESSMENT_NAMES = ("reaction_evidence", "kinetics")
REACTION_FAMILY_FILES = {
    "electron": "reactions_electron.csv",
    "ion": "reactions_ion.csv",
    "neutral": "reactions_neutral.csv",
    "surface": "reactions_surface.csv",
}
ASSESSMENT_COMMON_OUTPUTS = (
    "family_summary.csv",
    "reaction_family.svg",
    "reactions.csv",
    *REACTION_FAMILY_FILES.values(),
    "summary.csv",
    "verdict_counts.svg",
)


def _assessment_output_names(layer: str) -> tuple[str, ...]:
    state_output = ("states.csv",) if layer in STATE_ASSESSMENT_NAMES else ()
    return (*ASSESSMENT_COMMON_OUTPUTS, *state_output)


LEGACY_NETWORK_OUTPUTS = (
    "network.svg",
    "network_equations.svg",
    "network_overview.svg",
    "network_overview_equations.svg",
)
LEGACY_ASSESSMENT_OUTPUTS = ("assessment.csv", *LEGACY_NETWORK_OUTPUTS)
ASSESSMENT_OVERVIEW_OUTPUTS = (
    "composition.svg",
    "network.html",
    "network.png",
    "pathways.png",
    "statistics.csv",
    "statistics.svg",
)
SCREENING_STAGES = (
    ("state_consistency", (("state",), ("consistency",))),
    (
        "state_consistency_thermochemistry",
        (("state",), ("consistency",), ("thermochemistry",)),
    ),
    (
        "state_consistency_thermochemistry_kinetics_or_reaction_evidence",
        (
            ("state",),
            ("consistency",),
            ("thermochemistry",),
            ("kinetics", "reaction_evidence"),
        ),
    ),
)
LEGACY_SCREENING_STAGES = (
    "state_consistency_thermochemistry_kinetics",
    "state_consistency_thermochemistry_kinetics_reaction_evidence",
)
SCREENING_OUTPUTS = (
    "reactions.csv",
    *REACTION_FAMILY_FILES.values(),
    "retention.svg",
    "states.csv",
    "summary.csv",
)
LEGACY_SCREENING_OUTPUTS = LEGACY_NETWORK_OUTPUTS
LEGACY_NETWORK_DIRECTORY = "network"
ASSESSMENT_FILES = (
    tuple(
        f"assessments/{name}/{filename}"
        for name in ASSESSMENT_NAMES
        for filename in _assessment_output_names(name)
    )
    + tuple(f"assessments/{filename}" for filename in ASSESSMENT_OVERVIEW_OUTPUTS)
    + tuple(
        f"assessments/screening/{stage}/{filename}"
        for stage, _ in SCREENING_STAGES
        for filename in SCREENING_OUTPUTS
    )
)
CSV_FILES = ("states.csv", "reactions.csv", *REACTION_FAMILY_FILES.values())
PUBLIC_FILES = YAML_FILES + CSV_FILES + ASSESSMENT_FILES
ROOT_ENTRIES = YAML_FILES + CSV_FILES + ("assessments",)

STATE_SYMBOLS = {
    "metastable": "m",
    "resonant": "r",
    "electronic": "*",
    "vibrational": "v",
}
TERM_SYMBOLS = {
    "1d": "¹D",
    "1d2": "¹D₂",
    "1s": "¹S",
    "a1dg": "a¹Δg",
    "b1sg+": "b¹Σg+",
}
REACTION_TYPES = {
    ("electron", "attachment"): "Electron attachment",
    ("electron", "deexcitation"): "Electron-impact deexcitation (superelastic)",
    ("electron", "detachment"): "Electron-impact detachment",
    ("electron", "dissociation"): "Electron-impact dissociation",
    ("electron", "dissociative_attachment"): "Dissociative electron attachment",
    ("electron", "dissociative_detachment"): "Dissociative electron detachment",
    ("electron", "dissociative_ionization"): "Dissociative ionization",
    ("electron", "dissociative_recombination"): "Dissociative recombination",
    ("electron", "elastic"): "Electron elastic scattering",
    ("electron", "excitation"): "Electron-impact excitation",
    ("electron", "ionization"): "Electron-impact ionization",
    ("electron", "recombination"): "Electron-ion recombination",
    ("ion", "charge_exchange"): "Charge exchange",
    ("ion", "collision_induced_dissociation"): "Collision-induced target dissociation",
    ("ion", "collisional_detachment"): "Collisional electron detachment",
    ("ion", "dissociative_charge_transfer"): "Dissociative charge transfer",
    ("ion", "elastic"): "Ion-neutral elastic scattering",
    ("ion", "ion_induced_deexcitation"): "Ion-induced deexcitation",
    ("ion", "ion_induced_excitation"): "Ion-induced excitation",
    ("ion", "ligand_transfer"): "Ligand transfer",
    ("ion", "mutual_neutralization"): "Ion-ion mutual neutralization",
    ("ion", "projectile_dissociation"): "Projectile-ion dissociation",
    ("ion", "reactive_scattering"): "Ion-neutral reactive scattering",
    ("ion", "resonant_charge_exchange"): "Resonant charge exchange",
    ("neutral", "association"): "Bimolecular association",
    ("neutral", "associative_ionization"): "Associative ionization",
    ("neutral", "dissociation"): "Neutral-impact dissociation",
    ("neutral", "penning_ionization"): "Penning ionization",
    ("neutral", "quenching"): "Excited-state quenching",
    ("neutral", "radical_abstraction"): "Radical abstraction",
    ("neutral", "reactive_scattering"): "Neutral reactive scattering",
    ("neutral", "three_body_association"): "Three-body association",
    ("neutral", "v_t_relaxation"): "Vibrational-translational (V-T) relaxation",
    ("surface", "surface_recombination"): "Surface recombination",
}
ROOT_REACTION_COLUMNS = (
    "equation",
    "reaction_type",
    "family",
    "process",
    "origin",
    "depth",
    "consistency_verdict",
    "state_verdict",
    "thermochemistry_verdict",
    "reaction_evidence_verdict",
    "kinetics_verdict",
    "delta_h_eV",
    "delta_g_eV",
    "threshold_eV",
    "kinetic_data",
    "selected",
    "exclusion_reason",
    "id",
)


def write(outdir: Path, result: PipelineResult, *, include_csv: bool = False) -> None:
    """Write complete files without replacing the user-visible directory."""

    _validate_output(outdir)
    documents = {
        "states": _states(result),
        "reactions": _reactions(result),
        "selected": _selected(result),
    }
    payloads: dict[str, Payload] = {
        f"{name}.yaml": _dump(payload) for name, payload in documents.items()
    }
    if include_csv:
        payloads.update(_review_payloads(documents))
    _publish(outdir, payloads)


def _validate_output(outdir: Path) -> None:
    if not outdir.exists():
        return
    unexpected = sorted(path.name for path in outdir.iterdir() if path.name not in ROOT_ENTRIES)
    if unexpected:
        raise OSError(f"output directory contains non-bundle entries: {', '.join(unexpected)}")
    assessments = outdir / "assessments"
    if not assessments.exists():
        return
    _validate_assessments(assessments)


def _validate_assessments(assessments: Path) -> None:
    if not assessments.is_dir():
        raise OSError("output entry assessments is not a directory")
    unexpected_layers = sorted(
        path.name
        for path in assessments.iterdir()
        if path.name not in ASSESSMENT_NAMES + ASSESSMENT_OVERVIEW_OUTPUTS + ("screening",)
    )
    if unexpected_layers:
        raise OSError("output assessments contains unknown layers: " + ", ".join(unexpected_layers))
    for overview in ASSESSMENT_OVERVIEW_OUTPUTS:
        path = assessments / overview
        if path.exists() and not path.is_file():
            raise OSError(f"output assessment overview is not a file: {overview}")
    for layer_name in ASSESSMENT_NAMES:
        layer = assessments / layer_name
        if not layer.exists():
            continue
        if not layer.is_dir():
            raise OSError(f"output assessment layer is not a directory: {layer.name}")
        unexpected_files = sorted(
            path.name
            for path in layer.iterdir()
            if path.name
            not in _assessment_output_names(layer_name)
            + LEGACY_ASSESSMENT_OUTPUTS
            + (("states.csv",) if layer_name in REACTION_ONLY_ASSESSMENT_NAMES else ())
            + (LEGACY_NETWORK_DIRECTORY,)
        )
        if unexpected_files:
            raise OSError(
                f"output assessment {layer.name} contains unknown files: "
                + ", ".join(unexpected_files)
            )
        _validate_legacy_network_directory(layer / LEGACY_NETWORK_DIRECTORY)
    screening = assessments / "screening"
    if screening.exists():
        _validate_screening(screening)


def _validate_screening(screening: Path) -> None:
    if not screening.is_dir():
        raise OSError("output assessment screening is not a directory")
    stage_names = tuple(name for name, _ in SCREENING_STAGES)
    allowed_stage_names = stage_names + LEGACY_SCREENING_STAGES
    unexpected_stages = sorted(
        path.name for path in screening.iterdir() if path.name not in allowed_stage_names
    )
    if unexpected_stages:
        raise OSError("output screening contains unknown stages: " + ", ".join(unexpected_stages))
    for stage_name in stage_names:
        stage = screening / stage_name
        if not stage.exists():
            continue
        if not stage.is_dir():
            raise OSError(f"output screening stage is not a directory: {stage_name}")
        unexpected_files = sorted(
            path.name
            for path in stage.iterdir()
            if path.name
            not in SCREENING_OUTPUTS + LEGACY_SCREENING_OUTPUTS + (LEGACY_NETWORK_DIRECTORY,)
        )
        if unexpected_files:
            raise OSError(
                f"output screening {stage_name} contains unknown files: "
                + ", ".join(unexpected_files)
            )
        _validate_legacy_network_directory(stage / LEGACY_NETWORK_DIRECTORY)


def _validate_legacy_network_directory(directory: Path) -> None:
    if not directory.exists():
        return
    if not directory.is_dir():
        raise OSError(f"output complete network is not a directory: {directory}")
    unexpected = sorted(
        path.name
        for path in directory.iterdir()
        if path.name != "index.csv" and not _is_legacy_network_page(path.name)
    )
    if unexpected:
        raise OSError(
            f"output complete network {directory} contains unknown files: " + ", ".join(unexpected)
        )
    non_files = sorted(path.name for path in directory.iterdir() if not path.is_file())
    if non_files:
        raise OSError(
            f"output complete network {directory} contains non-files: " + ", ".join(non_files)
        )


def _is_legacy_network_page(name: str) -> bool:
    number = name.removeprefix("page_").removesuffix(".svg")
    return (
        name.startswith("page_")
        and name.endswith(".svg")
        and len(number) == 4
        and number.isdigit()
        and int(number) > 0
    )


Payload = str | bytes


def _review_payloads(documents: dict[str, dict]) -> dict[str, Payload]:
    states = documents["states"]
    reactions = documents["reactions"]
    selected = documents["selected"]
    payloads: dict[str, Payload] = {
        "states.csv": _states_csv(states, selected),
        "reactions.csv": _reactions_csv(reactions, states, selected),
    }
    payloads.update(
        {
            filename: _reactions_csv(reactions, states, selected, family=family)
            for family, filename in REACTION_FAMILY_FILES.items()
        }
    )
    payloads.update(_assessment_outputs(states, reactions))
    return payloads


def _publish(outdir: Path, payloads: dict[str, Payload]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    targets = {name: outdir / name for name in payloads}
    for target in targets.values():
        target.parent.mkdir(parents=True, exist_ok=True)
    temporary = {name: target.with_name(f".{target.name}.tmp") for name, target in targets.items()}
    try:
        for name, content in payloads.items():
            if isinstance(content, bytes):
                temporary[name].write_bytes(content)
            else:
                temporary[name].write_text(content, encoding="utf-8")
        for name in payloads:
            temporary[name].replace(targets[name])
        _remove_stale_outputs(outdir, payloads)
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def _remove_stale_outputs(outdir: Path, payloads: dict[str, Payload]) -> None:
    for stale in set(PUBLIC_FILES) - set(payloads):
        (outdir / stale).unlink(missing_ok=True)
    _remove_legacy_network_directories(outdir)
    assessments = outdir / "assessments"
    _remove_legacy_assessment_files(assessments)
    screening = assessments / "screening"
    _remove_legacy_screening_files(screening)
    _remove_empty_directories(
        screening,
        tuple(stage_name for stage_name, _ in SCREENING_STAGES) + LEGACY_SCREENING_STAGES,
    )
    if screening.exists() and not any(screening.iterdir()):
        screening.rmdir()
    _remove_empty_directories(assessments, ASSESSMENT_NAMES)
    if assessments.exists() and not any(assessments.iterdir()):
        assessments.rmdir()


def _remove_legacy_assessment_files(assessments: Path) -> None:
    for layer_name in ASSESSMENT_NAMES:
        for filename in LEGACY_ASSESSMENT_OUTPUTS:
            (assessments / layer_name / filename).unlink(missing_ok=True)
    for layer_name in REACTION_ONLY_ASSESSMENT_NAMES:
        (assessments / layer_name / "states.csv").unlink(missing_ok=True)


def _remove_legacy_screening_files(screening: Path) -> None:
    for stage_name, _ in SCREENING_STAGES:
        for filename in LEGACY_SCREENING_OUTPUTS:
            (screening / stage_name / filename).unlink(missing_ok=True)
    for stage_name in LEGACY_SCREENING_STAGES:
        for filename in SCREENING_OUTPUTS + LEGACY_SCREENING_OUTPUTS:
            (screening / stage_name / filename).unlink(missing_ok=True)


def _remove_legacy_network_directories(outdir: Path) -> None:
    directories = [
        outdir / "assessments" / name / LEGACY_NETWORK_DIRECTORY for name in ASSESSMENT_NAMES
    ]
    directories.extend(
        outdir / "assessments" / "screening" / stage / LEGACY_NETWORK_DIRECTORY
        for stage, _ in SCREENING_STAGES
    )
    for directory in directories:
        if not directory.exists():
            continue
        for path in directory.iterdir():
            path.unlink(missing_ok=True)
        directory.rmdir()


def _remove_empty_directories(parent: Path, names: tuple[str, ...]) -> None:
    for name in names:
        directory = parent / name
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()


def _states(result: PipelineResult) -> dict:
    return {
        "metadata": result.metadata,
        "states": [
            {
                "id": state.id,
                "composition": state.composition,
                "charge": state.charge,
                "state": asdict(state.state),
                "state_axes": {
                    "excitation": state_excitation(state.state.kind, state.state.label),
                    "lifetime_class": state_lifetime_class(state.state.kind, state.classes),
                    "canonical_label": canonical_state_label(state.state.kind, state.state.label),
                    "structure_scope": _structure_scope(state.composition, state.id),
                },
                "classes": sorted(state.classes),
                "chemical_character": {
                    "formula_scope": formula_scope(state.composition),
                    "electronic": electronic_character(state.composition, state.charge),
                    "generation_roles": sorted(state.classes & {"feed", "fragment", "rearranged"}),
                },
                "origin": state.origin,
                "depth": state.depth,
                "introduced_by": list(state.introduced_by),
                "evidence": _state_evidence(result.evaluation.state_evidence[state.id]),
                "assessments": {
                    name: _assessment(value)
                    for name, value in result.evaluation.state_assessments[state.id].items()
                },
            }
            for state in sorted(result.candidates.states.values(), key=lambda item: item.id)
        ],
    }


def _reactions(result: PipelineResult) -> dict:
    return {
        "metadata": result.metadata,
        "reactions": [
            _reaction_document(reaction, result)
            for reaction in sorted(result.candidates.reactions.values(), key=lambda item: item.id)
        ],
    }


def _reaction_document(reaction: ReactionCandidate, result: PipelineResult) -> dict:
    reactants = _ordered_terms(
        reaction.reactants,
        result.candidates.states,
        reactant_side=True,
    )
    products = _ordered_terms(
        reaction.products,
        result.candidates.states,
        reactant_side=False,
    )
    return {
        "id": reaction.id,
        "equation": _canonical_equation(reactants, products, reaction.third_body, reaction.surface),
        "reactants": [{"species": term.species, "n": term.n} for term in reactants],
        "products": [{"species": term.species, "n": term.n} for term in products],
        "family": reaction.family,
        "process": reaction.process,
        "origin": reaction.origin,
        "generation_rule": reaction.generation_rule,
        "depth": reaction.depth,
        "third_body": reaction.third_body,
        "surface": reaction.surface,
        "kinetic_effects": list(reaction.kinetic_effects),
        "thermochemistry": result.evaluation.thermochemistry.get(reaction.id),
        "numerical_capabilities": {
            "thermochemistry": asdict(result.evaluation.thermo_capabilities[reaction.id]),
            "kinetics": asdict(result.evaluation.kinetics_capabilities[reaction.id]),
        },
        "evidence": _reaction_evidence(result.evaluation.reaction_evidence[reaction.id]),
        "assessments": {
            name: _assessment(value)
            for name, value in result.evaluation.reaction_assessments[reaction.id].items()
        },
    }


def _ordered_terms(
    terms: tuple[Term, ...],
    states: dict[str, StateCandidate],
    *,
    reactant_side: bool,
) -> list[Term]:
    return sorted(
        terms,
        key=lambda term: _participant_order(term.species, states, reactant_side),
    )


def _participant_order(
    state_id: str,
    states: dict[str, StateCandidate],
    reactant_side: bool,
) -> tuple[int, str]:
    state = states[state_id]
    if state_id == "e":
        return (0 if reactant_side else 6, state_id)
    if state.charge > 0:
        return (1, state_id)
    if state.charge < 0:
        return (2, state_id)
    if state.state.kind != "ground":
        return (3, state_id)
    atom_or_reactive = sum(state.composition.values()) == 1 or "reactive_candidate" in state.classes
    return (4 if atom_or_reactive else 5, state_id)


def _canonical_equation(
    reactants: list[Term],
    products: list[Term],
    third_body: str | None,
    surface: str | None,
) -> str:
    left = [str(term) for term in reactants]
    right = [str(term) for term in products]
    if third_body:
        left.append("M")
        right.append("M")
    if surface:
        left.append(f"[{surface}]")
    return f"{' + '.join(left)} -> {' + '.join(right)}"


def _selected(result: PipelineResult) -> dict:
    selection = result.selection
    return {
        "metadata": result.metadata,
        "policy": selection.policy,
        "readiness": asdict(selection.readiness),
        "selected_states": list(selection.state_ids),
        "selected_reactions": list(selection.reaction_ids),
        "not_selected_states": selection.excluded_states,
        "not_selected_reactions": selection.excluded_reactions,
    }


def _state_evidence(evidence: StateEvidence) -> dict:
    return {
        "match": evidence.match,
        "records": [_state_record(record) for record in evidence.records],
    }


def _state_record(record: StateRecord) -> dict:
    return {
        "id": record.id,
        "origin": record.origin,
        "status": record.status,
        "tier": record.tier,
        "source": record.source,
        "state": asdict(record.candidate.state),
        "energy_eV": record.energy_eV,
        "existence": record.existence,
        "quantum": {
            "configuration": record.configuration,
            "term": record.term,
            "J": record.j,
            "parity": record.parity,
            "degeneracy": record.degeneracy,
        },
        "lifetime_s": record.lifetime_s,
        "properties": {name: asdict(value) for name, value in sorted(record.properties.items())},
        "thermo": None if record.thermo is None else asdict(record.thermo),
    }


def _reaction_evidence(evidence: ReactionEvidence) -> dict:
    return {
        "sources": list(evidence.sources),
        "exact_channel_records": [_reaction_record(record) for record in evidence.exact_records],
        "related_total_process_records": [
            _reaction_record(record) for record in evidence.total_records
        ],
        "related_physical_process_records": [
            _reaction_record(record) for record in evidence.related_records
        ],
        "overlay_datasets": [_dataset(dataset) for dataset in evidence.overlay_datasets],
    }


def _reaction_record(record: ReactionRecord) -> dict:
    return {
        "id": record.id,
        "origin": record.origin,
        "family": record.family,
        "process": record.process,
        "channel_scope": record.channel_scope,
        "status": record.status,
        "tier": record.tier,
        "source": record.source,
        "threshold_eV": record.threshold_eV,
        "delta_e_eV": record.delta_e_eV,
        "datasets": [_dataset(dataset) for dataset in record.datasets],
    }


def _dataset(dataset: NumericDataset) -> dict:
    return dataset_payload(dataset)


def _assessment(value: Assessment) -> dict:
    return {
        "verdict": value.verdict,
        "basis": list(value.basis),
        "message": value.message,
    }


def _dump(payload: dict) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def _states_csv(states: dict, selected: dict) -> str:
    selected_ids = set(selected["selected_states"])
    rows = []
    state_names = {state["id"]: _state_display(state) for state in states["states"]}
    alternatives = _resolution_alternatives(states["states"], state_names)
    ordered_states = sorted(
        states["states"], key=lambda state: (state["depth"], _state_display(state), state["id"])
    )
    for state in ordered_states:
        assessments = state["assessments"]
        # Related manifolds are useful evidence, but their numerical values do
        # not belong to this candidate state.  Only exact identity matches may
        # populate the flat property columns.
        records = state["evidence"]["records"] if state["evidence"]["match"] == "exact" else []
        properties = {
            name: _common(record["properties"].get(name, {}).get("value") for record in records)
            for name in (
                "mass_amu",
                "enthalpy_formation_eV",
                "ionization_energy_eV",
                "electron_affinity_eV",
            )
        }
        rows.append(
            {
                "species": _state_display(state),
                "formula": formula(state["composition"]),
                "charge": state["charge"],
                "excitation": state["state_axes"]["excitation"],
                "resolution": state["state"]["resolution"],
                "lifetime_class": state["state_axes"]["lifetime_class"],
                "state_label": state["state_axes"]["canonical_label"],
                "state_symbol": _state_symbol(state),
                "state_meaning": _state_meaning(state),
                "alternative_resolution_states": alternatives[state["id"]],
                "structure_scope": state["state_axes"]["structure_scope"],
                "origin": state["origin"],
                "depth": state["depth"],
                "state_verdict": assessments["state"]["verdict"],
                "thermochemistry_verdict": assessments["thermochemistry"]["verdict"],
                "selected": _boolean(state["id"] in selected_ids),
                "state_energy_eV": _common(record["energy_eV"] for record in records),
                "lifetime_s": _common(record["lifetime_s"] for record in records),
                **properties,
                "id": state["id"],
            }
        )
    return _csv(rows)


def _reactions_csv(
    reactions: dict,
    states: dict,
    selected: dict,
    *,
    family: str | None = None,
) -> str:
    selected_ids = set(selected["selected_reactions"])
    excluded = selected["not_selected_reactions"]
    state_names = {state["id"]: _state_display(state) for state in states["states"]}
    rows = []
    ordered_reactions = _ordered_reactions(reactions["reactions"], state_names)
    for reaction in ordered_reactions:
        if family is not None and reaction["family"] != family:
            continue
        assessments = reaction["assessments"]
        thermo = reaction["thermochemistry"] or {}
        kinetics_ready = reaction["numerical_capabilities"]["kinetics"]
        rows.append(
            {
                "equation": _reaction_display(reaction, state_names),
                "reaction_type": _reaction_type(reaction),
                "family": reaction["family"],
                "process": reaction["process"],
                "origin": reaction["origin"],
                "depth": reaction["depth"],
                "consistency_verdict": assessments["consistency"]["verdict"],
                "state_verdict": assessments["state"]["verdict"],
                "thermochemistry_verdict": assessments["thermochemistry"]["verdict"],
                "reaction_evidence_verdict": assessments["reaction_evidence"]["verdict"],
                "kinetics_verdict": assessments["kinetics"]["verdict"],
                "delta_h_eV": thermo.get("delta_h_eV", ""),
                "delta_g_eV": thermo.get("delta_g_eV", ""),
                "threshold_eV": thermo.get("threshold_eV", ""),
                "kinetic_data": _kinetic_data(kinetics_ready),
                "selected": _boolean(reaction["id"] in selected_ids),
                "exclusion_reason": excluded.get(reaction["id"], ""),
                "id": reaction["id"],
            }
        )
    return _csv(rows, fieldnames=ROOT_REACTION_COLUMNS)


def _assessment_outputs(states: dict, reactions: dict) -> dict[str, Payload]:
    state_names = {state["id"]: _state_display(state) for state in states["states"]}
    ordered_states = sorted(
        states["states"], key=lambda state: (state["depth"], state_names[state["id"]], state["id"])
    )
    alternatives = _resolution_alternatives(states["states"], state_names)
    ordered_reactions = _ordered_reactions(reactions["reactions"], state_names)
    rows_by_layer: dict[str, list[dict]] = {name: [] for name in ASSESSMENT_NAMES}

    for state in ordered_states:
        assessment = state["assessments"]["consistency"]
        rows_by_layer["consistency"].append(
            {
                "candidate": state_names[state["id"]],
                "entity": "state",
                "reaction_type": "",
                **_state_view_fields(state, alternatives),
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": state["id"],
            }
        )
    for reaction in ordered_reactions:
        assessment = reaction["assessments"]["consistency"]
        rows_by_layer["consistency"].append(
            {
                "candidate": _reaction_display(reaction, state_names),
                "entity": "reaction",
                "reaction_type": _reaction_type(reaction),
                "family": reaction["family"],
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": reaction["id"],
            }
        )

    for state in ordered_states:
        assessment = state["assessments"]["state"]
        rows_by_layer["state"].append(
            {
                "candidate": state_names[state["id"]],
                "entity": "state",
                "reaction_type": "",
                **_state_view_fields(state, alternatives),
                "evidence": _state_evidence_display(state["evidence"]),
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": state["id"],
            }
        )
        assessment = state["assessments"]["thermochemistry"]
        rows_by_layer["thermochemistry"].append(
            {
                "candidate": state_names[state["id"]],
                "entity": "state",
                "reaction_type": "",
                **_state_view_fields(state, alternatives),
                "delta_h_eV": "",
                "delta_g_eV": "",
                "threshold_eV": "",
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": state["id"],
            }
        )

    for reaction in ordered_reactions:
        equation = _reaction_display(reaction, state_names)
        reaction_type = _reaction_type(reaction)
        assessment = reaction["assessments"]["state"]
        rows_by_layer["state"].append(
            {
                "candidate": equation,
                "entity": "reaction",
                "reaction_type": reaction_type,
                "family": reaction["family"],
                "evidence": "",
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": reaction["id"],
            }
        )

        thermo = reaction["thermochemistry"] or {}
        assessment = reaction["assessments"]["thermochemistry"]
        rows_by_layer["thermochemistry"].append(
            {
                "candidate": equation,
                "entity": "reaction",
                "reaction_type": reaction_type,
                "family": reaction["family"],
                "delta_h_eV": thermo.get("delta_h_eV", ""),
                "delta_g_eV": thermo.get("delta_g_eV", ""),
                "threshold_eV": thermo.get("threshold_eV", ""),
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": reaction["id"],
            }
        )

        evidence = reaction["evidence"]
        assessment = reaction["assessments"]["reaction_evidence"]
        rows_by_layer["reaction_evidence"].append(
            {
                "candidate": equation,
                "entity": "reaction",
                "reaction_type": reaction_type,
                "family": reaction["family"],
                "matched_source": _join(evidence["sources"]),
                "channel_scope": _channel_scopes(evidence),
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": reaction["id"],
            }
        )

        datasets = _datasets(evidence)
        assessment = reaction["assessments"]["kinetics"]
        rows_by_layer["kinetics"].append(
            {
                "candidate": equation,
                "entity": "reaction",
                "reaction_type": reaction_type,
                "family": reaction["family"],
                "data_kind": _join(dataset["kind"] for dataset in datasets),
                "unit": _join(dataset["unit"] for dataset in datasets),
                "applicable_range": _join(_validity(dataset) for dataset in datasets),
                "dataset_id": _join(dataset["id"] for dataset in datasets),
                "verdict": assessment["verdict"],
                "reason": assessment["message"],
                "id": reaction["id"],
            }
        )

    outputs: dict[str, Payload] = {}
    network_reactions = [
        {**reaction, "reaction_type": _reaction_type(reaction)} for reaction in ordered_reactions
    ]
    for layer, rows in rows_by_layer.items():
        directory = f"assessments/{layer}"
        state_rows = [row for row in rows if row["entity"] == "state"]
        reaction_rows = [row for row in rows if row["entity"] == "reaction"]
        if layer in STATE_ASSESSMENT_NAMES:
            outputs[f"{directory}/states.csv"] = _assessment_csv(layer, "state", state_rows)
        outputs[f"{directory}/reactions.csv"] = _assessment_csv(layer, "reaction", reaction_rows)
        outputs.update(
            {
                f"{directory}/{filename}": _assessment_csv(
                    layer,
                    "reaction",
                    [row for row in reaction_rows if row["family"] == family],
                )
                for family, filename in REACTION_FAMILY_FILES.items()
            }
        )
        outputs[f"{directory}/family_summary.csv"] = _csv(
            reaction_family_rows(layer, network_reactions)
        )
        outputs[f"{directory}/reaction_family.svg"] = reaction_family_svg(layer, network_reactions)
        outputs[f"{directory}/summary.csv"] = _csv(summary_rows(rows))
        outputs[f"{directory}/verdict_counts.svg"] = verdict_counts_svg(layer, rows)
    outputs["assessments/statistics.csv"] = _csv(
        statistics_rows(rows_by_layer, states["states"], reactions["reactions"])
    )
    outputs["assessments/statistics.svg"] = statistics_svg(
        rows_by_layer, states["states"], reactions["reactions"]
    )
    outputs["assessments/composition.svg"] = composition_svg(
        states["states"], reactions["reactions"]
    )
    outputs.update(_screening_outputs(states["states"], state_names, network_reactions))
    network_views = _network_views(network_reactions)
    outputs["assessments/network.html"] = network_explorer_html(
        case_name=str(states["metadata"]["case"]),
        states=states["states"],
        state_names=state_names,
        state_meanings={state["id"]: _state_meaning(state) for state in states["states"]},
        state_alternatives=alternatives,
        reactions=network_reactions,
        views=network_views,
    )
    outputs["assessments/network.png"] = network_matrix_png(
        case_name=str(states["metadata"]["case"]),
        states=states["states"],
        state_names=state_names,
        reactions=network_reactions,
    )
    pathway_view, pathway_reactions = _static_pathway_view(
        network_views, states["states"], network_reactions
    )
    outputs["assessments/pathways.png"] = pathway_png(
        case_name=str(states["metadata"]["case"]),
        view_label=str(pathway_view["label"]),
        states=states["states"],
        state_names=state_names,
        reactions=pathway_reactions,
    )
    return outputs


def _static_pathway_view(
    views: list[dict], states: list[dict], reactions: list[dict]
) -> tuple[dict, list[dict]]:
    screening_views = [view for view in views if view["id"].startswith("screening:")]
    candidates = [views[-1], *reversed(screening_views[:-1])]
    for view in candidates:
        reaction_ids = set(view["reaction_ids"] or [])
        selected = [reaction for reaction in reactions if reaction["id"] in reaction_ids]
        reachability = reaction_reachability(states, selected)
        if choose_pathway_target(states, selected, reachability) is not None:
            return view, selected
    return {"label": "All candidates - topology only"}, reactions


def _screening_outputs(
    states: list[dict], state_names: dict[str, str], reactions: list[dict]
) -> dict[str, str]:
    outputs = {}
    alternatives = _resolution_alternatives(states, state_names)
    for stage_name, gates in SCREENING_STAGES:
        screened_states = [state for state in states if _passes_screen(state, gates)]
        screened_reactions = [reaction for reaction in reactions if _passes_screen(reaction, gates)]
        summary = _screening_summary(states, reactions, gates)
        directory = f"assessments/screening/{stage_name}"
        outputs[f"{directory}/states.csv"] = _screened_states_csv(
            screened_states, state_names, alternatives
        )
        outputs[f"{directory}/reactions.csv"] = _screened_reactions_csv(
            screened_reactions, state_names
        )
        outputs.update(
            {
                f"{directory}/{filename}": _screened_reactions_csv(
                    [reaction for reaction in screened_reactions if reaction["family"] == family],
                    state_names,
                )
                for family, filename in REACTION_FAMILY_FILES.items()
            }
        )
        outputs[f"{directory}/summary.csv"] = _csv(summary)
        outputs[f"{directory}/retention.svg"] = screening_retention_svg(summary)
    return outputs


def _network_views(reactions: list[dict]) -> list[dict]:
    views: list[dict] = [
        {
            "id": f"assessment:{layer}",
            "label": f"All candidates - {layer.replace('_', ' ').title()}",
            "assessment": layer,
            "reaction_ids": None,
        }
        for layer in ASSESSMENT_NAMES
    ]
    views.extend(
        {
            "id": f"screening:{stage_name}",
            "label": f"Screening - {_screening_label(gates)}",
            "assessment": None,
            "reaction_ids": [
                reaction["id"] for reaction in reactions if _passes_screen(reaction, gates)
            ],
        }
        for stage_name, gates in SCREENING_STAGES
    )
    return views


def _passes_screen(candidate: dict, gates: tuple[tuple[str, ...], ...]) -> bool:
    assessments = candidate["assessments"]
    for gate in gates:
        applicable = [layer for layer in gate if layer in assessments]
        if applicable and not any(assessments[layer]["verdict"] == "pass" for layer in applicable):
            return False
    return True


def _screening_summary(
    states: list[dict], reactions: list[dict], gates: tuple[tuple[str, ...], ...]
) -> list[dict]:
    rows = []
    for entity, candidates in (("state", states), ("reaction", reactions)):
        active = list(candidates)
        rows.append(
            _screening_summary_row(entity, "all", "applied", active, active, len(candidates))
        )
        for gate in gates:
            before = active
            assessments = candidates[0]["assessments"] if candidates else {}
            applicable = [layer for layer in gate if layer in assessments]
            if not applicable:
                applicability = "not_applicable"
            else:
                applicability = "applied"
                active = [
                    candidate
                    for candidate in before
                    if any(
                        candidate["assessments"][layer]["verdict"] == "pass" for layer in applicable
                    )
                ]
            rows.append(
                _screening_summary_row(
                    entity,
                    _screening_gate_key(gate),
                    applicability,
                    before,
                    active,
                    len(candidates),
                )
            )
    return rows


def _screening_summary_row(
    entity: str,
    layer: str,
    applicability: str,
    before: list[dict],
    retained: list[dict],
    total: int,
) -> dict:
    return {
        "entity": entity,
        "step": layer,
        "applicability": applicability,
        "input": len(before),
        "retained": len(retained),
        "rejected_at_step": len(before) - len(retained),
        "total": total,
        "retained_percent": round(100 * len(retained) / total, 3) if total else 0.0,
    }


def _screened_states_csv(
    states: list[dict],
    state_names: dict[str, str],
    alternatives: dict[str, str],
) -> str:
    rows = [
        {
            "species": state_names[state["id"]],
            "formula": formula(state["composition"]),
            "charge": state["charge"],
            "excitation": state["state_axes"]["excitation"],
            "resolution": state["state"]["resolution"],
            "lifetime_class": state["state_axes"]["lifetime_class"],
            "state_meaning": _state_meaning(state),
            "alternative_resolution_states": alternatives[state["id"]],
            "origin": state["origin"],
            "depth": state["depth"],
            "id": state["id"],
        }
        for state in states
    ]
    columns = (
        "species",
        "formula",
        "charge",
        "excitation",
        "resolution",
        "lifetime_class",
        "state_meaning",
        "alternative_resolution_states",
        "origin",
        "depth",
        "id",
    )
    return _csv(rows, fieldnames=columns)


def _screened_reactions_csv(
    reactions: list[dict],
    state_names: dict[str, str],
) -> str:
    rows = [
        {
            "equation": _reaction_display(reaction, state_names),
            "reaction_type": _reaction_type(reaction),
            "family": reaction["family"],
            "process": reaction["process"],
            "origin": reaction["origin"],
            "depth": reaction["depth"],
            "state_verdict": reaction["assessments"]["state"]["verdict"],
            "consistency_verdict": reaction["assessments"]["consistency"]["verdict"],
            "thermochemistry_verdict": reaction["assessments"]["thermochemistry"]["verdict"],
            "kinetics_verdict": reaction["assessments"]["kinetics"]["verdict"],
            "reaction_evidence_verdict": reaction["assessments"]["reaction_evidence"]["verdict"],
            "kinetics_or_reaction_evidence_verdict": _or_verdict(reaction),
            "accepted_by": _or_basis(reaction),
            "id": reaction["id"],
        }
        for reaction in reactions
    ]
    columns = (
        "equation",
        "reaction_type",
        "family",
        "process",
        "origin",
        "depth",
        "state_verdict",
        "consistency_verdict",
        "thermochemistry_verdict",
        "kinetics_verdict",
        "reaction_evidence_verdict",
        "kinetics_or_reaction_evidence_verdict",
        "accepted_by",
        "id",
    )
    return _csv(rows, fieldnames=columns)


def _screening_label(gates: tuple[tuple[str, ...], ...]) -> str:
    return " -> ".join(
        " OR ".join(layer.replace("_", " ").title() for layer in gate) for gate in gates
    )


def _screening_gate_key(gate: tuple[str, ...]) -> str:
    return "_or_".join(gate)


def _or_verdict(reaction: dict) -> str:
    verdicts = {
        reaction["assessments"][layer]["verdict"] for layer in ("kinetics", "reaction_evidence")
    }
    if "pass" in verdicts:
        return "pass"
    if "unknown" in verdicts:
        return "unknown"
    if "fail" in verdicts:
        return "fail"
    return "not_applicable"


def _or_basis(reaction: dict) -> str:
    return "; ".join(
        layer
        for layer in ("kinetics", "reaction_evidence")
        if reaction["assessments"][layer]["verdict"] == "pass"
    )


ASSESSMENT_COLUMNS = {
    ("consistency", "state"): (
        "candidate",
        "excitation",
        "resolution",
        "lifetime_class",
        "state_meaning",
        "alternative_resolution_states",
        "verdict",
        "reason",
        "id",
    ),
    ("consistency", "reaction"): (
        "candidate",
        "reaction_type",
        "verdict",
        "reason",
        "id",
    ),
    ("state", "state"): (
        "candidate",
        "excitation",
        "resolution",
        "lifetime_class",
        "state_meaning",
        "alternative_resolution_states",
        "evidence",
        "verdict",
        "reason",
        "id",
    ),
    ("state", "reaction"): ("candidate", "reaction_type", "verdict", "reason", "id"),
    ("thermochemistry", "state"): (
        "candidate",
        "excitation",
        "resolution",
        "lifetime_class",
        "state_meaning",
        "alternative_resolution_states",
        "verdict",
        "reason",
        "id",
    ),
    ("thermochemistry", "reaction"): (
        "candidate",
        "reaction_type",
        "delta_h_eV",
        "delta_g_eV",
        "threshold_eV",
        "verdict",
        "reason",
        "id",
    ),
    ("reaction_evidence", "state"): ("candidate", "verdict", "reason", "id"),
    ("reaction_evidence", "reaction"): (
        "candidate",
        "reaction_type",
        "matched_source",
        "channel_scope",
        "verdict",
        "reason",
        "id",
    ),
    ("kinetics", "state"): ("candidate", "verdict", "reason", "id"),
    ("kinetics", "reaction"): (
        "candidate",
        "reaction_type",
        "data_kind",
        "unit",
        "applicable_range",
        "dataset_id",
        "verdict",
        "reason",
        "id",
    ),
}


def _assessment_csv(layer: str, entity: str, rows: list[dict]) -> str:
    columns = ASSESSMENT_COLUMNS[(layer, entity)]
    projected = [{column: row.get(column, "") for column in columns} for row in rows]
    return _csv(projected, fieldnames=columns)


def _csv(rows: list[dict], *, fieldnames: tuple[str, ...] | None = None) -> str:
    if not rows and fieldnames is None:
        return ""
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(fieldnames or rows[0]),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _boolean(value: object) -> str:
    return "true" if value else "false"


def _structure_scope(composition: dict[str, int], state_id: str) -> str:
    if state_id == "e" or sum(composition.values()) <= 1:
        return "not_applicable"
    if sum(composition.values()) == 2:
        return "formula_determined"
    return "formula_only"


def _state_view_fields(state: dict, alternatives: dict[str, str]) -> dict[str, str]:
    return {
        "excitation": state["state_axes"]["excitation"],
        "resolution": state["state"]["resolution"],
        "lifetime_class": state["state_axes"]["lifetime_class"],
        "state_label": state["state_axes"]["canonical_label"],
        "state_symbol": _state_symbol(state),
        "state_meaning": _state_meaning(state),
        "alternative_resolution_states": alternatives[state["id"]],
        "structure_scope": state["state_axes"]["structure_scope"],
    }


def _resolution_alternatives(states: list[dict], state_names: dict[str, str]) -> dict[str, str]:
    groups: dict[tuple, list[dict]] = {}
    for state in states:
        axes = state["state_axes"]
        if axes["excitation"] in {"ground", "electron"}:
            continue
        key = (
            tuple(sorted(state["composition"].items())),
            state["charge"],
            axes["excitation"],
        )
        groups.setdefault(key, []).append(state)
    alternatives = {state["id"]: "" for state in states}
    for grouped in groups.values():
        for state in grouped:
            opposite = "resolved" if state["state"]["resolution"] == "lumped" else "lumped"
            names = sorted(
                state_names[other["id"]]
                for other in grouped
                if other["state"]["resolution"] == opposite
            )
            alternatives[state["id"]] = "; ".join(names)
    return alternatives


def _state_display(state: dict) -> str:
    if state["id"] == "e":
        return "e"
    name = formula(state["composition"]) + _charge_display(state["charge"])
    kind = state["state"]["kind"]
    if kind == "ground":
        return name
    symbol = _state_symbol(state)
    return f"{name}{symbol}" if symbol == "*" else f"{name}({symbol})"


def _state_symbol(state: dict) -> str:
    label = state["state"]["label"].lower()
    return (
        TERM_SYMBOLS.get(label, label) if label else STATE_SYMBOLS.get(state["state"]["kind"], "")
    )


def _state_meaning(state: dict) -> str:
    if state["id"] == "e":
        return "free electron"
    axes = state["state_axes"]
    excitation = axes["excitation"]
    lifetime = axes["lifetime_class"]
    resolution = state["state"]["resolution"]
    symbol = _state_symbol(state)
    if excitation == "ground":
        return "electronic ground state"
    if resolution == "resolved":
        if symbol.lower().startswith("v"):
            return f"resolved vibrational level {symbol}"
        return (
            f"resolved spectroscopic state {symbol}" if symbol else "resolved spectroscopic state"
        )
    if excitation == "vibrational":
        return "vibrationally excited manifold (lumped)"
    label = "" if symbol == "*" else f"{symbol} "
    if lifetime == "metastable":
        return "metastable electronic-state manifold (lumped)"
    if lifetime == "resonant_radiative":
        return "resonant radiative electronic-state manifold (lumped)"
    if lifetime == "mixed_metastable_resonant":
        return f"{label}electronic-state manifold (lumped; mixed metastable/resonant)"
    return f"{label}electronic-state manifold (lumped; lifetime unspecified)"


def _reaction_type(reaction: dict) -> str:
    key = (reaction["family"], reaction["process"])
    return REACTION_TYPES.get(key, reaction["process"].replace("_", " "))


def _ordered_reactions(reactions: list[dict], state_names: dict[str, str]) -> list[dict]:
    family_order = {"electron": 0, "ion": 1, "neutral": 2, "surface": 3}
    return sorted(
        reactions,
        key=lambda reaction: (
            reaction["depth"],
            family_order.get(reaction["family"], 9),
            reaction["process"],
            _reaction_display(reaction, state_names),
            reaction["id"],
        ),
    )


def _charge_display(charge: int) -> str:
    if charge == 0:
        return ""
    sign = "+" if charge > 0 else "-"
    return sign if abs(charge) == 1 else f"^{abs(charge)}{sign}"


def _reaction_display(reaction: dict, state_names: dict[str, str]) -> str:
    left = [_term_display(term, state_names) for term in reaction["reactants"]]
    right = [_term_display(term, state_names) for term in reaction["products"]]
    if reaction["third_body"]:
        left.append("M")
        right.append("M")
    if reaction["surface"]:
        left.append(f"[{reaction['surface']}]")
    return f"{' + '.join(left)} -> {' + '.join(right)}"


def _term_display(term: dict, state_names: dict[str, str]) -> str:
    name = state_names.get(term["species"], term["species"])
    count = term["n"]
    if count == 1:
        return name
    written = int(count) if count == int(count) else count
    return f"{written} {name}"


def _common(values) -> object:
    unique = []
    for value in values:
        if value is not None and value not in unique:
            unique.append(value)
    return unique[0] if len(unique) == 1 else ""


def _kinetic_data(capabilities: dict) -> str:
    kinds = []
    if capabilities["cross_section_ready"]:
        kinds.append("cross_section")
    if capabilities["direct_rate_ready"]:
        kinds.append("rate_coefficient")
    if capabilities["estimated"]:
        kinds.append("estimated")
    return "; ".join(kinds)


def _state_evidence_display(evidence: dict) -> str:
    records = "; ".join(record["id"] for record in evidence["records"])
    return f"{evidence['match']}: {records}" if records else evidence["match"]


def _channel_scopes(evidence: dict) -> str:
    records = (
        evidence["exact_channel_records"]
        + evidence["related_total_process_records"]
        + evidence["related_physical_process_records"]
    )
    return _join(
        [record["channel_scope"] for record in records]
        + [dataset["channel_scope"] for dataset in evidence["overlay_datasets"]]
    )


def _datasets(evidence: dict) -> list[dict]:
    datasets = list(evidence["overlay_datasets"])
    for record in evidence["exact_channel_records"] + evidence["related_total_process_records"]:
        datasets.extend(record["datasets"])
    unique: dict[str, dict] = {}
    for dataset in datasets:
        unique.setdefault(dataset["id"], dataset)
    return list(unique.values())


def _validity(dataset: dict) -> str:
    validity = dataset["validity"]
    if not validity:
        return ""
    minimum = validity["minimum"]
    maximum = validity["maximum"]
    if minimum is None and maximum is None:
        return ""
    if minimum is None:
        interval = f"<= {maximum}"
    elif maximum is None:
        interval = f">= {minimum}"
    else:
        interval = f"{minimum}..{maximum}"
    unit = f" {validity['unit']}" if validity["unit"] else ""
    return f"{validity['quantity']} {interval}{unit}"


def _join(values) -> str:
    unique = []
    for value in values:
        if value not in (None, ""):
            written = str(value)
            if written not in unique:
                unique.append(written)
    return "; ".join(unique)
