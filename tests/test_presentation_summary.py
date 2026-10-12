"""Readable summaries use saved numerical values and keep work responsibilities distinct."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from reactgen import export, needs
from reactgen.case import Case, Conditions
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.presentation import analysis_overview, reaction_equation, state_name


def test_overview_retains_zero_unit_conditions_and_separates_models_from_inputs() -> None:
    saved = export.document(
        analyze(
            Case("summary", ("Ar",), Conditions(gas_temperature_K=298)), EvidenceCatalog.load(None)
        )
    )
    reaction = saved["reactions"][0]
    reaction["data_use"].update(
        status="coefficient", dataset_id="nominal", kind="rate_coefficient", value=0, unit="m3/s"
    )
    pending = saved["reactions"][1]["data_use"]
    pending.update(
        status="needs_input", required_inputs=["electron_energy_distribution", "ion_temperature"]
    )
    reaction["evidence"]["overlay_datasets"] = [
        {
            "id": "nominal",
            "validity": {
                "quantity": "gas_temperature",
                "minimum": 100,
                "maximum": 400,
                "unit": "K",
            },
        }
    ]
    before = deepcopy(saved)
    work = needs.build(saved)
    output = "\n".join(analysis_overview(saved, work))
    names = {state["id"]: state_name(state) for state in saved["states"]}
    assert f"{reaction_equation(reaction, names)}: rate coefficient = 0 m3/s" in output
    assert "gas temperature = 298 K" in output
    assert "declared applicability: gas_temperature [100, 400] K" in output
    assert "conditions.ion_temperature_K" in output
    assert "conditions.electron_energy_distribution" not in output
    assert (
        f"Next work: {work['summary']['known_prerequisites']} "
        "distinct known target/quantity prerequisites" in output
    )
    assert "saved work groups" not in output
    assert f"Other saved findings: {work['summary']['findings_without_prerequisites']}" in output
    assert "mechanism" in output
    assert "predictive" in output
    assert saved == before
    saved["states"].reverse()
    saved["reactions"].reverse()
    assert "\n".join(analysis_overview(saved, needs.build(saved))) == output


def test_cli_leads_with_targets_and_saved_values_then_next_work_and_files(
    tmp_path: Path, capsys
) -> None:
    assert main(["analyze", "Ar", "--out", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    saved = export.read(tmp_path)
    assert output.startswith("Targets: Ar\nConditions: none supplied\n")
    assert f"Usable coefficients: {saved['summary']['data_use'].get('coefficient', 0)}" in output
    assert (
        output.index("Next work:")
        < output.index("Results:")
        < output.index(str(tmp_path / "result.yaml"))
    )
    assert all(str(tmp_path / filename) in output for filename in export.PUBLIC_FILES)
