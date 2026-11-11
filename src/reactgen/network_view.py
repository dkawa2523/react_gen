# ruff: noqa: E501
"""Build one self-contained, lossless reaction-network explorer per case."""

from __future__ import annotations

import json
from typing import Any

from reactgen.pathway import (
    LATER_PRODUCER_CONTEXT,
    MINIMUM_DEPTH_ALTERNATIVE,
    ProducerPathway,
    minimum_pathway_producers,
    net_stoichiometry,
    pathway_context,
    pathway_state_claims,
)
from reactgen.presentation import (
    CalculationRecordIndex,
    calculation_record_index,
    calculation_source,
    calculation_uses,
    conditions_text,
    diagram_terms,
    missing_collision_state_notes,
    numerical_records,
    reaction_equation,
    saved_requirement_summary,
)
from reactgen.reaction_tables import energy_values
from reactgen.records import calculation_record_reference


def network_explorer_html(
    *,
    case_name: str,
    document: dict,
    state_names: dict[str, str],
    state_meanings: dict[str, str],
    views: list[dict],
    pathways: dict,
    exploration_status: str,
    target: str | None = None,
    mode: str = "conditioned",
    selected: ProducerPathway | None = None,
    skipped_requested_expansions: dict[str, dict] | None = None,
) -> str:
    """Return an offline HTML explorer containing every reaction exactly once."""

    records = calculation_record_index(document)
    used_records: dict[str, dict[str, dict]] = {}
    payload = {
        "case": case_name,
        "conditions_text": conditions_text(document["input"].get("conditions", {})),
        "missing_collision_states": missing_collision_state_notes(document),
        "exploration_status": exploration_status,
        "exploration_complete": document["metadata"]["generation"].get("complete"),
        "states": [
            _state_payload(state, state_names, state_meanings, records, used_records)
            for state in document["states"]
        ],
        "reactions": [
            _reaction_payload(
                reaction, state_names, records, used_records, energy_values(document, reaction)
            )
            for reaction in document["reactions"]
        ],
        "calculation_sources": used_records,
        "views": views,
        "pathway_default_mode": mode,
        "pathway_requested_target": target,
        "pathway_via": {
            "producer": selected.producer,
            "target": selected.pathway.target,
            "mode": mode,
            "equation_and_energy_checks_pass": selected.equation_and_energy_checks_pass,
            "seeds": selected.reachability.seeds,
            "state_layers": selected.reachability.state_layers,
            "reaction_layers": selected.reachability.reaction_layers,
            "supported_by": selected.pathway.supported_by,
        }
        if selected
        else None,
        "pathways": pathways,
        "pathway_context": pathway_context(document["reactions"]),
        "pathway_minimum_producers": {
            key: minimum_pathway_producers(pathways[key])
            for key in ("candidate", "conditioned", "checked")
            if key in pathways
        },
        "pathway_producer_labels": {
            "minimum": MINIMUM_DEPTH_ALTERNATIVE,
            "later": LATER_PRODUCER_CONTEXT,
        },
        "pathway_state_claims": pathway_state_claims(document["states"]),
        "skipped_requested_expansions": skipped_requested_expansions or {},
        "scope_note": document["metadata"]["generation"]["scope"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return _HTML.replace("__NETWORK_DATA__", encoded)


def _state_payload(
    state: dict,
    state_names: dict[str, str],
    state_meanings: dict[str, str],
    records: CalculationRecordIndex,
    used_records: dict[str, dict[str, dict]],
) -> dict[str, Any]:
    _save_assessment_sources(state, records, used_records)
    return {
        "id": state["id"],
        "name": state_names[state["id"]],
        "meaning": state_meanings[state["id"]],
        "charge": state["charge"],
        "kind": state["state"]["kind"],
        "excitation": state["state_axes"]["excitation"],
        "resolution": state["state"]["resolution"],
        "lifetime_class": state["state_axes"]["lifetime_class"],
        "structure_scope": state["state_axes"]["structure_scope"],
        "composition": state.get("composition", {}),
        "assessments": state.get("assessments", {}),
        "evidence": state.get("evidence", {}),
    }


def _reaction_payload(
    reaction: dict,
    state_names: dict[str, str],
    records: CalculationRecordIndex,
    used_records: dict[str, dict[str, dict]],
    collision_energy: dict,
) -> dict[str, Any]:
    _save_assessment_sources(reaction, records, used_records)
    uses = []
    for term, use in calculation_uses(reaction):
        if (record := calculation_source(records, term)) is not None:
            record_id = term["record_id"]
            record_ref = term.get("record_ref") or calculation_record_reference(record)
            used_records.setdefault(term["target"], {})[record_ref] = record
            uses.append(use | {"record_id": record_id, "record_ref": record_ref})
    return {
        "id": reaction["id"],
        "equation": reaction_equation(reaction, state_names),
        "reaction_type": reaction["reaction_type"],
        "family": reaction["family"],
        "process": reaction["process"],
        "origin": reaction["origin"],
        "generation_rule": reaction["generation_rule"],
        "depth": reaction["depth"],
        "reactants": reaction["reactants"],
        "products": reaction["products"],
        "diagram_reactants": [term._asdict() for term in diagram_terms(reaction, "reactants")],
        "diagram_products": [term._asdict() for term in diagram_terms(reaction, "products")],
        "net_stoichiometry": {
            state_id: net_stoichiometry(reaction, state_id)
            for state_id in sorted(
                {term["species"] for side in ("reactants", "products") for term in reaction[side]}
            )
        },
        "third_body": reaction.get("third_body"),
        "surface": reaction.get("surface"),
        "stabilization": reaction.get("stabilization"),
        "assessments": reaction["assessments"],
        "thermochemistry": reaction.get("thermochemistry", {}),
        "collision_energy": collision_energy,
        "thermochemical_calculations": reaction.get("thermochemical_calculations", {}),
        "calculation_uses": uses,
        "data_use": reaction.get("data_use", {}),
        "evidence": reaction.get("evidence", {}),
        "numerical_records": numerical_records(reaction),
        "numerical_requirements": saved_requirement_summary(reaction.get("data_use", {})),
    }


def _save_assessment_sources(
    subject: dict, records: CalculationRecordIndex, used_records: dict[str, dict[str, dict]]
) -> None:
    for claim in subject.get("assessments", {}).values():
        for term in claim.get("record_inputs", ()):
            if (source := calculation_source(records, term)) is not None:
                used_records.setdefault(term["target"], {})[term["record_ref"]] = source


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReactGen reaction-network explorer</title>
<style>
:root{--ink:#1f2933;--muted:#64717d;--line:#d7dde2;--panel:#f7f9fa;--blue:#2f6b9a;--orange:#c56a2d;--pass:#2f6b9a;--fail:#a34d52;--unknown:#8a6a2e;--na:#727b83}
*{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:22px 28px 16px;border-bottom:1px solid var(--line)}h1{margin:0 0 5px;font-size:24px}header p{margin:0;color:var(--muted)}
.counts{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}.count{padding:5px 9px;border:1px solid var(--line);border-radius:14px;background:var(--panel);font-variant-numeric:tabular-nums}
.controls{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:14px 28px;border-bottom:1px solid var(--line);background:#fbfcfc;position:sticky;top:0;z-index:4}
.controls[hidden]{display:none}
.controls label,.controls select,.controls input[type=search]{min-width:0}
#equation-pass{vertical-align:middle;margin-right:5px}
label{display:grid;gap:4px;color:var(--muted);font-size:11px;font-weight:650;text-transform:uppercase;letter-spacing:.04em}select,input,button{font:inherit;color:var(--ink);border:1px solid #bfc8cf;border-radius:5px;background:#fff;padding:8px 10px}button{cursor:pointer}button:hover{border-color:var(--blue)}
main{display:grid;grid-template-columns:minmax(340px,430px) minmax(600px,1fr);min-height:calc(100vh - 170px)}
main.pathway-mode{grid-template-columns:minmax(0,1fr)}main.pathway-mode .browser{display:none}main.pathway-mode .detail{overflow:hidden}
.browser{border-right:1px solid var(--line);min-width:0}.browser-head{padding:13px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px;align-items:center}.browser-head strong{font-variant-numeric:tabular-nums}.hint{color:var(--muted);font-size:12px}
#reaction-list{height:calc(100vh - 255px);overflow:auto}.reaction{width:100%;border:0;border-bottom:1px solid #e8ecef;border-radius:0;padding:11px 15px;text-align:left;background:#fff}.reaction:hover{background:#f5f8fa}.reaction.selected{background:#eaf2f7;box-shadow:inset 4px 0 var(--blue)}.equation{font-weight:650;line-height:1.35}.row-meta{display:flex;gap:8px;align-items:center;margin-top:5px;color:var(--muted);font-size:11px;flex-wrap:wrap}.family-dot{width:8px;height:8px;border-radius:50%;display:inline-block}.verdict{padding:1px 6px;border-radius:9px;border:1px solid currentColor;font-weight:650}.pass{color:var(--pass)}.fail{color:var(--fail)}.unknown{color:var(--unknown)}.not_applicable{color:var(--na)}.unselected{color:var(--muted)}select:disabled{color:var(--muted);background:var(--panel)}
.pager{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-top:1px solid var(--line)}.pager span{font-variant-numeric:tabular-nums;color:var(--muted)}
.detail{padding:18px 22px;min-width:0;overflow:auto}.detail h2{margin:0;font-size:18px}
.graph{margin-top:14px;border:1px solid var(--line);border-radius:7px;background:#fff;overflow:auto}.graph svg{display:block;width:100%;min-width:760px;height:auto}
.view-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:13px}.view-tab{padding:7px 12px;background:#fff}.view-tab.active{color:#fff;background:var(--blue);border-color:var(--blue)}
.assessment-summary{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.assessment-summary button{padding:5px 8px;font-size:12px}.assessment-summary button[aria-pressed="true"]{border-color:var(--blue);background:#eaf2f7}.assessment-summary .verdict{margin-left:6px}.assessment-grid>details{grid-column:1/-1}.assessment-grid>details>summary{cursor:pointer}.assessment-grid>.assessment{grid-column:1/-1}
.pathway-related-item small{display:block;color:var(--muted)}
.matrix-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-end;margin-top:14px}.matrix-head h3{margin:0;font-size:16px}.matrix-summary{color:var(--muted);font-size:12px;text-align:right}.matrix-graph{max-height:calc(100vh - 330px);overflow:auto}.matrix-graph svg{width:auto;max-width:none;min-width:0}.matrix-key{display:inline-block;width:17px;height:13px;border:1px solid #27313a}.matrix-key.reactant{background:linear-gradient(#c56a2d 33%,transparent 33%)}.matrix-key.product{background:linear-gradient(transparent 67%,#2f6b9a 67%)}.matrix-key.both{background:linear-gradient(#c56a2d 33%,transparent 33%,transparent 67%,#2f6b9a 67%)}.matrix-key.unchanged{background:linear-gradient(transparent 33%,#6e7881 33%,#6e7881 67%,transparent 67%)}
.network-legend{display:flex;gap:16px;align-items:center;flex-wrap:wrap;padding:9px 12px;border:1px solid var(--line);border-top:0;border-radius:0 0 7px 7px;color:var(--muted);font-size:11px}.legend-group{display:flex;gap:8px;align-items:center}.legend-line{width:28px;border-top:2px solid var(--blue)}.legend-line.unknown{border-top-style:dashed}.legend-state{width:18px;height:12px;border:1px solid var(--ink);border-radius:3px;background:#fff}.legend-state.positive{background:#e8f0f6}.legend-state.negative{background:#f7eae2}.legend-state.excited{background:#fff7e0}
.neighborhood-head{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:14px}.neighborhood-head h3{margin:0;font-size:16px}.role-pagers{display:flex;gap:7px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.role-pager{display:flex;gap:4px;align-items:center;border:1px solid var(--line);border-radius:5px;padding:4px}.role-pager button{padding:3px 7px}.role-pager span{color:var(--muted);font-size:10px;font-variant-numeric:tabular-nums}.neighborhood-summary{margin-top:5px;color:var(--muted);font-size:12px}
.pathway-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;margin-top:14px}.pathway-head h3{margin:0;font-size:16px}.pathway-controls{display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;justify-content:flex-end}.pathway-controls label{min-width:240px}.pathway-graph{max-height:calc(100vh - 390px);overflow:auto}.pathway-graph svg{width:auto;max-width:none;min-width:100%}.pathway-summary{margin-top:6px;color:var(--muted);font-size:12px}.pathway-related{margin-top:12px;border:1px solid var(--line);border-radius:6px;background:#fff}.pathway-related summary{cursor:pointer;padding:10px 12px;font-weight:650}.pathway-related-list{max-height:320px;overflow:auto;border-top:1px solid var(--line)}.pathway-related-item{display:grid;grid-template-columns:125px 1fr auto;gap:10px;width:100%;padding:8px 11px;border:0;border-bottom:1px solid #edf0f2;border-radius:0;text-align:left;background:#fff}.pathway-related-item:hover{background:#f5f8fa}.pathway-related-item span:first-child{color:var(--muted);font-size:11px}.pathway-related-item code{color:var(--muted);font-size:10px}
.state-notation{padding:7px 28px;border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}.state-notation summary{cursor:pointer;font-weight:650;color:var(--ink)}.state-notation p{margin:6px 0 2px}
.facts{display:grid;grid-template-columns:repeat(4,minmax(130px,1fr));gap:8px;margin-top:12px}.fact{padding:9px 11px;background:var(--panel);border:1px solid var(--line);border-radius:5px;min-width:0}.fact span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase}.fact strong{display:block;margin-top:3px;overflow-wrap:anywhere}
.science-detail{margin-top:14px;border:1px solid var(--line);border-radius:5px;padding:12px}.science-detail h3{margin:0 0 8px;font-size:15px}.science-detail summary{cursor:pointer;font-weight:650}.science-detail pre,.assessment pre{white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.5 ui-monospace,monospace}.science-detail dl{display:grid;grid-template-columns:minmax(150px,1fr) 3fr;gap:5px 12px;margin:8px 0}.science-detail dt{color:var(--muted)}.science-detail dd{margin:0;overflow-wrap:anywhere}.science-detail details{margin-top:8px}.participant{margin-top:12px;padding-top:8px;border-top:1px solid var(--line)}.assessment-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-top:12px}.assessment{border:1px solid var(--line);border-top:3px solid currentColor;border-radius:5px;padding:9px;min-width:0}.assessment h3{margin:0 0 4px;font-size:12px}.assessment p{margin:5px 0 0;color:var(--muted);font-size:11px;overflow-wrap:anywhere}.empty{padding:30px;color:var(--muted);text-align:center}
@media(max-width:1050px){.controls{grid-template-columns:repeat(3,minmax(0,1fr))}main{grid-template-columns:1fr}.browser{border-right:0;border-bottom:1px solid var(--line)}#reaction-list{height:360px}.facts{grid-template-columns:repeat(2,1fr)}.assessment-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:650px){header,.controls{padding-left:14px;padding-right:14px}.controls{position:static;grid-template-columns:repeat(2,minmax(0,1fr))}.detail{padding:14px}.facts,.assessment-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><h1 id="title">Reaction-network explorer</h1><p>Find a reaction, inspect its saved judgments, or trace a path to a state.</p><p><strong id="exploration-status"></strong></p><details><summary>Analysis scope</summary><p id="scope-note"></p></details><div class="counts"><span class="count" id="state-count"></span><span class="count" id="reaction-count"></span><button class="count" id="state-filter" type="button" hidden></button></div></header>
<section class="controls" id="list-controls">
<label>Assessment layer to display<select id="view"></select></label>
<label>Reaction, state, type, or ID<input id="search" type="search" placeholder="e.g. SF6, charge exchange, rxn_..."></label>
<label>Family<select id="family"><option value="">All families</option></select></label>
<label>Process<select id="process"><option value="">All processes</option></select></label>
<label>Applied collision input<select id="collision-input"><option value="">All collision inputs</option></select></label>
<label>Verdict for selected layer<select id="verdict" disabled title="Select an assessment layer to filter its verdicts."><option value="">All verdicts</option><option value="pass">Pass</option><option value="fail">Fail</option><option value="unknown">Unresolved</option><option value="not_applicable">Not applicable</option><option value="not_recorded">Not recorded</option></select></label>
<label>Generation depth<select id="depth"><option value="">All depths</option></select></label>
<button id="reset" type="button">Reset</button>
<label><span><input id="equation-pass" type="checkbox"> Require conservation and process pass</span></label>
</section>
<p class="state-notation" id="saved-conditions"></p>
<ul class="state-notation" id="missing-collision-states" hidden></ul>
<p class="state-notation" id="judgment-note"></p>
<details class="state-notation"><summary>State notation and axes</summary><p>plain: ground-state candidate · +/-: charge · (v): lumped vibrational excitation · (*): lumped electronic excitation · (m): lumped metastable manifold · (r): lumped resonant radiative manifold · state label: the separately represented state. State details separate excitation, resolution, lifetime class, and identity scope. A ground-state label alone does not establish physical existence or stability.</p></details>
<!-- Pathway semantics: all reactants are required; candidate generation depth is not used. -->
<main id="main">
<section class="browser"><div class="browser-head"><strong id="result-count"></strong><span class="hint">100 reactions per screen</span></div><div id="reaction-list"></div><div class="pager"><button id="previous" type="button">Previous</button><span id="page"></span><button id="next" type="button">Next</button></div></section>
<section class="detail">
  <nav class="view-tabs" aria-label="Result views">
    <button id="reaction-tab" class="view-tab" type="button">Reaction details</button>
    <button id="pathway-tab" class="view-tab" type="button">Pathways</button>
    <button id="neighborhood-tab" class="view-tab" type="button">State connections</button>
    <button id="overview-tab" class="view-tab" type="button">Matrix</button>
  </nav>
  <h2 id="detail-equation"></h2><div id="detail-type" class="hint"></div>
  <section id="overview-panel" hidden>
    <div class="matrix-head"><div class="hint">State rows · reaction columns</div><div id="matrix-summary" class="matrix-summary"></div></div>
    <div id="matrix-graph" class="graph matrix-graph"></div>
    <div class="network-legend"><strong>Participation</strong><span class="legend-group"><i class="matrix-key reactant"></i>reactant</span><span class="legend-group"><i class="matrix-key product"></i>product</span><span class="legend-group"><i class="matrix-key both"></i>both, net change</span><span class="legend-group"><i class="matrix-key unchanged"></i>zero-net participant</span></div>
  </section>
  <section id="pathway-panel" hidden>
    <div class="pathway-head">
      <div class="pathway-controls">
        <label>Pathway scope<select id="pathway-scope"><option value="conditioned">Conditioned candidates</option><option value="candidate">Conservation-compatible candidates</option></select></label>
        <label>Target state<select id="pathway-target"></select></label>
        <button id="pathway-via-toggle" type="button" hidden></button>
        <button id="pathway-download" type="button">Download graph PNG</button>
      </div>
    </div>
    <div id="pathway-summary" class="pathway-summary"></div>
    <div id="pathway-graph" class="graph pathway-graph"></div>
    <div id="pathway-state-claims"></div>
    <div id="pathway-conditions"></div>
    <details id="pathway-related" class="pathway-related"><summary id="pathway-related-summary"></summary><div id="pathway-related-list" class="pathway-related-list"></div></details>
    <details id="pathway-excluded" class="pathway-related"><summary id="pathway-excluded-summary"></summary><div id="pathway-excluded-list" class="pathway-related-list"></div></details>
  </section>
  <section id="reaction-panel">
    <p id="selection-note" class="hint" hidden></p>
    <div id="reaction-content">
    <div id="assessment-summary" class="assessment-summary" aria-label="Saved verdicts"></div>
    <div id="assessments" class="assessment-grid"></div>
    <div id="graph" class="graph"></div>
    <details class="science-detail"><summary>Numerical use</summary><div id="numerical-use"></div></details>
    <details class="science-detail"><summary>Energy quantities</summary><div id="energy-values"></div></details>
    <details class="science-detail"><summary>Sources and calculation inputs</summary><div id="sources"></div></details>
    <details class="science-detail"><summary>Participant state assessments</summary><div id="participant-assertions"></div></details>
    <details class="science-detail"><summary>Candidate generation and ID</summary><div id="facts" class="facts"></div></details>
    </div>
  </section>
  <section id="neighborhood-panel" hidden>
    <div class="neighborhood-head"><div><h3 id="neighborhood-title"></h3><div id="neighborhood-summary" class="neighborhood-summary"></div></div><button id="neighborhood-pathway" type="button">Pathways to this state</button><div id="neighborhood-pagers" class="role-pagers"></div></div>
    <div id="neighborhood-graph" class="graph"></div>
    <div class="network-legend"><strong>Role</strong><span>net producer: Δν &gt; 0</span><span>net consumer: Δν &lt; 0</span><span>zero-net participant: Δν = 0</span><span>Zero-net does not imply a physically unchanged collision.</span><span>Click a reaction node for details.</span></div>
  </section>
</section>
</main>
<script id="network-data" type="application/json">__NETWORK_DATA__</script>
<script>
const data=JSON.parse(document.getElementById('network-data').textContent);
const stateById=new Map(data.states.map(s=>[s.id,s]));
const reactionById=new Map(data.reactions.map(r=>[r.id,r]));
const viewById=new Map(data.views.map(v=>[v.id,v]));
const familyColor={electron:'#2f6b9a',ion:'#c56a2d',neutral:'#71884a',surface:'#b05a7a'};
const verdictDash={unselected:'',pass:'',fail:'10 4 2 4',unknown:'7 5',not_applicable:'2 5',not_recorded:'2 5'};
const pageSize=100;const neighborhoodPageSize=7;
let filtered=[];let pageIndex=0;let selectedId=null;let focusedStateId=null;let neighborhoodPages={producer:0,consumer:0,preserving:0};let activePanel=data.pathway_requested_target?'pathway':'reaction';let pathwayReachability=null;let requestedPathwayTarget=data.pathway_requested_target;
let showSelectedProducer=true;
const el=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const currentView=()=>viewById.get(el('view').value);
const assessmentName=layer=>viewById.get(layer)?.label??layer.replaceAll('_',' ');
const verdictFor=reaction=>{const view=currentView();return view.assessment?(reaction.assessments[view.assessment]?.verdict??'not_recorded'):'unselected'};
const verdictLabel=verdict=>({unselected:'judgment not selected',not_recorded:'judgment not recorded',unknown:'unresolved',not_applicable:'not applicable'})[verdict]??verdict;
const collisionText=c=>{
  if(!c.collision_input)return '';
  const roles=[c.projectile_state,c.target_state];
  const pair=roles.every(Boolean)?roles.map(id=>stateById.get(id)?.name??id).join(' → '):c.collision_entrance;
  const incident=c.incident_energy_eV==null?'':`${c.incident_energy_eV} eV${c.incident_energy_frame?` (${c.incident_energy_frame})`:''}`;
  return [pair,incident].filter(Boolean).join(' · ')||'General collision input';
};
const collisionKey=c=>c.collision_input?JSON.stringify([c.collision_input,c.projectile_state,c.target_state,c.collision_entrance]):'';
function populateControls(){
  el('title').textContent=`${data.case} — reaction-network explorer`;
  el('saved-conditions').textContent=`Saved physical conditions: ${data.conditions_text}`;
  const missing=el('missing-collision-states');
  missing.hidden=!data.missing_collision_states.length;
  missing.innerHTML=data.missing_collision_states.map(note=>`<li>${esc(note)}</li>`).join('');
  el('state-count').textContent=`${data.states.length.toLocaleString()} states`;
  el('reaction-count').textContent=`${data.reactions.length.toLocaleString()} saved candidates`;
  el('exploration-status').textContent=data.exploration_status;
  el('scope-note').textContent=data.scope_note;
  if(data.pathways.checked)el('pathway-scope').add(new Option('Checked candidate pathway','checked'));
  el('pathway-scope').value=data.pathway_default_mode;
  for(const view of data.views)el('view').add(new Option(view.label,view.id));
  el('view').value=data.views[0].id;
  for(const family of [...new Set(data.reactions.map(r=>r.family))].sort())el('family').add(new Option(family,family));
  for(const process of [...new Set(data.reactions.map(r=>r.process))].sort())el('process').add(new Option(process.replaceAll('_',' '),process));
  const inputs=new Map(data.reactions.filter(r=>r.collision_energy.collision_input).map(r=>[collisionKey(r.collision_energy),collisionText(r.collision_energy)]));
  for(const [key,label] of [...inputs].sort(([a],[b])=>a.localeCompare(b)))el('collision-input').add(new Option(label,key));
  for(const depth of [...new Set(data.reactions.map(r=>r.depth))].sort((a,b)=>a-b))el('depth').add(new Option(depth,depth));
}
function searchable(reaction){
  const stateText=[...reaction.reactants,...reaction.products].map(t=>`${t.species} ${stateById.get(t.species)?.name??''}`).join(' ');
  return `${reaction.id} ${reaction.equation} ${reaction.reaction_type} ${reaction.family} ${reaction.process} ${stateText} ${[...reaction.reactants,...reaction.products].map(t=>stateById.get(t.species)?.meaning??'').join(' ')}`.toLowerCase();
}
function applyFilters(preserveReaction=false){
  const view=currentView();const query=el('search').value.trim().toLowerCase();
  const selectedJudgment=Boolean(view.assessment);el('verdict').disabled=!selectedJudgment;if(!selectedJudgment)el('verdict').value='';el('verdict').title=selectedJudgment?`Filter ${view.label} verdicts`:'Select an assessment layer to filter its verdicts.';el('judgment-note').textContent=selectedJudgment?`Badges, verdict filtering and reaction line patterns show ${view.label} only. Other judgments remain separate.`:'No judgment selected. Verdict filtering is unavailable; reaction lines are solid.';
  const includesFocusedState=r=>!focusedStateId||[...r.reactants,...r.products].some(t=>t.species===focusedStateId);
  const equationPass=r=>['conservation','consistency'].every(key=>r.assessments[key]?.verdict==='pass');
  const match=(id,value)=>!el(id).value||el(id).value===value;
  filtered=data.reactions.filter(r=>includesFocusedState(r)&&(!query||searchable(r).includes(query))
    &&match('family',r.family)&&match('process',r.process)&&match('collision-input',collisionKey(r.collision_energy))
    &&match('verdict',verdictFor(r))&&match('depth',String(r.depth))&&(!el('equation-pass').checked||equationPass(r)));
  const state=stateById.get(focusedStateId);el('state-filter').hidden=!state;el('state-filter').textContent=state?`Connected state: ${state.name} (clear)`:'';
  const index=filtered.findIndex(r=>r.id===selectedId);
  pageIndex=index<0?0:Math.floor(index/pageSize);
  neighborhoodPages={producer:0,consumer:0,preserving:0};
  if(index<0&&!preserveReaction)selectedId=filtered[0]?.id??null;
  render();
}
function render(){
  renderList();
  showPanel(activePanel);
  el('result-count').textContent=`${filtered.length.toLocaleString()} matching reactions`;
}
function renderList(){
  const totalPages=Math.max(1,Math.ceil(filtered.length/pageSize));pageIndex=Math.min(pageIndex,totalPages-1);const start=pageIndex*pageSize;const rows=filtered.slice(start,start+pageSize);const list=el('reaction-list');list.textContent='';
  if(!rows.length){list.innerHTML='<div class="empty">No reactions match these filters.</div>';}else for(const r of rows){const button=document.createElement('button');button.type='button';button.className=`reaction${r.id===selectedId?' selected':''}`;button.dataset.id=r.id;const verdict=verdictFor(r);const collision=collisionText(r.collision_energy);button.innerHTML=`<div class="equation">${esc(r.equation)}</div><div class="row-meta"><span class="family-dot" style="background:${familyColor[r.family]??'#727b83'}"></span><span>${esc(r.family)} · ${esc(r.reaction_type)}${r.stabilization?` · ${esc(r.stabilization)}`:''}</span>${verdict==='unselected'?'':`<span class="verdict ${esc(verdict)}">${esc(verdictLabel(verdict))}</span>`}</div>${collision?`<div class="row-meta">${esc(collision)}</div>`:''}`;button.onclick=()=>selectReaction(r.id);list.append(button);}
  el('page').textContent=filtered.length?`${start+1}-${Math.min(start+pageSize,filtered.length)} of ${filtered.length}`:'0 of 0';el('previous').disabled=pageIndex===0;el('next').disabled=pageIndex>=totalPages-1;
}
function detailHeading(title,subtitle=''){
  el('detail-equation').textContent=title;
  el('detail-type').textContent=subtitle;
}
function renderReaction(){
  const reaction=reactionById.get(selectedId),note=el('selection-note');
  el('reaction-content').hidden=!reaction;
  note.hidden=!reaction||filtered.some(r=>r.id===selectedId);
  note.textContent=note.hidden?'':'This graph selection is outside the current reaction-list filters.';
  if(!reaction){detailHeading('No reaction selected');return}
  detailHeading(reaction.equation,`${reaction.family} · ${reaction.reaction_type}`);
  renderAssessments(reaction);
  el('graph').innerHTML=reactionSvg(reaction);
  renderNumericalUse(reaction);
  renderEnergyValues(reaction);
  renderParticipantAssertions(reaction);
  renderSources(reaction);
  renderFacts(reaction);
}
function showPanel(panel){
  activePanel=panel;
  const isPathway=panel==='pathway';
  el('main').classList.toggle('pathway-mode',isPathway);
  el('list-controls').hidden=isPathway;
  el('judgment-note').hidden=isPathway;
  el('state-filter').hidden=isPathway||!focusedStateId;
  for(const name of ['overview','pathway','reaction','neighborhood']){
    el(`${name}-panel`).hidden=panel!==name;
    el(`${name}-tab`).classList.toggle('active',panel===name);
  }
  if(panel==='pathway')renderPathway();
  if(panel==='reaction')renderReaction();
  if(panel==='overview'){detailHeading('Reaction-state matrix','Current reaction selection');renderMatrix()}
  if(panel==='neighborhood'){
    const state=stateById.get(focusedStateId);
    detailHeading(state?.name??'State connections',state?stateDescription(state):'Select a state from the matrix or reaction view.');
    el('neighborhood-pathway').disabled=!state;
    renderNeighborhood();
  }
}
function selectReaction(reactionId){
  if(!reactionById.has(reactionId))return;
  selectedId=reactionId;
  const index=filtered.findIndex(r=>r.id===reactionId);
  if(index>=0)pageIndex=Math.floor(index/pageSize);
  showPanel('reaction');
  renderList();
}
function termNodes(reaction,side){return reaction[`diagram_${side}`].map(t=>({id:t.species,label:`${t.n===1?'':`${t.n} `}${stateById.get(t.species)?.name??t.species}`,state:stateById.get(t.species)}));}
function nodeFill(state){if(!state)return'#f2f4f5';if(state.id==='e')return'#f2f4f5';if(state.charge>0)return'#e8f0f6';if(state.charge<0)return'#f7eae2';if(state.kind==='composition')return'#f2f4f5';if(state.kind!=='ground')return'#fff7e0';return'#fff'}
function stateDescription(state){return `${state.meaning} · excitation=${state.excitation} · ${state.resolution} · lifetime=${state.lifetime_class} · structure=${state.structure_scope}`}
function reactionSvg(r){
  const left=termNodes(r,'reactants'),right=termNodes(r,'products'),rows=Math.max(left.length,right.length,1),height=Math.max(330,120+rows*78),junctionY=70+(rows-1)*39+31,color=familyColor[r.family]??'#727b83',verdict=verdictFor(r),dash=verdictDash[verdict],marker='arrow';
  const positions=(items,x)=>items.map((term,i)=>({term,x,y:70+i*78}));const lp=positions(left,35),rp=positions(right,685);
  const context=[r.family,pathwayCollisionEnergy(r),r.stabilization,r.surface&&`Surface · ${r.surface}`,verdictLabel(verdict)].filter(Boolean).join(' · ');
  let svg=`<svg viewBox="0 0 1000 ${height}" role="img" aria-label="${esc(r.equation)}"><defs><marker id="${marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="${color}"/></marker></defs><text x="500" y="30" text-anchor="middle" font-size="14" font-weight="650" fill="#1f2933">${esc(r.reaction_type)}</text><text x="500" y="50" text-anchor="middle" font-size="11" fill="#64717d">${esc(context)}</text>`;
  for(const p of lp)svg+=edge(p.x+250,p.y+27,490,junctionY,color,dash,marker);for(const p of rp)svg+=edge(510,junctionY,p.x,p.y+27,color,dash,marker);for(const p of [...lp,...rp])svg+=stateNode(p);svg+=`<polygon points="500,${junctionY-9} 509,${junctionY} 500,${junctionY+9} 491,${junctionY}" fill="#fff" stroke="${color}" stroke-width="2"${dash?` stroke-dasharray="${dash}"`:''}/></svg>`;return svg;
}
function edge(x1,y1,x2,y2,color,dash,marker){return `<path d="M${x1} ${y1} C${(x1+x2)/2} ${y1},${(x1+x2)/2} ${y2},${x2} ${y2}" fill="none" stroke="#fff" stroke-width="5"/><path d="M${x1} ${y1} C${(x1+x2)/2} ${y1},${(x1+x2)/2} ${y2},${x2} ${y2}" fill="none" stroke="${color}" stroke-width="1.8"${dash?` stroke-dasharray="${dash}"`:''} marker-end="url(#${marker})"/>`}
function stateNode(p){const state=p.term.state;const clickable=state?` data-state-id="${esc(p.term.id)}" style="cursor:pointer"`:'';const subtitle=state?`${state.excitation} · ${state.resolution} · q=${state.charge>=0?'+':''}${state.charge}`:'Third body',title=state?`<title>${esc(`${state.name}: ${stateDescription(state)}`)}</title>`:'';return `<g${clickable}>${title}<rect x="${p.x}" y="${p.y}" width="250" height="54" rx="7" fill="${nodeFill(state)}" stroke="#27313a" stroke-width="1.3"/><text x="${p.x+125}" y="${p.y+23}" text-anchor="middle" font-size="13" font-weight="650" fill="#1f2933">${esc(p.term.label)}</text><text x="${p.x+125}" y="${p.y+41}" text-anchor="middle" font-size="10" fill="#64717d">${esc(subtitle)}</text></g>`}
function renderFacts(r){const values=[['Reaction ID',r.id],['Family',r.family],['Process',r.process],['Generation depth',r.depth],['Origin',r.origin],['Generation rule',r.generation_rule],['Third body',r.third_body??'—'],['Surface',r.surface??'—'],['Stabilization',r.stabilization??'—']];el('facts').innerHTML=values.map(([k,v])=>`<div class="fact"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');}
function savedDetails(title,value){return `<details><summary>${esc(title)}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`}
function workLabel(value){return ({user_inputs:'Accepted physical input',source_information:'Source declaration',source_review:'Source review',source_selection:'Source selection',identity:'Target identification',external_models:'External model',transforms:'Unperformed conversion',unsupported_inputs:'Unsupported input'})[value]??String(value).replaceAll('_',' ')}
function outcomeLabel(value){return ({satisfied:'Satisfied named proposition',not_satisfied:'Rejected named proposition',data_missing:'Source data missing',input_missing:'Physical input missing',review_required:'Source review required',selection_required:'Source selection required',identity_unresolved:'Target identity unresolved',model_unsupported:'Required model not implemented',interface_unsupported:'Required input interface not implemented',unresolved:'Unresolved',available:'Quantity available for the named use',computed:'Quantity computed',excluded:'Numerical record excluded',out_of_range:'Outside declared range',conflicting_data:'Conflicting scientific declarations',not_applicable:'Not applicable'})[value]??value}
function outcomeMarkup(result){return result.label?`<p><strong>Result label: ${esc(outcomeLabel(result.label))}</strong>${result.blocking_causes?.length?` · ${result.blocking_causes.map(value=>esc(outcomeLabel(value))).join('; ')}`:''}</p>`:''}
function assessmentMarkup(layer,a){
  const requirements=a.requirements;
  const needs=requirements===undefined?'<p>Requirements not recorded in this saved result.</p>':requirements.length?`<ul>${requirements.map(item=>`<li><strong>${esc(workLabel(item.responsibility))}</strong>: ${esc(stateById.get(item.target)?.name??item.target)} · ${esc(item.quantity)}${item.reason?` — ${esc(item.reason)}`:''}</li>`).join('')}</ul>`:'';
  const dependencies=a.dependencies?.length?`<p>Depends on: ${a.dependencies.map(([stateId,key])=>`${esc(stateById.get(stateId)?.name??stateId)} / ${esc(key.replaceAll('_',' '))}`).join('; ')}</p>`:'';
  const sources=(a.record_inputs??[]).map(input=>{
    const record=data.calculation_sources[input.target]?.[input.record_ref];
    return record?savedDetails(`Source for ${input.quantity}`,record):'';
  }).join('');
  return `<section class="assessment ${esc(a.verdict)}"><h3>${esc(assessmentName(layer))}</h3><strong>${esc(a.proposition?a.proposition.replaceAll('_',' '):'Proposition not recorded')} — ${esc(verdictLabel(a.verdict))}</strong><p>${esc(a.message||'Explanation not recorded.')}</p>${outcomeMarkup(a)}<p>${esc(a.scope||'Scope not recorded for this assessment.')}</p>${needs}${dependencies}${sources}${a.basis?.length?savedDetails('Saved supporting references',a.basis):''}</section>`;
}
function renderAssessments(reaction){
  const layer=currentView().assessment,assessment=reaction.assessments[layer];
  const saved=data.views.filter(view=>view.assessment&&reaction.assessments[view.assessment]);
  const list=el('assessment-summary');
  list.innerHTML=saved.map(view=>{
    const verdict=reaction.assessments[view.assessment].verdict;
    return `<button type="button" data-assessment="${esc(view.id)}" aria-pressed="${view.id===layer}">${esc(view.label)}<span class="verdict ${esc(verdict)}">${esc(verdictLabel(verdict))}</span></button>`;
  }).join('');
  const selected=assessment?assessmentMarkup(layer,assessment):layer?`<p>No ${esc(assessmentName(layer))} judgment was recorded for this reaction.</p>`:'';
  const other=saved.filter(view=>view.assessment!==layer).map(view=>assessmentMarkup(view.assessment,reaction.assessments[view.assessment])).join('');
  el('assessments').innerHTML=selected+(other?`<details><summary>${layer?'Other saved assessment details':'All saved assessment details'}</summary>${other}</details>`:!layer?'<p>No assessments were recorded for this reaction.</p>':'');
}
function renderNumericalUse(r){
  const use=r.data_use,selected=r.numerical_records.filter(record=>record.id===use.dataset_id);
  if(!use.status){el('numerical-use').innerHTML='<h3>Numerical use</h3><p>No numerical-use result recorded.</p>';return}
  const rows=[['Saved use',use.status],['Quantity',use.kind??'not selected'],['Value',use.value===null||use.value===undefined?'not evaluated':`${use.value} ${use.unit??''}`],['Supplied conditions',data.conditions_text],['Use and selection reason',use.reason??'not recorded']];
  if(use.estimated)rows.push(['Qualification','estimated']);
  el('numerical-use').innerHTML=`<h3>Numerical use under supplied conditions</h3>${outcomeMarkup(use)}${factsList(rows)}${selected.map(record=>factsList([['Selected representation',record.form??'not recorded'],['Applicability',record.validity?JSON.stringify(record.validity):'not recorded'],['Uncertainty declaration',record.uncertainty?JSON.stringify(record.uncertainty):'not recorded']])).join('')}<ul>${Object.entries(r.numerical_requirements).filter(([,values])=>values.length).map(([responsibility,values])=>`<li><strong>${esc(workLabel(responsibility))}</strong>: ${esc(values.join(', '))}</li>`).join('')}</ul>${use.disagreements?.length?`<p>Saved disagreement records: ${esc(use.disagreements.join(', '))}</p>`:''}${savedDetails('Saved selection request',use.selection??{})}${savedDetails('Every numerical record assessment',use.datasets??[])}`;
}
function factsList(rows){return `<dl>${rows.map(([label,value])=>`<dt>${esc(label)}</dt><dd>${esc(value!==null&&typeof value==='object'?JSON.stringify(value):value)}</dd>`).join('')}</dl>`}
function renderEnergyValues(r){
  const c=r.collision_energy,collision=collisionText(c);
  const budget=[['Applied collision input',collision],['COM energy',c.relative_collision_energy_eV],['Endpoint state difference',c.state_energy_difference_eV],['COM residual',c.collision_energy_margin_eV]].filter(([,value])=>value!==null&&value!=='').map(([label,value])=>[label,typeof value==='number'?`${value} eV`:value]);
  const labels={delta_h_eV:'Formation enthalpy difference ΔH / eV',delta_h_reference_temperature_K:'ΔH reference temperature / K',delta_h_standard_pressure_Pa:'ΔH standard pressure / Pa',delta_g_eV:'Gibbs energy difference ΔG / eV',state_energy_difference_eV:'Endpoint state difference / eV',collision_energy_margin_eV:'COM residual / eV',delta_e_eV:'Declared internal energy difference / eV'};
  const thermal=Object.entries(r.thermochemistry).filter(([key])=>!['threshold_eV','state_energy_difference_eV','relative_collision_energy_eV','collision_energy_margin_eV'].includes(key));
  const calculations=Object.entries(r.thermochemical_calculations??{}).map(([quantity,result])=>`<section><h4>${esc(labels[quantity]??quantity)} · ${esc(result.status)}</h4>${outcomeMarkup(result)}<p>${esc(result.reason)}</p>${result.value!==null?factsList([['Value',`${result.value} ${result.unit}`]]):''}${savedDetails('Calculation conditions and prerequisites',result)}</section>`).join('');
  el('energy-values').innerHTML=`<h3>Collision energy necessary condition</h3>${budget.length?factsList(budget):'<p>No collision budget quantities recorded.</p>'}${thermal.length?`<h3>Other saved energy quantities</h3>${factsList(thermal.map(([key,value])=>[labels[key]??key,value]))}`:''}${calculations}`;
}
function renderParticipantAssertions(r){
  const ids=[...new Set([...r.reactants,...r.products].map(term=>term.species))];
  el('participant-assertions').innerHTML=ids.map(id=>{const state=stateById.get(id);if(!state)return '';return `<section class="participant"><h3>${esc(state.name)}</h3><p>${esc(stateDescription(state))}</p><div class="assessment-grid">${Object.entries(state.assessments).map(([layer,a])=>assessmentMarkup(layer,a)).join('')||'<p>State assertions not recorded.</p>'}</div>${savedDetails('Saved state evidence and source declarations',state.evidence)}</section>`}).join('');
}
function renderSources(r){
  const use=r.data_use,selected=r.numerical_records.filter(record=>record.id===use.dataset_id);
  const calculationSources=new Map();
  for(const input of r.calculation_uses){
    const key=JSON.stringify([input.target,input.record_ref]);
    if(!calculationSources.has(key)){
      const record=data.calculation_sources[input.target][input.record_ref];
      calculationSources.set(key,{record_id:input.record_id,record,uses:[]});
    }
    calculationSources.get(key).uses.push(input);
  }
  const threshold=r.thermochemistry.threshold_eV;
  el('sources').innerHTML=`<h3>Sources and adopted numerical record</h3>${threshold==null?'':factsList([['Source-declared threshold',`${threshold} eV`]])}${selected.length?selected.map(record=>`<p>${esc(record.source?.citation??record.provenance?.citation??record.id)}</p>${savedDetails('Selected scientific record, conditions, derivation and provenance',record)}`).join(''):'<p>No numerical record selected in the saved result.</p>'}${[...calculationSources.values()].map(entry=>savedDetails(`Calculation input: ${entry.record_id}`,entry)).join('')}${savedDetails('All saved channel evidence, offered records and source declarations',r.evidence)}`;
}
function netStoichiometry(reaction,stateId){return reaction.net_stoichiometry[stateId]??0}
function computePathwayReachability(){
  if(pathwayReachability)return pathwayReachability;
  const mode=el('pathway-scope').value||'conditioned',saved=data.pathways[mode];
  const seeds=new Set(data.pathways.seeds.filter(id=>!Object.hasOwn(saved.excluded_seeds??{},id)));
  pathwayReachability={
    saved,seeds,
    stateLayers:new Map(Object.entries(saved.state_layers)),
    reactionLayers:new Map(Object.entries(saved.reaction_layers)),
    minimumProducers:data.pathway_minimum_producers[mode]
  };
  return pathwayReachability;
}
function populatePathwayTargets(reachability){
  const selector=el('pathway-target'),desired=requestedPathwayTarget||selector.value;
  const via=showSelectedProducer?selectedProducerFor(data.pathway_via?.target):null;
  const targets=data.states.map(state=>({state,step:reachability.stateLayers.get(state.id)}));
  const rank=step=>step===undefined?Infinity:step===0?Number.MAX_SAFE_INTEGER:step;
  targets.sort((a,b)=>rank(a.step)-rank(b.step)||a.state.name.localeCompare(b.state.name)||a.state.id.localeCompare(b.state.id));
  selector.textContent='';
  selector.add(new Option('Select a target state',''));
  for(const {state,step} of targets){
    const status=via?.target===state.id?'selected producer':step===undefined?'not reachable':step===0?'supplied seed':`${step} step${step===1?'':'s'}`;
    selector.add(new Option(`${state.name} — ${status}`,state.id));
  }
  selector.value=stateById.has(desired)?desired:reachability.saved.default_target??'';
  requestedPathwayTarget=null;
  return targets.filter(target=>target.step>0).length;
}
function selectedProducerFor(targetId){
  const choice=data.pathway_via;
  return choice&&choice.target===targetId&&choice.mode===el('pathway-scope').value?choice:null;
}
function selectHierarchicalPath(targetId,reachability){
  const states=new Set(),reactions=new Set(),supportedBy=new Map(),{saved,seeds,minimumProducers}=reachability;
  const support=[targetId];
  while(support.length){
    const stateId=support.pop();
    if(states.has(stateId))continue;
    states.add(stateId);
    if(seeds.has(stateId))continue;
    const producer=saved.primary_producer[stateId];
    if(!producer)continue;
    reactions.add(producer);
    supportedBy.set(stateId,producer);
    support.push(...reactionById.get(producer).reactants.map(term=>term.species));
  }
  const context=data.pathway_context,relatedCategories=new Map(),visited=new Set(seeds),pending=[...states];
  const labels=data.pathway_producer_labels;
  while(pending.length){
    const stateId=pending.pop();
    if(visited.has(stateId))continue;
    visited.add(stateId);
    for(const id of saved.producer_ids[stateId]??[]){
      if(!relatedCategories.has(id))relatedCategories.set(id,labels.later);
    }
    for(const id of minimumProducers[stateId]??[]){
      if(relatedCategories.get(id)===labels.minimum)continue;
      relatedCategories.set(id,labels.minimum);
      pending.push(...reactionById.get(id).reactants.map(term=>term.species));
    }
  }
  const eligible=id=>!Object.hasOwn(saved.excluded,id);
  for(const stateId of states){
    if(seeds.has(stateId))continue;
    for(const id of context.potential_producers[stateId]??[]){
      if(eligible(id)&&!reachability.reactionLayers.has(id)&&!relatedCategories.has(id)){
        relatedCategories.set(id,'unreachable potential producer');
      }
    }
  }
  for(const [id,category] of Object.entries(context.target_neighbors[targetId]??{})){
    if(eligible(id)&&!relatedCategories.has(id)){
      relatedCategories.set(id,reachability.reactionLayers.has(id)?category:`${category} (unreachable)`);
    }
  }
  const related=[...relatedCategories].filter(([id])=>!reactions.has(id)).map(([id,category])=>{
    const reaction=reactionById.get(id);
    const reason=reachability.reactionLayers.has(id)?'':unreachableReactantsText(reaction,reachability);
    return {reaction,category,reason};
  });
  related.sort((a,b)=>a.category.localeCompare(b.category)||a.reaction.equation.localeCompare(b.reaction.equation)||a.reaction.id.localeCompare(b.reaction.id));
  return {states,reactions,supportedBy,related};
}
function pathwayReferenceText(reaction,reference){
  if(reference.condition==='unconfirmed_participant_states')return `Unconfirmed participant states: ${reference.states.map(id=>stateById.get(id).name).join(', ')}`;
  if(!reference.assessment)return reference.condition.replaceAll('_',' ');
  const state=stateById.get(reference.state),assessment=(state??reaction).assessments[reference.assessment];
  return [state?.name,assessmentName(reference.assessment),assessment?.verdict&&verdictLabel(assessment.verdict),assessment?.message,reference.condition?.replaceAll('_',' ')].filter(Boolean).join(' · ');
}
function unreachableReactantsText(reaction,reachability){
  const missing=reaction.reactants.filter(term=>!reachability.stateLayers.has(term.species)).map(term=>stateById.get(term.species).name);
  return `Unreachable reactants: ${missing.join(', ')}`;
}
function renderBlockedProducers(targetId,reachability,reachable){
  const rows=[];
  for(const id of data.pathway_context.potential_producers[targetId]??[]){
    const reaction=reactionById.get(id),excluded=reachability.saved.excluded[id];
    if(excluded){
      rows.push({reaction,category:'Excluded by this scope',reason:excluded.map(ref=>pathwayReferenceText(reaction,ref)).join(' | ')});
    }else if(!reachable&&!reachability.reactionLayers.has(id)){
      rows.push({reaction,category:'Unreachable producer',reason:unreachableReactantsText(reaction,reachability)});
    }
  }
  el('pathway-excluded').hidden=!rows.length;
  el('pathway-excluded-summary').textContent=`Blocked direct producers (${rows.length})`;
  el('pathway-excluded-list').innerHTML=rows.map(pathwayReactionRow).join('');
}
function pathwayReactionRow({reaction,category,reason}){
  return `<button class="pathway-related-item" type="button" data-reaction-id="${esc(reaction.id)}"><span>${esc(category)}</span><span><strong>${esc(reaction.equation)}</strong>${reason?`<small>${esc(reason)}</small>`:''}</span></button>`;
}
function pathwayParticipants(path){
  const participants=new Set(path.states);
  for(const id of path.reactions){
    const reaction=reactionById.get(id);
    for(const term of [...reaction.reactants,...reaction.products])participants.add(term.species);
  }
  return [...participants].sort();
}
function pathwayStateClaims(participants){
  return Object.fromEntries(Object.entries(data.pathway_state_claims).map(([verdict,claims])=>[
    verdict,participants.flatMap(id=>claims[id]??[])
  ]));
}
function renderPathwayStateClaims(claims){
  const rows=Object.entries(claims).flatMap(([verdict,references])=>references.map(ref=>{
    const state=stateById.get(ref.state),assessment=state.assessments[ref.assessment];
    const text=`${state.name} · ${ref.proposition.replaceAll('_',' ')} · ${verdictLabel(verdict)}`;
    return `<li><strong>${esc(text)}</strong> — ${esc(assessment.message||assessment.scope)}</li>`;
  }));
  el('pathway-state-claims').innerHTML=rows.length?`<details><summary>Participant state evidence: ${claims.fail.length} refuted, ${claims.unknown.length} unresolved</summary><ul>${rows.join('')}</ul></details>`:'';
}
function renderPathway(){
  const scope=computePathwayReachability(),targetCount=populatePathwayTargets(scope);
  const targetId=el('pathway-target').value,target=stateById.get(targetId);
  const choice=selectedProducerFor(targetId);
  const via=showSelectedProducer?choice:null;
  const toggle=el('pathway-via-toggle');
  toggle.hidden=!choice;
  toggle.textContent=via?'Show shortest support':'Show selected producer';
  const reachability=via?{
    ...scope,via:via.producer,seeds:new Set(via.seeds),
    equationAndEnergyChecksPass:via.equation_and_energy_checks_pass,
    stateLayers:new Map(Object.entries(via.state_layers)),
    reactionLayers:new Map(Object.entries(via.reaction_layers))
  }:scope;
  const step=reachability.stateLayers.get(targetId),reachable=step!==undefined;
  detailHeading(target?`Pathways to ${target.name}`:'Pathways');
  el('pathway-download').disabled=!reachable;
  renderBlockedProducers(targetId,scope,reachable);
  const path=via?{
    states:new Set(reachability.stateLayers.keys()),reactions:new Set(reachability.reactionLayers.keys()),
    supportedBy:new Map(Object.entries(via.supported_by)),related:[]
  }:reachable?selectHierarchicalPath(targetId,reachability):{reactions:[],related:[],states:[]};
  const query=pathwayQuery(targetId||null,path,reachability);
  renderPathwayStateClaims(query.state_claims);
  el('pathway-conditions').innerHTML=savedDetails('Saved query, unresolved conditions and exclusions',query);
  el('pathway-related').hidden=!path.related.length;
  el('pathway-related-summary').textContent=`Alternative support and target context (${path.related.length})`;
  el('pathway-related-list').innerHTML=path.related.map(pathwayReactionRow).join('');
  if(!reachable){
    const message=target?`${target.name} · Not reachable in this scope`:'Select a target state';
    el('pathway-graph').innerHTML=`<div class="empty">${esc(message)}</div>`;
    el('pathway-summary').textContent=`${targetCount} reachable targets in this pathway query`;
    return;
  }
  const title=via?'Selected producer':step===0?'Supplied target':'One shortest support';
  el('pathway-summary').textContent=title;
  el('pathway-graph').innerHTML=hierarchicalPathSvg(targetId,path,reachability,title);
}
function pathwayQuery(target,path,reachability){
  const saved=reachability.saved;
  const participants=pathwayParticipants(path);
  return {
    seeds:data.pathways.seeds,
    effective_seeds:[...reachability.seeds],
    conditions:data.pathways.conditions,
    mode:el('pathway-scope').value,
    target,
    ...(reachability.via&&{via:reachability.via,equation_and_energy_checks_pass:reachability.equationAndEnergyChecksPass}),
    reaction_ids:[...path.reactions].sort(),
    related_reactions:Object.fromEntries(path.related.map(item=>[item.reaction.id,item.category])),
    unresolved:Object.fromEntries([...path.reactions].filter(id=>saved.unresolved[id]).map(id=>[id,saved.unresolved[id]])),
    unconfirmed_states:Object.fromEntries(participants.filter(id=>data.pathways.unconfirmed_states[id]).map(id=>[id,data.pathways.unconfirmed_states[id]])),
    state_claims:pathwayStateClaims(participants),
    skipped_requested_expansions:Object.fromEntries([...path.reactions].filter(id=>data.skipped_requested_expansions[id]).map(id=>[id,data.skipped_requested_expansions[id]])),
    excluded:saved.excluded,
    ...(saved.excluded_seeds&&{excluded_seeds:saved.excluded_seeds})
  };
}

const pathNodeWidth=226,pathColumnGap=346,pathTop=82,pathSide=26;
function hierarchicalPathSvg(targetId,path,reachability,title){
  const {nodes,edges}=pathwayDiagram(targetId,path,reachability);
  const {positions,routes,boxHeight,height}=hierarchicalPositions(nodes,edges);
  const rightmost=Math.max(...[...positions.values()].map(position=>position.x));
  const width=Math.max(610,pathSide+pathNodeWidth+rightmost);
  const target=stateById.get(targetId).name,heading=`Target ${target} · ${data.case}`;
  const scope={checked:'Checked candidates',candidate:'Conservation-compatible candidates',
    conditioned:'Conditioned candidates'}[el('pathway-scope').value];
  const status=[scope,title,data.exploration_complete===false?'Partial exploration':''].filter(Boolean).join(' · ');
  const markers=Object.entries({...familyColor,other:'#727b83'}).map(([family,color])=>
    `<marker id="p-${family}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="${color}"/></marker>`).join('');
  const renderedEdges=routes.map(route=>hierarchicalEdge(route,positions,boxHeight));
  const content=[...renderedEdges.map(edge=>edge.path),...renderedEdges.map(edge=>edge.coefficient)];
  for(const [id,node] of nodes)content.push(hierarchicalNode(node,positions.get(id),boxHeight));
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(heading)}"><defs>${markers}</defs><rect width="${width}" height="${height}" fill="#fff"/><g font-family="system-ui,sans-serif">${pathwayText(pathSide,28,heading,17,'#1f2933',true)}${pathwayText(pathSide,52,status,11,'#64717d')}${content.join('')}</g></svg>`;
}
function pathwayDiagram(targetId,path,reachability){
  const nodes=new Map(),edges=[];
  const addState=(id,level,species,role)=>{
    const state=stateById.get(species);
    nodes.set(id,{level,state,lines:pathwayLines(state?.name??species),role});
  };
  for(const [species,producer] of path.supportedBy){
    addState(`state:${species}`,3*reachability.reactionLayers.get(producer)-1,species,
      species===targetId?'Target':'Intermediate');
  }
  if(!path.reactions.size)addState(`state:${targetId}`,0,targetId,'Supplied target');
  for(const reactionId of path.reactions){
    const r=reactionById.get(reactionId),id=`reaction:${reactionId}`;
    const layer=reachability.reactionLayers.get(reactionId),level=3*layer-2;
    const lines=pathwayLines(r.reaction_type);
    const checks=(reachability.saved.unresolved[reactionId]??[]).some(note=>!note.state);
    const tags=[r.family,pathwayCollisionEnergy(r),r.stabilization?.replaceAll('_',' '),
      r.surface&&`Surface · ${r.surface}`,checks&&'Open checks'].filter(Boolean).flatMap(pathwayLines);
    nodes.set(id,{level,reaction:r,lines,tags,checks});
    for(const side of ['reactants','products']){
      const incoming=side==='reactants';
      r[`diagram_${side}`].forEach(({species,n},index)=>{
        const stateId=`state:${species}`;
        const shared=nodes.has(stateId)&&(incoming||path.supportedBy.get(species)===reactionId);
        const local=species==='e'?`local-electron:${side}:${layer}`:`${side}:${reactionId}:${index}`;
        const participant=shared?stateId:local;
        if(!nodes.has(participant)){
          const role=!stateById.has(species)?'Third body':incoming
            ?(reachability.seeds.has(species)?'Supply':'Reactant'):'Other product';
          addState(participant,level+(incoming?-1:1),species,role);
        }
        edges.push({source:incoming?participant:id,target:incoming?id:participant,
          family:r.family,coefficient:n});
      });
    }
  }
  return {nodes,edges};
}
function pathwayCollisionEnergy(reaction){
  const c=reaction.collision_energy;
  if(c?.relative_collision_energy_eV!=null)return `${c.relative_collision_energy_eV} eV COM`;
  if(c?.incident_energy_eV!=null)return `${c.incident_energy_eV} eV${c.incident_energy_frame?` ${c.incident_energy_frame.toUpperCase()}`:''}`;
  return '';
}
function pathwayLines(text){
  const lines=[];
  for(const word of String(text).split(/\s+/)){
    if(!word)continue;
    const letters=Array.from(word);
    const last=lines.at(-1);
    if(last&&Array.from(last).length+letters.length<27){lines[lines.length-1]+=` ${word}`;continue}
    for(let start=0;start<letters.length;start+=27)lines.push(letters.slice(start,start+27).join(''));
  }
  return lines;
}
function pathwayText(x,y,text,size,color,bold=false,anchor='start'){
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-size="${size}" fill="${color}"${bold?' font-weight="650"':''}>${esc(text)}</text>`;
}
function hierarchicalPositions(nodes,edges){
  const columns=[...new Set([...nodes.values()].map(node=>node.level))].sort((a,b)=>a-b);
  const columnForLevel=new Map(columns.map((level,index)=>[level,index]));
  const levels=new Map([...nodes].map(([id,node])=>[id,columnForLevel.get(node.level)]));
  const routes=edges.map((edge,index)=>{
    const via=[];
    for(let level=levels.get(edge.source)+1;level<levels.get(edge.target);level++){
      const relay=`route:${index}:${level}`;
      levels.set(relay,level);
      via.push(relay);
    }
    return {...edge,via};
  });
  const byLevel=new Map(),predecessors=new Map(),successors=new Map();
  for(const [id,level] of levels){
    if(!byLevel.has(level))byLevel.set(level,[]);
    byLevel.get(level).push(id);
    predecessors.set(id,[]);
    successors.set(id,[]);
  }
  for(const {source,target,via} of routes){
    const chain=[source,...via,target];
    chain.slice(1).forEach((id,index)=>{
      predecessors.get(id).push(chain[index]);
      successors.get(chain[index]).push(id);
    });
  }
  const orders=[...byLevel.keys()].sort((a,b)=>a-b);
  for(const ids of byLevel.values())ids.sort();
  const order=new Map([...byLevel.values()].flatMap(ids=>ids.map((id,index)=>[id,index])));
  const neighbors=id=>predecessors.get(id).length?predecessors.get(id):successors.get(id);
  for(const level of orders){
    const column=byLevel.get(level);
    column.sort((a,b)=>pathwayBarycentre(neighbors(a),order)-pathwayBarycentre(neighbors(b),order)
      ||a.localeCompare(b));
    column.forEach((id,index)=>order.set(id,index));
  }
  const boxHeight=Math.max(62,...[...nodes.values()].map(n=>18*(n.lines.length+(n.tags?.length??1))+20));
  const rowGap=boxHeight+24,maxRows=Math.max(...[...byLevel.values()].map(ids=>ids.length),1);
  const positions=new Map();
  for(const [level,ids] of byLevel){
    const offset=(maxRows-ids.length)*rowGap/2;
    ids.forEach((id,index)=>positions.set(id,{x:pathSide+level*pathColumnGap,y:pathTop+offset+index*rowGap}));
  }
  for(const [end,other] of [['source','target'],['target','source']]){
    const ports=new Map();
    for(const route of routes){
      if(!ports.has(route[end]))ports.set(route[end],[]);
      ports.get(route[end]).push(route);
    }
    for(const group of ports.values()){
      const nextY=route=>positions.get((end==='source'?route.via[0]:route.via.at(-1))??route[other]).y;
      group.sort((a,b)=>nextY(a)-nextY(b));
      group.forEach((route,index)=>route[`${end}Port`]=(index+1)*boxHeight/(group.length+1));
    }
  }
  return {positions,routes,boxHeight,height:pathTop+(maxRows-1)*rowGap+boxHeight+30};
}
function pathwayBarycentre(neighbors,order){
  return neighbors.length?neighbors.reduce((sum,id)=>sum+order.get(id),0)/neighbors.length:Infinity;
}
function hierarchicalEdge(route,positions,height){
  const source=positions.get(route.source),target=positions.get(route.target);
  const start=[source.x+pathNodeWidth,source.y+route.sourcePort],end=[target.x,target.y+route.targetPort];
  const via=route.via.map(id=>{
    const p=positions.get(id);
    return [p.x+pathNodeWidth/2,p.y+height/2];
  });
  let [x,y]=start,path=`M${x} ${y}`;
  for(const [nextX,nextY] of [...via,end]){
    const middle=(x+nextX)/2;
    path+=` C${middle} ${y},${middle} ${nextY},${nextX} ${nextY}`;
    [x,y]=[nextX,nextY];
  }
  const family=Object.hasOwn(familyColor,route.family)?route.family:'other',color=familyColor[family]??'#727b83';
  let coefficient='';
  if(route.coefficient!==1){
    const [cx,cy]=route.source.startsWith('reaction:')?[end[0]-12,end[1]-6]:[start[0]+12,start[1]-6];
    const align=route.source.startsWith('reaction:')?'end':'start';
    coefficient=pathwayText(cx,cy,route.coefficient,12,'#1f2933',true,align)
      .replace('<text ','<text paint-order="stroke" stroke="#fff" stroke-width="4" ');
  }
  return {
    path:`<path d="${path}" fill="none" stroke="#fff" stroke-width="7"/><path d="${path}" fill="none" stroke="${color}" stroke-width="2" marker-end="url(#p-${family})"/>`,
    coefficient
  };
}
function hierarchicalNode(node,{x,y},height){
  const r=node.reaction,state=node.state,center=x+pathNodeWidth/2;
  const isTarget=node.role==='Target'||node.role==='Supplied target';
  const color=r?(familyColor[r.family]??'#727b83'):isTarget?'#355d39':'#64717d';
  const tagLines=r?node.tags:['Intermediate','Other product'].includes(node.role)?[]:[node.role];
  const body=[...node.lines.map(text=>[text,13,'#1f2933',true]),
    ...tagLines.map(text=>[text,10,text==='Open checks'?'#886319':'#64717d',false])];
  const title=r?r.equation:state?`${state.name} · ${stateDescription(state)}`:node.role;
  const key=r?`data-reaction-id="${esc(r.id)}"`:state?`data-pathway-state-id="${esc(state.id)}"`:'';
  const text=body.map(([line,size,ink,bold],i)=>
    pathwayText(center,y+height/2+5+18*(i-(body.length-1)/2),line,size,ink,bold,'middle')).join('');
  const dash=node.checks?' stroke-dasharray="5 3"':'';
  return `<g ${key}${key?' style="cursor:pointer"':''}><title>${esc(title)}</title><rect x="${x}" y="${y}" width="${pathNodeWidth}" height="${height}" rx="7" fill="${r?'#fff':nodeFill(state)}" stroke="${color}" stroke-width="${isTarget?3:r?2:1.2}"${dash}/>${text}</g>`;
}
function downloadPathwayPng(){
  const svg=el('pathway-graph').querySelector('svg');
  if(!svg)return;
  const target=stateById.get(el('pathway-target').value);
  const source=new XMLSerializer().serializeToString(svg);
  const url=URL.createObjectURL(new Blob([source],{type:'image/svg+xml;charset=utf-8'}));
  const image=new Image();
  image.onload=()=>{
    const {width,height}=svg.viewBox.baseVal,scale=2,canvas=document.createElement('canvas');
    canvas.width=width*scale;
    canvas.height=height*scale;
    const context=canvas.getContext('2d');
    context.scale(scale,scale);
    context.drawImage(image,0,0);
    URL.revokeObjectURL(url);
    canvas.toBlob(png=>{
      if(!png)return;
      const link=document.createElement('a');
      link.href=URL.createObjectURL(png);
      link.download=`${data.case}-${target?.name??'target'}-pathway.png`;
      link.click();
      setTimeout(()=>URL.revokeObjectURL(link.href),1000);
    },'image/png');
  };
  image.onerror=()=>URL.revokeObjectURL(url);
  image.src=url;
}
function matrixReactions(){const order={electron:0,ion:1,neutral:2,surface:3};return [...filtered].sort((a,b)=>(order[a.family]??9)-(order[b.family]??9)||a.process.localeCompare(b.process)||a.depth-b.depth||a.id.localeCompare(b.id))}
function matrixMark(reaction,state,x,y,width,height,reactant,product){
  const attrs=`data-reaction-id="${esc(reaction.id)}" style="cursor:pointer"`;
  const title=`${reaction.equation} · ${state.name} · ${reactant} → ${product}`;
  const band=Math.floor(height/3);
  const mark=(top,color)=>`<rect x="${x}" y="${top}" width="${width}" height="${band}" fill="${color}"/>`;
  const glyph=reactant&&product&&netStoichiometry(reaction,state.id)===0
    ?mark(y+band,'#6e7881')
    :[reactant?mark(y,'#c56a2d'):'',product?mark(y+2*band,'#2f6b9a'):''].join('');
  return `<g ${attrs}><title>${esc(title)}</title>${glyph}</g>`;
}
function renderMatrix(){
  const reactions=matrixReactions(),states=data.states;
  const graph=el('matrix-graph'),summary=el('matrix-summary');
  summary.textContent=`${states.length.toLocaleString()} states · ${reactions.length.toLocaleString()} reactions`;
  if(!reactions.length){graph.innerHTML='<div class="empty">No matching reactions</div>';return}
  const labelWidth=Math.max(190,...states.map(state=>20+8*state.name.length));
  const rowHeight=24,header=52,matrixWidth=Math.max(1000,3*reactions.length);
  const width=labelWidth+matrixWidth,height=header+states.length*rowHeight+1;
  const rows=new Map(states.map((state,index)=>[state.id,header+rowHeight*index]));
  const labels=states.map((state,index)=>{
    const y=rows.get(state.id);
    return `<rect x="0" y="${y}" width="${width}" height="${rowHeight}" fill="${index%2?'#f4f7f9':'#fff'}"/>`
      +`<text x="12" y="${y+16}" font-size="11" font-weight="650" fill="#1f2933" data-state-id="${esc(state.id)}" style="cursor:pointer">${esc(state.name)}</text>`;
  });
  const columns=reactions.map((reaction,index)=>{
    const x=labelWidth+Math.floor(index*matrixWidth/reactions.length);
    const w=labelWidth+Math.floor((index+1)*matrixWidth/reactions.length)-x;
    const incoming=new Map(reaction.diagram_reactants.map(term=>[term.species,term.n]));
    const outgoing=new Map(reaction.diagram_products.map(term=>[term.species,term.n]));
    const marks=[...new Set([...incoming.keys(),...outgoing.keys()])].filter(id=>rows.has(id)).map(id=>
      matrixMark(reaction,stateById.get(id),x,rows.get(id),w,rowHeight,incoming.get(id)??0,outgoing.get(id)??0));
    const band=`<rect x="${x}" y="27" width="${w}" height="20" fill="${familyColor[reaction.family]??'#727b83'}" data-reaction-id="${esc(reaction.id)}" style="cursor:pointer"><title>${esc(reaction.equation)}</title></rect>`;
    return band+marks.join('');
  });
  graph.innerHTML=`<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Reaction-state participation"><rect width="${width}" height="${height}" fill="white"/><text x="12" y="41" font-size="12" font-weight="650">State</text><text x="${labelWidth}" y="17" font-size="12" font-weight="650">Reaction family / process / depth</text>${labels.join('')}${columns.join('')}</svg>`;
}
function neighborhoodRole(reaction,stateId){const delta=netStoichiometry(reaction,stateId);return delta>0?'producer':delta<0?'consumer':'preserving'}
function neighborhoodGroups(){const groups={producer:[],consumer:[],preserving:[]};if(!focusedStateId)return groups;for(const reaction of filtered)groups[neighborhoodRole(reaction,focusedStateId)].push(reaction);return groups}
function neighborhoodRange(role,total){if(!total)return'0 of 0';const start=neighborhoodPages[role]*neighborhoodPageSize;return`${start+1}-${Math.min(start+neighborhoodPageSize,total)} of ${total}`}
function renderNeighborhoodPagers(groups){const labels={producer:'producers',consumer:'consumers',preserving:'zero-net'};el('neighborhood-pagers').innerHTML=Object.entries(groups).map(([role,items])=>{const pages=Math.max(1,Math.ceil(items.length/neighborhoodPageSize)),page=Math.min(neighborhoodPages[role],pages-1);neighborhoodPages[role]=page;return`<div class="role-pager"><button data-role="${role}" data-step="-1" type="button"${page===0?' disabled':''}>←</button><span>${labels[role]} ${neighborhoodRange(role,items.length)}</span><button data-role="${role}" data-step="1" type="button"${page>=pages-1?' disabled':''}>→</button></div>`}).join('')}
function renderNeighborhood(){
  const state=stateById.get(focusedStateId);if(!state){el('neighborhood-title').textContent='State-neighborhood network';el('neighborhood-summary').textContent='Click a state row in Matrix or a state node in Reaction hyperedge.';el('neighborhood-graph').innerHTML='<div class="empty">No focal state selected.</div>';el('neighborhood-pagers').textContent='';return;}
  const groups=neighborhoodGroups();renderNeighborhoodPagers(groups);const visible=Object.fromEntries(Object.entries(groups).map(([role,items])=>{const start=neighborhoodPages[role]*neighborhoodPageSize;return[role,items.slice(start,start+neighborhoodPageSize)]}));
  el('neighborhood-title').textContent=`${state.name} — state-neighborhood network`;el('neighborhood-summary').textContent=`${stateDescription(state)}. ${groups.producer.length} net producers · ${groups.consumer.length} net consumers · ${groups.preserving.length} zero-net participants. Each role has independent paging; current assessment and filters are applied.`;el('neighborhood-graph').innerHTML=neighborhoodSvg(state,visible);
}
function neighborhoodSvg(state,groups){
  const mainRows=Math.max(groups.producer.length,groups.consumer.length,1),rowGap=92,top=88,focalY=top+(mainRows-1)*rowGap/2,preserveRows=Math.ceil(groups.preserving.length/2),preserveTop=top+mainRows*rowGap+70,height=Math.max(390,preserveTop+Math.max(1,preserveRows)*92+55);let svg=`<svg viewBox="0 0 1200 ${height}" role="img" aria-label="Connected reaction network for ${esc(state.name)}">${neighborhoodDefinitions()}<text x="205" y="34" text-anchor="middle" font-size="13" font-weight="650" fill="#1f2933">Net producers (Δν &gt; 0)</text><text x="600" y="34" text-anchor="middle" font-size="13" font-weight="650" fill="#1f2933">Focal state</text><text x="995" y="34" text-anchor="middle" font-size="13" font-weight="650" fill="#1f2933">Net consumers (Δν &lt; 0)</text>`;
  svg+=neighborhoodStateNode(state,500,focalY);groups.producer.forEach((reaction,index)=>{const y=top+index*rowGap;svg+=neighborhoodReactionNode(reaction,30,y,360,'producer');svg+=neighborhoodEdge(410,y+36,500,focalY+31,reaction)});groups.consumer.forEach((reaction,index)=>{const y=top+index*rowGap;svg+=neighborhoodEdge(700,focalY+31,790,y+36,reaction);svg+=neighborhoodReactionNode(reaction,810,y,360,'consumer')});
  if(groups.preserving.length){svg+=`<text x="600" y="${preserveTop-28}" text-anchor="middle" font-size="13" font-weight="650" fill="#1f2933">Zero-net participants (Δν = 0)</text>`;groups.preserving.forEach((reaction,index)=>{const x=index%2?625:175,y=preserveTop+Math.floor(index/2)*92;svg+=neighborhoodBidirectionalEdge(600,focalY+62,x+200,y,reaction);svg+=neighborhoodReactionNode(reaction,x,y,400,'preserving')})}svg+='</svg>';return svg;
}
function neighborhoodDefinitions(){return `<defs>${Object.entries(familyColor).map(([family,color])=>`<marker id="n-${family}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${color}"/></marker>`).join('')}</defs>`}
function neighborhoodStateNode(state,x,y){const subtitle=`${state.excitation} · ${state.resolution} · q=${state.charge>=0?'+':''}${state.charge}`;return `<g><title>${esc(`${state.name}: ${stateDescription(state)}`)}</title><rect x="${x}" y="${y}" width="200" height="62" rx="8" fill="${nodeFill(state)}" stroke="#1f2933" stroke-width="2"/><text x="${x+100}" y="${y+27}" text-anchor="middle" font-size="15" font-weight="700" fill="#1f2933">${esc(state.name)}</text><text x="${x+100}" y="${y+47}" text-anchor="middle" font-size="10" fill="#64717d">${esc(subtitle)}</text></g>`}
function neighborhoodReactionNode(reaction,x,y,width,role){const color=familyColor[reaction.family]??'#727b83',verdict=verdictFor(reaction),dash=verdictDash[verdict],diamondX=role==='producer'?x+width+10:role==='consumer'?x-20:x+width/2,diamondY=role==='preserving'?y:y+36;return `<g data-reaction-id="${esc(reaction.id)}" style="cursor:pointer"><rect x="${x}" y="${y}" width="${width}" height="72" rx="6" fill="#fff" stroke="${color}" stroke-width="1.8"${dash?` stroke-dasharray="${dash}"`:''}/><foreignObject x="${x+10}" y="${y+7}" width="${width-20}" height="58"><div xmlns="http://www.w3.org/1999/xhtml" style="font:600 11px/1.3 system-ui;color:#1f2933;overflow-wrap:anywhere">${esc(reaction.equation)}<div style="margin-top:4px;font-size:9px;font-weight:400;color:#64717d">${esc(reaction.family)} · ${esc(reaction.reaction_type)} · depth ${reaction.depth} · ${esc(verdictLabel(verdict))}</div></div></foreignObject><polygon points="${diamondX},${diamondY-9} ${diamondX+8},${diamondY} ${diamondX},${diamondY+9} ${diamondX-8},${diamondY}" fill="#fff" stroke="${color}" stroke-width="2"${dash?` stroke-dasharray="${dash}"`:''}/></g>`}
function neighborhoodEdge(x1,y1,x2,y2,reaction){const color=familyColor[reaction.family]??'#727b83',dash=verdictDash[verdictFor(reaction)],control=(x1+x2)/2,path=`M${x1} ${y1} C${control} ${y1},${control} ${y2},${x2} ${y2}`;return `<path d="${path}" fill="none" stroke="#fff" stroke-width="5"/><path d="${path}" fill="none" stroke="${color}" stroke-width="1.8"${dash?` stroke-dasharray="${dash}"`:''} marker-end="url(#n-${reaction.family})"/>`}
function neighborhoodBidirectionalEdge(x1,y1,x2,y2,reaction){const color=familyColor[reaction.family]??'#727b83',dash=verdictDash[verdictFor(reaction)],path=`M${x1} ${y1} C${x1} ${y1+35},${x2} ${y2-35},${x2} ${y2}`;return `<path d="${path}" fill="none" stroke="#fff" stroke-width="5"/><path d="${path}" fill="none" stroke="${color}" stroke-width="1.8"${dash?` stroke-dasharray="${dash}"`:''} marker-start="url(#n-${reaction.family})" marker-end="url(#n-${reaction.family})"/>`}
function followState(stateId){
  if(!stateById.has(stateId))return;
  focusedStateId=stateId;
  el('search').value='';
  activePanel='neighborhood';
  applyFilters();
  el('reaction-list').scrollTop=0;
}
function chooseAssessment(layer,preserveReaction=false){
  el('view').value=layer;
  el('verdict').value='';
  applyFilters(preserveReaction);
}
el('assessment-summary').addEventListener('click',event=>{
  const button=event.target.closest('[data-assessment]');
  if(button)chooseAssessment(button.dataset.assessment,true);
});
el('graph').addEventListener('click',event=>{const node=event.target.closest('[data-state-id]');if(node)followState(node.dataset.stateId)});
el('pathway-graph').addEventListener('click',event=>{
  const reaction=event.target.closest('[data-reaction-id]');
  if(reaction){selectReaction(reaction.dataset.reactionId);return}
  const state=event.target.closest('[data-pathway-state-id]');
  if(state){requestedPathwayTarget=state.dataset.pathwayStateId;renderPathway()}
});
for(const id of ['pathway-related-list','pathway-excluded-list']){
  el(id).addEventListener('click',event=>{
    const reaction=event.target.closest('[data-reaction-id]');
    if(reaction)selectReaction(reaction.dataset.reactionId);
  });
}
el('matrix-graph').addEventListener('click',event=>{const reaction=event.target.closest('[data-reaction-id]');if(reaction){selectReaction(reaction.dataset.reactionId);return}const state=event.target.closest('[data-state-id]');if(state)followState(state.dataset.stateId)});
el('neighborhood-graph').addEventListener('click',event=>{const node=event.target.closest('[data-reaction-id]');if(node)selectReaction(node.dataset.reactionId)});el('neighborhood-pagers').addEventListener('click',event=>{const button=event.target.closest('[data-role]');if(!button)return;const role=button.dataset.role;neighborhoodPages[role]+=Number(button.dataset.step);renderNeighborhood()});el('overview-tab').onclick=()=>showPanel('overview');el('pathway-tab').onclick=()=>showPanel('pathway');el('reaction-tab').onclick=()=>showPanel('reaction');el('neighborhood-tab').onclick=()=>showPanel('neighborhood');el('pathway-scope').addEventListener('change',()=>{pathwayReachability=null;renderPathway()});
el('neighborhood-pathway').onclick=()=>{requestedPathwayTarget=focusedStateId;showPanel('pathway')};
el('pathway-target').addEventListener('change',renderPathway);
el('pathway-via-toggle').onclick=()=>{showSelectedProducer=!showSelectedProducer;renderPathway()};
el('pathway-download').onclick=downloadPathwayPng;
el('state-filter').onclick=()=>{focusedStateId=null;activePanel='reaction';applyFilters(true)};
el('view').addEventListener('change',()=>chooseAssessment(el('view').value,true));
for(const id of ['family','process','collision-input','verdict','depth','equation-pass'])el(id).addEventListener('change',()=>applyFilters());
el('search').addEventListener('input',()=>applyFilters());
el('reset').onclick=()=>{
  focusedStateId=null;
  activePanel='reaction';
  for(const id of ['search','family','process','collision-input','verdict','depth'])el(id).value='';
  el('equation-pass').checked=false;
  chooseAssessment(data.views[0].id);
};
el('previous').onclick=()=>{pageIndex--;renderList()};
el('next').onclick=()=>{pageIndex++;renderList()};
function applyInitialLocation(){
  const params=new URLSearchParams(location.search),view=params.get('view'),state=params.get('state'),target=params.get('target');
  if(viewById.has(view))el('view').value=view;
  if(stateById.has(state)){focusedStateId=state;activePanel='neighborhood'}
  if(params.get('panel')==='pathway'){
    activePanel='pathway';
    if(stateById.has(target))requestedPathwayTarget=target;
  }
}
populateControls();
applyInitialLocation();
applyFilters();
</script>
</body>
</html>
"""
