from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from plasma_reactgen.data_sources import chemicals_adapter
from plasma_reactgen.data_sources.chemicals_provider import (
    ChemicalsPropertyProvider,
    ChemicalsSpeciesProvider,
    j_per_mol_to_ev,
    kj_per_mol_to_ev,
)
from plasma_reactgen.data_sources.registry import get_providers
from plasma_reactgen.preparation import prepare_case
from plasma_reactgen.preparation.property_enrichment import enrich_species_properties


def test_chemicals_providers_return_empty_when_package_unavailable(monkeypatch):
    _force_chemicals_unavailable(monkeypatch)

    species_provider = ChemicalsSpeciesProvider()
    property_provider = ChemicalsPropertyProvider()

    assert species_provider.find_species("CF4") == []
    assert property_provider.find_properties("CF4", ["mass_amu"]) == []
    assert species_provider.status()["available"] is False
    assert species_provider.status()["reason"] == "chemicals package not installed"
    assert property_provider.status()["reason"] == "chemicals package not installed"


def test_chemicals_species_and_property_candidates_with_fake_package(monkeypatch):
    _fake_chemicals(monkeypatch)

    species = ChemicalsSpeciesProvider().find_species("tetrafluoromethane")
    properties = ChemicalsPropertyProvider().find_properties(
        "CF4",
        ["mass_amu", "dipole_moment_D", "enthalpy_formation_eV", "collision_radius_A"],
    )

    assert species[0]["id"] == "CF4"
    assert species[0]["formula"] == "CF4"
    assert species[0]["molecular_weight_amu"] == 88.0043
    assert species[0]["aliases"] == ["tetrafluoromethane"]
    assert species[0]["cas"] == "75-73-0"
    assert species[0]["CAS"] == "75-73-0"
    assert species[0]["classes"] == ["neutral"]
    assert species[0]["source_record"] == {
        "source_type": "python_package",
        "database": "chemicals",
        "source_name": "chemicals_optional",
        "source_id": "chemicals:75-73-0",
        "evidence_type": "local_package_databank",
    }
    assert species[0]["molecular_weight"] == 88.0043

    by_name = {item["property"]: item for item in properties}
    assert by_name["mass_amu"]["value"] == 88.0043
    assert by_name["mass_amu"]["source_name"] == "chemicals_optional"
    assert by_name["dipole_moment_D"]["value"] == 0.0
    assert by_name["enthalpy_formation_eV"]["value"] == pytest.approx(j_per_mol_to_ev(-933200.0))
    assert "collision_radius_A" not in by_name
    assert all(item["source_record"]["source_type"] == "python_package" for item in properties)
    assert all(item["source_record"]["database"] == "chemicals" for item in properties)
    assert all(
        item["source_record"]["evidence_type"] == "local_package_databank" for item in properties
    )


def test_chemicals_optional_and_local_are_registered_for_profile_lookup():
    species_providers = get_providers(
        "species_identity",
        {"species_identity": ["chemicals_optional", "chemicals_local"]},
    )
    property_providers = get_providers(
        "properties",
        {"properties": ["chemicals_optional", "chemicals_local"]},
    )

    assert isinstance(species_providers[0], ChemicalsSpeciesProvider)
    assert isinstance(species_providers[1], ChemicalsSpeciesProvider)
    assert isinstance(property_providers[0], ChemicalsPropertyProvider)
    assert isinstance(property_providers[1], ChemicalsPropertyProvider)


def test_chemicals_unit_conversion_helpers():
    assert j_per_mol_to_ev(96485.33212331002) == pytest.approx(1.0)
    assert kj_per_mol_to_ev(96.48533212331002) == pytest.approx(1.0)


def test_chemicals_property_adapter_supports_positional_optional_apis(monkeypatch):
    chemical = SimpleNamespace(MW=28.0, CASs="test-cas")

    def positional_value(cas=None, **kwargs):
        if kwargs:
            raise TypeError("keyword form unavailable")
        assert cas == "test-cas"
        return 1.25

    def fake_import(name, package=None):
        if name == "chemicals.identifiers":
            return SimpleNamespace(search_chemical=lambda query: chemical)
        if name == "chemicals.dipole":
            return SimpleNamespace(dipole_moment=positional_value)
        if name == "chemicals.reaction":
            return SimpleNamespace(Hfg=positional_value)
        if name == "chemicals.lennard_jones":
            return SimpleNamespace(sigma_A=positional_value)
        raise ImportError(name)

    monkeypatch.setattr(chemicals_adapter.importlib, "import_module", fake_import)

    properties = ChemicalsPropertyProvider().find_properties(
        "test",
        ["dipole_moment_D", "enthalpy_formation_eV", "collision_radius_A"],
    )
    values = {item["property"]: item["value"] for item in properties}

    assert values["dipole_moment_D"] == 1.25
    assert values["enthalpy_formation_eV"] == pytest.approx(j_per_mol_to_ev(1.25))
    assert values["collision_radius_A"] == 1.25


