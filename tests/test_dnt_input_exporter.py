from pathlib import Path

import yaml

from plasma_reactgen.application.config import load_case_config
from plasma_reactgen.application.dnt_input_builder import build_dnt_inputs
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.infrastructure.dnt_writer import write_dnt_inputs
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.interface.cli import main


ROOT = Path(__file__).resolve().parents[1]


def _sample_network():
    registry = FileRegistry(ROOT / "registry")
    config = load_case_config(ROOT / "cases" / "ar_cf4" / "input.yaml", ROOT / "registry")
    deps = NetworkBuilderDependencies(registry, registry, registry)
    return config, ReactionNetworkBuilder(deps).generate(config)


def test_build_dnt_inputs_uses_normalized_pair_schema():
    _, network = _sample_network()
    dnt_inputs = build_dnt_inputs(network)

    assert dnt_inputs["summary"]["total_pairs"] == len(dnt_inputs["pairs"])
    pair = next(item for item in dnt_inputs["pairs"] if item["channels"])
    assert pair["model_variant"] in {"dnt_plus", "dnt_plus_dm"}
    assert pair["projectile"]["id"]
    assert pair["target"]["id"]
    assert "missing_required_properties" in pair["pair_properties"]

    channel = pair["channels"][0]
    assert {
        "reaction_id",
        "type",
        "dnt_class",
        "products",
        "threshold_eV",
        "deltaE_products_minus_reactants_eV",
        "missing_for_complete_dnt",
        "provenance",
    } <= set(channel)
    assert channel["provenance"]["source_type"] == "registry"
    if channel["threshold_eV"] is None:
        assert "threshold_eV" in channel["missing_for_complete_dnt"]
    if channel["deltaE_products_minus_reactants_eV"] is None:
        assert "deltaE_products_minus_reactants_eV" in channel["missing_for_complete_dnt"]


def test_missing_required_data_are_written_instead_of_raising():
    _, network = _sample_network()
    dnt_inputs = build_dnt_inputs(network)

    pair = next(item for item in dnt_inputs["pairs"] if item["status"] == "missing_required_data")
    missing = pair["pair_properties"]["missing_required_properties"]

    assert missing
    assert all(field.startswith(("projectile.", "target.")) for field in missing)
    assert any(
        payload["value"] is None and payload["source"] == "missing"
        for side in ("projectile", "target")
        for payload in pair[side]["properties"].values()
    )


def test_write_dnt_inputs_creates_manifest_and_pair_files(tmp_path):
    _, network = _sample_network()
    dnt_inputs = build_dnt_inputs(network)

    write_dnt_inputs(tmp_path / "outputs", dnt_inputs)

    manifest_path = tmp_path / "outputs" / "dnt_manifest.yaml"
    assert manifest_path.exists()
    assert list((tmp_path / "outputs" / "dnt_inputs").glob("*.yaml"))

    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["summary"]["total_pairs"] == len(dnt_inputs["pairs"])
    assert all((tmp_path / "outputs" / pair["file"]).exists() for pair in manifest["pairs"])


def test_generate_default_keeps_dnt_tasks_without_dnt_inputs(tmp_path):
    output_dir = tmp_path / "outputs"

    rc = main(
        [
            "generate",
            str(ROOT / "cases" / "ar_cf4" / "input.yaml"),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / "dnt_tasks.yaml").exists()
    assert build_dnt_tasks(_sample_network()[1])
    assert not (output_dir / "dnt_manifest.yaml").exists()
    assert not (output_dir / "dnt_inputs").exists()


def test_generate_writes_dnt_inputs_when_config_flag_is_enabled(tmp_path):
    source = yaml.safe_load((ROOT / "cases" / "ar_cf4" / "input.yaml").read_text(encoding="utf-8"))
    source.setdefault("outputs", {})["dnt_inputs"] = True
    input_path = tmp_path / "input.yaml"
    input_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    output_dir = tmp_path / "outputs"

    rc = main(
        [
            "generate",
            str(input_path),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / "dnt_tasks.yaml").exists()
    assert (output_dir / "dnt_manifest.yaml").exists()
    assert list((output_dir / "dnt_inputs").glob("*.yaml"))


def test_export_dnt_cli_writes_normalized_inputs(tmp_path):
    output_dir = tmp_path / "outputs"

    rc = main(
        [
            "export-dnt",
            str(ROOT / "cases" / "ar_cf4" / "input.yaml"),
            "--registry",
            str(ROOT / "registry"),
            "--output",
            str(output_dir),
        ]
    )

    assert rc == 0
    assert (output_dir / "dnt_manifest.yaml").exists()
    assert list((output_dir / "dnt_inputs").glob("*.yaml"))
