"""Read/write boundary checks for saved numerical results and derived claims."""

from copy import deepcopy
from pathlib import Path

import pytest

from reactgen import export, needs
from reactgen.case import Case, Conditions, Limits
from reactgen.chemistry import parse_state_id
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.records import NumericDataset, Validity
from reactgen.selection import DataSelection
from reactgen.structure import StructureUnavailable, structure_key


@pytest.fixture(scope="module")
def saved_curve() -> dict:
    case = Case(
        "curve",
        ("Ar",),
        Conditions(electron_energy_eV=100),
        limits=Limits(max_atoms=1, max_depth=1),
        supplies=("e",),
    )
    generated = analyze(case, EvidenceCatalog())
    target = next(
        item
        for item in generated.candidates.reactions.values()
        if item.process == "elastic"
        and item.family == "electron"
        and any(term.species == "Ar@ground" for term in item.reactants)
    )
    curve = NumericDataset(
        "elastic-curve",
        "cross_section",
        "constant",
        unit="m2",
        independent_variable="electron_energy",
        observable="elastic",
        params={"value": 1e-20},
        tier="reviewed",
        validity=Validity("electron_energy", 1, 10, "eV"),
    )
    return export.document(analyze(case, EvidenceCatalog(overlay_datasets={target.id: (curve,)})))


@pytest.fixture
def curve_result(saved_curve: dict) -> dict:
    return deepcopy(saved_curve)


def curve_reaction(document: dict) -> dict:
    return next(item for item in document["reactions"] if item["data_use"]["dataset_id"])


def rehash(document: dict) -> None:
    from hashlib import sha256

    document["helper_views"] = {
        name: sha256(value.encode()).hexdigest()
        for name, value in export.csv_views(document).items()
    }


def test_native_curve_and_coefficient_work_are_separate_and_roundtrip(
    tmp_path: Path, curve_result: dict
) -> None:
    document = curve_result
    reaction = curve_reaction(document)
    native = reaction["data_use"]["datasets"][0]
    assert native["status"] == "valid"
    assert native["kind"] == "cross_section"
    assert native["observable"] == "elastic"
    assert native["value"] is None
    assert native["requirements"] == []
    assert native["required_transforms"] == []
    work = reaction["data_use"]["requirements"]
    assert {item["responsibility"] for item in work} == {"external_models", "transforms"}
    assert reaction["assessments"]["kinetics"]["verdict"] == "unknown"
    export.rebuild_views(document, tmp_path)
    from reactgen import yamlio

    (tmp_path / "result.yaml").write_text(yamlio.dump(document), encoding="utf-8")
    assert export.read(tmp_path, verify_views=True) == document


@pytest.mark.parametrize("field", ["required_inputs", "scope"])
def test_current_numerical_fields_cannot_drop_saved_responsibility(
    field: str, curve_result: dict
) -> None:
    document = curve_result
    use = curve_reaction(document)["data_use"]
    use[field] = ["gas_temperature"] if field == "required_inputs" else ""
    rehash(document)
    with pytest.raises(ValueError, match="responsibilit|scope"):
        export.validate(document)


def test_coefficient_projection_cannot_contradict_or_duplicate_numerical_result(
    curve_result: dict,
) -> None:
    document = curve_result
    claim = curve_reaction(document)["assessments"]["kinetics"]
    claim["verdict"] = "pass"
    rehash(document)
    with pytest.raises(ValueError, match="coefficient projection"):
        export.validate(document)
    claim["verdict"] = "unknown"
    claim["requirements"] = [
        {
            "responsibility": "source_information",
            "target": "elastic-curve",
            "quantity": "unrelated",
            "reason": "duplicate work",
        }
    ]
    rehash(document)
    with pytest.raises(ValueError, match="duplicates numerical work"):
        export.validate(document)


def test_participant_projection_uses_exact_saved_state_claims(curve_result: dict) -> None:
    document = curve_result
    claim = curve_reaction(document)["assessments"]["state"]
    claim["dependencies"] = []
    rehash(document)
    with pytest.raises(ValueError, match="participant projection"):
        export.validate(document)


