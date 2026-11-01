"""Derived values retain quantity qualification and their complete input evidence."""

from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from math import isfinite
from pathlib import Path

import pytest

from reactgen import cli, derive, yamlio
from reactgen.evidence import EvidenceCatalog, registry_state_candidate
from reactgen.generate import candidates
from reactgen.records import (
    FormationReference,
    Property,
    RegistryState,
    SourceRef,
    Species,
    StateRecord,
    Uncertainty,
    normalized_property,
)
from reactgen.registry import Registry


def registry_of(*species):
    return Registry(Path("."), {item.id: item for item in species}, {}, {})


def point(quantity, value, unit, **kwargs):
    return Property(value, unit, tier="reviewed", review_scope=(quantity,), **kwargs)


def parent(**kwargs):
    properties = {
        "mass_amu": point("mass_amu", 40, "amu"),
        "enthalpy_formation_eV": point(
            "enthalpy_formation_eV",
            1,
            "eV",
            formation_reference=FormationReference(0, "standard_elements", 100000),
        ),
    }
    return Species("Ar", {"Ar": 1}, 0, frozenset(), phase="gas", properties=properties, **kwargs)


def child(prop, **kwargs):
    return Species(
        "Ar_4s",
        {"Ar": 1},
        0,
        frozenset(),
        state=RegistryState(kind="electronic", resolution="resolved", label="4s"),
        phase="gas",
        properties={"excitation_energy_eV": prop},
        **kwargs,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"status": "rejected"},
        {"status": "conflicting"},
        {"review_scope": ("polarizability_A3",)},
        {"tier": "imported"},
        {"qualifier": "upper bound"},
        {"value": -1},
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": None},
        {"unit": "m/s"},
    ],
)
def test_unusable_excitation_cannot_be_promoted_but_independent_mass_survives(change):
    level = replace(point("excitation_energy_eV", 2, "eV"), **change)
    result = derive.carried_from(parent(), level)
    assert set(result) == {"mass_amu"}
    if level.value is not None and (not isfinite(level.value) or level.value < 0):
        with pytest.raises(ValueError, match="finite and nonnegative"):
            child(level)
        return
    excited = child(level)
    registry = registry_of(parent(), excited)
    overlay = derive.overlay(registry)["properties"]
    assert set(overlay[registry_state_candidate(excited).id]) == {"mass_amu"}


def test_scalar_excitation_is_not_a_scientific_declaration():
    with pytest.raises(ValueError, match="Property record"):
        derive.carried_from(parent(), 2)  # type: ignore[arg-type]
    assert set(derive.carried_from(parent(), None)) == {"mass_amu"}


@pytest.mark.parametrize("quantity", ["mass_amu", "enthalpy_formation_eV"])
@pytest.mark.parametrize(
    "change",
    [
        {"status": "rejected"},
        {"review_scope": ("state_existence",)},
        {"tier": "imported"},
        {"qualifier": "estimated upper limit"},
    ],
)
def test_each_parent_quantity_keeps_its_own_qualification(quantity, change):
    ground = parent()
    properties = dict(ground.properties)
    properties[quantity] = replace(properties[quantity], **change)
    ground = replace(ground, properties=properties)
    actual = derive.carried_from(ground, point("excitation_energy_eV", 2, "eV"))
    assert quantity not in actual
    assert set(actual) == {"mass_amu", "enthalpy_formation_eV"} - {quantity}


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_stopped_parent_declaration_does_not_stop_active_independent_evidence(status):
    ground = parent(status=status)
    level = point("excitation_energy_eV", 2, "eV")
    assert derive.carried_from(ground, level) == {}
    active = StateRecord(
        "independent",
        registry_state_candidate(ground),
        properties=ground.properties,
        status="imported",
        tier="imported",
        review_scope=("state_existence",),
    )
    with_active = replace(ground, records=(active,))
    assert set(derive.carried_from(with_active, level)) == {"mass_amu", "enthalpy_formation_eV"}
    assert (
        derive.carried_from(replace(with_active, records=(replace(active, status=status),)), level)
        == {}
    )


