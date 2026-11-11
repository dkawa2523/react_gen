"""Physical applicability and legacy acquisition annotations stay distinct."""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from reactgen import export, yamlio
from reactgen.case import Case, Conditions, Limits
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import data_use
from reactgen.pipeline import analyze
from reactgen.records import (
    Validity,
    dataset_payload,
    normalized_dataset,
    scientific_dataset_content,
    scientific_datasets_equivalent,
)
from reactgen.registry import Registry

REACTION = ReactionCandidate(
    "elastic",
    (Term("Ar@ground", 2),),
    (Term("Ar@ground", 2),),
    "neutral",
    "elastic",
    "test",
    "test",
    0,
)


def document(**validity_fields: object) -> dict:
    return {
        "id": "rate",
        "kind": "rate_coefficient",
        "form": "constant",
        "unit": "m3/s",
        "observable": "reaction_rate",
        "independent_variable": "gas_temperature",
        "parameters": {"value": 1e-15},
        "status": "reviewed",
        "validity": {
            "quantity": "gas_temperature",
            "minimum": 300,
            "maximum": 500,
            "unit": "K",
        }
        | validity_fields,
    }


@pytest.mark.parametrize("annotation", ["method", "derivation"])
def test_legacy_acquisition_annotations_do_not_change_coefficient(annotation: str) -> None:
    raw = document(conditions={annotation: "original acquisition annotation"})
    record = normalized_dataset(raw)
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(record,)), Conditions(gas_temperature_K=350)
    )
    assert use.status == "coefficient"
    assert use.value == 1e-15
    assert use.requirements == ()
    assert record.validity is not None
    assert record.validity.unresolved_conditions == {}
    assert record.source_declaration["validity"]["conditions"] == raw["validity"]["conditions"]


@pytest.mark.parametrize("field", ["conditions", "unresolved_conditions"])
def test_physical_conditions_preserve_values_and_block_automatic_applicability(field: str) -> None:
    original = {"electron_regime": "thermal", "pressure": {"value": 1000, "unit": "Pa"}}
    raw = document(**{field: original})
    record = normalized_dataset(raw)
    original["pressure"]["value"] = 9999
    assert record.validity is not None
    assert record.validity.unresolved_conditions["pressure"] == {"value": 1000, "unit": "Pa"}
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(record,)), Conditions(gas_temperature_K=350)
    )
    assert use.status == "needs_input"
    assert use.value == 1e-15
    assert use.datasets[0].status == "needs_input"
    assert {item.quantity for item in use.requirements} == {
        "dataset_applicability.electron_regime",
        "dataset_applicability.pressure",
    }
    assert {item.responsibility for item in use.requirements} == {"external_models"}
    assert use.required_inputs == (
        "dataset_applicability.electron_regime",
        "dataset_applicability.pressure",
    )
    assert use.required_transforms == ()
    restored = normalized_dataset(dataset_payload(record))
    assert restored == record
    assert normalized_dataset(asdict(record)) == record


@pytest.mark.parametrize("conditions", [None, "thermal", [], {"": "thermal"}, {3: "thermal"}])
def test_typed_conditions_validate_mapping_and_names(conditions: object) -> None:
    with pytest.raises(ValueError, match="validity.unresolved_conditions must be a mapping"):
        Validity("gas_temperature", 300, 500, "K", conditions)  # type: ignore[arg-type]


def test_legacy_and_canonical_condition_conflict_fails_before_evaluation() -> None:
    with pytest.raises(ValueError, match="conflicting validity condition: electron_regime"):
        normalized_dataset(
            document(
                conditions={"electron_regime": "thermal"},
                unresolved_conditions={"electron_regime": "nonthermal"},
            )
        )


@pytest.mark.parametrize("same_scope", [False, True])
def test_value_comparison_requires_the_same_explicit_physical_scope(same_scope: bool) -> None:
    first = normalized_dataset(document(conditions={"electron_regime": "thermal"}))
    second = replace(
        normalized_dataset(
            document(conditions={"electron_regime": "thermal" if same_scope else "nonthermal"})
        ),
        id="another-rate",
        params={"value": 3e-15},
    )
    for offered in ((first, second), (second, first)):
        use = data_use(
            REACTION, ReactionEvidence(overlay_datasets=offered), Conditions(gas_temperature_K=350)
        )
        assert use.status == ("conflict" if same_scope else "needs_input")
        models = [item for item in use.requirements if item.responsibility == "external_models"]
        assert len(models) == 2
        assert [item.value for item in use.datasets] == [3e-15, 1e-15]


def test_empty_default_has_the_same_comparison_content_as_old_canonical_records() -> None:
    record = normalized_dataset(document())
    original = dataset_payload(record)
    current = deepcopy(original)
    current["validity"]["unresolved_conditions"] = {}
    assert "unresolved_conditions" not in original["validity"]
    assert scientific_dataset_content(current) == scientific_dataset_content(original)
    assert scientific_datasets_equivalent(current, original)
    assert current["validity"]["unresolved_conditions"] == {}


def test_existing_registry_legacy_conditions_are_preserved() -> None:
    registry = Registry.load(Path(__file__).parents[1] / "registry")
    records = [
        dataset for group in registry.channels.values() for row in group for dataset in row.datasets
    ]
    conditions = [
        dataset
        for dataset in records
        if isinstance(dataset.source_declaration, dict)
        and dataset.source_declaration.get("validity", {}).get("conditions")
    ]
    physical = next(
        dataset
        for dataset in conditions
        if "electron_regime" in dataset.source_declaration["validity"]["conditions"]
    )
    assert physical.validity is not None
    assert physical.validity.unresolved_conditions == {"electron_regime": "thermal"}
    assert all(normalized_dataset(dataset_payload(dataset)) == dataset for dataset in conditions)


def test_legacy_snapshot_condition_survives_saved_result_roundtrip(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot.yaml"
    record = document(conditions={"electron_regime": "thermal", "derivation": "original analysis"})
    record.update({"reaction": "Ar + Ar -> Ar + Ar", "type": "elastic"})
    snapshot.write_text(
        yamlio.dump({"snapshot_version": 1, "kind": "rate_coefficient", "records": [record]}),
        encoding="utf-8",
    )
    case = Case(
        "argon",
        ("Ar",),
        Conditions(gas_temperature_K=350),
        limits=Limits(max_atoms=1, max_depth=1),
    )
    catalog = EvidenceCatalog.load(Path(__file__).parents[1] / "registry", known=(snapshot,))
    result = analyze(case, catalog)
    export.write(tmp_path / "saved", result)
    restored = export.read(tmp_path / "saved", verify_views=True)
    target = next(row for row in restored["reactions"] if row["data_use"]["dataset_id"] == "rate")
    assert target["data_use"]["status"] == "needs_input"
    assert target["data_use"]["value"] == 1e-15
    offered = target["evidence"]["overlay_datasets"] + [
        dataset for row in target["evidence"]["records"] for dataset in row["datasets"]
    ]
    selected = next(row for row in offered if row["id"] == "rate")
    assert selected["validity"]["unresolved_conditions"] == {"electron_regime": "thermal"}
    raw_conditions = selected["source_declaration"]["validity"]["conditions"]
    assert raw_conditions == record["validity"]["conditions"]
