"""Source requests select assessed numbers without changing scientific qualification."""

from __future__ import annotations

from dataclasses import replace

import pytest

from reactgen.case import Case, Conditions
from reactgen.evidence import ReactionEvidence
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import DataUse, data_use
from reactgen.records import NumericDataset, normalized_dataset
from reactgen.selection import DataSelection, QuantitySelection

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


def _dataset(
    identifier: str,
    value: float = 1e-15,
    *,
    kind: str = "rate_coefficient",
    provider: str | None = "provider-a",
    collection: str | None = "collection-a",
    method: str = "measured",
    **changes: object,
) -> NumericDataset:
    axis = "electron_energy" if kind == "cross_section" else "gas_temperature"
    document = {
        "id": identifier,
        "kind": kind,
        "representation": "constant",
        "unit": {"rate_coefficient": "m3/s", "cross_section": "m2", "sticking_coefficient": "1"}[
            kind
        ],
        "independent_variable": axis,
        "observable": {
            "rate_coefficient": "reaction_rate",
            "cross_section": "elastic",
            "sticking_coefficient": "sticking_probability",
        }[kind],
        "parameters": {"value": value},
        "validity": {
            "quantity": axis,
            "minimum": 0 if kind == "cross_section" else 300,
            "maximum": 100 if kind == "cross_section" else 1000,
            "unit": "eV" if kind == "cross_section" else "K",
        },
        "source": {"provider": provider, "collection": collection},
        "method": method,
        "status": "reviewed",
    }
    document.update(changes)
    return normalized_dataset(document)


def _selection(kind: str = "rate_coefficient", **values: object) -> DataSelection:
    return DataSelection.from_document({"quantities": {kind: values}})


def _use(
    *datasets: NumericDataset,
    selection: DataSelection | None = None,
    conditions: Conditions | None = None,
    reaction: ReactionCandidate = REACTION,
) -> DataUse:
    return data_use(
        reaction,
        ReactionEvidence(overlay_datasets=datasets),
        conditions or Conditions(gas_temperature_K=350),
        selection,
    )


def test_case_round_trip_preserves_analysis_request_and_keeps_conditions_separate() -> None:
    document = {
        "gases": ["Ar"],
        "conditions": {"gas_temperature_K": 350},
        "data_selection": {
            "quantities": {
                "rate_coefficient": {
                    "mode": "prefer",
                    "methods": ["evaluated", "measured"],
                    "providers": ["internal_measurements"],
                },
                "cross_section": {
                    "mode": "only",
                    "collections": ["collection-a"],
                    "record": "curve",
                },
            }
        },
    }
    case = Case.from_document(document)
    assert Case.from_document(case.document()) == case
    assert case.document()["data_selection"] == document["data_selection"]
    assert case.conditions == Conditions(gas_temperature_K=350)
    assert "data_selection" not in Case("plain", ("Ar",)).document()


@pytest.mark.parametrize(
    "policy_document",
    [
        {"evidence": {"state_identity": {"mode": "prefer"}}},
        {"quantities": {"formation_enthalpy": {"mode": "prefer"}}},
        {"quantities": {"thermo": {"mode": "prefer"}}},
        {"quantities": {"rate_coefficient": {"mode": "first"}}},
        {"quantities": {"rate_coefficient": {"methods": ["experimental"]}}},
        {"quantities": {"rate_coefficient": {"providers": "provider-a"}}},
        {"quantities": {"rate_coefficient": {"providers": ["provider-a", "provider-a"]}}},
        {"quantities": {"rate_coefficient": {"providers": [""]}}},
        {"quantities": {"rate_coefficient": {"record": ""}}},
        {"quantities": {"rate_coefficient": {"record": 12}}},
        {"quantities": {"rate_coefficient": {"mode": "only"}}},
        {"quantities": {"rate_coefficient": {"priority": 1}}},
        {"quantities": []},
    ],
)
def test_unsupported_or_malformed_selection_is_an_input_error(policy_document: object) -> None:
    with pytest.raises(ValueError, match="selection"):
        Case.from_document({"gases": ["Ar"], "data_selection": policy_document})


def test_direct_api_requires_validated_selection_types() -> None:
    with pytest.raises(ValueError, match="validated DataSelection"):
        Case("bad", ("Ar",), data_selection={})
    with pytest.raises(ValueError, match="validated QuantitySelection"):
        DataSelection({"rate_coefficient": {"mode": "prefer"}})
    with pytest.raises(ValueError, match="validated DataSelection"):
        _use(_dataset("rate"), selection={"quantities": {}})


