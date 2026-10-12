"""Numerical comparison needs a common rate law and overlapping applicability."""

from __future__ import annotations

from dataclasses import replace
from math import exp

import pytest

from reactgen.case import Conditions
from reactgen.evidence import ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import DataUse, data_use
from reactgen.records import NumericDataset, Uncertainty, normalized_dataset
from reactgen.units import EV_PER_K

REACTION = ReactionCandidate(
    "test",
    (Term("e"), Term("Ar@ground")),
    (Term("e"), Term("Ar@ground")),
    "electron",
    "elastic",
    "test",
    "test",
    0,
)


def _rate(dataset_id: str, value: float = 1e-15, **changes: object) -> NumericDataset:
    document = {
        "id": dataset_id,
        "kind": "rate_coefficient",
        "form": "constant",
        "unit": "m3/s",
        "independent_variable": "gas_temperature",
        "observable": "reaction_rate",
        "parameters": {"value": value},
        "validity": {"quantity": "gas_temperature", "minimum": 300, "maximum": 1000, "unit": "K"},
        "status": "reviewed",
    }
    document.update(changes)
    return normalized_dataset(document)


def _use(*datasets: NumericDataset, conditions: Conditions | None = None) -> DataUse:
    return data_use(
        REACTION, ReactionEvidence(overlay_datasets=datasets), conditions or Conditions()
    )


@pytest.mark.parametrize(("unit", "value"), [("m6/s", 1e-15), ("m6/s", 2e-15), ("cm6/s", 1e-3)])
def test_different_rate_orders_need_explicit_selection_regardless_of_magnitude(
    unit: str,
    value: float,
) -> None:
    elementary = _rate("elementary")
    empirical = _rate("empirical", value, reaction_order=3, unit=unit)
    first = _use(elementary, empirical, conditions=Conditions(gas_temperature_K=300))
    second = _use(empirical, elementary, conditions=Conditions(gas_temperature_K=300))
    assert first == second
    assert first.status == "needs_input"
    assert first.required_inputs == ("rate_law_selection",)
    assert first.dataset_id is None
    assert first.value is None
    assert {item.status for item in first.datasets} == {"valid"}
    assert {item.unit for item in first.datasets} == {"m3/s", "m6/s"}


@pytest.mark.parametrize("selected", ["elementary", "empirical"])
def test_preferred_source_can_choose_between_declared_rate_laws(selected: str) -> None:
    elementary = replace(_rate("elementary"), preferred=selected == "elementary")
    empirical = replace(
        _rate("empirical", reaction_order=3, unit="m6/s"),
        preferred=selected == "empirical",
    )
    result = _use(elementary, empirical, conditions=Conditions(gas_temperature_K=300))
    assert result.status == "coefficient"
    assert result.dataset_id == selected
    assert result.unit == ("m3/s" if selected == "elementary" else "m6/s")
    assert "explicitly preferred" in result.reason


def test_two_preferred_rate_laws_do_not_resolve_model_ambiguity() -> None:
    elementary = replace(_rate("elementary"), preferred=True)
    empirical = replace(_rate("empirical", reaction_order=3, unit="m6/s"), preferred=True)
    result = _use(elementary, empirical, conditions=Conditions(gas_temperature_K=300))
    assert result.status == "needs_input"
    assert result.required_inputs == ("rate_law_selection",)
    assert result.value is None


def test_out_of_range_rate_law_does_not_hide_the_applicable_coefficient() -> None:
    empirical = _rate(
        "empirical",
        reaction_order=3,
        unit="m6/s",
        validity={"quantity": "gas_temperature", "maximum": 250, "unit": "K"},
    )
    result = _use(_rate("elementary"), empirical, conditions=Conditions(gas_temperature_K=300))
    assert result.status == "coefficient"
    assert result.dataset_id == "elementary"
    assert {item.status for item in result.datasets} == {"valid", "out_of_range"}


def test_matching_explicit_and_elementary_orders_compare_after_unit_conversion() -> None:
    result = _use(
        _rate("elementary"),
        _rate("empirical", 1e-9, reaction_order=2, unit="cm3/s"),
        conditions=Conditions(gas_temperature_K=300),
    )
    assert result.status == "coefficient"
    assert result.value == pytest.approx(1e-15, rel=1e-12, abs=0)
    assert result.unit == "m3/s"
    assert "supplied conditions" in result.reason
    assert "equivalent" not in result.reason


