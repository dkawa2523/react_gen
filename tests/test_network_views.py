"""Display conclusions and preserve every matrix reaction at width boundaries."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from hashlib import sha256
from io import BytesIO
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image

from reactgen import export
from reactgen.case import Case
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.network_matrix import (
    MAX_MATRIX_COLUMNS,
    _column_bounds,
    network_matrix_pages,
    network_matrix_png,
)
from reactgen.pipeline import analyze
from reactgen.views import view


def _matrix_document(count: int) -> dict:
    """Rendering fixture with distinct IDs; it asserts no new physical channels."""
    states = [
        {
            "id": "Ar@ground",
            "composition": {"Ar": 1},
            "charge": 0,
            "state": {"kind": "ground", "resolution": "resolved", "label": ""},
            "phase": "gas",
            "structure": None,
            "classes": ["feed"],
        }
    ]
    reactions = [
        {
            "id": f"render_{index:05d}",
            "family": "neutral",
            "process": "elastic",
            "depth": 0,
            "reactants": [{"species": "Ar@ground", "n": 1.0}],
            "products": [{"species": "Ar@ground", "n": 1.0}],
            "assessments": {
                layer: {"verdict": "pass"}
                for layer in (
                    "consistency",
                    "state",
                    "thermochemistry",
                    "reaction_evidence",
                    "kinetics",
                )
            },
        }
        for index in range(count)
    ]
    return {
        "input": {"gases": ["Ar"]},
        "metadata": {"generation": {"scope": "Rendering fixture only."}},
        "states": states,
        "reactions": reactions,
    }


@pytest.mark.parametrize("count", [0, 1, 8000, 8001, 10000, 16001])
def test_matrix_panels_have_disjoint_columns_and_complete_reaction_coverage(count: int) -> None:
    saved = _matrix_document(count)
    seen = []
    panels = network_matrix_pages(
        case_name="boundary",
        states=saved["states"],
        state_names={"Ar@ground": "Ar"},
        reactions=list(reversed(saved["reactions"])),
    )
    for start, stop, png in panels:
        ids = [reaction["id"] for reaction in saved["reactions"][start:stop]]
        seen.extend(ids)
        with Image.open(BytesIO(png)) as image:
            info = image.info
            assert int(info["reactgen.reaction_count"]) == len(ids) <= MAX_MATRIX_COLUMNS
            assert int(info["reactgen.total_reaction_count"]) == count
            assert int(info["reactgen.first_reaction"]) == (start + 1 if ids else 0)
            assert int(info["reactgen.last_reaction"]) == stop
            assert (
                info["reactgen.reaction_ids_sha256"] == sha256("\n".join(ids).encode()).hexdigest()
            )
            width = int(info["reactgen.matrix_columns_px"])
            bounds = [_column_bounds(index, len(ids), 0, width) for index in range(len(ids))]
            assert all(left[1] < right[0] for left, right in pairwise(bounds))
            assert not bounds or (bounds[0][0] == 0 and bounds[-1][1] == width - 1)
    assert seen == [reaction["id"] for reaction in saved["reactions"]]


def test_single_matrix_rejects_overflow_instead_of_merging_columns() -> None:
    saved = _matrix_document(MAX_MATRIX_COLUMNS + 1)
    with pytest.raises(ValueError, match="network_matrix_pages"):
        network_matrix_png(
            case_name="boundary",
            states=saved["states"],
            state_names={"Ar@ground": "Ar"},
            reactions=saved["reactions"],
        )


def test_split_matrix_index_preserves_previous_panels_after_publish_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from reactgen import views

    saved = _matrix_document(MAX_MATRIX_COLUMNS + 1)
    before = copy.deepcopy(saved)
    index = view(saved, tmp_path, "matrix")
    assert index.name == "matrix.html"
    html = index.read_text(encoding="utf-8")
    paths = sorted(set(re.findall(r'href="(matrix-[^"]+\.png)"', html)))
    assert len(paths) == 2
    assert "8,001 reactions in 2 panels" in html
    assert "Reactions 1-8,000 of 8,001" in html
    assert "Reactions 8,001-8,001 of 8,001" in html
    previous = {path: (tmp_path / path).read_bytes() for path in paths}
    assert saved == before
    saved["reactions"][0]["assessments"]["consistency"]["verdict"] = "fail"
    publish = views._publish_view

    def fail_second_panel(directory, filename, payload):
        if filename.startswith("matrix-002-"):
            raise OSError("injected panel failure")
        return publish(directory, filename, payload)

    monkeypatch.setattr(views, "_publish_view", fail_second_panel)
    with pytest.raises(OSError, match="panel failure"):
        view(saved, tmp_path, "matrix")
    assert index.read_text(encoding="utf-8") == html
    assert all((tmp_path / path).read_bytes() == content for path, content in previous.items())


def test_cli_reports_the_split_matrix_index(tmp_path: Path, monkeypatch, capsys) -> None:
    from reactgen import views

    monkeypatch.setattr(export, "read", lambda path: {})
    monkeypatch.setattr(views, "view", lambda *args, **kwargs: tmp_path / "matrix.html")
    assert main(["view", "saved", "--kind", "matrix", "--out", str(tmp_path)]) == 0
    assert "Split matrix: open" in capsys.readouterr().out


@pytest.mark.skipif(shutil.which("node") is None, reason="embedded JavaScript needs a JS runtime")
def test_unselected_judgment_is_distinct_in_badges_filters_and_graphs(tmp_path: Path) -> None:
    saved = export.document(analyze(Case("view-test", ("Ar",)), EvidenceCatalog.load_paths(())))
    saved["reactions"][0]["assessments"]["consistency"]["verdict"] = "unknown"
    saved["reactions"][1]["assessments"]["consistency"]["verdict"] = "fail"
    html = view(saved, tmp_path, "network").read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    source = _DOM_STUB + "\n" + scripts[-1] + "\n" + _JUDGMENT_ASSERTIONS
    encoded = json.dumps({"source": source, "data": scripts[0]})
    completed = subprocess.run(  # noqa: S603 - discovered local runtime, no shell
        [str(shutil.which("node")), "--input-type=commonjs", "-e", _RUN_JS],
        input=encoded,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("historical", [False, True])
def test_network_preserves_saved_scientific_meaning_and_absence_without_reassessment(
    tmp_path: Path, monkeypatch, historical: bool
) -> None:
    saved = export.document(analyze(Case("meaning", ("Ar",)), EvidenceCatalog.load(None)))
    reaction = saved["reactions"][0]
    state_id = reaction["reactants"][0]["species"]
    state = next(item for item in saved["states"] if item["id"] == state_id)
    assessment = reaction["assessments"]["state"]
    assessment.update(
        proposition="participant_support_<claim>",
        scope="Binding is not observed existence.",
        requirements=[
            {
                "responsibility": "external_models",
                "target": state_id,
                "quantity": "decay_model",
                "reason": "Model needed; not a scalar input.",
            }
        ],
        dependencies=[[state_id, "state"]],
    )
    if historical:
        assessment["proposition"] = ""
        for key in ("scope", "requirements", "dependencies"):
            assessment.pop(key)
    reaction["thermochemistry"] = {
        "delta_h_eV": 0,
        "delta_h_reference_temperature_K": 0,
        "delta_h_standard_pressure_Pa": 100000,
    }
    reaction["data_use"].update(
        status="needs_transform",
        kind="sticking_coefficient",
        value=0,
        unit="1",
        dataset_id="adopted",
        required_inputs=["electron_energy_distribution"],
        required_transforms=["surface_flux_conversion"],
        selection={"sticking_coefficient": {"record": "adopted"}},
        disagreements=["alternative"],
        reason="Saved selection and applicability reason.",
    )
    reaction["evidence"]["overlay_datasets"] = [
        {
            "id": "adopted",
            "kind": "sticking_coefficient",
            "source": {
                "citation": "Declared source <text> </script><script>alert('never')</script>"
            },
        },
        {
            "id": "alternative",
            "kind": "sticking_coefficient",
            "source": {"citation": "Competing source"},
        },
    ]
    saved["input"]["conditions"] = {"gas_temperature_K": 700}
    before = copy.deepcopy(saved)

    def forbidden(*args, **kwargs):
        raise AssertionError("views must not evaluate evidence or numerical records")

    monkeypatch.setattr("reactgen.numeric.data_use", forbidden)
    monkeypatch.setattr("reactgen.assessment.evaluate", forbidden)
    html = view(saved, tmp_path, "network").read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) == 2
    payload = json.loads(scripts[0])
    shown = next(item for item in payload["reactions"] if item["id"] == reaction["id"])
    shown_state = next(item for item in payload["states"] if item["id"] == state_id)
    assert shown["assessments"] == reaction["assessments"]
    assert shown["thermochemistry"] == reaction["thermochemistry"]
    assert shown["data_use"] == reaction["data_use"]
    assert shown["evidence"] == reaction["evidence"]
    assert shown_state["assessments"] == state["assessments"]
    assert shown_state["evidence"] == state["evidence"]
    assert shown["numerical_requirements"]["external_models"] == ["electron_energy_distribution"]
    assert shown["numerical_requirements"]["user_inputs"] == []
    assert payload["conditions"] == saved["input"]["conditions"]
    assert saved == before
    if shutil.which("node") is not None:
        assertions = """