def test_method_provider_collection_priorities_are_lexicographic() -> None:
    records = [
        _dataset("measured", provider="first", method="measured"),
        _dataset("evaluated-provider", provider="first", method="evaluated", collection="last"),
        _dataset("evaluated-collection", provider="first", method="evaluated", collection="first"),
        _dataset(
            "evaluated-other-provider", provider="last", method="evaluated", collection="first"
        ),
    ]
    request = _selection(
        methods=["evaluated", "measured"],
        providers=["first", "last"],
        collections=["first", "last"],
    )
    first = _use(*records, selection=request)
    second = _use(*reversed(records), selection=request)
    assert first == second
    assert first.dataset_id == "evaluated-collection"
    assert first.selection == request.document()
    assert len(first.datasets) == 4


def test_omitted_axes_do_not_rank_or_exclude_sources() -> None:
    measured = _dataset("measured", value=2e-15, provider="target", method="measured")
    evaluated = _dataset("evaluated", provider="other", method="evaluated")
    result = _use(measured, evaluated, selection=_selection(providers=["target"]))
    assert result.status == "coefficient"
    assert result.dataset_id == "measured"
    assert result.disagreements == ("evaluated",)


def test_unlisted_sources_share_one_fallback_rank() -> None:
    left = _dataset("a", provider="fallback-a")
    right = _dataset("z", value=2e-15, provider="fallback-z")
    result = _use(left, right, selection=_selection(providers=["unavailable-preference"]))
    assert result.status == "conflict"
    assert result.dataset_id is result.value is None
    assert result.disagreements == ("a", "z")
    assert "fallback used for providers" in result.reason


def test_only_is_an_allowed_set_without_priority_from_list_order() -> None:
    records = [
        _dataset("a", provider="provider-a"),
        _dataset("b", value=2e-15, provider="provider-b"),
    ]
    first = _use(
        *records, selection=_selection(mode="only", providers=["provider-a", "provider-b"])
    )
    second = _use(
        *records, selection=_selection(mode="only", providers=["provider-b", "provider-a"])
    )
    assert first.status == second.status == "conflict"
    assert first.value is second.value is None


def test_only_excludes_unspecified_providers_without_discarding_their_assessments() -> None:
    result = _use(
        _dataset("outside", provider="outside", value=2e-15),
        _dataset("inside"),
        selection=_selection(mode="only", providers=["provider-a"]),
    )
    assert result.dataset_id == "inside"
    assert result.disagreements == ("outside",)
    assert {item.dataset_id for item in result.datasets} == {"inside", "outside"}


def test_only_without_offered_records_returns_unavailable_and_keeps_the_request() -> None:
    request = _selection(mode="only", providers=["missing"])
    result = _use(_dataset("rate"), selection=request)
    assert result.status == "unavailable"
    assert result.dataset_id is result.value is None
    assert result.selection == request.document()
    assert "no eligible record satisfies the only request" in result.reason


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"status": "imported"}, "unreviewed"),
        ({"unit": "s-1"}, "invalid"),
        ({"channel_scope": "total_process"}, "invalid"),
        (
            {"validity": {"quantity": "gas_temperature", "maximum": 300, "unit": "K"}},
            "out_of_range",
        ),
    ],
)
def test_prefer_evaluates_qualification_and_applicability_before_fallback(
    changes: dict, status: str
) -> None:
    preferred = _dataset("preferred", provider="target", **changes)
    fallback = _dataset("fallback", provider="fallback")
    result = _use(preferred, fallback, selection=_selection(providers=["target"]))
    assert result.dataset_id == "fallback"
    assert result.status == "coefficient"
    assert {item.dataset_id: item.status for item in result.datasets}["preferred"] == status
    assert "fallback used for providers" in result.reason


def test_preferred_source_missing_conditions_is_not_replaced_by_a_ready_fallback() -> None:
    requested = _dataset(
        "requested",
        provider="target",
        independent_variable="electron_temperature",
        validity={"quantity": "electron_temperature", "minimum": 0.1, "maximum": 10, "unit": "eV"},
    )
    result = _use(
        requested,
        _dataset("fallback", provider="fallback"),
        selection=_selection(providers=["target"]),
    )
    assert result.status == "needs_input"
    assert result.dataset_id == "requested"
    assert result.required_inputs == ("electron_temperature",)
    assert "fallback used" not in result.reason


def test_same_rank_missing_conditions_remain_unresolved() -> None:
    pending = _dataset("pending", validity=None)
    result = _use(_dataset("ready"), pending, selection=_selection(providers=["provider-a"]))
    assert result.status == "needs_input"
    assert result.dataset_id is result.value is None
    assert result.required_inputs == ("dataset_applicability_conditions",)