def test_resolved_offset_preserves_full_inputs_without_inventing_uncertainty(tmp_path):
    ground = parent()
    level = point(
        "excitation_energy_eV",
        2,
        "eV",
        source="resolved level measurement",
        provenance=SourceRef(provider="example", record_id="level-2"),
        source_declaration={"source_row": {"energy": "2.000(4)"}, "conditions": "gas"},
        method="measured",
        uncertainty=Uncertainty(absolute=0.004),
        definition="energy above the identified ground state",
    )
    excited = child(level)
    result = derive.carried_from(ground, level)
    formed = result["enthalpy_formation_eV"]
    assert formed.value == 3
    assert formed.source_declaration["level_property"] == asdict(level)
    assert formed.source_declaration["parent_formation_properties"] == [
        asdict(ground.properties["enthalpy_formation_eV"])
    ]
    assert formed.uncertainty is None
    registry = registry_of(ground, excited)
    path = tmp_path / "derived.yaml"
    path.write_text(yamlio.dump(derive.overlay(registry)), encoding="utf-8")
    restored = EvidenceCatalog.load(None, path).state(registry_state_candidate(excited)).preferred
    assert restored is not None
    assert restored.properties["enthalpy_formation_eV"] == normalized_property(
        yamlio.load(yamlio.dump(asdict(formed)))
    )
    mass = restored.properties["mass_amu"]
    assert mass.source_declaration["parent_mass_properties"] == [
        yamlio.load(yamlio.dump(asdict(ground.properties["mass_amu"])))
    ]


def test_finite_temperature_parent_does_not_invent_an_excited_thermal_correction():
    ground = parent()
    formation = ground.properties["enthalpy_formation_eV"]
    ground = replace(
        ground,
        properties=ground.properties
        | {
            "enthalpy_formation_eV": replace(
                formation,
                formation_reference=FormationReference(298.15, "standard_elements", 100000),
            )
        },
    )
    assert set(derive.carried_from(ground, point("excitation_energy_eV", 2, "eV"))) == {"mass_amu"}


def test_atomic_mass_selection_is_qualified_and_conflict_is_order_independent():
    first = parent()
    imported = replace(first, id="Ar_other", properties={"mass_amu": Property(41, "amu")})
    registry = registry_of(first, imported)
    assert derive.element_masses(registry) == {"Ar": 40}
    opposing = replace(imported, properties={"mass_amu": point("mass_amu", 41, "amu")})
    for ordered in ((first, opposing), (opposing, first)):
        assert derive.element_masses(registry_of(*ordered)) == {}
    assert derive.element_masses(registry_of(replace(first, status="rejected"))) == {}


def test_composition_mass_retains_atomic_input_declarations():
    atom = parent()
    molecule = Species("Ar2", {"Ar": 2}, 0, frozenset(), phase="gas")
    registry = registry_of(atom, molecule)
    result = derive.overlay(registry)["properties"][registry_state_candidate(molecule).id][
        "mass_amu"
    ]
    assert result["value"] == 80
    assert result["source_declaration"]["atomic_mass_inputs"] == {
        "Ar": [{"species": "Ar", "property": asdict(atom.properties["mass_amu"])}]
    }
    assert result["status"] == "derived"
    assert result["method"] == "calculated"


