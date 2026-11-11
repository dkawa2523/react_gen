"""The console gives the saved outcomes and a way to inspect them."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from reactgen import export
from reactgen.case import Case, CollisionPair, Conditions, Limits
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.presentation import analysis_overview


def test_overview_uses_saved_counts_and_conditions_without_expanding_work() -> None:
    saved = export.document(
        analyze(
            Case(
                "summary",
                ("Ar",),
                Conditions(gas_temperature_K=298),
                limits=Limits(max_depth=1, max_atoms=1),
                supplies=("e",),
            ),
            EvidenceCatalog(),
        )
    )
    before = deepcopy(saved)
    output = "\n".join(analysis_overview(saved))
    energy = saved["summary"]["judgments"]["reactions"]["energy"]
    assert "gas temperature = 298 K" in output
    assert "Supplied particles: Ar, e" in output
    assert f"Collision-energy check: {energy.get('pass', 0)} pass" in output
    assert f"{energy.get('unknown', 0)} unknown" in output
    assert "Conditioned pathways:" in output
    assert "Unresolved because source data are missing" not in output
    assert saved == before
    saved["states"].reverse()
    saved["reactions"].reverse()
    assert "\n".join(analysis_overview(saved)) == output


def test_cli_leads_with_targets_and_saved_values_then_next_work_and_files(
    tmp_path: Path, capsys
) -> None:
    assert main(["analyze", "Ar", "--out", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    saved = export.read(tmp_path)
    assert output.startswith("Targets: Ar\nConditions: none supplied\n")
    assert f"Usable coefficients: {saved['summary']['data_use'].get('coefficient', 0)}" in output
    assert output.index("Results:") < output.index("Optional graphs and source inspection:")
    assert str(tmp_path / "judgments") in output
    assert "--kind pathway --target STATE_ID" in output
    assert "--kind judgment --judgment energy" in output
    assert "--kind energy" not in output
    assert f'rgen needs "{tmp_path}" --detail' in output
    assert all(str(tmp_path / filename) in output for filename in export.PUBLIC_FILES)


def test_overview_reports_absent_collision_state_alongside_evaluated_pair() -> None:
    saved = export.document(
        analyze(
            Case(
                "pair scope",
                ("Ar",),
                Conditions(
                    collision_pairs=(
                        CollisionPair("e", "Ar", 17, "com"),
                        CollisionPair("e", "Ar^3+", 50, "com"),
                    )
                ),
                limits=Limits(max_depth=1, max_atoms=1),
                supplies=("e",),
            ),
            EvidenceCatalog(),
        )
    )
    assert saved["summary"]["judgments"]["reactions"]["energy"]["pass"] > 0
    output = analysis_overview(saved)
    assert "Collision pair e on Ar^3+@ground has no saved state for Ar^3+@ground." in output
    assert not any("has no saved state" in line and "e on Ar@ground" in line for line in output)


def test_formula_representation_does_not_invent_generation_limitations():
    saved = export.document(
        analyze(
            Case("scope", ("N2O", "Ar"), limits=Limits(max_depth=1, max_reactions=400)),
            EvidenceCatalog(),
        )
    )
    assert saved["metadata"]["generation"]["input_scope"] == {"Ar": "atom", "N2O": "formula_only"}
    output = "\n".join(analysis_overview(saved))
    assert "Generation operations with recorded limitations" not in output
    saved["input"]["structures"] = {"N2O@ground": "[N-]=[N+]=O"}
    assert "Generation operations with recorded limitations" not in "\n".join(
        analysis_overview(saved)
    )
    saved["metadata"]["generation"]["gaps"] = [
        {"target": "N2O@ground", "operation": "graph_input", "reason": "RDKit cannot load"}
    ]
    output = "\n".join(analysis_overview(saved))
    assert "Generation operations with recorded limitations: 1" in output
    assert "graph_input: N2O@ground; RDKit cannot load" in output