def test_prepare_case_does_not_crash_when_chemicals_unavailable(tmp_path, monkeypatch):
    _force_chemicals_unavailable(monkeypatch)
    registry_root = _make_minimal_registry(tmp_path / "registry")
    input_path = tmp_path / "case.yaml"
    output_dir = tmp_path / "prepared_registry"
    input_path.write_text(
        yaml.safe_dump(
            {
                "case": {"name": "chemicals-unavailable"},
                "gases": ["CF4"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    original_registry = {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    }

    report = prepare_case(
        input_path=input_path,
        registry_root=registry_root,
        source_profile={
            "name": "chemicals_unavailable_test",
            "species_identity": ["local_registry", "chemicals_optional"],
            "properties": ["local_registry", "chemicals_optional"],
        },
        output_dir=output_dir,
    )

    assert report["schema_version"] == 2
    assert report["source_profile"]["chemicals_optional"] is True
    assert (output_dir / "prepare_report.yaml").exists()
    assert not (output_dir / "species" / "CF4.yaml").exists()
    assert {
        path: path.read_text(encoding="utf-8") for path in registry_root.rglob("*.yaml")
    } == original_registry


def test_chemicals_enrichment_does_not_overwrite_existing_value_and_reports_conflict(
    tmp_path, monkeypatch
):
    _fake_chemicals(monkeypatch)
    prepared_registry = tmp_path / "prepared_registry"
    _write_yaml(
        prepared_registry / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "properties": {
                "mass_amu": {
                    "value": 87.0,
                    "unit": "amu",
                    "source": "curated",
                }
            },
            "metadata": {"status": "prepared"},
        },
    )

    report = enrich_species_properties(
        prepared_registry,
        [ChemicalsPropertyProvider()],
        {"name": "chemicals_test", "properties": ["chemicals_optional"]},
    )

    payload = yaml.safe_load(
        (prepared_registry / "species" / "CF4.yaml").read_text(encoding="utf-8")
    )
    assert payload["properties"]["mass_amu"]["value"] == 87.0
    assert {
        "kind": "property_conflict",
        "species": "CF4",
        "property": "mass_amu",
        "existing_value": 87.0,
        "candidate_value": 88.0043,
        "candidate_source": {
            "source_type": "python_package",
            "database": "chemicals",
            "source_name": "chemicals_optional",
            "source_id": "chemicals:75-73-0:mass_amu",
            "evidence_type": "local_package_databank",
        },
        "action": "manual_review",
    } in report["property_conflicts"]


def test_chemicals_enrichment_fills_missing_property_with_metadata_source(tmp_path, monkeypatch):
    _fake_chemicals(monkeypatch)
    prepared_registry = tmp_path / "prepared_registry"
    _write_yaml(
        prepared_registry / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "properties": {},
            "metadata": {"status": "prepared"},
        },
    )

    report = enrich_species_properties(
        prepared_registry,
        [ChemicalsPropertyProvider(provider_name="chemicals_local")],
        {"name": "chemicals_test", "properties": ["chemicals_local"]},
    )

    payload = yaml.safe_load(
        (prepared_registry / "species" / "CF4.yaml").read_text(encoding="utf-8")
    )
    source_record = payload["metadata"]["property_sources"]["mass_amu"]
    assert report["summary"]["n_properties_filled"] >= 1
    assert payload["properties"]["mass_amu"]["value"] == 88.0043
    assert source_record["database"] == "chemicals"
    assert source_record["source_name"] == "chemicals_local"
    assert source_record["evidence_type"] == "local_package_databank"


def _force_chemicals_unavailable(monkeypatch) -> None:
    real_import = chemicals_adapter.importlib.import_module

    def fake_import(name, package=None):
        if name.startswith("chemicals"):
            raise ImportError("chemicals unavailable for test")
        return real_import(name, package)

    monkeypatch.setattr(chemicals_adapter.importlib, "import_module", fake_import)


def _fake_chemicals(monkeypatch) -> None:
    chemical = SimpleNamespace(
        formula="CF4",
        MW=88.0043,
        synonyms=["tetrafluoromethane"],
        CASs="75-73-0",
        common_name="tetrafluoromethane",
    )

    def fake_import(name, package=None):
        if name == "chemicals.identifiers":
            return SimpleNamespace(search_chemical=lambda query: chemical)
        if name == "chemicals.dipole":
            return SimpleNamespace(dipole_moment=lambda CASRN=None: 0.0)
        if name == "chemicals.reaction":
            return SimpleNamespace(Hfg=lambda CASRN=None: -933200.0)
        if name == "chemicals":
            return SimpleNamespace()
        raise ImportError(name)

    monkeypatch.setattr(chemicals_adapter.importlib, "import_module", fake_import)


def _make_minimal_registry(root: Path) -> Path:
    _write_yaml(
        root / "species" / "CF4.yaml",
        {
            "schema_version": 1,
            "id": "CF4",
            "display_name": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "classes": ["neutral", "molecule"],
            "state": {"kind": "ground", "label": "X", "excitation_energy_eV": 0.0},
            "properties": {"polarizability_A3": {"value": None, "unit": "A3", "source": None}},
            "metadata": {"status": "curated", "notes": []},
        },
    )
    return root


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