def _separate_ranges() -> tuple[NumericDataset, NumericDataset]:
    return (
        _rate("low", validity={"quantity": "gas_temperature", "maximum": 300, "unit": "K"}),
        _rate("high", 2e-15, validity={"quantity": "gas_temperature", "minimum": 500, "unit": "K"}),
    )


def test_disjoint_one_sided_ranges_need_temperature_not_conflict() -> None:
    low, high = _separate_ranges()
    first, second = _use(low, high), _use(high, low)
    assert first == second
    assert first.status == "needs_input"
    assert first.required_inputs == ("gas_temperature",)
    assert first.dataset_id is None
    assert first.value is None
    assert {item.status for item in first.datasets} == {"needs_input"}


def test_temperature_can_resolve_rate_orders_in_separate_regimes() -> None:
    low, high = _separate_ranges()
    high = replace(high, reaction_order=3, unit="m6/s")
    missing = _use(low, high)
    assert missing.status == "needs_input"
    assert missing.required_inputs == ("gas_temperature",)
    assert missing.dataset_id is None
    specified = _use(low, high, conditions=Conditions(gas_temperature_K=600))
    assert specified.status == "coefficient"
    assert specified.dataset_id == "high"
    assert specified.unit == "m6/s"


@pytest.mark.parametrize(
    ("temperature", "selected", "status"),
    [
        (200, "low", "coefficient"),
        (300, "low", "coefficient"),
        (400, None, "unavailable"),
        (500, "high", "coefficient"),
        (600, "high", "coefficient"),
    ],
)
def test_one_sided_applicability_preserves_boundaries_and_the_gap(
    temperature: float,
    selected: str | None,
    status: str,
) -> None:
    result = _use(*_separate_ranges(), conditions=Conditions(gas_temperature_K=temperature))
    assert result.status == status
    assert result.dataset_id == selected
    assert result.value == ({"low": 1e-15, "high": 2e-15}.get(selected or ""))


@pytest.mark.parametrize("lower", [300, 200])
def test_overlapping_one_sided_ranges_keep_missing_temperature_when_values_conflict(
    lower: float,
) -> None:
    low = _rate("low", validity={"quantity": "gas_temperature", "maximum": 300, "unit": "K"})
    high = _rate(
        "high", 2e-15, validity={"quantity": "gas_temperature", "minimum": lower, "unit": "K"}
    )
    result = _use(low, high)
    assert result.status == "conflict"
    assert result.required_inputs == ("gas_temperature",)
    assert "checked points" in result.reason


def test_overlap_without_an_upper_bound_uses_finite_comparison_points() -> None:
    first = _rate("first", validity={"quantity": "gas_temperature", "minimum": 300, "unit": "K"})
    second = _rate(
        "second", 2e-15, validity={"quantity": "gas_temperature", "minimum": 500, "unit": "K"}
    )
    assert _use(first, second).status == "conflict"


def test_one_sided_temperature_ranges_are_converted_without_changing_quantity() -> None:
    first = _rate(
        "cold",
        independent_variable="electron_temperature",
        validity={"quantity": "electron_temperature", "maximum": 300, "unit": "K"},
    )
    second = _rate(
        "hot",
        2e-15,
        independent_variable="electron_temperature",
        validity={"quantity": "electron_temperature", "minimum": 500 * EV_PER_K, "unit": "eV"},
    )
    result = _use(first, second, conditions=Conditions(gas_temperature_K=300))
    assert result.status == "needs_input"
    assert result.required_inputs == ("electron_temperature",)
    specified = _use(first, second, conditions=Conditions(electron_temperature_eV=600 * EV_PER_K))
    assert specified.status == "coefficient"
    assert specified.dataset_id == "hot"


def test_finite_point_agreement_does_not_prove_continuous_domain_equivalence() -> None:
    constant = replace(_rate("constant"), uncertainty=Uncertainty(relative=0.5))
    peaked = replace(
        _rate("peaked"),
        form="arrhenius",
        params={"A": 1.6e-15 * exp(4), "b": -4, "Ea": 1800 * EV_PER_K},
        reference_temperature_K=450,
        parameter_units={"Ea": "eV"},
    )
    missing = _use(constant, peaked)
    assert missing.status == "needs_input"
    assert missing.dataset_id is None
    assert missing.value is None
    assert missing.required_inputs == ("gas_temperature",)
    assert "finite-point checks" in missing.reason
    assert "do not establish continuous-domain equivalence" in missing.reason
    peak = _use(constant, peaked, conditions=Conditions(gas_temperature_K=450))
    assert peak.status == "conflict"
    assert "supplied conditions" in peak.reason


