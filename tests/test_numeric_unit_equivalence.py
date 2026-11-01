"""Unit copies of one known scalar model retain one scientific record identity."""

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import data_use
from reactgen.pipeline import analyze
from reactgen.records import (
    NumericDataset,
    dataset_payload,
    normalized_dataset,
    scientific_dataset_content,
    scientific_datasets_equivalent,
)
from reactgen.registry import Registry
from reactgen.units import EV_PER_K, JOULE_PER_EV, numerical_unit, numerical_unit_basis

REACTION = ReactionCandidate(
    "test",
    (Term("Ar@ground", 2),),
    (Term("Ar@ground", 2),),
    "neutral",
    "elastic",
    "test",
    "test",
    0,
)


def document(**changes: object) -> dict:
    result = {
        "id": "same",
        "kind": "rate_coefficient",
        "form": "constant",
        "unit": "m3/s",
        "observable": "reaction_rate",
        "reaction_order": 2,
        "parameters": {"value": 1e-15},
        "independent_variable": "electron_temperature",
        "status": "reviewed",
        "validity": {
            "quantity": "electron_temperature",
            "minimum": 300,
            "maximum": 500,
            "unit": "K",
        },
        "uncertainty": {"absolute": 1e-16},
        "source": {"provider": "laboratory", "record_id": "same"},
    }
    result.update(changes)
    return result


def copies() -> tuple[NumericDataset, NumericDataset]:
    first = normalized_dataset(document())
    second = normalized_dataset(
        document(
            unit="cm3/s",
            parameters={"value": 1e-9},
            uncertainty={"absolute": 1e-10},
            validity={
                "quantity": "electron_temperature",
                "minimum": 300 * EV_PER_K,
                "maximum": 500 * EV_PER_K,
                "unit": "eV",
            },
        )
    )
    return first, second


def test_equivalent_numeric_units_do_not_mutate_declarations_or_fingerprints() -> None:
    first, second = copies()
    held = deepcopy((dataset_payload(first), dataset_payload(second)))
    assert scientific_dataset_content(first) != scientific_dataset_content(second)
    for one, two in (
        (first, second),
        (second, first),
        (dataset_payload(first), dataset_payload(second)),
        (asdict(first), asdict(second)),
    ):
        assert scientific_datasets_equivalent(one, two)
    assert (dataset_payload(first), dataset_payload(second)) == held
    for records in ((first, second), (second, first)):
        use = data_use(
            REACTION,
            ReactionEvidence(overlay_datasets=records),
            Conditions(electron_temperature_eV=350 * EV_PER_K),
        )
        assert use.status == "coefficient"
        assert use.disagreements == ()
        assert use.value == pytest.approx(1e-15, rel=1e-12, abs=0)
        assert len(use.datasets) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"observable": "other"},
        {"reaction_order": 3},
        {"review_scope": ("other",)},
        {"channel_scope": "total_process"},
        {"tier": "imported"},
        {"method": "estimated"},
    ],
)
def test_unit_equivalence_does_not_erase_other_scientific_meaning(change) -> None:
    first, second = copies()
    assert not scientific_datasets_equivalent(first, replace(second, **change))


def test_same_unit_small_change_is_not_conversion_roundoff() -> None:
    first, _ = copies()
    second = replace(first, params={"value": 1e-15 * (1 + 5e-13)})
    assert not scientific_datasets_equivalent(first, second)
    alias = replace(first, unit="m^3/s")
    assert scientific_datasets_equivalent(first, alias)
    assert not scientific_datasets_equivalent(first, replace(second, unit="m^3/s"))


def test_underflow_does_not_make_a_nonzero_unit_copy_equivalent_to_zero() -> None:
    first = normalized_dataset(document(parameters={"value": 0}, uncertainty=None))
    second = normalized_dataset(
        document(unit="cm3/s", parameters={"value": 1e-320}, uncertainty=None)
    )
    assert not scientific_datasets_equivalent(first, second)


def test_unknown_and_contradictory_source_fields_are_retained() -> None:
    first, second = copies()
    raw = deepcopy(second.source_declaration)
    raw["conditions_note"] = "unknown but scientifically relevant condition"
    assert not scientific_datasets_equivalent(first, replace(second, source_declaration=raw))
    raw = deepcopy(second.source_declaration)
    raw["parameters"]["value"] = 42
    assert not scientific_datasets_equivalent(first, replace(second, source_declaration=raw))
    raw["parameters"]["value"] = 1e-9
    raw["validity"]["minimum"] = 42
    assert not scientific_datasets_equivalent(first, replace(second, source_declaration=raw))


def test_matching_one_original_alias_does_not_erase_a_contradictory_alias_unit() -> None:
    first, second = copies()
    left, right = deepcopy(first.source_declaration), deepcopy(second.source_declaration)
    left["params"] = right["params"] = {"value": 42}
    assert not scientific_datasets_equivalent(
        replace(first, source_declaration=left),
        replace(second, source_declaration=right),
    )


