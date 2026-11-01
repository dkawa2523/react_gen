"""Lookup aliases retain acquisition context without changing scientific subjects."""

from copy import deepcopy
from pathlib import Path

import pytest

from acquire import targets
from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog, snapshot_state
from reactgen.pipeline import analyze
from reactgen.records import scientific_state_content, state_record_payload

ETHANOL = {
    "molecularFormula": "C2H6O",
    "name": "ethanol",
    "other_names": ["ethyl alcohol"],
    "cas": "64-17-5",
    "inChI": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
}


def write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


def mapped(identity, formula, alias, *, structure=None):
    entry = {"id": formula, "query": alias}
    if structure is not None:
        entry["structure"] = structure
    request = targets.requests([entry])[0][0]
    raw = {
        "species": alias,
        "property": "mass_amu",
        "value": 46.07,
        "unit": "amu",
        "source": {"provider": "independent_lab", "record_id": "mass-measurement"},
    }
    original = deepcopy(raw)
    result = targets.records_for(request, [raw], identity=identity)[0]
    assert raw == original
    assert "source_query" not in result
    assert result["source_declaration"]["acquisition"]["request"]["query"] == alias
    return result


@pytest.mark.parametrize("reverse", [False, True])
def test_requested_names_resolve_to_one_independent_source_structure(tmp_path, reverse):
    offered = [
        mapped(ETHANOL, "C2H6O", "ethanol", structure="ethanol"),
        mapped(ETHANOL, "C2H6O", "ethyl alcohol", structure="ethyl alcohol"),
        mapped(ETHANOL, "C2H6O", "64-17-5", structure="CAS=64-17-5"),
    ]
    if reverse:
        offered.reverse()
    assert {record["structure"] for record in offered} == {ETHANOL["inChI"]}
    paths = tuple(
        write(tmp_path / f"snapshot-{i}.yaml", {"records": [record]})
        for i, record in enumerate(offered)
    )
    catalog = EvidenceCatalog.load_paths(paths)
    assert len({record.record_id for record in catalog.state_records}) == 1
    assert len({record.candidate.key for record in catalog.state_records}) == 1
    assert all(
        scientific_state_content(record) == scientific_state_content(catalog.state_records[0])
        for record in catalog.state_records
    )
    assert len(catalog.state_records) == len(offered)
    assert (
        catalog.state_records[0].source_declaration != catalog.state_records[1].source_declaration
    )
    root = tmp_path / "registry"
    write(
        root / "species" / "ethanol.yaml",
        {
            "id": "ethanol",
            "composition": {"C": 2, "H": 6, "O": 1},
            "phase": "gas",
            "structure": ETHANOL["inChI"],
        },
    )
    for i, record in enumerate(catalog.state_records):
        overlay = write(
            tmp_path / f"overlay-{i}.yaml",
            {"state_records": {record.candidate.id: [state_record_payload(record)]}},
        )
        assert adopt.adopt(overlay, root).written
        assert not adopt.adopt(overlay, root).written
    saved = EvidenceCatalog.load(root)
    retained = [
        record
        for record in saved.state_records
        if record.provenance.record_id == "mass-measurement"
    ]
    assert len(retained) == len(offered)


def test_lookup_aliases_round_trip_through_ingest_and_adopt_without_scientific_conflict(tmp_path):
    identity = {"molecularFormula": "O2", "name": "oxygen", "other_names": ["molecular oxygen"]}
    offered = [mapped(identity, "O2", alias) for alias in ("oxygen", "molecular oxygen")]
    bundle, overlay = tmp_path / "result", tmp_path / "overlay.yaml"
    export.write(bundle, analyze(Case("oxygen", ("O2",)), EvidenceCatalog()))
    for i, record in enumerate(offered):
        source = write(tmp_path / f"snapshot-{i}.yaml", {"records": [record]})
        assert ingest.ingest(source, bundle, overlay).accepted == 1
    catalog = EvidenceCatalog.load_paths((overlay,))
    assert len(catalog.state_records) == 2
    assert len({record.record_id for record in catalog.state_records}) == 1
    assert scientific_state_content(catalog.state_records[0]) == scientific_state_content(
        catalog.state_records[1]
    )
    root = tmp_path / "registry"
    write(root / "species" / "O2.yaml", {"id": "O2", "composition": {"O": 2}, "phase": "gas"})
    assert adopt.adopt(overlay, root).written
    assert not adopt.adopt(overlay, root).written


def test_source_specific_property_remains_related_to_an_unidentified_formula(tmp_path):
    entry = targets.requests(["C2H6O"])[0][0]
    record = targets.records_for(
        entry,
        [
            {
                "property": "enthalpy_formation_eV",
                "value": -2.43,
                "unit": "eV",
                "status": "reviewed",
                "formation_reference": {
                    "temperature_K": 298.15,
                    "basis": "standard_elements",
                    "standard_pressure_Pa": 1e5,
                },
                "source": {"provider": "independent_lab", "record_id": "enthalpy-measurement"},
            }
        ],
        identity=ETHANOL,
    )[0]
    path = write(tmp_path / "snapshot.yaml", {"records": [record]})
    catalog = EvidenceCatalog.load_paths((path,))
    source = snapshot_state(record, {})
    assert source is not None
    assert source.properties["enthalpy_formation_eV"].reviewed_for("enthalpy_formation_eV")
    result = analyze(Case("unidentified connectivity", ("C2H6O",)), catalog)
    state = next(
        state
        for state in result.candidates.states.values()
        if state.composition == {"C": 2, "H": 6, "O": 1}
        and state.charge == 0
        and state.state.kind == "ground"
    )
    assert result.evaluation.state_evidence[state.id].match == "compatible"
    assessment = result.evaluation.state_assessments[state.id]["thermochemistry"]
    assert assessment.verdict == "unknown"
    assert any(work.responsibility == "identity" for work in assessment.requirements)
    bundle, overlay = tmp_path / "result", tmp_path / "overlay.yaml"
    export.write(bundle, result)
    report = ingest.ingest(path, bundle, overlay)
    assert report.accepted == 0
    assert report.review[0]["reason"] == "no match"


def test_complete_smiles_does_not_drop_an_explicit_diatomic_isotope_without_inchi():
    identity = {"molecularFormula": "O2", "smiles": "[18O][18O]"}
    record = mapped(identity, "O2", "oxygen-18", structure="SMILES=[18O][18O]")
    assert record["structure"] == "SMILES=[18O][18O]"
    assert record["species"] != targets.requests(["O2"])[0][0].target.id
