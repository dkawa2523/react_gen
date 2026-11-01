"""Native numerical quantities and coefficient-producing work have distinct scope."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import export, needs
from reactgen.case import Case, Conditions
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import assess_dataset, data_use, table_points
from reactgen.pipeline import analyze
from reactgen.records import NumericDataset, normalized_dataset
from reactgen.selection import DataSelection, QuantitySelection
from reactgen.units import EV_PER_K

REACTION = ReactionCandidate(
    "elastic",
    (Term("e"), Term("Ar@ground")),
    (Term("e"), Term("Ar@ground")),
    "electron",
    "elastic",
    "test",
    "test",
    0,
)


def dataset(identifier: str = "native", **changes: object) -> NumericDataset:
    document = {
        "id": identifier,
        "kind": "rate_coefficient",
        "form": "constant",
        "unit": "m3/s",
        "observable": "reaction_rate",
        "independent_variable": "gas_temperature",
        "parameters": {"value": 1e-15},
        "status": "reviewed",
        "validity": {"quantity": "gas_temperature", "minimum": 300, "maximum": 1000, "unit": "K"},
    }
    document.update(changes)
    return normalized_dataset(document)


@pytest.mark.parametrize(
    ("amplitude", "exponent", "activation", "reference", "expected"),
    [
        (1e300, 0.0, 1000 * EV_PER_K * 1000, 300.0, 5.07595889754946e-135),
        (1e-15, 2000.0, 2000 * 0.6931471805599453 * EV_PER_K * 1000, 500.0, 1e-15),
        (0.0, 2000.0, -1.0, 500.0, 0.0),
        (1e-15, 0.0, 0.0, 300.0, 1e-15),
    ],
)
def test_arrhenius_preserves_finite_final_values_and_zero_amplitude(
    amplitude, exponent, activation, reference, expected
):
    """Known limits of A (T/Tref)^b exp(-Ea/kBT), including cancelling factors."""
    record = dataset(
        form="arrhenius",
        parameters={"A": amplitude, "b": exponent, "Ea": activation},
        parameter_units={"A": "m3/s", "Ea": "eV"},
        reference_temperature_K=reference,
        reaction_order=2,
    )
    result = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(record,)), Conditions(gas_temperature_K=1000)
    )
    assert result.status == "coefficient"
    assert result.value == pytest.approx(expected, rel=1e-12, abs=0)


@pytest.mark.parametrize("activation_sign", [1, -1])
def test_unrepresentable_positive_rate_is_a_calculation_limit_after_roundtrip(
    tmp_path, activation_sign
):
    case = Case("arithmetic range", ("Ar",), Conditions(gas_temperature_K=1000))
    initial = analyze(case, EvidenceCatalog())
    reaction = next(
        item
        for item in initial.candidates.reactions.values()
        if item.family == "electron" and item.process == "elastic"
    )
    record = dataset(
        form="arrhenius",
        parameters={"A": 1e-15, "b": 0.0, "Ea": activation_sign * 1000 * EV_PER_K * 1000},
        parameter_units={"A": "m3/s", "Ea": "eV"},
        reference_temperature_K=300.0,
        reaction_order=2,
    )
    result = analyze(case, EvidenceCatalog(overlay_datasets={reaction.id: (record,)}))
    export.write(tmp_path, result)
    saved = export.read(tmp_path, verify_views=True)
    item = next(item for item in saved["reactions"] if item["id"] == reaction.id)
    assert item["data_use"]["status"] == "unavailable"
    assert item["data_use"]["value"] is None
    native = item["data_use"]["datasets"][0]
    assert native["status"] == "unavailable"
    assert native["blocking_causes"] == ["model_unsupported"]
    assert item["assessments"]["kinetics"]["verdict"] == "unknown"
    work = needs.build(saved, detail=True)["work_details"]
    assert any(
        item["responsibility"] == "external_models"
        and item["quantity"] == "numerical_evaluation_range"
        for item in work
    )


def curve(identifier: str = "curve", **changes: object) -> NumericDataset:
    return dataset(
        identifier,
        **(
            {
                "kind": "cross_section",
                "unit": "m2",
                "observable": "elastic",
                "independent_variable": "electron_energy",
                "parameters": {"value": 1e-20},
                "validity": {
                    "quantity": "electron_energy",
                    "minimum": 1,
                    "maximum": 10,
                    "unit": "eV",
                },
            }
            | changes
        ),
    )


def table(tmp_path: Path, content: str, **changes: object) -> NumericDataset:
    path = tmp_path / "table.csv"
    path.write_text(content, encoding="utf-8")
    return replace(
        dataset(**changes),
        form="table",
        asset=normalized_dataset(
            {"asset": path.name},
            base=tmp_path,
        ).asset,
    )


@pytest.mark.parametrize("energy", [None, 3, 100])
def test_native_curve_does_not_imply_a_point_query_or_distribution(energy) -> None:
    source = curve()
    conditions = Conditions(electron_energy_eV=energy)
    evidence = ReactionEvidence(overlay_datasets=(source,))
    native = assess_dataset(source, REACTION, evidence, conditions)
    assert native.status == "valid"
    assert native.kind == "cross_section"
    assert native.observable == "elastic"
    assert native.value is None
    assert native.requirements == ()
    assert "scalar point" in native.scope
    use = data_use(REACTION, evidence, conditions)
    assert use.status == "needs_input"
    assert use.value is None
    assert use.datasets == (native,)
    assert {item.responsibility for item in use.requirements} == {"external_models", "transforms"}
    assert use.required_inputs == ("electron_energy_distribution",)
    assert use.required_transforms == ("eedf_integration",)


def test_native_probability_and_surface_rate_have_independent_requirements() -> None:
    source = dataset(
        kind="sticking_coefficient",
        unit="1",
        observable="sticking_probability",
        parameters={"value": 0.4},
    )
    reaction = replace(REACTION, family="surface", surface="wall")
    evidence = ReactionEvidence(overlay_datasets=(source,))
    use = data_use(reaction, evidence, Conditions(gas_temperature_K=350))
    native = use.datasets[0]
    assert native.status == "valid"
    assert native.value == 0.4
    assert native.requirements == ()
    assert use.status == "needs_input"
    assert use.value == native.value
    assert {item.quantity for item in use.requirements} == {
        "surface_incident_flux_model",
        "surface_flux_conversion",
    }


def test_curve_conversion_work_does_not_obstruct_a_usable_coefficient() -> None:
    evidence = ReactionEvidence(overlay_datasets=(curve(), dataset()))
    use = data_use(REACTION, evidence, Conditions(gas_temperature_K=350))
    assert use.status == "coefficient"
    assert use.dataset_id == "native"
    assert use.requirements == ()
    assert {item.kind for item in use.datasets if item.status == "valid"} == {
        "rate_coefficient",
        "cross_section",
    }


def test_nonoverlapping_curve_domains_are_not_a_numerical_conflict() -> None:
    low = curve("low")
    high = curve(
        "high",
        validity={
            "quantity": "electron_energy",
            "minimum": 20,
            "maximum": 30,
            "unit": "eV",
        },
        parameters={"value": 2e-20},
    )
    for sources in ((low, high), (high, low)):
        use = data_use(
            REACTION, ReactionEvidence(overlay_datasets=sources), Conditions(electron_energy_eV=3)
        )
        assert use.status == "needs_input"
        assert use.disagreements == ()
        assert use.dataset_id == "high"


def test_curve_comparison_uses_only_common_numeric_and_source_domain(tmp_path) -> None:
    sources = []
    for identifier, contents in (
        ("low", "E,sigma\n1,1e-20\n5,2e-20\n10,2e-20\n"),
        ("high", "E,sigma\n5,2e-20\n10,2e-20\n15,9e-20\n"),
    ):
        path = tmp_path / f"{identifier}.csv"
        path.write_text(contents, encoding="utf-8")
        sources.append(
            replace(
                curve(identifier),
                form="table",
                validity=curve(
                    validity={
                        "quantity": "electron_energy",
                        "minimum": 1,
                        "maximum": 100,
                        "unit": "eV",
                    },
                ).validity,
                asset=normalized_dataset({"asset": path.name}, base=tmp_path).asset,
            )
        )
    use = data_use(
        REACTION,
        ReactionEvidence(overlay_datasets=tuple(sources)),
        Conditions(electron_energy_eV=15),
    )
    assert all(item.status == "valid" and item.value is None for item in use.datasets)
    assert use.disagreements == ()
    assert use.status == "needs_input"


def test_coefficient_purpose_keeps_native_transport_curves_and_uses_collision_quantity() -> None:
    elastic = curve("elastic")
    momentum = replace(curve("momentum"), observable="momentum_transfer")
    evidence = ReactionEvidence(overlay_datasets=(momentum, elastic))
    use = data_use(REACTION, evidence, Conditions())
    assert use.status == "needs_input"
    assert use.dataset_id == "elastic"
    assert use.disagreements == ()
    assert use.required_inputs == ("electron_energy_distribution",)
    assert all(item.status == "valid" for item in use.datasets)
    selected = data_use(
        REACTION,
        evidence,
        Conditions(),
        DataSelection(
            {
                "cross_section": QuantitySelection(record="momentum"),
            }
        ),
    )
    assert selected.dataset_id is None
    assert selected.status == "unavailable"
    assert selected.datasets[1].observable == "momentum_transfer"
    assert selected.required_inputs == ()
    assert selected.required_transforms == ()
    assert [
        (item.responsibility, item.target, item.quantity) for item in selected.requirements
    ] == [
        ("source_information", "momentum", "reaction_collision_cross_section"),
    ]


def test_source_preference_cannot_choose_a_different_observable_or_rate_law() -> None:
    elastic = curve("elastic")
    momentum = replace(curve("momentum"), observable="momentum_transfer", method="measured")
    use = data_use(
        REACTION,
        ReactionEvidence(overlay_datasets=(elastic, momentum)),
        Conditions(),
        DataSelection({"cross_section": QuantitySelection(methods=("measured",))}),
    )
    assert use.dataset_id == "elastic"
    assert use.required_inputs == ("electron_energy_distribution",)
    ordinary = dataset("ordinary")
    empirical = replace(dataset("empirical"), reaction_order=3, unit="m6/s", method="measured")
    use = data_use(
        REACTION,
        ReactionEvidence(overlay_datasets=(ordinary, empirical)),
        Conditions(gas_temperature_K=350),
        DataSelection({"rate_coefficient": QuantitySelection(methods=("measured",))}),
    )
    assert use.dataset_id is None
    assert use.required_inputs == ("rate_law_selection",)


@pytest.mark.parametrize("condition", [100, 1100])
def test_supplied_condition_outside_table_is_not_a_missing_input(tmp_path, condition) -> None:
    source = table(
        tmp_path,
        "T,k\n300,1e-15\n1000,2e-15\n",
        validity={
            "quantity": "gas_temperature",
            "maximum": 1200,
            "unit": "K",
        },
    )
    use = data_use(
        REACTION,
        ReactionEvidence(overlay_datasets=(source,)),
        Conditions(gas_temperature_K=condition),
    )
    assert use.status == "unavailable"
    assert use.datasets[0].status == "out_of_range"
    assert use.datasets[0].requirements == ()
    assert "table" in use.datasets[0].reason
    assert use.required_inputs == ()


def test_source_applicability_can_be_broader_than_the_numeric_table(tmp_path) -> None:
    source = table(
        tmp_path,
        "T,k\n300,1e-15\n1000,2e-15\n",
        validity={
            "quantity": "gas_temperature",
            "minimum": 100,
            "maximum": 1200,
            "unit": "K",
        },
    )
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(source,)), Conditions(gas_temperature_K=650)
    )
    assert use.status == "coefficient"
    assert use.value == pytest.approx(1.5e-15)


@pytest.mark.parametrize("first", ["300,bad", "bad,1e-15", "NaN,bad"])
def test_broken_first_numeric_row_cannot_be_discarded_as_a_header(tmp_path, first) -> None:
    source = table(
        tmp_path,
        f"{first}\n400,1e-15\n500,2e-15\n",
        validity={
            "quantity": "gas_temperature",
            "minimum": 400,
            "maximum": 500,
            "unit": "K",
        },
    )
    assert table_points(source) is None
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(source,)), Conditions(gas_temperature_K=450)
    )
    assert use.status == "unavailable"
    assert use.datasets[0].status == "invalid"
    assert use.datasets[0].requirements[0].responsibility == "source_review"


def test_native_missing_conditions_record_the_actual_input_boundary_once() -> None:
    source = dataset(
        form="arrhenius",
        parameters={"A": 1e-15, "b": 0, "Ea": 0},
        parameter_units={"Ea": "eV"},
        reference_temperature_K=300,
    )
    native = assess_dataset(source, REACTION, ReactionEvidence(), Conditions())
    assert native.status == "needs_input"
    assert len(native.requirements) == 1
    missing = native.requirements[0]
    assert (missing.responsibility, missing.target, missing.quantity) == (
        "user_inputs",
        "native",
        "conditions.gas_temperature_K",
    )
    assert native.required_inputs == ("gas_temperature",)


def test_applicability_source_gap_is_independent_of_user_condition() -> None:
    source = dataset(validity=None)
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(source,)), Conditions(gas_temperature_K=350)
    )
    assert use.status == "needs_input"
    assert [(item.responsibility, item.target, item.quantity) for item in use.requirements] == [
        ("source_information", "native", "dataset_applicability_conditions"),
    ]
    assert "user condition does not establish" in use.datasets[0].reason


def test_aggregate_requirements_keep_each_record_target() -> None:
    evidence = ReactionEvidence(overlay_datasets=(dataset("left"), dataset("right")))
    use = data_use(REACTION, evidence, Conditions())
    assert use.status == "needs_input"
    assert {(item.target, item.quantity) for item in use.requirements} == {
        ("left", "conditions.gas_temperature_K"),
        ("right", "conditions.gas_temperature_K"),
    }
    assert use.required_inputs == ("gas_temperature",)


def test_no_matched_record_identifies_missing_quantity_within_supplied_evidence() -> None:
    use = data_use(REACTION, ReactionEvidence(), Conditions())
    assert use.status == "unavailable"
    assert use.required_inputs == use.required_transforms == ()
    assert len(use.requirements) == 1
    missing = use.requirements[0]
    assert (missing.responsibility, missing.target, missing.quantity) == (
        "source_information",
        REACTION.id,
        "rate_coefficient",
    )
    assert "supplied evidence" in missing.reason


def test_identity_conflict_does_not_choose_a_quantity_from_input_order() -> None:
    coefficient, cross_section = dataset("same"), curve("same")
    first = data_use(
        REACTION,
        ReactionEvidence(overlay_datasets=(coefficient, cross_section)),
        Conditions(gas_temperature_K=350),
    )
    second = data_use(
        REACTION,
        ReactionEvidence(overlay_datasets=(cross_section, coefficient)),
        Conditions(gas_temperature_K=350),
    )
    assert first == second
    assert first.status == "conflict"
    native = first.datasets[0]
    assert native.kind is native.observable is None
    assert "no unambiguous native quantity" in native.scope
    assert native.requirements[0].quantity == "record_identity"


@pytest.mark.parametrize("extra", [float("nan"), float("inf"), -float("inf")])
def test_arrhenius_uses_only_its_declared_formula_parameters(extra: float) -> None:
    base = dataset(
        form="arrhenius",
        parameters={"A": 1e-15, "b": 0, "Ea": 0},
        parameter_units={"Ea": "eV"},
        reference_temperature_K=300,
    )
    changed = replace(base, params=base.params | {"unconsumed_source_column": extra})
    conditions = Conditions(gas_temperature_K=350)
    first = data_use(REACTION, ReactionEvidence(overlay_datasets=(base,)), conditions)
    second = data_use(REACTION, ReactionEvidence(overlay_datasets=(changed,)), conditions)
    assert second == first
    assert second.status == "coefficient"
    assert second.value == 1e-15
    assert "unconsumed_source_column" in changed.params


@pytest.mark.parametrize("parameter", ["A", "b", "Ea"])
def test_nonfinite_consumed_arrhenius_parameter_remains_invalid(parameter: str) -> None:
    source = dataset(
        form="arrhenius",
        parameters={"A": 1e-15, "b": 0, "Ea": 0} | {parameter: float("nan")},
        parameter_units={"Ea": "eV"},
        reference_temperature_K=300,
    )
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(source,)), Conditions(gas_temperature_K=350)
    )
    assert use.status == "unavailable"
    assert use.datasets[0].status == "invalid"
    assert "parameters must be finite" in use.datasets[0].reason


@pytest.mark.parametrize("condition", ["pressure_Pa", "bath_gas", "distribution", "population"])
def test_unsupported_applicability_conditions_are_not_partially_accepted(condition: str) -> None:
    with pytest.raises(ValueError, match=f"unsupported validity fields: {condition}"):
        dataset(
            validity={
                "quantity": "gas_temperature",
                "minimum": 300,
                "maximum": 500,
                "unit": "K",
                condition: "extra condition",
            }
        )


def test_legacy_physical_conditions_stay_unresolved_instead_of_becoming_applicable() -> None:
    source = dataset(
        validity={
            "quantity": "gas_temperature",
            "minimum": 300,
            "maximum": 500,
            "unit": "K",
            "conditions": {"electron_regime": "thermal"},
        }
    )
    use = data_use(
        REACTION, ReactionEvidence(overlay_datasets=(source,)), Conditions(gas_temperature_K=350)
    )
    assert use.status == "needs_input"
    assert use.value == 1e-15
    assert use.requirements[0].responsibility == "external_models"
    assert use.requirements[0].quantity == "dataset_applicability.electron_regime"
    assert use.required_inputs == ("dataset_applicability.electron_regime",)


def test_legacy_conditions_must_be_a_mapping() -> None:
    with pytest.raises(ValueError, match="validity.conditions must be a mapping"):
        dataset(
            validity={
                "quantity": "gas_temperature",
                "minimum": 300,
                "maximum": 500,
                "unit": "K",
                "conditions": "unknown",
            }
        )
