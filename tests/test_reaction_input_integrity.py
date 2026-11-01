"""Source normalization must preserve valid terms and reject malformed originals."""

from pathlib import Path

import pytest

from reactgen import yamlio
from reactgen.assessment import assess_consistency
from reactgen.case import Case
from reactgen.chemistry import candidate_state, electron_state, parse_equation
from reactgen.evidence import EvidenceCatalog
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.records import ReactionRecord, RegistryReaction
from reactgen.registry import Registry


def registry_file(root: Path, products: list[dict], *, projectile: str = "e") -> Path:
    species = root / "species"
    species.mkdir(parents=True)
    (species / "Ar.yaml").write_text(
        yamlio.dump({"id": "Ar", "composition": {"Ar": 1}, "phase": "gas"}),
        encoding="utf-8",
    )
    path = root / "reactions" / "electron" / "pair.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yamlio.dump(
            {
                "pair": {"family": "electron", "projectile": projectile, "target": "Ar"},
                "channels": [
                    {
                        "id": "source-elastic",
                        "type": "elastic",
                        "products": products,
                        "status": "reviewed",
                        "source_record": {"source_id": "synthetic-boundary"},
                        "review_scope": ["channel_assertion"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("count", [-1, 0, float("nan"), float("inf"), True, None, "bad", 10**400])
def test_registry_rejects_each_original_coefficient_before_combining(
    tmp_path: Path, count: object
) -> None:
    root = tmp_path / "registry"
    path = registry_file(
        root,
        [{"species": "e"}, {"species": "Ar", "n": count}, {"species": "Ar", "n": 2}],
    )
    with pytest.raises(ValueError, match="source-elastic") as error:
        EvidenceCatalog.load(root)
    assert str(path) in str(error.value)
    assert "source-elastic" in str(error.value)


@pytest.mark.parametrize("coefficient", ["-1", "0", "nan", "inf", "-inf"])
def test_equation_parser_rejects_invalid_terms_before_combining(coefficient: str) -> None:
    assert parse_equation(f"e + Ar -> e + {coefficient} Ar + 2 Ar") is None
    assert parse_equation(f"e + {coefficient} Ar + 2 Ar -> e + Ar") is None
    assert parse_equation(f"Ar + {coefficient} M -> Ar + M") is None


@pytest.mark.parametrize("third_body", ["2 M", "M + M"])
def test_equation_parser_does_not_discard_third_body_multiplicity(third_body: str) -> None:
    assert parse_equation(f"Ar + {third_body} -> Ar + {third_body}") is None


@pytest.mark.parametrize("side", ["reactants", "products"])
@pytest.mark.parametrize("count", [-1, 0, float("nan"), float("inf"), True, 10**400])
def test_direct_scientific_records_reject_invalid_original_terms(side: str, count: float) -> None:
    terms = {"reactants": [Term("Ar")], "products": [Term("Ar")]}
    terms[side] = [Term("Ar", count), Term("Ar", 2)]
    with pytest.raises(ValueError, match="stoichiometric coefficient"):
        RegistryReaction("source", "neutral", "elastic", **terms)
    equation = (None, None, tuple(terms["reactants"]), tuple(terms["products"]))
    with pytest.raises(ValueError, match="stoichiometric coefficient"):
        ReactionRecord("source", equation, "neutral", "elastic", (candidate_state({"Ar": 1}, 0),))


def test_duplicate_positive_counts_cannot_overflow_the_canonical_equation(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    registry_file(root, [{"species": "Ar", "n": 1e308}, {"species": "Ar", "n": 1e308}])
    with pytest.raises(ValueError, match="summed stoichiometric coefficient"):
        EvidenceCatalog.load(root)
    assert parse_equation("Ar -> 1e308 Ar + 1e308 Ar") is None


def test_positive_fractional_duplicates_keep_their_meaning(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    registry_file(
        root,
        [{"species": "e"}, {"species": "Ar", "n": "0.25"}, {"species": "Ar", "n": 0.75}],
    )
    registry = Registry.load(root)
    assert [term.n for term in registry.channels[("electron", "e", "Ar")][0].products] == [
        1,
        0.25,
        0.75,
    ]
    parsed = parse_equation("e + 0.25 Ar + 0.75 Ar -> e + Ar")
    assert parsed is not None
    assert parsed[0][2] == parsed[0][3]
    result = analyze(Case("fractions", ("Ar",)), EvidenceCatalog.load(root))
    elastic = next(
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.process == "elastic" and reaction.reactants == (Term("e"), Term("Ar@ground"))
    )
    assessments = result.evaluation.reaction_assessments[elastic.id]
    assert assessments["consistency"].verdict == "pass"
    assert assessments["reaction_evidence"].verdict == "pass"


@pytest.mark.parametrize("position", ["reactant", "product"])
def test_unregistered_registry_reference_is_an_input_error(tmp_path: Path, position: str) -> None:
    root = tmp_path / "registry"
    path = registry_file(
        root,
        [{"species": "e"}, {"species": "Ar_typo" if position == "product" else "Ar"}],
        projectile="Ar_typo" if position == "reactant" else "e",
    )
    for loader in (Registry.load, EvidenceCatalog.load):
        with pytest.raises(ValueError, match="unregistered species") as error:
            loader(root)
        assert str(path) in str(error.value)
        assert "source-elastic" in str(error.value)
        assert "unregistered species: Ar_typo" in str(error.value)


@pytest.mark.parametrize("count", [-1, 0, float("nan"), float("inf"), True])
def test_invalid_candidate_remains_a_scientific_consistency_failure(count: float) -> None:
    atom, electron = candidate_state({"Ar": 1}, 0), electron_state()
    candidate = ReactionCandidate(
        "invalid-hypothesis",
        (Term(electron.id), Term(atom.id)),
        (Term(electron.id), Term(atom.id, count), Term(atom.id, 2)),
        "electron",
        "elastic",
        "test",
        "test",
        0,
    )
    result = assess_consistency(candidate, CandidateSet(states={s.id: s for s in (atom, electron)}))
    assert result.verdict == "fail"


@pytest.mark.parametrize("assertion", [{"reaction": "e + Ne -> e + Ne"}, {"type": "ionization"}])
def test_registry_rejects_a_dataset_asserting_another_target(
    tmp_path: Path, assertion: dict
) -> None:
    root = tmp_path / "registry"
    path = registry_file(root, [{"species": "e"}, {"species": "Ar"}])
    document = yamlio.load(path.read_text(encoding="utf-8"))
    document["channels"][0]["data"] = {
        "datasets": [{"id": "measured-rate", "kind": "rate_coefficient", **assertion}]
    }
    path.write_text(yamlio.dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="physical target") as error:
        Registry.load(root)
    assert "measured-rate" in str(error.value)
    assert "source-elastic" in str(error.value)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("reverse", [False, True])
def test_registry_rejects_one_numerical_id_on_different_channels(
    tmp_path: Path, reverse: bool
) -> None:
    root = tmp_path / "registry"
    path = registry_file(root, [{"species": "e"}, {"species": "Ar"}])
    (root / "species" / "Ne.yaml").write_text(
        yamlio.dump({"id": "Ne", "composition": {"Ne": 1}, "phase": "gas"}), encoding="utf-8"
    )
    document = yamlio.load(path.read_text(encoding="utf-8"))
    for index, gas in enumerate(("Ne", "Ar") if reverse else ("Ar", "Ne")):
        document["pair"]["target"] = gas
        channel = document["channels"][0]
        channel["id"] = f"elastic-{gas}"
        channel["products"][1]["species"] = gas
        channel["data"] = {"datasets": [{"id": "same-record", "kind": "rate_coefficient"}]}
        (path.parent / f"{index}.yaml").write_text(yamlio.dump(document), encoding="utf-8")
    with pytest.raises(ValueError, match="different physical targets: same-record"):
        Registry.load(root)