def test_mass_arithmetic_has_no_source_selection_or_excitation_dependency():
    assert derive.mass_of({"Ar": 1}, 1, {"Ar": 40}) == pytest.approx(
        40 - derive.ELECTRON_MASS_AMU, abs=1e-6
    )
    assert derive.mass_of({"Ar": 1}, 0, {}) is None
    with pytest.raises(ValueError, match="positive atom counts"):
        derive.mass_of({"Ar": 1.5}, 0, {"Ar": 40})
    with pytest.raises(ValueError, match="positive atomic point masses"):
        derive.mass_of({"Ar": 1}, 0, {"Ar": float("inf")})


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_derive_same_file_retains_original_on_publish_failure(tmp_path, monkeypatch, failure):
    out = tmp_path / "overlay.yaml"
    before = b"properties: {}\n# existing source declarations\n"
    out.write_bytes(before)
    if failure == "write":
        original = cli.tempfile.NamedTemporaryFile

        @contextmanager
        def interrupted(**kwargs):
            with original(**kwargs) as stream:

                class BrokenStream:
                    name = stream.name

                    def write(self, content):
                        stream.write(content[:8])
                        raise OSError("interrupted output")

                yield BrokenStream()

        monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", interrupted)
    else:

        def interrupted(*args):
            raise OSError("interrupted replace")

        monkeypatch.setattr(cli.os, "replace", interrupted)
    registry = Path(__file__).parent / "fixtures" / "mini"
    assert (
        cli.main(["derive", "--registry", str(registry), "--overlay", str(out), "--out", str(out)])
        == 2
    )
    assert out.read_bytes() == before
    assert list(tmp_path.iterdir()) == [out]


@pytest.mark.parametrize("asset_state", ["valid", "declared_mismatch", "changed", "missing"])
def test_derive_to_another_directory_preserves_asset_identity_and_qualification(
    tmp_path, asset_state
):
    source_base, output_base = tmp_path / "source", tmp_path / "output"
    (source_base / "assets").mkdir(parents=True)
    (output_base / "assets").mkdir(parents=True)
    table = b"temperature_K,k_m3_s\n300,1e-15\n1000,1e-15\n"
    asset = source_base / "assets" / "rate.csv"
    if asset_state != "missing":
        asset.write_bytes(table)
    # A file with the old relative name at the destination must not be adopted.
    (output_base / "assets" / "rate.csv").write_bytes(b"unrelated output-side bytes")
    declared_asset = {"path": "assets/rate.csv"}
    if asset_state in {"declared_mismatch", "changed"}:
        declared_asset.update(
            sha256="0" * 64 if asset_state == "changed" else sha256(table).hexdigest(),
            declared_sha256="f" * 64 if asset_state == "declared_mismatch" else None,
        )
    reaction = next(
        item
        for item in candidates(("Ar",)).reactions.values()
        if item.family == "electron" and item.process == "elastic"
    )
    record = {
        "id": "preserved-rate",
        "kind": "rate_coefficient",
        "form": "table",
        "status": "reviewed",
        "unit": "m3/s",
        "observable": "reaction_rate",
        "independent_variable": "gas_temperature",
        "parameter_units": {"x": "K"},
        "asset": declared_asset,
        "validity": {"quantity": "gas_temperature", "minimum": 300, "maximum": 1000, "unit": "K"},
    }
    source_path, output_path = source_base / "overlay.yaml", output_base / "overlay.yaml"
    source_path.write_text(yamlio.dump({"datasets": {reaction.id: [record]}}), encoding="utf-8")
    before = EvidenceCatalog.load(None, overlay=source_path).overlay_datasets[reaction.id][0]
    registry = Path(__file__).parent / "fixtures" / "mini"
    assert (
        cli.main(
            [
                "derive",
                "--registry",
                str(registry),
                "--overlay",
                str(source_path),
                "--out",
                str(output_path),
            ]
        )
        == 0
    )
    after = EvidenceCatalog.load(None, overlay=output_path).overlay_datasets[reaction.id][0]
    assert before.asset is not None
    assert after.asset is not None
    assert after.id == before.id
    assert after.asset.sha256 == before.asset.sha256
    assert after.asset.declared_sha256 == before.asset.declared_sha256
    assert after.asset.integrity_ok == before.asset.integrity_ok
    assert after.asset.integrity_ok == (asset_state == "valid")
    assert (output_base / after.asset.reference).resolve() == asset.resolve()
    assert after.source_declaration == before.source_declaration
    assert source_path.read_text(encoding="utf-8") == yamlio.dump(
        {"datasets": {reaction.id: [record]}}
    )