def _pending_electron_rate(*, order: int = 3, preferred: bool = False) -> NumericDataset:
    return _rate(
        "electron-regime",
        reaction_order=order,
        unit="m6/s" if order == 3 else "m3/s",
        independent_variable="electron_temperature",
        validity={"quantity": "electron_temperature", "minimum": 0.1, "maximum": 10, "unit": "eV"},
        preferred=preferred,
    )


@pytest.mark.parametrize("order", [2, 3])
def test_an_applicable_rate_cannot_discard_a_source_with_unknown_applicability(order: int) -> None:
    known, pending = _rate("gas-regime"), _pending_electron_rate(order=order)
    inputs = Conditions(gas_temperature_K=300)
    first, second = _use(known, pending, conditions=inputs), _use(pending, known, conditions=inputs)
    assert first == second
    assert first.status == "needs_input"
    assert first.required_inputs == ("electron_temperature",)
    assert first.dataset_id is first.value is first.unit is None
    by_id = {item.dataset_id: item for item in first.datasets}
    assert by_id["gas-regime"].status == "valid"
    assert by_id["gas-regime"].value == pytest.approx(1e-15, rel=1e-12, abs=0)
    assert by_id["electron-regime"].status == "needs_input"


def test_conditions_can_exclude_a_pending_rate_law_or_reveal_selection_ambiguity() -> None:
    known, pending = _rate("gas-regime"), _pending_electron_rate()
    excluded = _use(
        known, pending, conditions=Conditions(gas_temperature_K=300, electron_temperature_eV=20)
    )
    assert excluded.status == "coefficient"
    assert excluded.dataset_id == "gas-regime"
    assert {item.status for item in excluded.datasets} == {"valid", "out_of_range"}
    both = _use(
        known, pending, conditions=Conditions(gas_temperature_K=300, electron_temperature_eV=1)
    )
    assert both.status == "needs_input"
    assert both.required_inputs == ("rate_law_selection",)
    assert both.dataset_id is both.value is None


@pytest.mark.parametrize("selected", ["known", "pending"])
def test_explicit_preference_retains_the_selected_source_application_requirements(
    selected: str,
) -> None:
    known = replace(_rate("gas-regime"), preferred=selected == "known")
    pending = _pending_electron_rate(preferred=selected == "pending")
    result = _use(known, pending, conditions=Conditions(gas_temperature_K=300))
    assert result.dataset_id == ("gas-regime" if selected == "known" else "electron-regime")
    assert result.status == ("coefficient" if selected == "known" else "needs_input")
    assert result.required_inputs == (() if selected == "known" else ("electron_temperature",))
    assert "explicitly preferred source" in result.reason


def test_two_preferences_do_not_discard_the_one_with_unknown_applicability() -> None:
    known = replace(_rate("gas-regime"), preferred=True)
    result = _use(
        known, _pending_electron_rate(preferred=True), conditions=Conditions(gas_temperature_K=300)
    )
    assert result.status == "needs_input"
    assert result.dataset_id is result.value is None
    assert result.required_inputs == ("electron_temperature",)


def test_missing_source_conditions_are_not_replaced_by_another_applicable_rate() -> None:
    pending = _rate("undeclared-range", validity=None)
    result = _use(_rate("known"), pending, conditions=Conditions(gas_temperature_K=300))
    assert result.status == "needs_input"
    assert result.required_inputs == ("dataset_applicability_conditions",)
    assert result.dataset_id is result.value is None


@pytest.mark.parametrize("order", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_declared_rate_order_is_retained_but_cannot_produce_a_coefficient(
    order: float,
) -> None:
    dataset = _rate("invalid-order", reaction_order=order)
    result = _use(dataset, conditions=Conditions(gas_temperature_K=300))
    assert result.status == "unavailable"
    assert result.datasets[0].status == "invalid"
    assert "reaction order" in result.datasets[0].reason
