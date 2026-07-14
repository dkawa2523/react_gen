from pathlib import Path

import pytest

from plasma_reactgen.interface.cli import main
from plasma_reactgen.visualization.loader import load_visualization_dataset
from plasma_reactgen.visualization.network import GraphvizOptions, build_reaction_network_dot
from plasma_reactgen.visualization.writer import write_visualizations


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def generated_outputs(tmp_path):
    outputs = tmp_path / "generated"
    assert main(
        [
            "generate",
            str(ROOT / "cases" / "ar_cf4" / "input.yaml"),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(outputs),
        ]
    ) == 0
    return outputs


def test_visualization_outputs_are_written(tmp_path, generated_outputs):
    manifest = write_visualizations(
        generated_outputs,
        tmp_path,
        graphviz_options=GraphvizOptions(render_formats=()),
    )

    assert (tmp_path / "statistics" / "reaction_family_counts.svg").exists()
    assert (tmp_path / "statistics" / "species_charge_counts.svg").exists()
    assert (tmp_path / "network" / "reaction_network.dot").exists()
    assert (tmp_path / "network" / "species_lineage.dot").exists()
    assert (tmp_path / "network" / "reaction_equation_network.svg").exists()
    assert manifest["statistics"]
    assert "lineage" in manifest
    assert manifest["reaction_pathway"]["reaction_nodes"] > 0

    reaction_type_svg = (tmp_path / "statistics" / "reaction_type_counts.svg").read_text(encoding="utf-8")
    assert "<title>electron:ionization" in reaction_type_svg
    assert "<title>ion_neutral:elastic" in reaction_type_svg


def test_reaction_network_dot_contains_state_nodes_and_reaction_edges(generated_outputs):
    dataset = load_visualization_dataset(generated_outputs)
    dot = build_reaction_network_dot(dataset, options=GraphvizOptions(render_formats=()))

    assert '"node:CF4"' in dot
    assert "e: ionization" in dot
    assert "ion: dissociative_charge_transfer" in dot
    assert "CF4" in dot
    assert "q=0" in dot
    assert "D0" in dot


def test_reaction_pathway_svg_contains_equations_and_precursors(tmp_path, generated_outputs):
    manifest = write_visualizations(
        generated_outputs,
        tmp_path,
        graphviz_options=GraphvizOptions(render_formats=()),
    )

    svg = (tmp_path / "network" / "reaction_equation_network.svg").read_text(encoding="utf-8")
    assert "反応経路図" in svg
    assert "e + CF4" in svg
    assert "precursor_edges" not in svg
    assert manifest["reaction_pathway"]["precursor_edges"] > 0
