from plasma_reactgen.domain.models import PropertyValue, Species
from plasma_reactgen.inference import (
    composition_mass_amu,
    make_basic_fragment_candidates,
    make_parent_ion_candidates,
    parse_formula,
)


def test_parse_formula_supports_initial_scope():
    assert parse_formula("CF4") == {"C": 1, "F": 4}
    assert parse_formula("Ar") == {"Ar": 1}
    assert parse_formula("O2") == {"O": 2}
    assert parse_formula("N2") == {"N": 2}
    assert parse_formula("H2") == {"H": 2}
    assert parse_formula("SiH4") == {"Si": 1, "H": 4}
    assert parse_formula("C2F6") == {"C": 2, "F": 6}
    assert parse_formula("Cl2") == {"Cl": 2}
    assert parse_formula("C2H6") == {"C": 2, "H": 6}
    assert parse_formula("CHF3") == {"C": 1, "H": 1, "F": 3}


def test_parse_formula_rejects_unsupported_notation():
    assert parse_formula("CF4+") == {}
    assert parse_formula("C(OH)4") == {}
    assert parse_formula("Ar*") == {}


def test_composition_mass_returns_number_or_none():
    assert composition_mass_amu({"C": 1, "F": 4}) > 0
    assert composition_mass_amu({"Xe": 1}) is None
    assert composition_mass_amu({"C": 0}) is None


def test_parent_ion_candidates_for_neutral_species_are_inferred():
    candidates = make_parent_ion_candidates(
        {
            "id": "CF4",
            "composition": {"C": 1, "F": 4},
            "charge": 0,
            "properties": {"mass_amu": {"value": 88.004, "unit": "amu"}},
        }
    )

    assert {candidate["id"] for candidate in candidates} == {"CF4_p", "CF4_m"}
    assert {candidate["charge"] for candidate in candidates} == {1, -1}
    assert {candidate["kind"] for candidate in candidates} == {"species_candidate"}
    assert all(candidate["composition"] == {"C": 1, "F": 4} for candidate in candidates)
    assert all(candidate["status"] == "inferred" for candidate in candidates)


def test_parent_ion_candidates_accept_species_objects_and_skip_charged_parents():
    neutral = Species(
        id="CF4",
        composition={"C": 1, "F": 4},
        charge=0,
        classes={"neutral", "molecule"},
        properties={"mass_amu": PropertyValue(value=88.004, unit="amu", source="curated")},
    )
    charged = Species(id="CF4_p", composition={"C": 1, "F": 4}, charge=1, classes={"ion"})

    assert {candidate["charge"] for candidate in make_parent_ion_candidates(neutral)} == {1, -1}
    assert make_parent_ion_candidates(charged) == []


def test_basic_fragment_candidates_for_cf4_include_cf3_and_f():
    candidates = make_basic_fragment_candidates(
        {"id": "CF4", "formula": "CF4", "composition": {"C": 1, "F": 4}, "charge": 0}
    )

    fragment_pairs = [
        [fragment["composition"] for fragment in candidate["fragments"]]
        for candidate in candidates
    ]
    assert [{"C": 1, "F": 3}, {"F": 1}] in fragment_pairs
    assert all(candidate["kind"] == "fragment_set_candidate" for candidate in candidates)
    assert all(candidate["status"] == "inferred" for candidate in candidates)


def test_basic_fragment_candidates_respect_depth_limit():
    assert make_basic_fragment_candidates({"id": "CF4", "formula": "CF4", "charge": 0}, max_fragment_depth=0) == []
