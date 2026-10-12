"""Loading independent state declarations must preserve their scientific scope."""

from pathlib import Path

import pytest

from reactgen import derive, yamlio
from reactgen.assessment import assess_state
from reactgen.chemistry import parse_state_id
from reactgen.evidence import EvidenceCatalog, registry_state_candidate, snapshot_state
from reactgen.model import CandidateSet
from reactgen.registry import Registry


def write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


def test_overlay_does_not_replace_a_competing_registry_existence_declaration(tmp_path) -> None:
    root = tmp_path / "registry"
    write(
        root / "species" / "F.yaml",
        {
            "id": "F",
            "composition": {"F": 1},
            "phase": "gas",
            "state": {
                "existence": "unbound",
                "existence_source": "synthetic negative",
                "status": "reviewed",
            },
        },
    )
    overlay = write(
        tmp_path / "overlay.yaml",
        {
            "states": {
                "F@ground": {
                    "existence": "confirmed",
                    "existence_source": "synthetic positive",
                    "status": "reviewed",
                    "phase": "gas",
                }
            }
        },
    )
    candidate = parse_state_id("F@ground")
    assert candidate is not None
    for catalog in (
        EvidenceCatalog.load(root, overlay),
        EvidenceCatalog.load_paths((root, overlay)),
        EvidenceCatalog.load_paths((overlay, root)),
    ):
        evidence = catalog.state(candidate)
        assert evidence.match == "exact"
        assert (
            assess_state(
                candidate, evidence, CandidateSet(states={candidate.id: candidate})
            ).verdict
            == "unknown"
        )
        assert {record.existence for record in evidence.records} == {"confirmed", "unbound"}


def test_overlay_state_attributes_and_independent_energy_quality_are_preserved(tmp_path) -> None:
    overlay = write(
        tmp_path / "overlay.yaml",
        {
            "states": {
                "Ar@ground": {
                    "phase": "gas",
                    "existence": "confirmed",
                    "existence_source": "synthetic identity",
                    "status": "reviewed",
                    "source": {"citation": "individual state source"},
                    "configuration": "synthetic configuration",
                    "term": "synthetic term",
                    "J": "0",
                    "parity": "even",
                    "degeneracy": 1,
                    "lifetime_s": 10,
                    "excitation_energy_eV": 0,
                }
            },
            "properties": {
                "Ar@ground": {
                    "excitation_energy_eV": {
                        "value": 0,
                        "unit": "eV",
                        "source": "independent energy source",
                        "evidence_tier": "imported",
                    }
                }
            },
        },
    )
    record = EvidenceCatalog.load(None, overlay).state_records[0]
    assert record.configuration == "synthetic configuration"
    assert (record.term, record.j, record.parity, record.degeneracy, record.lifetime_s) == (
        "synthetic term",
        "0",
        "even",
        1,
        10,
    )
    assert record.source["citation"] == "individual state source"
    assert record.properties["excitation_energy_eV"].tier == "imported"
    assert record.properties["excitation_energy_eV"].source == "independent energy source"


@pytest.mark.parametrize("value", [True, "not numeric"])
def test_snapshot_numeric_state_attributes_are_format_checked(value) -> None:
    with pytest.raises(ValueError, match="numeric"):
        snapshot_state({"species": "Ar", "phase": "gas", "lifetime_s": value}, {})


@pytest.mark.parametrize("value", [True, "not numeric"])
def test_registry_numeric_state_attributes_are_format_checked(tmp_path, value) -> None:
    root = tmp_path / "registry"
    write(
        root / "species" / "Ar.yaml",
        {"id": "Ar", "composition": {"Ar": 1}, "state": {"lifetime_s": value}},
    )
    with pytest.raises(ValueError, match="numeric"):
        Registry.load(root)


def test_derived_overlay_uses_the_full_state_identity(tmp_path) -> None:
    root = tmp_path / "registry"
    write(
        root / "species" / "Ar.yaml",
        {
            "id": "Ar",
            "composition": {"Ar": 1},
            "phase": "gas",
            "properties": {"mass_amu": {"value": 40, "unit": "amu"}},
        },
    )
    write(
        root / "species" / "level.yaml",
        {
            "id": "Ar_4s",
            "composition": {"Ar": 1},
            "phase": "gas",
            "state": {"kind": "electronic", "resolution": "lumped", "label": "4s"},
        },
    )
    registry = Registry.load(root)
    expected = registry_state_candidate(registry.species["Ar_4s"])
    properties = derive.overlay(registry)["properties"]
    assert expected.id in properties
    assert "Ar_4s" not in properties
    overlay = write(tmp_path / "derived.yaml", {"properties": properties})
    assert EvidenceCatalog.load(None, overlay).state(expected).match == "exact"
