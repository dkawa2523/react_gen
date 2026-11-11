"""Optional visual views of a saved canonical result, without re-evaluation."""

from __future__ import annotations

import os
import tempfile
from hashlib import sha256
from html import escape
from pathlib import Path

from reactgen.chemistry import parse_state_id
from reactgen.network_matrix import MAX_MATRIX_COLUMNS, network_matrix_pages, network_matrix_png
from reactgen.network_view import network_explorer_html
from reactgen.pathway import (
    PATHWAY_POLICY_FORMAT,
    analyze_pathways,
    checked_pathway_query,
    producer_pathway,
)
from reactgen.pathway_view import pathway_png
from reactgen.presentation import exploration_status_text, state_meaning
from reactgen.reaction_graphs import energy_graphs, judgment_graph, reaction_diagram
from reactgen.reaction_tables import state_labels


def view(
    document: dict,
    outdir: Path,
    kind: str,
    *,
    seeds: tuple[str, ...] = (),
    target: str | None = None,
    checked: bool = False,
    via: str | None = None,
    filename: str | None = None,
) -> Path:
    """Render existing conclusions; pathway distance does not predict time or flux.

    Explicit seeds make a separate saved-context query over the same judgments.
    Seed electrons require explicit supply; internally generated electrons need
    their producer pathway. Display filters do not change the scientific edge
    set or source result.
    """
    if kind not in {"network", "matrix", "pathway"}:
        raise ValueError("view kind must be network, matrix, or pathway")
    if kind == "matrix" and (seeds or target is not None or checked or via is not None):
        raise ValueError(
            "matrix includes all candidates and does not use --seed, --target, --checked or --via"
        )
    if via is not None and target is None:
        raise ValueError("--via requires a saved state ID specified with --target")
    states, reactions = document["states"], document["reactions"]
    generation = document["metadata"]["generation"]
    exploration_status = exploration_status_text(generation)
    supplied = tuple(sorted(set(seeds))) if seeds else _input_seeds(document)
    if target is not None and target not in {state["id"] for state in states}:
        raise ValueError(
            f"unknown pathway target state: {target}. "
            f"The state is absent from the saved candidates. {exploration_status}"
        )
    names = state_labels(document)
    title = ", ".join(document["input"]["gases"])
    if kind == "matrix":
        if len(reactions) > MAX_MATRIX_COLUMNS:
            return _matrix_index(
                outdir, title, generation["scope"], exploration_status, states, names, reactions
            )
        return _publish_view(
            outdir,
            "matrix.png",
            network_matrix_png(
                case_name=title,
                states=states,
                state_names=names,
                reactions=reactions,
                exploration_status=exploration_status,
            ),
        )

    historical = document["metadata"].get("helper_view_format", 1) < PATHWAY_POLICY_FORMAT
    pathways = _pathway_analysis(
        document, supplied, override=bool(seeds) or (historical and (checked or via is not None))
    )
    mode = "checked" if checked else "conditioned"
    if checked:
        pathways = checked_pathway_query(states, reactions, pathways)
    selected = (
        producer_pathway(states, reactions, pathways, target=target, via=via, mode=mode)
        if via is not None and target is not None
        else None
    )
    skipped_requested_expansions = {
        task["reaction"]: {"depth": task["depth"], "reason": task["reason"]}
        for task in generation.get("unexpanded", ())
        if task.get("operation") == "requested_channel_addition"
    }
    payload: str | bytes
    if kind == "network":
        payload = network_explorer_html(
            case_name=title,
            state_names=names,
            state_meanings={state["id"]: state_meaning(state) for state in states},
            views=_assessment_views(reactions),
            document=document,
            target=target,
            pathways=pathways,
            mode=mode,
            exploration_status=exploration_status,
            selected=selected,
            skipped_requested_expansions=skipped_requested_expansions,
        )
    else:
        payload = pathway_png(
            case_name=title,
            view_label="Checked candidate pathway" if checked else "Conditioned candidates",
            states=states,
            state_names=names,
            reactions=reactions,
            target=target,
            pathways=pathways,
            mode=mode,
            exploration_status=exploration_status,
            exploration_complete=generation.get("complete"),
            selected=selected,
            skipped_requested_expansions=skipped_requested_expansions,
        )
    default_name = "network.html" if kind == "network" else "pathway.png"
    return _publish_view(outdir, filename or default_name, payload)


