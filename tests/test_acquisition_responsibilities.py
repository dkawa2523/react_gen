"""Acquisition identifies declarations; it does not supply missing physics or approval."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
import yaml

from acquire import (
    atoms,
    cccbdb,
    cli,
    ideal_gas,
    molecular,
    nasa,
    pubchem,
    targets,
    thermo,
    vibration,
)
from reactgen import naming, yamlio
from reactgen.evidence import EvidenceCatalog, snapshot_state
from reactgen.records import normalized_properties
from reactgen.registry import Registry


def write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


@pytest.mark.parametrize("formula", ["Ar_junk", "CF3+", "CH3(CH2)2OH", "Ar0"])
def test_plain_formula_never_partially_interprets_another_identity(formula):
    assert naming.parse_formula(formula) == {}


def test_plain_formula_adds_repeated_elements():
    assert naming.parse_formula("CH3OH") == {"C": 1, "H": 4, "O": 1}


@pytest.mark.parametrize("properties", [[], {"mass_amu": 40}, {1: {}}])
def test_property_mapping_rejects_malformed_declarations(properties):
    with pytest.raises(ValueError, match="properties must be a mapping"):
        normalized_properties(properties)


def test_property_loaders_do_not_discard_malformed_declarations(tmp_path):
    properties = {"mass_amu": 40}
    overlay = write(tmp_path / "overlay.yaml", {"properties": {"Ar": properties}})
    with pytest.raises(ValueError, match="properties must be a mapping"):
        EvidenceCatalog.load(None, overlay)
    root = tmp_path / "registry"
    write(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "properties": properties},
    )
    with pytest.raises(ValueError, match="properties must be a mapping"):
        Registry.load(root)
    with pytest.raises(ValueError, match="properties must be a mapping"):
        snapshot_state({"species": "Ar", "phase": "gas", "properties": properties}, {})


@pytest.mark.parametrize("container", ["properties", "thermo", "states"])
def test_an_invalid_legacy_overlay_target_is_not_silently_removed(tmp_path, container):
    path = write(tmp_path / "overlay.yaml", {container: {"not a physical target": {}}})
    with pytest.raises(ValueError, match="invalid state target"):
        EvidenceCatalog.load(None, path)


@pytest.mark.parametrize("record", [{"species": "foreign alias"}, {"reaction": "foreign -> alias"}])
def test_direct_snapshot_loading_names_unidentified_targets_and_the_matching_operation(
    tmp_path, record
):
    path = write(tmp_path / "snapshot.yaml", {"records": [record]})
    with pytest.raises(ValueError, match="unidentified .* target; use ingest"):
        EvidenceCatalog.load(None, known=(path,))


@pytest.mark.parametrize(
    "declaration",
    [
        {"composition": {"O": 1}},
        {"composition": {"O": True}},
        {"charge": True},
        {"state": {"kind": "electronic"}},
        {"phase": "solid"},
        {"structure": "another molecule"},
    ],
)
def test_snapshot_and_acquisition_apply_the_same_physical_identity_rules(declaration):
    target = "O2@ground;phase=gas;structure=oxygen"
    with pytest.raises(ValueError, match="contradicts"):
        snapshot_state({"species": target, **declaration}, {})
    with pytest.raises(ValueError, match="contradicts"):
        targets.requests([{"id": target, **declaration}])


@pytest.mark.parametrize("operation", ["thermo", "molecular"])
def test_ground_property_lookup_cannot_relabel_an_isomer(tmp_path, monkeypatch, operation):
    identity = {"molecularFormula": "C2H6O", "name": "dimethyl ether", "cas": "115-10-6"}
    module = {"thermo": thermo, "molecular": molecular}[operation]
    result = (
        thermo.Thermo("lookup", enthalpy_eV=-1.9, identity=identity)
        if operation == "thermo"
        else molecular.Molecule("lookup", dipole_D=1.3, identity=identity)
    )
    monkeypatch.setattr(module, "available", lambda: True)
    monkeypatch.setattr(module, "fetch", lambda *args: [replace(result, species=args[0][0])])
    request = write(
        tmp_path / "species.yaml", [{"id": "C2H6O", "structure": "ethanol", "query": "lookup"}]
    )
    out = tmp_path / "out"
    assert cli.main([operation, str(request), "--out", str(out)]) == 2
    assert not out.exists()


def test_formula_lookup_retains_source_structure_instead_of_identifying_every_isomer():
    identity = {
        "molecularFormula": "C2H6O",
        "name": "dimethyl ether",
        "inChI": "InChI=1S/C2H6O/c1-3-2/h1-2H3",
        "cas": "115-10-6",
    }
    request = targets.requests(["C2H6O"])[0][0]
    record = targets.records_for(
        request, [{"property": "enthalpy_formation_eV", "value": -1.9}], identity=identity
    )[0]
    assert record["structure"] == identity["inChI"]
    assert record["species"] != request.target.id
    assert record["source_identity"] == identity
    source = snapshot_state(record, {})
    assert source.candidate.structure == identity["inChI"]


def test_source_metadata_cannot_be_replaced_by_requested_identity():
    request = targets.requests([{"id": "C2H6O", "structure": "ethanol"}])[0][0]
    with pytest.raises(ValueError, match="composition"):
        targets.records_for(request, [{"property": "mass_amu", "value": 46}])
    identity = {"molecularFormula": "C2H6O", "name": "ethanol"}
    with pytest.raises(ValueError, match="contradicts its independent identity"):
        targets.records_for(request, [{"structure": "dimethyl ether"}], identity=identity)


def test_machine_structure_identifiers_remain_case_sensitive():
    identity = {"molecularFormula": "C2H6O", "inChI": "InChI=1S/C2H6O/c1-3-2/h1-2H3"}
    request = targets.requests([{"id": "C2H6O", "structure": identity["inChI"].lower()}])[0][0]
    with pytest.raises(ValueError, match="source structure"):
        targets.source_structure(identity, request)


@pytest.mark.parametrize("registered_mass", [None, 46, 100])
def test_pubchem_formula_agreement_does_not_confirm_an_explicit_isomer(registered_mass):
    entry = {"id": "C2H6O", "structure": "ethanol", "query": "dimethyl ether"}
    if registered_mass is not None:
        entry["mass_amu"] = registered_mass
    request = targets.requests([entry])[0][0]
    identity = pubchem.Identity(
        "dimethyl ether",
        cid=8254,
        formula="C2H6O",
        mass_amu=46,
        inchikey="LCGLNKUTAGEVQW-UHFFFAOYSA-N",
        synonyms=["dimethyl ether"],
    )
    summary, records = cli._identity_result(entry, request, identity)
    assert summary["verdict"] == "unresolved"
    assert "source structure" in summary["error"]
    assert not records


@pytest.mark.parametrize(
    ("source_fields", "full_smiles", "connectivity"),
    [
        (
            {"SMILES": "C[C@H](F)O", "ConnectivitySMILES": "CC(F)O"},
            "C[C@H](F)O",
            "CC(F)O",
        ),
        (
            {"IsomericSMILES": "C[C@H](F)O", "CanonicalSMILES": "CC(F)O"},
            "C[C@H](F)O",
            "CC(F)O",
        ),
        ({"CanonicalSMILES": "CC(F)O"}, None, "CC(F)O"),
    ],
)
def test_pubchem_current_and_historical_smiles_keep_their_identity_scope(
    monkeypatch, source_fields, full_smiles, connectivity
):
    payload = {"CID": 1, "MolecularFormula": "C2H5FO", "MolecularWeight": "64.06"}
    monkeypatch.setattr(
        pubchem,
        "_get",
        lambda url: {"PropertyTable": {"Properties": [payload | source_fields]}},
    )
    monkeypatch.setattr(pubchem, "_synonyms", lambda cid: [])
    identity = pubchem._one("source query")
    assert identity.smiles == full_smiles
    assert identity.connectivity_smiles == connectivity
    entry = {"id": "C2H5FO", "structure": "SMILES=C[C@H](F)O"}
    request = targets.requests([entry])[0][0]
    summary, records = cli._identity_result(entry, request, identity)
    assert summary["verdict"] == ("fills_gap" if full_smiles else "unresolved")
    assert bool(records) == bool(full_smiles)
    if records:
        source = records[0]["source_identity"]
        assert source["smiles"] == full_smiles
        assert source["connectivity_smiles"] == connectivity
    opposite = {"id": "C2H5FO", "structure": "SMILES=C[C@@H](F)O"}
    request = targets.requests([opposite])[0][0]
    assert cli._identity_result(opposite, request, identity)[0]["verdict"] == "unresolved"


def test_cccbdb_cli_keeps_multiple_requested_structures_of_the_same_formula(tmp_path, monkeypatch):
    listed = [
        cccbdb.Listed("C2H6O", "ethanol", 5.2),
        cccbdb.Listed("C2H6O", "dimethyl ether", 5.1),
    ]
    monkeypatch.setattr(cccbdb, "fetch", lambda offline: (listed, None))
    request = write(
        tmp_path / "request.yaml",
        {
            "states": [
                {"id": "C2H6O@ground;structure=ethanol"},
                {"id": "C2H6O@ground;structure=dimethyl%20ether"},
            ]
        },
    )
    out = tmp_path / "out"
    assert cli.main(["cccbdb", str(request), "--out", str(out)]) == 0
    records = yamlio.load((out / "snapshot.yaml").read_text(encoding="utf-8"))["records"]
    assert {record["structure"] for record in records} == {"ethanol", "dimethyl ether"}
    assert len(records) == 2


def test_cccbdb_composition_mapping_cannot_override_the_output_target():
    with pytest.raises(ValueError, match="composition contradicts"):
        cccbdb.records([cccbdb.Listed("Ar", "argon", 1.6)], {(("Ar", 1),): "F"}, "source")


@pytest.mark.parametrize("operation", ["molecular", "thermo", "idealgas", "vibration"])
def test_ground_adapter_cli_excludes_other_phases_and_states_before_lookup(
    tmp_path, monkeypatch, operation
):
    modules = {
        "molecular": molecular,
        "thermo": thermo,
        "idealgas": ideal_gas,
        "vibration": vibration,
    }
    module = modules[operation]
    monkeypatch.setattr(module, "available", lambda: True)

    def empty_lookup(names, *args):
        assert names == []
        return []

    monkeypatch.setattr(module, "fetch", empty_lookup)
    requested = write(
        tmp_path / "states.yaml",
        {
            "states": [
                {"id": "O2@ground;phase=solid", "composition": {"O": 2}, "phase": "solid"},
                {"id": "O2@electronic", "composition": {"O": 2}},
            ]
        },
    )
    out = tmp_path / "out"
    assert cli.main([operation, str(requested), "--out", str(out)]) in {0, 1}
    assert yamlio.load((out / "snapshot.yaml").read_text(encoding="utf-8"))["records"] == []


def test_thermo_cli_emits_the_requested_target_and_preserves_the_query(tmp_path, monkeypatch):
    monkeypatch.setattr(thermo, "available", lambda: True)

    def found(names, composition):
        assert names == ["molecular oxygen"]
        assert composition == {"molecular oxygen": {"O": 2}}
        return [
            thermo.Thermo(
                names[0],
                enthalpy_eV=0.0,
                identity={"molecularFormula": "O2", "name": "molecular oxygen"},
            )
        ]

    monkeypatch.setattr(thermo, "fetch", found)
    request = write(
        tmp_path / "request.yaml",
        {"states": [{"id": "O2@ground", "phase": "gas", "query": "molecular oxygen"}]},
    )
    out = tmp_path / "out"
    assert cli.main(["thermo", str(request), "--out", str(out)]) == 0
    saved = yamlio.load((out / "snapshot.yaml").read_text(encoding="utf-8"))["records"][0]
    assert saved["species"] == "O2@ground"
    assert saved["value"] == 0
    assert saved["source_declaration"]["acquisition"]["request"]["query"] == "molecular oxygen"
    assert saved["phase"] == "gas"


def test_molecular_absence_and_implementation_failure_are_different():
    assert molecular._lookup(lambda **kwargs: None, "CAS") is None

    def broken(**kwargs):
        raise RuntimeError("broken upstream implementation")

    with pytest.raises(RuntimeError, match="broken upstream"):
        molecular._lookup(broken, "CAS")


@pytest.mark.parametrize("value", [True, float("nan"), float("inf")])
def test_non_numeric_molecular_source_values_are_not_declared_available(value):
    with pytest.raises(ValueError, match="finite number"):
        molecular._lookup(lambda **kwargs: value, "CAS")


def test_dependency_identity_failure_is_not_an_unknown_molecule(monkeypatch):
    def broken(name):
        raise RuntimeError("identity implementation failure")

    monkeypatch.setitem(sys.modules, "chemicals", SimpleNamespace(dipole=None, lennard_jones=None))
    monkeypatch.setitem(
        sys.modules,
        "chemicals.identifiers",
        SimpleNamespace(CAS_from_any=broken, search_chemical=None),
    )
    with pytest.raises(RuntimeError, match="identity implementation"):
        molecular._one("O2")


@pytest.mark.parametrize("operation", [thermo._one, molecular._one, ideal_gas._one])
def test_direct_property_adapters_also_preserve_their_physical_scope(operation):
    found = operation("O2@ground;phase=solid", None)
    assert not found.known
    assert "neutral gas ground-state" in found.error


def test_a_broken_cantera_source_file_is_not_a_missing_species(tmp_path):
    with pytest.raises(FileNotFoundError):
        nasa._document(str(tmp_path / "missing.yaml"))
    path = tmp_path / "bad.yaml"
    path.write_text("species: [broken", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        nasa._document(str(path))


def test_nasa_canonical_identity_is_checked_before_fit_lookup():
    result = nasa._one({"id": "Ar@ground;phase=solid", "composition": {"Ar": 1}}, {})
    assert not result.known
    assert "gas-phase" in result.error
    with pytest.raises(ValueError, match="composition contradicts"):
        nasa._one({"id": "Ar", "composition": {"Ar": 1.5}}, {})
    result = nasa._one({"id": "O@1d2", "composition": {"O": 1}}, {})
    assert not result.known
    assert "independent evidence" in result.error


@pytest.mark.parametrize("code", [404, 500, 429])
def test_pubchem_404_is_absence_but_service_errors_are_failures(monkeypatch, code):
    def failed(request, **kwargs):
        raise HTTPError(request.full_url, code, "test response", {}, None)

    monkeypatch.setattr(pubchem, "urlopen", failed)
    identity = pubchem._one("Ar")
    assert identity.cid is None
    assert ("no PubChem entry" in identity.error) is (code == 404)
    assert ("request failed" in identity.error) is (code != 404)


@pytest.mark.parametrize("body", [b"not JSON", json.dumps([]).encode()])
def test_pubchem_bad_response_is_not_an_absent_identity(monkeypatch, body):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return body

    monkeypatch.setattr(pubchem, "urlopen", lambda *args, **kwargs: Response())
    identity = pubchem._one("Ar")
    assert "request failed" in identity.error
    assert "no PubChem entry" not in identity.error


def test_optional_synonym_failure_does_not_erase_known_identity_or_mass(monkeypatch):
    monkeypatch.setattr(
        pubchem,
        "_get",
        lambda url: {"PropertyTable": {"Properties": [{"CID": 1, "MolecularWeight": "40"}]}},
    )

    def failed(cid):
        raise OSError("synonyms unavailable")

    monkeypatch.setattr(pubchem, "_synonyms", failed)
    identity = pubchem._one("Ar")
    assert identity.resolved
    assert identity.mass_amu == 40
    assert pubchem.compare(identity) == "fills_gap"
    assert "synonyms request failed" in identity.error


def test_pubchem_cli_preserves_alias_queries_without_creating_an_unidentified_property(
    tmp_path, monkeypatch
):
    def fetch(names):
        assert names == ["argon"]
        return [pubchem.Identity("argon", cid=1, formula="Ar", mass_amu=40)]

    monkeypatch.setattr(pubchem, "fetch", fetch)
    path = write(
        tmp_path / "request.yaml",
        {"states": [{"id": "Ar@ground", "query": "argon"}, "argon", "Ar@electronic"]},
    )
    out = tmp_path / "out"
    assert cli.main(["pubchem", str(path), "--out", str(out)]) == 0
    records = yamlio.load((out / "snapshot.yaml").read_text(encoding="utf-8"))["records"]
    assert len(records) == 1
    assert records[0]["species"] == "Ar@ground"
    assert records[0]["phase"] == "gas"
    assert records[0]["source_declaration"]["acquisition"]["request"]["query"] == "argon"
    report = yamlio.load((out / "identity.yaml").read_text(encoding="utf-8"))["identity"]
    assert {entry["verdict"] for entry in report} == {
        "fills_gap",
        "identity_only",
        "not_applicable",
    }


def test_vibration_fetch_does_not_supply_undeclared_geometry_or_atom_count(monkeypatch):
    monkeypatch.setattr(vibration, "available", lambda: True)
    calls = []
    monkeypatch.setattr(vibration, "_one", lambda *args: calls.append(args))
    vibration.fetch(["CO2"])
    assert calls == [("CO2", None, None, None)]


def test_vibration_geometry_has_only_declared_or_derived_inputs():
    assert vibration._geometry(None, None, 2) is True
    assert vibration._geometry(None, None, 3) is None
    assert vibration._geometry(True, None, 3) is True
    with pytest.raises(ValueError, match="agree"):
        vibration._geometry(True, 2, 3)
    with pytest.raises(ValueError, match="diatomic"):
        vibration._geometry(False, 2, 2)


def test_vibration_alias_lookup_checks_target_composition_not_only_atom_count(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "chemicals.identifiers",
        SimpleNamespace(
            CAS_from_any=lambda name: "methane",
            search_chemical=lambda cas: SimpleNamespace(formula="CH4"),
        ),
    )
    found = vibration._one("methane", False, 5, {"C": 1, "F": 4})
    assert not found.known
    assert "composition" in found.error


def test_acquired_effective_quantum_is_an_estimate_with_a_distinct_scope():
    record = vibration.records([vibration.Quantum("CO2", energy_eV=0.1)], "fit")[0]
    assert record["quality"] == record["status"] == "estimated"
    assert record["quantity"] == "effective_vibrational_quantum"
    assert "no resolved vibrational level" in record["qualifier"]


def test_atomic_cli_reports_a_nominal_sign_without_repeating_the_binding_judgment(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(atoms, "available", lambda: True)
    monkeypatch.setattr(atoms, "fetch", lambda names: [atoms.Atom("F", affinity_eV=1)])
    assert cli.main(["atoms", "F", "--out", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "nominal EA > 0" in output
    assert "binds an electron" not in output


def test_nonfinite_atomic_ea_has_no_nominal_sign():
    assert atoms.Atom("F", affinity_eV=float("nan")).nominal_ea_positive is None
