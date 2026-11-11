"""Lookup aliases retain acquisition context without changing scientific subjects."""

from copy import deepcopy
from pathlib import Path

import pytest

from acquire import targets
from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case, Conditions, Limits
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, reaction_record_candidate, snapshot_state
from reactgen.pipeline import analyze
from reactgen.records import scientific_state_content, state_record_payload
from reactgen.structure import StructureUnavailable, physical_state_key

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
    case = Case(
        "oxygen", ("O2",), limits=Limits(max_depth=1, max_atoms=2, max_species=20, max_reactions=30)
    )
    export.write(bundle, analyze(case, EvidenceCatalog()))
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
    # Identity/source matching uses the supplied target; exhaustive fragment growth is unrelated.
    case = Case(
        "unidentified connectivity",
        ("C2H6O",),
        limits=Limits(max_depth=1, max_atoms=9, max_species=20, max_reactions=30),
    )
    result = analyze(case, catalog)
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


def test_verified_smiles_aliases_bind_reaction_and_state_evidence(tmp_path, monkeypatch):
    pytest.importorskip("rdkit.Chem")
    declaration = "e + N2@ground;structure=smiles:[N]#[N] -> e + 2 N"
    snapshot = write(
        tmp_path / "source.yaml",
        {
            "records": [
                {
                    "species": "N2@ground;structure=smiles:[N]#[N]",
                    "phase": "gas",
                    "property": "mass_amu",
                    "value": 28,
                    "unit": "amu",
                    "status": "reviewed",
                },
                {
                    "reaction": declaration,
                    "type": "dissociation",
                    "status": "reviewed",
                    "kind": "rate_coefficient",
                    "form": "constant",
                    "parameters": {"value": 1e-14},
                    "unit": "m3/s",
                    "reaction_order": 2,
                    "independent_variable": "electron_temperature",
                    "validity": {
                        "quantity": "electron_temperature",
                        "unit": "eV",
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "review_scope": ["channel_assertion", "rate_coefficient"],
                    "energy_properties": {
                        "delta_e_eV": {
                            "value": 10,
                            "unit": "eV",
                            "definition": "products_minus_reactants",
                            "evidence_tier": "reviewed",
                            "status": "reviewed",
                        }
                    },
                },
            ]
        },
    )
    case = Case(
        "explicit nitrogen",
        ("N2",),
        supplies=("e",),
        structures={"N2": "N#N"},
        conditions=Conditions(
            collision_energy_eV=12, collision_energy_frame="com", electron_temperature_eV=3
        ),
        limits=Limits(max_depth=1, max_atoms=2),
    )
    output = tmp_path / "result"
    export.write(output, analyze(case, EvidenceCatalog.load_paths((snapshot,))))
    saved = export.read(output, verify_views=True)
    state = next(state for state in saved["states"] if state["structure"] == "smiles:N#N")
    channel = next(
        channel
        for channel in saved["reactions"]
        if channel["process"] == "dissociation" and channel["evidence"].get("structure_aliases")
    )
    assert state["evidence"]["match"] == "exact"
    assert any(
        record["candidate"]["structure"] == "smiles:[N]#[N]"
        and record["properties"].get("mass_amu", {}).get("value") == 28
        for record in state["evidence"]["records"]
    )
    assert channel["assessments"]["reaction_evidence"]["verdict"] == "pass"
    assert channel["assessments"]["energy"]["verdict"] == "pass"
    assert channel["thermochemical_calculations"]["state_energy_difference_eV"]["value"] == 10
    assert channel["evidence"]["records"][0]["source_declaration"]["reaction"] == declaration
    assert channel["origin"] == "attested_only"
    assert channel["data_use"]["status"] == "coefficient"
    assert channel["data_use"]["value"] == 1e-14

    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(snapshot, output, overlay).accepted == 2
    roundtrip = export.document(analyze(case, EvidenceCatalog.load_paths((overlay,))))
    matched = next(item for item in roundtrip["reactions"] if item["id"] == channel["id"])
    assert matched["assessments"]["reaction_evidence"]["verdict"] == "pass"
    assert matched["assessments"]["energy"]["verdict"] == "pass"
    assert matched["evidence"]["records"][0]["source_declaration"]["reaction"] == declaration
    assert matched["evidence"]["overlay_datasets"][0]["reaction_target"] == channel["id"]
    assert (
        matched["evidence"]["overlay_datasets"][0]["source_declaration"]["reaction"] == declaration
    )
    combined = tmp_path / "combined"
    export.write(combined, analyze(case, EvidenceCatalog.load_paths((snapshot, overlay))))
    result = export.read(combined, verify_views=True)
    merged = next(item for item in result["reactions"] if item["id"] == channel["id"])
    assert merged["assessments"]["reaction_evidence"]["verdict"] == "pass"
    assert merged["assessments"]["energy"]["verdict"] == "pass"
    assert merged["data_use"] == channel["data_use"]
    assert len(merged["evidence"]["records"]) == 2

    def unavailable():
        raise StructureUnavailable("test environment lacks RDKit")

    monkeypatch.setattr("reactgen.structure._chem", unavailable)
    assert export.read(output, verify_views=True) == saved


def test_structure_comparison_keeps_isotopes_isomers_and_levels_distinct():
    pytest.importorskip("rdkit.Chem")
    nitrogen = candidate_state({"N": 2}, 0, structure="smiles:N#N")
    isotope = candidate_state({"N": 2}, 0, structure="smiles:[15N]#[15N]")
    excited = candidate_state({"N": 2}, 0, kind="electronic", structure="smiles:[N]#[N]")
    ethanol = candidate_state({"C": 2, "H": 6, "O": 1}, 0, structure="smiles:CCO")
    ether = candidate_state({"C": 2, "H": 6, "O": 1}, 0, structure="smiles:COC")
    assert len({physical_state_key(item) for item in (nitrogen, isotope, excited)}) == 3
    assert physical_state_key(ethanol) != physical_state_key(ether)


@pytest.mark.parametrize("verify_graph", [False, True], ids=["binding", "rdkit"])
def test_registry_molecular_identity_is_local_and_preserves_dissociation_source(
    tmp_path, monkeypatch, verify_graph
):
    if verify_graph:
        try:
            from reactgen.structure import structure_key

            structure_key(candidate_state({"O": 2}, 0, structure="smiles:O=O"))
        except StructureUnavailable as error:
            pytest.skip(str(error))
    else:
        # This branch exercises the actual evidence and archive layers when
        # optional graph verification is unavailable on the test host.
        monkeypatch.setattr(
            "reactgen.structure._canonical_smiles_structure",
            lambda _composition, _charge, structure: structure,
        )
    declaration = "e + O2 -> e + 2 O"
    external = write(
        tmp_path / "external.yaml",
        {
            "records": [
                {
                    "id": "independent-formula-state",
                    "species": "O2",
                    "phase": "gas",
                    "property": "mass_amu",
                    "value": 35,
                    "unit": "amu",
                    "status": "reviewed",
                },
                {
                    "id": "independent-formula-channel",
                    "reaction": declaration,
                    "type": "dissociation",
                    "status": "reviewed",
                },
            ]
        },
    )
    registry = Path(__file__).resolve().parents[1] / "registry"
    catalog = EvidenceCatalog.load_paths((registry, external))
    case = Case(
        "molecular oxygen",
        ("O2",),
        supplies=("e",),
        structures={"O2": "O=O"},
        conditions=Conditions(collision_energy_eV=6, collision_energy_frame="com"),
        limits=Limits(max_depth=1, max_atoms=2),
    )
    output = tmp_path / "result"
    export.write(output, analyze(case, catalog))
    saved = export.read(output, verify_views=True)
    oxygen = next(item for item in saved["states"] if item["structure"] == "smiles:O=O")
    assert oxygen["evidence"]["match"] == "exact"
    (state_record,) = oxygen["evidence"]["records"]
    assert state_record["candidate"]["id"] == "O2@ground"
    assert state_record["molecular_identity"]["source"]["record_id"] == "C7782447"
    assert any(
        item["properties"].get("mass_amu", {}).get("value") == 35
        for item in oxygen["evidence"]["related_records"]
    )
    channel = next(
        item
        for item in saved["reactions"]
        if any(record["id"] == "e_O2_dissociation_O_O" for record in item["evidence"]["records"])
        and any(term["species"] == oxygen["id"] for term in item["reactants"])
    )
    (channel_record,) = channel["evidence"]["records"]
    assert channel_record["equation_key"][2] == [["O2@ground", 1.0], ["e", 1.0]]
    assert channel_record["molecular_identities"]["O2@ground"]["smiles"] == "O=O"
    assert channel["assessments"]["energy"]["verdict"] == "pass"
    difference = channel["thermochemical_calculations"]["state_energy_difference_eV"]
    assert difference["value"] == pytest.approx(5.1167, abs=2e-4)
    assert any(term.get("record_id") == channel_record["id"] for term in difference["inputs"])
    raw_datasets = channel_record["datasets"]
    raw_record = next(
        record for record in catalog.reaction_records if record.id == channel_record["id"]
    )
    assert channel_record["source_declaration"] == raw_record.source_declaration
    assert raw_datasets
    assert {item["reaction_target"] for item in raw_datasets} == {
        reaction_record_candidate(raw_record).id
    }

    fluorine = catalog.state(candidate_state({"F": 2}, 0, structure="smiles:FF"))
    assert fluorine.match == "exact"
    assert fluorine.records[0].candidate.id == "F2@ground"
    assert fluorine.records[0].molecular_identity.source.record_id == "C7782414"
    formation = next(record for record in fluorine.records if record.provenance.provider == "ATcT")
    assert formation.record_id == "ATcT_1.228:7782-41-4*0"
    assert formation.molecular_identity.source.record_id == "7782-41-4*0"
    assert all(record.thermo is None for record in fluorine.records if record.record_id)

    isotope = candidate_state({"O": 2}, 0, structure="smiles:[18O]=[18O]")
    assert catalog.state(isotope).match != "exact"
    assert all(record.molecular_identity is None for record in catalog.state(isotope).records)
    modified = deepcopy(saved)
    bound = next(item for item in modified["reactions"] if item["id"] == channel["id"])
    bound["evidence"]["records"][0].pop("molecular_identities")
    with pytest.raises(ValueError, match="reaction record contradicts its physical target"):
        export.validate(modified)

    def unavailable(*_args):
        raise StructureUnavailable("test environment lacks RDKit")

    monkeypatch.setattr("reactgen.registry.structure_key", unavailable)
    monkeypatch.setattr("reactgen.structure._chem", unavailable)
    assert catalog.state(candidate_state({"O": 2}, 0, structure="smiles:O=O")).match != "exact"
    assert export.read(output, verify_views=True) == saved


def test_complete_smiles_does_not_drop_an_explicit_diatomic_isotope_without_inchi():
    identity = {"molecularFormula": "O2", "smiles": "[18O][18O]"}
    record = mapped(identity, "O2", "oxygen-18", structure="SMILES=[18O][18O]")
    assert record["structure"] == "SMILES=[18O][18O]"
    assert record["species"] != targets.requests(["O2"])[0][0].target.id