def plot(
    document: dict,
    outdir: Path,
    kind: str,
    reactions: list[dict],
    *,
    judgment: str | None = None,
    reaction_id: str | None = None,
    selection: str = "",
) -> tuple[Path, ...]:
    """Publish one SVG per figure with a single visual subject."""
    if kind == "energy":
        figures = energy_graphs(document, reactions, selection=selection)
    elif kind == "judgment" and judgment:
        available = document["summary"]["judgments"]["reactions"]
        if judgment not in available:
            keys = ", ".join(sorted(available)) or "none"
            raise ValueError(f"reaction judgment {judgment!r} is not saved; available: {keys}")
        figures = {
            f"judgment-{judgment}.svg": judgment_graph(
                reactions,
                judgment,
                selection=selection,
                generation=document["metadata"]["generation"],
            )
        }
    elif kind == "reaction" and reaction_id:
        figures = {f"reaction-{reaction_id}.svg": reaction_diagram(document, reaction_id)}
    else:
        raise ValueError("specify an energy, judgment or reaction figure")
    suffix = f"-selection-{sha256(selection.encode()).hexdigest()[:8]}" if selection else ""
    return tuple(
        _publish_view(outdir, f"{Path(name).stem}{suffix}.svg", content)
        for name, content in figures.items()
    )


def _pathway_analysis(document: dict, supplied: tuple[str, ...], *, override: bool) -> dict:
    existing = document.get("pathways") if not override else None
    if existing is not None:
        return existing
    return analyze_pathways(
        document["states"],
        document["reactions"],
        seeds=supplied,
        conditions=document["input"].get("conditions", {}),
    )


def _matrix_index(
    outdir: Path,
    title: str,
    scope: str,
    exploration_status: str,
    states: list[dict],
    names: dict[str, str],
    reactions: list[dict],
) -> Path:
    panels = []
    for index, (start, stop, payload) in enumerate(
        network_matrix_pages(
            case_name=title,
            states=states,
            state_names=names,
            reactions=reactions,
            exploration_status=exploration_status,
        ),
        start=1,
    ):
        # Content-named panels keep a previously published index coherent if a
        # later render fails before its new index can be published.
        filename = f"matrix-{index:03d}-{sha256(payload).hexdigest()[:12]}.png"
        _publish_view(outdir, filename, payload)
        label = f"Reactions {start + 1:,}-{stop:,} of {len(reactions):,}"
        panels.append(
            f'<section><h2><a href="{filename}">{label}</a></h2>'
            f'<a href="{filename}"><img src="{filename}" loading="lazy" '
            f'alt="{label}"></a></section>'
        )
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)} - reaction matrix</title>"
        "<style>body{font:16px system-ui;max-width:1200px;margin:2rem auto;padding:0 1rem}"
        "img{max-width:100%;height:auto;border:1px solid #cbd2d9}section{margin:2rem 0}</style>"
        f"<h1>{escape(title)} - reaction-state matrix</h1>"
        f"<p>{len(reactions):,} reactions in {len(panels)} panels · shared state rows</p>"
        f"<p><strong>{escape(exploration_status)}</strong></p>"
        f"<p>{escape(scope)}</p>" + "".join(panels) + "</html>"
    )
    return _publish_view(outdir, "matrix.html", html)


def _input_seeds(document: dict) -> tuple[str, ...]:
    if "supply_state_ids" in document.get("metadata", {}):
        return tuple(document["metadata"]["supply_state_ids"])
    inputs = [parse_state_id(written) for written in document["input"]["gases"]]
    return tuple(
        sorted(
            state["id"]
            for state in document["states"]
            if any(
                candidate is not None
                and state["composition"] == candidate.composition
                and state["charge"] == 0
                and state["state"]["kind"] == "ground"
                and state["phase"] == "gas"
                and state["structure"] is None
                for candidate in inputs
            )
        )
    )


def _assessment_views(reactions: list[dict]) -> list[dict]:
    labels = {
        "conservation": "Conservation",
        "consistency": "Process consistency",
        "state": "Participant state support",
        "energy": "Collision energy condition",
        "thermochemistry": "Thermochemical assessment",
        "reaction_evidence": "Reaction evidence",
        "kinetics": "Rate coefficient availability",
    }
    recorded = {layer for reaction in reactions for layer in reaction["assessments"]}
    layers = [layer for layer in labels if layer in recorded] + sorted(recorded - labels.keys())
    return [
        {"id": "all", "label": "No assessment selected", "assessment": None},
        *[
            {
                "id": layer,
                "label": labels.get(layer, layer.replace("_", " ")),
                "assessment": layer,
            }
            for layer in layers
        ],
    ]


def _publish_view(outdir: Path, filename: str, payload: str | bytes) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    content = payload.encode("utf-8") if isinstance(payload, str) else payload
    temporary: Path | None = None
    destination = outdir / filename
    try:
        with tempfile.NamedTemporaryFile(
            dir=outdir, prefix=f".{filename}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
