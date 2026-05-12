from plasma_reactgen.domain.models import Species, SpeciesAmount
from plasma_reactgen.validation.validators import validate_reaction


def sp(id, composition, charge):
    return Species(id=id, composition=composition, charge=charge, classes=set())


def test_charge_and_element_balance_ok():
    species = {
        "e": sp("e", {}, -1),
        "CF4": sp("CF4", {"C": 1, "F": 4}, 0),
        "CF3": sp("CF3", {"C": 1, "F": 3}, 0),
        "F-": sp("F-", {"F": 1}, -1),
    }
    result = validate_reaction(
        [SpeciesAmount("e"), SpeciesAmount("CF4")],
        [SpeciesAmount("CF3"), SpeciesAmount("F-")],
        species,
    )
    assert result["charge_balance"] == "ok"
    assert result["element_balance"] == "ok"


def test_element_balance_failed():
    species = {
        "e": sp("e", {}, -1),
        "CF4": sp("CF4", {"C": 1, "F": 4}, 0),
        "CF3": sp("CF3", {"C": 1, "F": 3}, 0),
    }
    result = validate_reaction(
        [SpeciesAmount("e"), SpeciesAmount("CF4")],
        [SpeciesAmount("e"), SpeciesAmount("CF3")],
        species,
    )
    assert result["element_balance"] == "failed"
