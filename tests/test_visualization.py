from pathlib import Path

from plasma_reactgen.visualization.loader import load_visualization_dataset
from plasma_reactgen.visualization.network import GraphvizOptions, build_reaction_network_dot
from plasma_reactgen.visualization.writer import write_visualizations


ROOT = Path(__file__).resolve().parents[1]


def test_visualization_outputs_are_written(tmp_path):
    outputs = ROOT / "cases" / "ar_cf4" / "outputs"
    manifest = write_visualizations(
        outputs,
        tmp_path,
        graphviz_options=GraphvizOptions(render_formats=()),
    )

    assert (tmp_path / "statistics" / "reaction_family_counts.svg").exists()
    assert (tmp_path / "statistics" / "species_charge_counts.svg").exists()
    assert (tmp_path / "network" / "reaction_network.dot").exists()
    assert (tmp_path / "network" / "species_lineage.dot").exists()
    assert manifest["statistics"]
    assert "lineage" in manifest

    reaction_type_svg = (tmp_path / "statistics" / "reaction_type_counts.svg").read_text(encoding="utf-8")
    assert "<title>electron:ionization" in reaction_type_svg
    assert "<title>ion_neutral:elastic" in reaction_type_svg


def test_reaction_network_dot_contains_state_nodes_and_reaction_edges():
    outputs = ROOT / "cases" / "ar_cf4" / "outputs"
    dataset = load_visualization_dataset(outputs)
    dot = build_reaction_network_dot(dataset, options=GraphvizOptions(render_formats=()))

    assert '"node:CF4"' in dot
    assert "e: ionization" in dot
    assert "ion: dissociative_charge_transfer" in dot
    assert "CF4" in dot
    assert "q=0" in dot
    assert "D0" in dot
