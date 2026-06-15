import socket
from pathlib import Path

import yaml

from plasma_reactgen.data_sources.pubchem_provider import PubChemProvider
from plasma_reactgen.data_sources.registry import get_providers
from plasma_reactgen.preparation import prepare_case


def test_pubchem_provider_returns_empty_when_disabled():
    provider = PubChemProvider()

    assert provider.available is False
    assert provider.find_species("CF4") == []
    assert provider.find_properties("CF4", ["mass_amu"]) == []
    assert provider.status()["available"] is False
    assert "not enabled" in provider.status()["message"]


def test_pubchem_provider_does_not_open_network_socket(monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("network access should not be attempted")

    monkeypatch.setattr(socket, "socket", fail_socket)
    provider = PubChemProvider(enabled=True)

    assert provider.find_species("tetrafluoromethane") == []
    assert provider.find_properties("CF4", ["mass_amu", "ionization_energy_eV"]) == []
    assert provider.status()["enabled"] is True


def test_pubchem_registry_entries_are_unavailable_placeholders():
    species_provider = get_providers(
        "species_identity",
        {"species_identity": ["pubchem_offline", "pubchem_online"]},
    )
    property_provider = get_providers(
        "properties",
        {"properties": ["pubchem_online"]},
    )[0]

    assert len(species_provider) == 2
    assert all(provider.available is False for provider in species_provider)
    assert property_provider.find_properties("CF4", ["mass_amu"]) == []


def test_prepare_does_not_fail_when_pubchem_is_listed_but_unavailable(tmp_path, monkeypatch):
    def fail_socket(*args, **kwargs):
        raise AssertionError("network access should not be attempted")

    monkeypatch.setattr(socket, "socket", fail_socket)
    input_path = tmp_path / "case.yaml"
    registry_root = tmp_path / "registry"
    output_dir = tmp_path / "prepared_registry"
    input_path.write_text(
        yaml.safe_dump(
            {
                "case": {"name": "pubchem-disabled-test"},
                "gases": ["CF4"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = prepare_case(
        input_path=input_path,
        registry_root=registry_root,
        source_profile={
            "schema_version": 1,
            "name": "pubchem_disabled_test",
            "species_identity": ["pubchem_offline", "pubchem_online"],
            "properties": ["pubchem_online"],
            "pubchem": {
                "enabled": False,
                "mode": "online",
                "cache_dir": "external_data/pubchem/cache",
            },
        },
        output_dir=output_dir,
    )

    report_payload = yaml.safe_load((output_dir / "prepare_report.yaml").read_text(encoding="utf-8"))
    assert report["registry_mutated"] is False
    assert report_payload["source_profile"]["name"] == "pubchem_disabled_test"
    assert not list(output_dir.rglob("species/*.yaml"))