def test_record_selection_keeps_other_qualified_disagreement() -> None:
    result = _use(_dataset("a"), _dataset("b", value=2e-15), selection=_selection(record="b"))
    assert result.status == "coefficient"
    assert result.dataset_id == "b"
    assert result.value == 2e-15
    assert result.disagreements == ("a",)
    assert "requested record 'b'" in result.reason


@pytest.mark.parametrize("changes", [{"status": "imported"}, {"channel_scope": "total_process"}])
def test_record_selection_cannot_bypass_review_or_scope_and_does_not_substitute(
    changes: dict,
) -> None:
    result = _use(
        _dataset("requested", **changes),
        _dataset("fallback"),
        selection=_selection(record="requested"),
    )
    assert result.status == "unavailable"
    assert result.dataset_id is result.value is None
    assert "requested record 'requested' is unavailable or inapplicable" in result.reason


def test_absent_record_is_unavailable_without_fallback() -> None:
    result = _use(_dataset("offered"), selection=_selection(record="missing"))
    assert result.status == "unavailable"
    assert result.dataset_id is None


def test_record_must_describe_the_requested_quantity() -> None:
    with pytest.raises(ValueError, match="another quantity"):
        _use(_dataset("curve", kind="cross_section"), selection=_selection(record="curve"))


def test_record_must_obey_only_restrictions() -> None:
    with pytest.raises(ValueError, match="contradicts only restrictions"):
        _use(
            _dataset("rate", provider="other"),
            selection=_selection(mode="only", providers=["target"], record="rate"),
        )
    result = _use(_dataset("rate"), selection=_selection(mode="only", record="rate"))
    assert result.dataset_id == "rate"


def test_record_selection_does_not_resolve_a_duplicate_id_conflict() -> None:
    result = _use(
        _dataset("same"), _dataset("same", value=2e-15), selection=_selection(record="same")
    )
    assert result.status == "conflict"
    assert result.dataset_id is result.value is None
    assert result.disagreements == ("same",)


def test_new_request_overrides_data_preferred_only_for_its_quantity() -> None:
    records = [_dataset("legacy", preferred=True), _dataset("requested", provider="target")]
    legacy = _use(*records)
    requested = _use(*records, selection=_selection(providers=["target"]))
    assert legacy.dataset_id == "legacy"
    assert "deprecated" in legacy.reason
    assert "migrate to data_selection" in legacy.reason
    assert requested.dataset_id == "requested"
    assert "deprecated" not in requested.reason


def test_equal_values_have_a_stable_representative_after_unit_conversion() -> None:
    first = _dataset("a", unit="cm3/s", value=1e-9)
    second = _dataset("z")
    result = _use(first, second, selection=_selection(providers=["provider-a"]))
    assert result.dataset_id == "a"
    assert result.value == pytest.approx(1e-15, rel=1e-12, abs=0)
    assert result.unit == "m3/s"
    assert result.disagreements == ()


@pytest.mark.parametrize("kind", ["cross_section", "sticking_coefficient"])
def test_other_numeric_quantities_use_the_request_and_keep_conversion_requirements(
    kind: str,
) -> None:
    reaction = REACTION
    if kind == "sticking_coefficient":
        reaction = replace(REACTION, family="surface", surface="SiO2")
    first = _dataset("a", kind=kind, value=0.1, provider="other", preferred=True)
    second = _dataset("b", kind=kind, value=0.2, provider="target")
    result = _use(
        first, second, reaction=reaction, selection=_selection(kind, providers=["target"])
    )
    assert result.dataset_id == "b"
    assert result.kind == kind
    assert result.status == "needs_input"
    assert result.required_transforms == (
        ("eedf_integration",) if kind == "cross_section" else ("surface_flux_conversion",)
    )
    assert result.disagreements == ("a",)


def test_request_for_another_quantity_does_not_rank_rate_sources() -> None:
    result = _use(
        _dataset("a", provider="target"),
        _dataset("b", provider="other", value=2e-15),
        selection=_selection("cross_section", providers=["target"]),
    )
    assert result.status == "conflict"
    assert result.dataset_id is result.value is None


def test_unknown_method_is_a_record_property_and_omitted_methods_impose_no_constraint() -> None:
    unknown = _dataset("unknown", method="unknown")
    measured = _dataset("measured", value=2e-15, method="measured")
    result = _use(unknown, measured, selection=_selection(methods=["unknown"]))
    assert result.dataset_id == "unknown"
    assert (
        _use(unknown, measured, selection=_selection(providers=["provider-a"])).status == "conflict"
    )


def test_native_selection_ranks_only_the_specified_axes() -> None:
    policy = QuantitySelection(providers=("first", "second"))
    assert policy.rank("unknown", "outside-a", None) == policy.rank("measured", "outside-b", "x")
    assert policy.rank("unknown", "first", None) < policy.rank("measured", "second", "x")
