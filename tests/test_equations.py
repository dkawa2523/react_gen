from plasma_reactgen.domain.equations import format_equation
from plasma_reactgen.domain.models import SpeciesAmount


def test_format_equation():
    equation = format_equation(
        [SpeciesAmount("e"), SpeciesAmount("CF4")],
        [SpeciesAmount("e", 2), SpeciesAmount("CF4+")],
    )
    assert equation == "e + CF4 -> 2 e + CF4+"