def test_thermal_flat_values_are_only_a_projection_of_calculation_outcomes(
    curve_result: dict,
) -> None:
    document = curve_result
    reaction = curve_reaction(document)
    reaction["thermochemical_calculations"]["delta_h_eV"] = {
        "status": "computed",
        "value": 0,
        "unit": "eV",
        "reason": "same-state cancellation",
        "requirements": [],
        "conditions": {},
        "label": "computed",
        "blocking_causes": [],
    }
    reaction["thermochemistry"]["delta_h_eV"] = 1
    rehash(document)
    with pytest.raises(ValueError, match="thermal values contradict"):
        export.validate(document)
    reaction["thermochemistry"]["delta_h_eV"] = 0
    document["summary"] = export.summary(document["states"], document["reactions"])
    rehash(document)
    export.validate(document)


def test_current_results_cannot_omit_an_unavailable_thermal_calculation(curve_result: dict) -> None:
    document = curve_result
    del curve_reaction(document)["thermochemical_calculations"]["delta_g_eV"]
    rehash(document)
    with pytest.raises(ValueError, match="calculation outcomes are missing"):
        export.validate(document)


def test_saved_mapped_supply_must_describe_its_recorded_graph(monkeypatch) -> None:
    state = parse_state_id("C2H6O@ground;structure=smiles:CCO")
    assert state is not None
    try:
        structure_key(state)
    except StructureUnavailable as error:
        pytest.skip(str(error))
    case = Case(
        "mapped ethanol",
        ("C2H6O",),
        structures={"C2H6O": "OCC"},
        limits=Limits(max_atoms=9, max_depth=1, max_species=20, max_reactions=20),
    )
    result = export.document(analyze(case, EvidenceCatalog()))
    mapped = result["input"]["structures"]
    (target,) = mapped
    mapped[target] = "COC"
    with pytest.raises(ValueError, match="saved supply does not correspond"):
        export.validate(result)
    mapped[target] = "CCO"
    export.validate(result)

    def unavailable():
        raise StructureUnavailable("test environment lacks RDKit")

    monkeypatch.setattr("reactgen.structure._chem", unavailable)
    mapped[target] = "OCC"
    export.validate(result)
    mapped[target] = "COC"
    with pytest.raises(ValueError, match="saved supply does not correspond"):
        export.validate(result)


def test_saved_work_is_used_without_parsing_messages_or_obsolete_string_fields(
    curve_result: dict,
) -> None:
    document = curve_result
    before = needs.build(document, detail=True)
    altered = deepcopy(document)
    use = curve_reaction(altered)["data_use"]
    use["reason"] = "not a source of scientific work categories"
    use["required_inputs"] = ["made_up_input"]
    after = needs.build(altered, detail=True)
    target = use["dataset_id"]
    expected = [item for item in before["work_details"] if item["target"] == target]
    actual = [item for item in after["work_details"] if item["target"] == target]
    assert actual == expected


def test_historical_format_three_does_not_receive_new_scientific_meaning(
    tmp_path: Path, curve_result: dict
) -> None:
    document = curve_result
    document["metadata"]["helper_view_format"] = 3
    for candidate in (*document["states"], *document["reactions"]):
        for assessment in candidate["assessments"].values():
            assessment.pop("label")
            assessment.pop("blocking_causes")
    for reaction in document["reactions"]:
        reaction.pop("thermochemical_calculations")
        use = reaction["data_use"]
        for record in (use, *use["datasets"]):
            record.pop("scope")
            record.pop("requirements")
        for record in use["datasets"]:
            record.pop("kind")
            record.pop("observable")
        # Historic native records included coefficient-conversion requirements.
        if use["dataset_id"]:
            record = use["datasets"][0]
            record.update(
                status="needs_input",
                required_inputs=use["required_inputs"],
                required_transforms=use["required_transforms"],
            )
    rehash(document)
    document["summary"] = export.summary(document["states"], document["reactions"])
    from reactgen import yamlio

    (tmp_path / "result.yaml").write_text(yamlio.dump(document), encoding="utf-8")
    export.rebuild_views(document, tmp_path)
    assert export.read(tmp_path, verify_views=True) == document


