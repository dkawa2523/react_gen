"""Standalone figures retain the scope and conclusions of the saved data."""

from xml.etree import ElementTree

from reactgen.reaction_graphs import energy_graphs, judgment_graph, reaction_diagram

SVG = "{http://www.w3.org/2000/svg}"


def _parse_figure(svg: str) -> ElementTree.Element:
    return ElementTree.fromstring(svg)  # noqa: S314 - generated SVG, no external input.


def _visible_labels(svg: str) -> list[str]:
    return [item.text or "" for item in _parse_figure(svg).iter(f"{SVG}text")]


def _state(identifier: str, composition: dict, *, charge: int = 0, label: str = "") -> dict:
    return {
        "id": identifier,
        "composition": composition,
        "charge": charge,
        "state": {"kind": "electronic" if label else "ground", "label": label},
        "phase": "gas",
        "structure": None,
    }


def _terms(*species: str) -> list[dict]:
    return [{"species": name, "n": species.count(name)} for name in dict.fromkeys(species)]


def test_energy_figure_keeps_distinct_entrances_and_omits_missing_residuals() -> None:
    def branch(identifier, entrance, product, process, verdict, difference, residual) -> dict:
        return {
            "id": identifier,
            "reactants": _terms("e", entrance),
            "products": _terms("e", product),
            "process": process,
            "assessments": {"energy": {"verdict": verdict}},
            "thermochemical_calculations": {
                "state_energy_difference_eV": {"value": difference},
                "collision_energy_margin_eV": {
                    "value": residual,
                    "inputs": [{"input": "conditions.collision_energy_eV", "frame": "com"}],
                    "conditions": {"relative_collision_energy_eV": 10},
                },
            },
        }

    saved = {
        "input": {"conditions": {"collision_energy_eV": 10}},
        "metadata": {"generation": {"complete": False, "stop_reason": "max_depth=1"}},
        "states": [
            _state("e", {}, charge=-1),
            _state("Ar@ground", {"Ar": 1}),
            _state(
                "Ar@1s5",
                {"Ar": 1},
                label="state identification with a long source label ending in level 1s5",
            ),
            _state("Ar@4s", {"Ar": 1}, label="4s"),
            _state("He@ground", {"He": 1}),
        ],
    }
    finite = branch("rxn-excitation", "Ar@ground", "Ar@1s5", "excitation", "fail", 11.5, -1.5)
    missing = branch("rxn-unresolved", "Ar@ground", "Ar@4s", "excitation", "unknown", None, None)
    elastic = branch("rxn-elastic", "He@ground", "He@ground", "elastic", "pass", 0, 10)
    for branch_reaction in (finite, missing):
        margin = branch_reaction["thermochemical_calculations"]["collision_energy_margin_eV"]
        margin["inputs"][0].update(projectile_state="e", target_state="Ar@ground")
    figures = energy_graphs(saved, [finite, missing, elastic], selection="family=electron")

    assert len(figures) == 2
    ar = next(svg for name, svg in figures.items() if "Ar-ground" in name)
    he = next(svg for name, svg in figures.items() if "He-ground" in name)
    labels = _visible_labels(ar)
    assert "Residuals 1 / 2 bound · Partial exploration" in labels
    assert "e on Ar · 10 eV (com)" in labels
    assert "level 1s5)" in " ".join(labels)
    assert "Fail" in labels
    assert "Pass" not in labels
    assert "[rxn-excitation]" in ar
    assert "COM input: 10 eV; endpoint difference: 11.5 eV; residual: -1.5 eV" in ar
    assert "[rxn-unresolved]" not in ar
    assert "[rxn-elastic]" not in ar
    assert "[rxn-elastic]" in he
    assert "family=electron" in ar
    assert "Partial candidate exploration" in ar
    assert energy_graphs(saved, [missing]) == {}


def test_standalone_figures_distinguish_saved_verdicts_and_reaction_terms() -> None:
    reaction = {
        "id": "rxn-Ar-ionization",
        "family": "electron",
        "process": "ionization",
        "reactants": _terms("e", "Ar@ground"),
        "products": _terms("Ar+@ground", "e", "e"),
        "assessments": {"energy": {"verdict": "unknown"}},
    }
    outside = {"family": "electron", "assessments": {"energy": {"verdict": "not_applicable"}}}
    absent = {"family": "electron", "assessments": {}}
    chart = judgment_graph([reaction, outside, absent], "energy")
    assert "Collision energy necessary condition" in chart
    assert "Unresolved: 1 / 3" in chart
    assert "Not applicable: 1 / 3" in chart
    assert "Not recorded: 1 / 3" in chart

    saved = {
        "states": [
            _state("e", {}, charge=-1),
            _state("Ar@ground", {"Ar": 1}),
            _state("Ar+@ground", {"Ar": 1}, charge=1),
        ],
        "reactions": [reaction],
    }
    diagram = reaction_diagram(saved, reaction["id"])
    assert "Reactants" in diagram
    assert "Products" in diagram
    assert "e + Ar → Ar+ + 2 e" in diagram
    assert "Ar+@ground" in diagram
    assert "2 e" in _visible_labels(diagram)


def test_reaction_diagram_keeps_environment_outside_stoichiometric_arrows() -> None:
    state_label = "a long declared molecular state with exact suffix alpha"
    reaction = {
        "id": "rxn-surface-output",
        "family": "surface",
        "process": "surface_recombination",
        "reactants": _terms("F@ground"),
        "products": [{"species": "F2@record", "n": 0.123456789}],
        "third_body": "M",
        "surface": "reactor wall",
    }
    svg = reaction_diagram(
        {
            "states": [
                _state("F@ground", {"F": 1}),
                _state("F2@record", {"F": 2}, label=state_label),
            ],
            "reactions": [reaction],
        },
        reaction["id"],
    )
    labels = _visible_labels(svg)
    assert labels.count("M") == 2
    assert "Surface · reactor wall" in " ".join(labels)
    assert reaction["id"] not in labels
    assert f"0.123456789 F2({state_label})" in " ".join(labels)
    root = _parse_figure(svg)
    arrows = [item for item in root.iter(f"{SVG}path") if item.get("marker-end")]
    assert len(arrows) == 4