def test_arrhenius_amplitude_and_explicit_activation_energy_units_compare() -> None:
    base = document(
        form="arrhenius",
        parameters={"A": 1e-15, "b": 0.5, "Ea": 0.1},
        parameter_units={"Ea": "eV"},
        reference_temperature_K=300,
    )
    first = normalized_dataset(base)
    second = normalized_dataset(
        base
        | {
            "unit": "cm3/s",
            "parameters": {"A": 1e-9, "b": 0.5, "Ea": 0.1 * JOULE_PER_EV},
            "parameter_units": {"Ea": "J"},
            "uncertainty": {"absolute": 1e-10},
        }
    )
    assert scientific_datasets_equivalent(first, second)
    assert not scientific_datasets_equivalent(
        first, replace(second, params=second.params | {"b": 1})
    )


def test_absolute_uncertainty_import_supports_the_declared_numeric_quantity() -> None:
    imported = normalized_dataset(
        document(uncertainty={"absolute": 1e-10, "unit": "cm3/s", "note": "measured"})
    )
    assert imported.uncertainty is not None
    assert imported.uncertainty.note == "measured"
    assert imported.uncertainty.absolute == pytest.approx(1e-16, rel=1e-12, abs=0)
    assert imported.source_declaration["uncertainty"]["unit"] == "cm3/s"
    parent_copy = normalized_dataset(document(uncertainty={"absolute": 1e-16, "note": "measured"}))
    assert scientific_datasets_equivalent(imported, parent_copy)
    with pytest.raises(ValueError, match="absolute uncertainty unit"):
        normalized_dataset(document(uncertainty={"absolute": 1, "unit": "m2"}))


def test_unit_basis_does_not_assign_rate_order_or_accept_unrepresentable_scale() -> None:
    assert numerical_unit_basis("m3/s", "rate_coefficient") == ("m3/s", 1)
    assert numerical_unit("m3/s", "rate_coefficient", None) is None
    assert numerical_unit("m3/s", "rate_coefficient", 3) is None
    for unit in ("1/s", "s-1", "m0/s", "cm0/s"):
        assert numerical_unit_basis(unit, "rate_coefficient") == ("s-1", 1)
        assert numerical_unit(unit, "rate_coefficient", 1) == ("s-1", 1)
    assert numerical_unit_basis("cm10000/s", "rate_coefficient") is None
    assert numerical_unit_basis("m" + "9" * 400 + "/s", "rate_coefficient") is None
    assert numerical_unit("m3.0000003/s", "rate_coefficient", 2) is None
    assert numerical_unit("m1.5000001/s", "rate_coefficient", 1 + 1.5000001 / 3) is not None


def test_table_and_unknown_model_unit_equivalence_are_not_inferred() -> None:
    first, second = copies()
    for form in ("table", "unknown_model"):
        assert not scientific_datasets_equivalent(
            replace(first, form=form), replace(second, form=form)
        )


def test_unknown_quantity_does_not_inherit_activation_energy_semantics() -> None:
    first = normalized_dataset(
        document(
            kind="unknown_quantity",
            form="arrhenius",
            parameters={"A": 1, "b": 0, "Ea": 1},
            parameter_units={"Ea": "eV"},
            reference_temperature_K=300,
        )
    )
    second = replace(first, params=first.params | {"Ea": JOULE_PER_EV}, parameter_units={"Ea": "J"})
    assert not scientific_datasets_equivalent(first, second)


def write(path: Path, content: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(content), encoding="utf-8")
    return path


def test_numeric_unit_copies_survive_snapshot_ingest_adopt_and_saved_result(tmp_path) -> None:
    root = tmp_path / "registry"
    write(root / "species" / "Ar.yaml", {"id": "Ar", "composition": {"Ar": 1}, "phase": "gas"})
    write(
        root / "reactions" / "neutral" / "pair.yaml",
        {
            "pair": {"family": "neutral", "projectile": "Ar", "target": "Ar"},
            "channels": [
                {"id": "elastic", "type": "elastic", "products": [{"species": "Ar", "n": 2}]}
            ],
        },
    )
    case = Case("argon", ("Ar",), Conditions(electron_temperature_eV=350 * EV_PER_K))
    export.write(tmp_path / "bundle", analyze(case, EvidenceCatalog.load(root)))
    original, converted = copies()
    overlay = tmp_path / "overlay.yaml"
    for index, source in enumerate((original, converted)):
        record = dataset_payload(source) | {"reaction": "Ar + Ar -> Ar + Ar", "type": "elastic"}
        snapshot = write(
            tmp_path / f"snapshot{index}.yaml",
            {
                "snapshot_version": 1,
                "kind": "rate_coefficient",
                "records": [record],
            },
        )
        assert ingest.ingest(snapshot, tmp_path / "bundle", overlay).accepted == 1
    assert adopt.adopt(overlay, root).values > 0
    records = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets
    assert len(records) == 2
    assert {item.unit for item in records} == {"m3/s", "cm3/s"}
    result = analyze(case, EvidenceCatalog.load(root))
    export.write(tmp_path / "saved", result)
    stored = export.read(tmp_path / "saved", verify_views=True)
    target = next(item for item in stored["reactions"] if item["data_use"]["dataset_id"] == "same")
    assert target["data_use"]["status"] == "coefficient"
    assert len(target["evidence"]["records"][0]["datasets"]) == 2
    assert adopt.adopt(overlay, root).values == 0
