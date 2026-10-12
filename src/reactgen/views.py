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
from reactgen.pathway import reaction_reachability
from reactgen.pathway_view import pathway_png
from reactgen.presentation import state_meaning, state_name


def view(
    document: dict,
    outdir: Path,
    kind: str,
    *,
    seeds: tuple[str, ...] = (),
    target: str | None = None,
) -> Path:
    """Render existing conclusions; pathway distance does not predict time or flux.

    Explicit seeds replace the default input gases. Electrons are available only
    when explicitly named. Third bodies and walls are implicit topology inputs,
    whose physical availability is outside this view's conclusion.
    """
    if kind not in {"network", "matrix", "pathway"}:
        raise ValueError("view kind must be network, matrix, or pathway")
    if kind == "matrix" and (seeds or target is not None):
        raise ValueError("matrix includes all candidates and does not use seed or target options")
    states, reactions = document["states"], document["reactions"]
    supplied = tuple(sorted(set(seeds))) if seeds else _input_seeds(document)
    reachability = reaction_reachability(states, reactions, seeds=supplied)
    if target is not None and target not in {state["id"] for state in states}:
        raise ValueError(f"unknown pathway target state: {target}")
    names = {state["id"]: state_name(state) for state in states}
    title = ", ".join(document["input"]["gases"])
    scope = document["metadata"]["generation"]["scope"]
    payload: str | bytes
    if kind == "network":
        payload = network_explorer_html(
            case_name=title,
            states=states,
            state_names=names,
            state_meanings={state["id"]: state_meaning(state) for state in states},
            state_alternatives=dict.fromkeys(names, ""),
            reactions=reactions,
            views=_assessment_views(reactions),
            seeds=reachability.seeds,
            target=target,
            scope_note=scope,
            conditions=document["input"].get("conditions", {}),
        )
    elif kind == "matrix":
        if len(reactions) > MAX_MATRIX_COLUMNS:
            return _matrix_index(outdir, title, scope, states, names, reactions)
        payload = network_matrix_png(
            case_name=title,
            states=states,
            state_names=names,
            reactions=reactions,
        )
    else:
        payload = pathway_png(
            case_name=title,
            view_label="All saved candidates",
            states=states,
            state_names=names,
            reactions=reactions,
            seeds=reachability.seeds,
            target=target,
        )
    filename = "network.html" if kind == "network" else f"{kind}.png"
    return _publish_view(outdir, filename, payload)


def _matrix_index(
    outdir: Path,
    title: str,
    scope: str,
    states: list[dict],
    names: dict[str, str],
    reactions: list[dict],
) -> Path:
    panels = []
    for index, (start, stop, payload) in enumerate(
        network_matrix_pages(
            case_name=title, states=states, state_names=names, reactions=reactions
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
        f"<p>{len(reactions):,} reactions in {len(panels)} panels. Every reaction has its own "
        "column in one panel; all panels use the same state rows. Click an image for full "
        "resolution. No reactions are sampled or merged.</p>"
        f"<p>{escape(scope)}</p>" + "".join(panels) + "</html>"
    )
    return _publish_view(outdir, "matrix.html", html)


def _input_seeds(document: dict) -> tuple[str, ...]:
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
    layers = sorted({layer for reaction in reactions for layer in reaction["assessments"]})
    return [
        {"id": "all", "label": "All saved candidates", "assessment": None, "reaction_ids": None},
        *[
            {
                "id": layer,
                "label": layer.replace("_", " "),
                "assessment": layer,
                "reaction_ids": None,
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
