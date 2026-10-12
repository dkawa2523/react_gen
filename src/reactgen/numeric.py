"""Assess every numerical record before choosing a value for the given inputs.

This module can return a coefficient, a probability, or an unevaluated curve.
It does not solve distributions, surface fluxes, or a reaction mechanism.
Arrhenius convention: k=A (T/Tref)^b exp(-Ea/(k_B T)). Both Tref and
the energy unit are declared, rather than inferred from a parameter name.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import combinations, pairwise
from math import exp, inf, isclose, isfinite

from reactgen.case import Conditions
from reactgen.evidence import ReactionEvidence
from reactgen.model import ReactionCandidate
from reactgen.records import (
    TIER_RANK,
    NumericDataset,
    Property,
    channel_energy_status,
    energy_declarations_agree,
    energy_properties_equivalent,
    property_energy_bounds,
    qualified_channel_energy,
    reaction_energy_definition_compatible,
    review_scope_covers,
    scientific_dataset_content,
)
from reactgen.selection import DataSelection, QuantitySelection
from reactgen.units import EV_PER_K, canonical_axis_unit, energy_eV, numerical_unit, quantity_value


@dataclass(frozen=True)
class DatasetAssessment:
    dataset_id: str
    status: str
    reason: str
    value: float | None = None
    unit: str | None = None
    required_inputs: tuple[str, ...] = ()
    required_transforms: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataUse:
    status: str = "unavailable"
    reason: str = "no numerical data"
    dataset_id: str | None = None
    kind: str | None = None
    value: float | None = None
    unit: str | None = None
    required_inputs: tuple[str, ...] = ()
    required_transforms: tuple[str, ...] = ()
    estimated: bool = False
    datasets: tuple[DatasetAssessment, ...] = ()
    selection: dict = field(default_factory=dict)
    disagreements: tuple[str, ...] = ()


def data_use(
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
    conditions: Conditions,
    selection: DataSelection | None = None,
) -> DataUse:
    """Record-level validity is distinct from reaction existence or feasibility."""
    grouped: dict[str, list[NumericDataset]] = {}
    for dataset in evidence.datasets:
        group = grouped.setdefault(dataset.id, [])
        if all(
            scientific_dataset_content(dataset) != scientific_dataset_content(held)
            for held in group
        ):
            group.append(dataset)
    assessed: list[DatasetAssessment] = []
    accepted: list[tuple[NumericDataset, DatasetAssessment]] = []
    for dataset_id, group in sorted(grouped.items()):
        if len(group) > 1:
            assessed.append(
                DatasetAssessment(dataset_id, "conflict", "same ID has different content")
            )
            continue
        dataset = group[0]
        result = assess_dataset(dataset, reaction, evidence, conditions)
        assessed.append(result)
        if result.status in {"valid", "needs_input"}:
            accepted.append((dataset, result))
    results = tuple(assessed)
    selection = DataSelection() if selection is None else selection
    if not isinstance(selection, DataSelection):
        raise ValueError("selection must be a validated DataSelection")
    selected, notes = _selection_candidates(accepted, evidence.datasets, selection)
    if not accepted:
        conflict = any(item.status == "conflict" for item in results)
        use = DataUse(
            "conflict" if conflict else "unavailable",
            "dataset identity conflicts" if conflict else "no valid numerical representation",
            datasets=results,
        )
    elif not selected:
        use = DataUse(
            "unavailable", "no eligible numerical records satisfy the request", datasets=results
        )
    else:
        use = _choose_data(selected, results, conditions, reaction)
    disagreement_ids = {
        dataset.id
        for left, right in combinations([dataset for dataset, _ in accepted], 2)
        if _conflicting([left, right], conditions, reaction)
        for dataset in (left, right)
    }
    disagreement_ids.update(item.dataset_id for item in results if item.status == "conflict")
    if use.dataset_id is not None:
        disagreement_ids.discard(use.dataset_id)
    return replace(
        use,
        reason="; ".join((use.reason, *notes)),
        selection=selection.document() if selection.quantities else {},
        disagreements=tuple(sorted(disagreement_ids)),
    )


def _selection_candidates(
    accepted: list[tuple[NumericDataset, DatasetAssessment]],
    offered: tuple[NumericDataset, ...],
    selection: DataSelection,
) -> tuple[list[tuple[NumericDataset, DatasetAssessment]], list[str]]:
    selected = []
    notes: list[str] = []
    kinds = sorted({dataset.kind for dataset in offered} | set(selection.quantities))
    for kind in kinds:
        group = [(dataset, result) for dataset, result in accepted if dataset.kind == kind]
        policy = selection.for_quantity(kind)
        if policy is None:
            # Compatibility for existing input declarations, removed in 0.8.
            preferred = [(dataset, result) for dataset, result in group if dataset.preferred]
            selected.extend(preferred or group)
            if preferred:
                notes.append(
                    f"{kind}: explicitly preferred source (deprecated data preferred; "
                    "migrate to data_selection)"
                )
            continue
        chosen = _requested_candidates(kind, policy, offered, group)
        selected.extend(chosen)
        notes.append(_request_reason(kind, policy, chosen))
    return selected, notes


def _source_axes(dataset: NumericDataset) -> tuple[str, str | None, str | None]:
    return dataset.method, dataset.provenance.provider, dataset.provenance.collection


def _requested_candidates(
    kind: str,
    policy: QuantitySelection,
    offered: tuple[NumericDataset, ...],
    eligible: list[tuple[NumericDataset, DatasetAssessment]],
) -> list[tuple[NumericDataset, DatasetAssessment]]:
    matches = [dataset for dataset in offered if dataset.id == policy.record]
    if policy.record is not None:
        if any(dataset.kind != kind for dataset in matches):
            raise ValueError(
                f"data_selection {kind}: record {policy.record!r} describes another quantity"
            )
        if any(not policy.allows(*_source_axes(dataset)) for dataset in matches):
            raise ValueError(
                f"data_selection {kind}: record {policy.record!r} contradicts only restrictions"
            )
        return [(dataset, result) for dataset, result in eligible if dataset.id == policy.record]
    allowed = [
        (dataset, result) for dataset, result in eligible if policy.allows(*_source_axes(dataset))
    ]
    if policy.mode == "only" or not allowed:
        return allowed
    best_rank = min(policy.rank(*_source_axes(dataset)) for dataset, _ in allowed)
    return [
        (dataset, result)
        for dataset, result in allowed
        if policy.rank(*_source_axes(dataset)) == best_rank
    ]


def _request_reason(
    kind: str,
    policy: QuantitySelection,
    chosen: list[tuple[NumericDataset, DatasetAssessment]],
) -> str:
    if policy.record is not None:
        return f"{kind}: requested record {policy.record!r}" + (
            "" if chosen else " is unavailable or inapplicable"
        )
    if not chosen:
        return f"{kind}: no eligible record satisfies the {policy.mode} request"
    fallback = [
        name
        for name, actual in zip(
            ("methods", "providers", "collections"), _source_axes(chosen[0][0]), strict=True
        )
        if getattr(policy, name) and actual not in getattr(policy, name)
    ]
    return f"{kind}: {policy.mode} request applied" + (
        f"; fallback used for {', '.join(fallback)}" if policy.mode == "prefer" and fallback else ""
    )


def _choose_data(
    accepted: list[tuple[NumericDataset, DatasetAssessment]],
    results: tuple[DatasetAssessment, ...],
    conditions: Conditions,
    reaction: ReactionCandidate,
) -> DataUse:
    selected = accepted
    applicable = [(dataset, result) for dataset, result in selected if result.status == "valid"]
    pending_rates = [
        (dataset, result)
        for dataset, result in selected
        if dataset.kind == "rate_coefficient" and result.status == "needs_input"
    ]
    if pending_rates and any(dataset.kind == "rate_coefficient" for dataset, _ in applicable):
        return DataUse(
            "needs_input",
            "missing conditions must determine rate-law applicability before source selection",
            required_inputs=tuple(
                sorted({value for _, result in pending_rates for value in result.required_inputs})
            ),
            required_transforms=tuple(
                sorted(
                    {value for _, result in pending_rates for value in result.required_transforms}
                )
            ),
            datasets=results,
        )
    choices = applicable or selected
    inputs = tuple(sorted({value for _, result in choices for value in result.required_inputs}))
    transforms = tuple(
        sorted({value for _, result in choices for value in result.required_transforms})
    )
    rates = [dataset for dataset, _ in choices if dataset.kind == "rate_coefficient"]
    if any(not _same_quantity(left, right, reaction) for left, right in combinations(rates, 2)):
        return DataUse(
            "needs_input",
            "missing conditions must determine rate-law applicability before source selection"
            if inputs
            else "sources describe different rate laws; explicit source selection is required",
            required_inputs=inputs or ("rate_law_selection",),
            required_transforms=transforms,
            datasets=results,
        )
    if _conflicting([item[0] for item in choices], conditions, reaction):
        return DataUse(
            "conflict",
            "numerical sources disagree at the supplied conditions"
            if applicable
            else "numerical sources disagree at checked points of overlapping applicability",
            required_inputs=inputs,
            required_transforms=transforms,
            datasets=results,
        )
    if len(choices) > 1 and inputs:
        return DataUse(
            "needs_input",
            "conditions are needed to select a source; finite-point checks do not establish "
            "continuous-domain equivalence",
            required_inputs=inputs,
            required_transforms=transforms,
            datasets=results,
        )
    dataset, result = min(
        choices,
        key=lambda item: (
            TIER_RANK.get(item[0].tier, 5),
            0 if item[0].kind == "rate_coefficient" else 1,
            item[0].id,
        ),
    )
    inputs = result.required_inputs
    transforms = result.required_transforms
    status = "needs_input" if inputs else "needs_transform" if transforms else "coefficient"
    reason = result.reason
    if len(choices) > 1:
        reason += (
            "; no disagreement at the supplied conditions; "
            "selected by quality, kind, then stable ID"
        )
    return DataUse(
        status,
        reason,
        dataset.id,
        dataset.kind,
        result.value,
        result.unit,
        inputs,
        transforms,
        dataset.estimated,
        results,
    )


def assess_dataset(
    dataset: NumericDataset,
    reaction: ReactionCandidate,
    evidence: ReactionEvidence,
    conditions: Conditions,
) -> DatasetAssessment:
    if dataset.form == "reference_only":
        return DatasetAssessment(
            dataset.id, "reference_only", "source has no numerical representation"
        )
    problem = _metadata_problem(dataset, reaction) or _representation_problem(dataset, evidence)
    if problem is not None:
        return DatasetAssessment(dataset.id, "invalid", problem)
    if dataset.tier not in {
        "curated",
        "reviewed",
        "derived",
        "estimated",
    } or not review_scope_covers(dataset.review_scope, dataset.kind):
        return DatasetAssessment(dataset.id, "unreviewed", "numerical source has not been reviewed")
    return _evaluated_dataset(dataset, reaction, conditions)


def _coefficient_order(dataset: NumericDataset, reaction: ReactionCandidate) -> float | None:
    if dataset.reaction_order is not None:
        return dataset.reaction_order
    if reaction.surface is not None:
        return None
    return sum(term.n for term in reaction.reactants) + bool(reaction.third_body)


def _metadata_problem(dataset: NumericDataset, reaction: ReactionCandidate) -> str | None:
    numerical_problem = _numerical_problem(dataset)
    if numerical_problem is not None:
        return numerical_problem
    if dataset.status in {"rejected", "conflicting"}:
        return f"source status is {dataset.status}"
    if dataset.channel_scope != "product_resolved":
        return (
            "total data do not determine this product channel"
            if dataset.channel_scope in {"total", "total_process"}
            else "source does not declare product-resolved channel scope"
        )
    if not _observable_matches(dataset, reaction):
        return "observable is missing or describes a different quantity"
    if numerical_unit(dataset.unit, dataset.kind, _coefficient_order(dataset, reaction)) is None:
        return "unit does not match quantity and reaction order"
    if dataset.kind == "sticking_coefficient" and reaction.surface is None:
        return "sticking probability requires a surface"
    return None


def _numerical_problem(dataset: NumericDataset, value: float | None = 1.0) -> str | None:
    if dataset.asset is not None and not dataset.asset.integrity_ok:
        return "asset is unavailable or differs from its recorded or declared checksum"
    if dataset.uncertainty is None or value is None:
        return None
    try:
        dataset.uncertainty.bounds(value)
    except ValueError as error:
        return str(error)
    return None


def _application_requirements(
    dataset: NumericDataset,
    reaction: ReactionCandidate,
    conditions: Conditions,
) -> tuple[set[str], set[str], bool]:
    inputs: set[str] = set()
    transforms: set[str] = set()
    if dataset.kind == "cross_section":
        inputs.add(
            "electron_energy_distribution"
            if reaction.family == "electron"
            else "collision_energy_distribution"
        )
        transforms.add(
            "eedf_integration"
            if reaction.family == "electron"
            else "energy_distribution_integration"
        )
    if dataset.kind == "sticking_coefficient":
        inputs.add("surface_incident_flux_model")
        transforms.add("surface_flux_conversion")
    validity = dataset.validity
    if validity is None or (validity.minimum is None and validity.maximum is None):
        inputs.add("dataset_applicability_conditions")
    elif dataset.kind != "cross_section":
        condition = condition_value(conditions, validity.quantity, validity.unit)
        if condition is None:
            inputs.add(validity.quantity)
        elif not validity.covers(condition):
            return inputs, transforms, True
    return inputs, transforms, False


def _evaluated_dataset(
    dataset: NumericDataset, reaction: ReactionCandidate, conditions: Conditions
) -> DatasetAssessment:
    inputs, transforms, out_of_range = _application_requirements(dataset, reaction, conditions)
    if out_of_range:
        return DatasetAssessment(
            dataset.id, "out_of_range", "outside the declared applicability range"
        )
    value = _value(dataset, conditions)
    numerical_problem = _numerical_problem(dataset, value)
    if numerical_problem is not None:
        return DatasetAssessment(dataset.id, "invalid", numerical_problem)
    if dataset.kind != "cross_section" and value is None and dataset.form != "constant":
        inputs.add(dataset.independent_variable or "dataset_independent_variable")
    unit = numerical_unit(dataset.unit, dataset.kind, _coefficient_order(dataset, reaction))
    if unit is None:
        return DatasetAssessment(dataset.id, "invalid", "unsupported numerical unit")
    if value is not None:
        value *= unit[1]
        if (
            not isfinite(value)
            or value < 0.0
            or (dataset.kind == "sticking_coefficient" and value > 1.0)
        ):
            return DatasetAssessment(
                dataset.id, "invalid", "evaluated value is outside its physical range"
            )
    reason = "coefficient evaluated for the supplied conditions"
    if dataset.kind == "cross_section":
        reason = "curve checked; distribution coverage and integration are not performed"
    elif dataset.kind == "sticking_coefficient":
        reason = "probability checked; conversion to a surface rate is not performed"
    elif inputs:
        reason = "representation checked; applicability or evaluation inputs are missing"
    return DatasetAssessment(
        dataset.id,
        "needs_input" if inputs else "valid",
        reason,
        value,
        unit[0],
        tuple(sorted(inputs)),
        tuple(sorted(transforms)),
    )


def _observable_matches(dataset: NumericDataset, reaction: ReactionCandidate) -> bool:
    if dataset.kind == "rate_coefficient":
        return dataset.observable == "reaction_rate"
    if dataset.kind == "sticking_coefficient":
        return dataset.observable == "sticking_probability"
    if dataset.kind != "cross_section":
        return False
    allowed = {"reaction", reaction.process}
    if reaction.process == "elastic":
        allowed = {"elastic", "momentum_transfer", "effective_momentum_transfer"}
    elif reaction.process == "resonant_charge_exchange":
        allowed = {"charge_exchange", "momentum_transfer"}
    return dataset.observable in allowed


def _representation_problem(dataset: NumericDataset, evidence: ReactionEvidence) -> str | None:
    axis = dataset.independent_variable
    if axis is not None and canonical_axis_unit(axis) is None:
        return "physical quantity is unspecified or unsupported"
    if dataset.kind == "cross_section" and axis not in {
        "collision_energy",
        "electron_energy",
        "ion_energy",
    }:
        return "cross section requires a collision-energy axis"
    problem = _validity_problem(dataset)
    if problem is not None:
        return problem
    if dataset.form == "constant":
        return _constant_problem(dataset)
    if dataset.form == "arrhenius":
        return _arrhenius_problem(dataset)
    if dataset.form == "table":
        return _table_problem(dataset, evidence)
    return "unsupported numerical representation"


def _validity_problem(dataset: NumericDataset) -> str | None:
    axis = dataset.independent_variable
    validity = dataset.validity
    if validity is not None:
        canonical = canonical_axis_unit(validity.quantity)
        if canonical is None or validity.unit is None:
            return "validity physical quantity or unit is unspecified or unsupported"
        if (
            axis is not None
            and axis != validity.quantity
            and not (
                dataset.kind == "cross_section"
                and "collision_energy" in {axis, validity.quantity}
                and {axis, validity.quantity}
                <= {"collision_energy", "electron_energy", "ion_energy"}
            )
        ):
            return "validity quantity differs from the independent variable"
        bounds = [value for value in (validity.minimum, validity.maximum) if value is not None]
        if any(
            quantity_value(value, validity.quantity, validity.unit, canonical) is None
            for value in bounds
        ):
            return "validity unit is incompatible with its quantity"
        if any(value < 0 or not isfinite(value) for value in bounds):
            return "validity bounds must be finite and non-negative"
        if (
            validity.minimum is not None
            and validity.maximum is not None
            and validity.minimum > validity.maximum
        ):
            return "validity bounds are reversed"
    return None


def _constant_problem(dataset: NumericDataset) -> str | None:
    value = dataset.params.get("value")
    if value is None or not isfinite(value) or value < 0.0:
        return "constant must be finite and non-negative"
    if dataset.kind == "sticking_coefficient" and value > 1.0:
        return "sticking probability must be between zero and one"
    return None


def _arrhenius_problem(dataset: NumericDataset) -> str | None:
    axis = dataset.independent_variable
    if axis not in {
        "gas_temperature",
        "electron_temperature",
        "ion_temperature",
        "surface_temperature",
    }:
        return "Arrhenius requires a declared temperature quantity"
    if {"A", "b", "Ea"} - dataset.params.keys():
        return "Arrhenius requires A, b, Ea in the declared convention"
    if not all(isfinite(value) for value in dataset.params.values()) or dataset.params["A"] < 0.0:
        return "Arrhenius parameters must be finite and A non-negative"
    reference = dataset.reference_temperature_K
    if reference is None or not isfinite(reference) or reference <= 0.0:
        return "Arrhenius requires a positive reference_temperature_K"
    if energy_eV(dataset.params["Ea"], dataset.parameter_units.get("Ea")) is None:
        return "Arrhenius activation energy unit is missing or unsupported"
    if dataset.kind == "sticking_coefficient":
        return _arrhenius_probability_problem(dataset)
    return None


def _table_problem(dataset: NumericDataset, evidence: ReactionEvidence) -> str | None:
    axis = dataset.independent_variable
    axis_unit = canonical_axis_unit(axis)
    points = table_points(dataset)
    if points is None or len(points) < 2:
        return "table is missing or is not a two-column finite numerical table"
    if any(right[0] <= left[0] for left, right in pairwise(points)):
        return "table coordinates must increase strictly"
    if any(x < 0.0 or y < 0.0 for x, y in points):
        return "table coordinates and values must be non-negative"
    if dataset.kind == "sticking_coefficient" and any(y > 1.0 for _, y in points):
        return "sticking probability must be between zero and one throughout the table"
    x_unit = _axis_unit(dataset)
    if axis is None or x_unit is None or axis_unit is None:
        return "table coordinate quantity and unit must be declared"
    if quantity_value(points[0][0], axis, x_unit, axis_unit) is None:
        return "table coordinate unit is incompatible with its quantity"
    return _table_domain_problem(dataset, points, x_unit) or _threshold_problem(
        dataset, evidence, points, x_unit
    )


def _table_domain_problem(
    dataset: NumericDataset, points: list[tuple[float, float]], x_unit: str
) -> str | None:
    validity = dataset.validity
    if validity is not None:
        for bound in (validity.minimum, validity.maximum):
            if bound is not None:
                converted = quantity_value(bound, validity.quantity, validity.unit or "", x_unit)
                if converted is None or not points[0][0] <= converted <= points[-1][0]:
                    return "declared validity exceeds the numerical table"
    return None


def _threshold_problem(
    dataset: NumericDataset,
    evidence: ReactionEvidence,
    points: list[tuple[float, float]],
    x_unit: str,
) -> str | None:
    if dataset.kind != "cross_section":
        return None
    declaration = _threshold_declaration_bound(evidence)
    if declaration is None:
        return None
    threshold, nominal = declaration
    if any(
        (energy := energy_eV(x, x_unit)) is not None and energy < threshold - 1e-9 and y > 0.0
        for x, y in points
    ):
        meaning = (
            "nominal declared channel threshold (uncertainty is unspecified)"
            if nominal
            else "lower bound of the declared channel-threshold interval"
        )
        return (
            f"positive cross section lies below the {meaning}; "
            "this is declaration consistency, not a measured absolute limit"
        )
    return None


def _threshold_declaration_bound(evidence: ReactionEvidence) -> tuple[float, bool] | None:
    """One conservative declared lower edge; the boolean marks nominal use."""
    if any(
        channel_energy_status(record, "threshold_eV") == "conflicting"
        and review_scope_covers(prop.review_scope, "threshold_eV")
        and reaction_energy_definition_compatible(prop, "threshold_eV")
        for record in evidence.exact_records
        if (prop := record.energy_properties.get("threshold_eV")) is not None
    ):
        return None
    declared = [
        (record, prop)
        for record in evidence.exact_records
        if (prop := qualified_channel_energy(record, "threshold_eV")) is not None
    ]
    if not declared:
        return None
    identifiers = {record.id for record, _ in declared}
    same_record: dict[str, tuple[tuple, Property]] = {}
    for record in (*evidence.records, *evidence.related_records):
        prop = record.energy_properties.get("threshold_eV")
        if (
            record.id not in identifiers
            or prop is None
            or not review_scope_covers(prop.review_scope, "threshold_eV")
            or not reaction_energy_definition_compatible(prop, "threshold_eV")
        ):
            continue
        if channel_energy_status(record, "threshold_eV") == "conflicting":
            return None
        target = (
            record.equation_key,
            record.process,
            record.channel_scope,
            channel_energy_status(record, "threshold_eV"),
        )
        previous = same_record.get(record.id)
        if previous is not None and (
            previous[0] != target or not energy_properties_equivalent(previous[1], prop)
        ):
            return None
        same_record[record.id] = target, prop
    bounds = [property_energy_bounds(prop) for _, prop in declared]
    if any(interval is None for interval in bounds):
        return None
    if not energy_declarations_agree([prop for _, prop in declared]):
        return None
    # Use the union's lower edge: an uncertain threshold cannot exclude points
    # inside its declared interval. An omitted uncertainty remains nominal.
    return (
        min(interval[0] for interval in bounds if interval is not None),
        any(prop.uncertainty is None for _, prop in declared),
    )


def _arrhenius_probability_problem(dataset: NumericDataset) -> str | None:
    validity = dataset.validity
    if validity is None or validity.minimum is None or validity.maximum is None:
        return "temperature-dependent probability requires a finite validity range"
    minimum = quantity_value(validity.minimum, validity.quantity, validity.unit or "", "K")
    maximum = quantity_value(validity.maximum, validity.quantity, validity.unit or "", "K")
    if minimum is None or maximum is None or minimum <= 0.0:
        return "probability temperature range must be positive"
    temperatures = [minimum, maximum]
    activation = energy_eV(dataset.params["Ea"], dataset.parameter_units.get("Ea"))
    exponent = dataset.params["b"]
    if activation is not None and exponent != 0.0:
        stationary = -activation / (EV_PER_K * exponent)
        if minimum < stationary < maximum:
            temperatures.append(stationary)
    values = [_arrhenius(dataset, temperature) for temperature in temperatures]
    return (
        "sticking probability exceeds zero-to-one range"
        if any(value is None or value > 1.0 for value in values)
        else None
    )


def table_points(dataset: NumericDataset) -> list[tuple[float, float]] | None:
    asset = dataset.asset
    content = asset.read_bytes() if asset is not None else None
    if content is None:
        return None
    try:
        lines = content.decode("utf-8-sig").splitlines()
    except UnicodeError:
        return None
    points: list[tuple[float, float]] = []
    header = False
    for line in lines:
        fields = line.split("#", 1)[0].replace(",", " ").split()
        if not fields:
            continue
        if len(fields) != 2:
            return None
        try:
            point = (float(fields[0]), float(fields[1]))
        except ValueError:
            if points or header:
                return None
            header = True
            continue
        if not all(isfinite(value) for value in point):
            return None
        points.append(point)
    return points


def _axis_unit(dataset: NumericDataset) -> str | None:
    return dataset.parameter_units.get("x") or (
        dataset.validity.unit if dataset.validity is not None else None
    )


def condition_value(conditions: Conditions, quantity: str, unit: str | None) -> float | None:
    value = conditions.value_of(quantity)
    if value is None or unit is None:
        return None
    source = (
        "eV"
        if quantity in {"electron_temperature", "ion_energy", "collision_energy"}
        else canonical_axis_unit(quantity)
    )
    return None if source is None else quantity_value(value, quantity, source, unit)


def _value(dataset: NumericDataset, conditions: Conditions) -> float | None:
    if dataset.form == "constant":
        return dataset.params.get("value")
    if dataset.form == "arrhenius":
        temperature = condition_value(conditions, dataset.independent_variable or "", "K")
        return None if temperature is None else _arrhenius(dataset, temperature)
    axis = dataset.independent_variable or ""
    coordinate = condition_value(conditions, axis, _axis_unit(dataset))
    return None if coordinate is None else _table_value(dataset, coordinate)


def _arrhenius(dataset: NumericDataset, temperature_K: float) -> float | None:
    activation = energy_eV(dataset.params.get("Ea", 0.0), dataset.parameter_units.get("Ea"))
    reference = dataset.reference_temperature_K
    if activation is None or reference is None or temperature_K <= 0:
        return None
    try:
        return (
            dataset.params["A"]
            * (temperature_K / reference) ** dataset.params["b"]
            * exp(-activation / (EV_PER_K * temperature_K))
        )
    except OverflowError:
        return float("inf")


def _table_value(dataset: NumericDataset, coordinate: float) -> float | None:
    points = table_points(dataset)
    if not points:
        return None
    for left, right in pairwise(points):
        if left[0] <= coordinate <= right[0]:
            fraction = (coordinate - left[0]) / (right[0] - left[0])
            return left[1] + fraction * (right[1] - left[1])
    return None


def _range(dataset: NumericDataset) -> tuple[str, float, float] | None:
    validity = dataset.validity
    if validity is None or (validity.minimum is None and validity.maximum is None):
        return None
    unit = canonical_axis_unit(validity.quantity)
    if unit is None or validity.unit is None:
        return None
    low = (
        -inf
        if validity.minimum is None
        else quantity_value(validity.minimum, validity.quantity, validity.unit, unit)
    )
    high = (
        inf
        if validity.maximum is None
        else quantity_value(validity.maximum, validity.quantity, validity.unit, unit)
    )
    return None if low is None or high is None else (validity.quantity, low, high)


def _comparison_samples(
    left: NumericDataset, right: NumericDataset, conditions: Conditions
) -> tuple[str | None, list[float | None]] | None:
    axis = (
        left.independent_variable
        or right.independent_variable
        or (left.validity.quantity if left.validity is not None else None)
        or (right.validity.quantity if right.validity is not None else None)
    )
    if axis is not None and conditions.value_of(axis) is not None:
        return axis, [None]
    left_range, right_range = _range(left), _range(right)
    if not left_range or not right_range:
        return None
    if left_range[0] != right_range[0]:
        return None
    low, high = max(left_range[1], right_range[1]), min(left_range[2], right_range[2])
    if low > high:
        return None
    axis = left_range[0]
    samples: list[float | None] = [bound for bound in (low, high) if isfinite(bound)]
    if isfinite(low) and isfinite(high):
        samples.append(low + (high - low) / 2.0)
    for dataset in (left, right):
        for x, _ in table_points(dataset) or []:
            converted = quantity_value(
                x, axis, _axis_unit(dataset) or "", canonical_axis_unit(axis) or ""
            )
            if converted is not None and low <= converted <= high:
                samples.append(converted)
    return axis, samples


def _same_quantity(
    left: NumericDataset, right: NumericDataset, reaction: ReactionCandidate
) -> bool:
    """Comparable coefficient values need the same declared rate order and dimension."""
    if left.kind != right.kind or left.observable != right.observable:
        return False
    left_order, right_order = (
        _coefficient_order(left, reaction),
        _coefficient_order(right, reaction),
    )
    if left.kind == "rate_coefficient" and left_order != right_order:
        return False
    left_unit = numerical_unit(left.unit, left.kind, left_order)
    right_unit = numerical_unit(right.unit, right.kind, right_order)
    return left_unit is not None and right_unit is not None and left_unit[0] == right_unit[0]


def _conflicting(
    datasets: list[NumericDataset], conditions: Conditions, reaction: ReactionCandidate
) -> bool:
    for left, right in combinations(datasets, 2):
        if not _same_quantity(left, right, reaction):
            continue
        comparison = _comparison_samples(left, right, conditions)
        if comparison is None:
            continue
        axis, samples = comparison
        for sample in samples:
            first = _sample_value(left, sample, axis, conditions, reaction)
            second = _sample_value(right, sample, axis, conditions, reaction)
            if first is None or second is None:
                continue
            first_bounds = _bounds(left, first, reaction)
            second_bounds = _bounds(right, second, reaction)
            separated = first_bounds[1] < second_bounds[0] or second_bounds[1] < first_bounds[0]
            if separated and not isclose(first, second, rel_tol=1e-9, abs_tol=0.0):
                return True
    return False


def _sample_value(
    dataset: NumericDataset,
    sample: float | None,
    axis: str | None,
    conditions: Conditions,
    reaction: ReactionCandidate,
) -> float | None:
    if sample is None or axis is None:
        value = _value(dataset, conditions)
    elif dataset.form == "constant":
        value = dataset.params.get("value")
    elif dataset.form == "arrhenius":
        value = _arrhenius(dataset, sample)
    else:
        coordinate = quantity_value(
            sample, axis, canonical_axis_unit(axis) or "", _axis_unit(dataset) or ""
        )
        value = None if coordinate is None else _table_value(dataset, coordinate)
    if value is None or not isfinite(value) or _numerical_problem(dataset, value) is not None:
        return None
    unit = numerical_unit(dataset.unit, dataset.kind, _coefficient_order(dataset, reaction))
    normalized = None if unit is None else value * unit[1]
    return normalized if normalized is not None and isfinite(normalized) else None


def _bounds(
    dataset: NumericDataset, value: float, reaction: ReactionCandidate
) -> tuple[float, float]:
    unit = numerical_unit(dataset.unit, dataset.kind, _coefficient_order(dataset, reaction))
    if dataset.uncertainty is None or unit is None:
        return value, value
    bounds = dataset.uncertainty.bounds(value / unit[1])
    return (bounds[0] * unit[1], bounds[1] * unit[1]) if bounds is not None else (value, value)