def test_source_priority_cannot_change_the_quantity_or_override_coefficient_purpose() -> None:
    case = Case(
        "scope",
        ("Ar",),
        limits=Limits(max_atoms=1, max_depth=1),
        supplies=("e",),
        data_selection=DataSelection.from_document(
            {"quantities": {"cross_section": {"methods": ["measured"]}}}
        ),
    )
    generated = analyze(case, EvidenceCatalog())
    target = next(
        item
        for item in generated.candidates.reactions.values()
        if item.family == "electron" and item.process == "elastic"
    )
    from dataclasses import replace

    curve = NumericDataset(
        "elastic",
        "cross_section",
        "constant",
        unit="m2",
        independent_variable="electron_energy",
        observable="elastic",
        params={"value": 1e-20},
        tier="reviewed",
        validity=Validity("electron_energy", 1, 10, "eV"),
    )
    transport = replace(curve, id="transport", observable="momentum_transfer", method="measured")
    document = export.document(
        analyze(case, EvidenceCatalog(overlay_datasets={target.id: (curve, transport)}))
    )
    use = curve_reaction(document)["data_use"]
    assert use["dataset_id"] == "elastic"
    assert {item["status"] for item in use["datasets"]} == {"valid"}
    export.validate(document)


@pytest.mark.parametrize("field", ["kind", "observable"])
def test_saved_native_labels_cannot_change_the_offered_scientific_quantity(
    field: str, curve_result: dict
) -> None:
    document = curve_result
    curve_reaction(document)["data_use"]["datasets"][0][field] = "different_quantity"
    rehash(document)
    with pytest.raises(ValueError, match="native quantity labels"):
        export.validate(document)


def test_native_curve_cannot_store_an_implicit_scalar_sample(curve_result: dict) -> None:
    document = curve_result
    reaction = curve_reaction(document)
    reaction["data_use"]["datasets"][0]["value"] = 1e-20
    rehash(document)
    with pytest.raises(ValueError, match="not a scalar point query"):
        export.validate(document)


def test_valid_native_quantity_cannot_include_coefficient_conversion_work(
    curve_result: dict,
) -> None:
    document = curve_result
    native = curve_reaction(document)["data_use"]["datasets"][0]
    native["requirements"] = [
        {
            "responsibility": "transforms",
            "target": native["dataset_id"],
            "quantity": "eedf_integration",
            "reason": "wrong responsibility",
        }
    ]
    native["required_transforms"] = ["eedf_integration"]
    rehash(document)
    with pytest.raises(ValueError, match="native quantity"):
        export.validate(document)


def rate_result(*values: float) -> dict:
    case = Case(
        "rates",
        ("Ar",),
        Conditions(gas_temperature_K=300),
        limits=Limits(max_atoms=1, max_depth=1),
        supplies=("e",),
    )
    generated = analyze(case, EvidenceCatalog())
    target = next(
        item
        for item in generated.candidates.reactions.values()
        if item.family == "electron" and item.process == "ionization"
    )
    records = tuple(
        NumericDataset(
            f"rate-{index}",
            "rate_coefficient",
            "constant",
            unit="m3/s",
            observable="reaction_rate",
            params={"value": value},
            tier="reviewed",
            validity=Validity("gas_temperature", 200, 400, "K"),
        )
        for index, value in enumerate(values)
    )
    return export.document(analyze(case, EvidenceCatalog(overlay_datasets={target.id: records})))


def test_unselected_native_values_still_obey_the_quantity_domain() -> None:
    document = rate_result(1e-16, 2e-16)
    reaction = next(
        item for item in document["reactions"] if item["data_use"]["status"] == "conflict"
    )
    reaction["data_use"]["datasets"][0]["value"] = -1
    rehash(document)
    with pytest.raises(ValueError, match="native quantity value"):
        export.validate(document)


def test_usable_coefficient_cannot_have_unresolved_typed_prerequisites() -> None:
    document = rate_result(1e-16)
    use = curve_reaction(document)["data_use"]
    use["requirements"] = [
        {
            "responsibility": "source_review",
            "target": use["dataset_id"],
            "quantity": "numerical_record",
            "reason": "still unresolved",
        }
    ]
    rehash(document)
    with pytest.raises(ValueError, match="coefficient has unresolved"):
        export.validate(document)