const reaction = data.reactions[0];
selectReaction(reaction.id);
assert.ok(el('numerical-use').innerHTML.includes('0 1'));
assert.ok(el('numerical-use').innerHTML.includes('External model'));
assert.ok(!el('numerical-use').innerHTML.includes('conditions.electron_energy_distribution'));
assert.ok(el('numerical-use').innerHTML.includes('alternative'));
assert.ok(el('sources').innerHTML.includes('Declared source &lt;text&gt;'));
assert.ok(el('sources').innerHTML.includes('&lt;/script&gt;'));
assert.ok(!el('sources').innerHTML.includes('<script>'));
assert.ok(el('sources').innerHTML.includes('Competing source'));
assert.ok(el('energy-values').innerHTML.includes('delta_h_reference_temperature_K'));
assert.ok(el('participant-assertions').innerHTML.includes('Saved state evidence'));
const a = reaction.assessments.state;
if (a.proposition) {
  assert.ok(el('assessments').innerHTML.includes('participant support &lt;claim&gt;'));
  assert.ok(el('assessments').innerHTML.includes('Binding is not observed existence.'));
  assert.ok(el('assessments').innerHTML.includes('Depends on:'));
} else {
  assert.ok(el('assessments').innerHTML.includes('Proposition not recorded'));
  assert.ok(el('assessments').innerHTML.includes('Scope not recorded for this assessment.'));
  assert.ok(!el('assessments').innerHTML.includes('Binding is not observed existence.'));
}
"""
        encoded = json.dumps(
            {"source": _DOM_STUB + "\n" + scripts[-1] + "\n" + assertions, "data": scripts[0]}
        )
        completed = subprocess.run(  # noqa: S603 - discovered local runtime, no shell
            [str(shutil.which("node")), "--input-type=commonjs", "-e", _RUN_JS],
            input=encoded,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr


_RUN_JS = """
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
vm.runInNewContext(input.source, {
  payload: input.data, assert: require('node:assert/strict'), URLSearchParams
});
"""

_DOM_STUB = """
const elements = new Map();
function makeElement() {
  return {
    value:'', children:[], options:[], listeners:{}, dataset:{}, _text:'',
    innerHTML:'', disabled:false, hidden:false, classList:{toggle(){}},
    get textContent(){return this._text},
    set textContent(value){this._text=value;this.children=[]},
    add(option){this.options.push(option)}, append(child){this.children.push(child)},
    addEventListener(name, callback){this.listeners[name]=callback},
    insertAdjacentHTML(){}, querySelector(){return null}
  };
}
const document = {
  getElementById(id){if(!elements.has(id))elements.set(id,makeElement());return elements.get(id)},
  createElement(){return makeElement()}
};
document.getElementById('network-data').textContent = payload;
const location = {search:''};
function Option(label, value){this.label=label;this.value=String(value)}
"""

_JUDGMENT_ASSERTIONS = """
const initial = JSON.stringify(data.reactions);
assert.equal(el('scope-note').textContent, data.scope_note);
assert.equal(currentView().assessment, null);
assert.equal(el('verdict').disabled, true);
assert.equal(filtered.length, data.reactions.length);
assert.equal(verdictFor(data.reactions[0]), 'unselected');
assert.ok(el('reaction-list').children.every(row=>row.innerHTML.includes('judgment not selected')));
assert.equal(verdictDash.unselected, '');
el('view').value = 'consistency';
el('view').listeners.change();
assert.equal(el('verdict').disabled, false);
el('verdict').value = 'unknown';
el('verdict').listeners.change();
assert.equal(filtered.length, 1);
assert.equal(filtered[0].id, data.reactions[0].id);
selectReaction(filtered[0].id);
assert.ok(el('graph').innerHTML.includes('stroke-dasharray="7 5"'));
assert.ok(!el('graph').innerHTML.includes('judgment not selected'));
el('view').value = 'all';
el('view').listeners.change();
assert.equal(el('verdict').disabled, true);
assert.equal(el('verdict').value, '');
assert.equal(filtered.length, data.reactions.length);
assert.ok(el('graph').innerHTML.includes('judgment not selected'));
assert.ok(!el('graph').innerHTML.includes('stroke-dasharray'));
const neighbor = neighborhoodReactionNode(data.reactions[0],0,0,360,'producer');
assert.ok(neighbor.includes('judgment not selected'));
assert.ok(!neighborhoodEdge(0,0,1,1,data.reactions[0]).includes('stroke-dasharray'));
el('view').value = 'state';
el('view').listeners.change();
el('reset').onclick();
assert.equal(el('view').value, 'all');
assert.equal(el('verdict').disabled, true);
assert.equal(JSON.stringify(data.reactions), initial);
assert.equal(el('scope-note').textContent, data.scope_note);
"""
