from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from plasma_reactgen.domain.equations import format_amount
from plasma_reactgen.domain.formula import ATOMIC_MASS_AMU, composition_mass_amu, parse_formula
from plasma_reactgen.domain.models import Species, SpeciesAmount
from plasma_reactgen.validation.validators import validate_reaction


@pytest.mark.property
@given(
    st.dictionaries(
        keys=st.sampled_from(sorted(ATOMIC_MASS_AMU)),
        values=st.integers(min_value=1, max_value=20),
        min_size=1,
    )
)
def test_formula_and_mass_round_trip_with_explicit_tolerance(
    composition: dict[str, int],
) -> None:
    formula = "".join(
        element + (str(count) if count != 1 else "") for element, count in composition.items()
    )

    parsed = parse_formula(formula)
    expected_mass = sum(ATOMIC_MASS_AMU[element] * count for element, count in composition.items())

    assert parsed == composition
    assert composition_mass_amu(parsed) == pytest.approx(expected_mass, rel=1e-12, abs=1e-12)


@pytest.mark.property
@given(st.integers(min_value=1, max_value=10))
def test_equation_amount_serialization_is_finite_and_stable(coefficient: int) -> None:
    rendered = format_amount(SpeciesAmount("Ar", coefficient))

    assert rendered == ("Ar" if coefficient == 1 else f"{coefficient} Ar")
    assert "nan" not in rendered.lower()
    assert "inf" not in rendered.lower()


@pytest.mark.property
@given(
    count=st.integers(min_value=1, max_value=20),
    charge=st.integers(min_value=-3, max_value=3),
    coefficient=st.integers(min_value=1, max_value=10),
)
def test_conservation_validation_is_symmetric_and_detects_perturbation(
    count: int,
    charge: int,
    coefficient: int,
) -> None:
    species = {
        "left": _species("left", count=count, charge=charge),
        "right": _species("right", count=count, charge=charge),
    }
    balanced = validate_reaction(
        [SpeciesAmount("left", coefficient)],
        [SpeciesAmount("right", coefficient)],
        species,
    )
    perturbed = validate_reaction(
        [SpeciesAmount("left", coefficient)],
        [SpeciesAmount("right", coefficient + 1)],
        species,
    )

    assert balanced == {
        "species_reference": "ok",
        "charge_balance": "ok",
        "element_balance": "ok",
    }
    assert perturbed["element_balance"] == "failed"


@pytest.mark.parametrize("coefficient", [math.nan, math.inf, -math.inf, 0.0, -1.0])
def test_conservation_validation_rejects_nonfinite_stoichiometry(coefficient: float) -> None:
    species = {
        "left": _species("left", count=1, charge=1),
        "right": _species("right", count=1, charge=1),
    }

    result = validate_reaction(
        [SpeciesAmount("left", 1)],
        [SpeciesAmount("right", coefficient)],
        species,
    )

    assert result["charge_balance"] == "failed"
    assert result["element_balance"] == "failed"


def _species(species_id: str, *, count: int, charge: int) -> Species:
    return Species(
        id=species_id,
        composition={"Ar": count},
        charge=charge,
        classes={"neutral"},
    )
