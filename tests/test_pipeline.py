"""Policy, bundle, CLI and canonical-ingest behavior."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml
from PIL import Image

from reactgen import adopt, export, ingest
from reactgen.assessment import Evaluation
from reactgen.case import Case, Conditions, Limits
from reactgen.cli import main
from reactgen.evidence import EvidenceCatalog
from reactgen.model import Assessment, CandidateSet
from reactgen.pipeline import run, select
from reactgen.registry import Registry

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


def _case(gases: tuple[str, ...] = ("Ar",), limits: Limits | None = None) -> Case:
    return Case("test", gases, limits=limits or Limits())


def test_registry_does_not_change_the_mechanical_set() -> None:
    case = _case(("Ar", "F2"))
    empty = run(case, EvidenceCatalog.load(None))
    filled = run(case, EvidenceCatalog.load(FIXTURE))
    empty_keys = {
        reaction.key
        for reaction in empty.candidates.reactions.values()
        if reaction.origin == "mechanical"
    }
    filled_keys = {
        reaction.key
        for reaction in filled.candidates.reactions.values()
        if reaction.origin == "mechanical"
    }
    assert empty_keys == filled_keys


def test_three_body_source_vocabulary_merges_into_the_mechanical_channel() -> None:
    result = run(_case(("O2",)), EvidenceCatalog.load(Path("registry")))
    association = [
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.equation == "2 O@ground + M -> O2@ground + M"
    ]
    assert len(association) == 1
    reaction = association[0]
    assert (reaction.family, reaction.process, reaction.origin) == (
        "neutral",
        "three_body_association",
        "mechanical",
    )
    assert (
        result.evaluation.reaction_assessments[reaction.id]["reaction_evidence"].verdict == "pass"
    )


def test_review_keeps_every_candidate_and_strict_excludes_unknown_kinetics() -> None:
    result = run(_case(), EvidenceCatalog.load(None))
    assert result.evaluation.state_assessments["Ar@ground"]["state"].verdict == "unknown"
    assert set(result.selection.reaction_ids) == set(result.candidates.reactions)
    strict = select(result.candidates, result.evaluation, "strict_simulation")
    assert not strict.reaction_ids
    assert all(
        any(
            layer in reason
            for layer in ("state", "thermochemistry", "reaction_evidence", "kinetics")
        )
        for reason in strict.excluded_reactions.values()
    )


def test_energy_policy_requires_thermochemistry() -> None:
    result = run(_case(), EvidenceCatalog.load(FIXTURE))
    energy = select(result.candidates, result.evaluation, "energy_balance")
    assert all(
        result.evaluation.thermo_capabilities[reaction_id].reaction_enthalpy_ready
        for reaction_id in energy.reaction_ids
    )


def test_exploratory_policy_allows_unknown_consistency_but_not_failure() -> None:
    result = run(_case(), EvidenceCatalog.load(None))
    reaction_id = next(iter(result.candidates.reactions))
    passed = Assessment("pass")
    unknown = Assessment("unknown")
    evaluation = Evaluation(
        state_assessments=result.evaluation.state_assessments,
        reaction_assessments={
            reaction_id: {
                "consistency": unknown,
                "state": unknown,
                "thermochemistry": unknown,
                "reaction_evidence": unknown,
                "kinetics": passed,
            }
        },
        state_evidence=result.evaluation.state_evidence,
        reaction_evidence=result.evaluation.reaction_evidence,
        thermochemistry=result.evaluation.thermochemistry,
        estimated_kinetics=result.evaluation.estimated_kinetics,
        thermo_capabilities=result.evaluation.thermo_capabilities,
        kinetics_capabilities=result.evaluation.kinetics_capabilities,
    )
    one_reaction = CandidateSet(
        states=result.candidates.states,
        reactions={reaction_id: result.candidates.reactions[reaction_id]},
    )
    assert select(one_reaction, evaluation, "exploratory_simulation").reaction_ids == (reaction_id,)

    evaluation.reaction_assessments[reaction_id]["consistency"] = Assessment("fail")
    assert not select(one_reaction, evaluation, "exploratory_simulation").reaction_ids

    evaluation.reaction_assessments[reaction_id]["consistency"] = Assessment("pass")
    evaluation.reaction_assessments[reaction_id]["state"] = Assessment("fail")
    assert not select(one_reaction, evaluation, "acquisition").reaction_ids


def test_simulation_policies_reject_thermochemical_failure() -> None:
    result = run(_case(), EvidenceCatalog.load(None))
    reaction_id = next(iter(result.candidates.reactions))
    passed = Assessment("pass")
    evaluation = result.evaluation
    evaluation.reaction_assessments[reaction_id] = {
        "consistency": passed,
        "state": passed,
        "thermochemistry": Assessment("fail"),
        "reaction_evidence": passed,
        "kinetics": passed,
    }
    one_reaction = CandidateSet(
        states=result.candidates.states,
        reactions={reaction_id: result.candidates.reactions[reaction_id]},
    )
    assert not select(one_reaction, evaluation, "exploratory_simulation").reaction_ids
    assert not select(one_reaction, evaluation, "strict_simulation").reaction_ids


def test_bundle_is_exactly_three_deterministic_files(tmp_path: Path) -> None:
    result = run(_case(), EvidenceCatalog.load(None))
    first = tmp_path / "first"
    second = tmp_path / "second"
    export.write(first, result)
    export.write(second, result)
    assert sorted(path.name for path in first.iterdir()) == [
        "reactions.yaml",
        "selected.yaml",
        "states.yaml",
    ]
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {
        path.name: path.read_bytes() for path in second.iterdir()
    }
    selected = yaml.safe_load((first / "selected.yaml").read_text(encoding="utf-8"))
    assert selected["metadata"]["complete"] is True
    assert selected["metadata"]["generator_version"] == "0.5.0"
    assert selected["metadata"]["schema_version"] == 4
    assert "readiness" in selected
    assert "not_selected_states" in selected
    assert "not_selected_reactions" in selected


def test_optional_review_views_are_grouped_deterministic_and_follow_policy(
    tmp_path: Path,
) -> None:
    result = run(_case(), EvidenceCatalog.load(None), "strict_simulation")
    first = tmp_path / "first"
    second = tmp_path / "second"
    export.write(first, result, include_csv=True)
    export.write(second, result, include_csv=True)

    expected_files = _expected_review_files()
    assert _relative_files(first) == expected_files
    assert {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }

    with (first / "states.csv").open(encoding="utf-8", newline="") as stream:
        states = list(csv.DictReader(stream))
    with (first / "reactions.csv").open(encoding="utf-8", newline="") as stream:
        reactions = list(csv.DictReader(stream))

    assert len(states) == len(result.candidates.states)
    assert len(reactions) == len(result.candidates.reactions)
    assert states[0]["id"] == "Ar@ground"
    assert [int(row["depth"]) for row in reactions] == sorted(
        int(row["depth"]) for row in reactions
    )
    assert {row["selected"] for row in reactions} == {"false"}
    assert {row["consistency_verdict"] for row in reactions} == {"pass"}
    assert all(row["exclusion_reason"] for row in reactions)
    assert list(states[0]) == [
        "species",
        "formula",
        "charge",
        "excitation",
        "resolution",
        "lifetime_class",
        "state_label",
        "state_symbol",
        "state_meaning",
        "alternative_resolution_states",
        "structure_scope",
        "origin",
        "depth",
        "state_verdict",
        "thermochemistry_verdict",
        "selected",
        "state_energy_eV",
        "lifetime_s",
        "mass_amu",
        "enthalpy_formation_eV",
        "ionization_energy_eV",
        "electron_affinity_eV",
        "id",
    ]
    assert list(reactions[0]) == [
        "equation",
        "reaction_type",
        "family",
        "process",
        "origin",
        "depth",
        "consistency_verdict",
        "state_verdict",
        "thermochemistry_verdict",
        "reaction_evidence_verdict",
        "kinetics_verdict",
        "delta_h_eV",
        "delta_g_eV",
        "threshold_eV",
        "kinetic_data",
        "selected",
        "exclusion_reason",
        "id",
    ]
    family_files = {
        "electron": "reactions_electron.csv",
        "ion": "reactions_ion.csv",
        "neutral": "reactions_neutral.csv",
        "surface": "reactions_surface.csv",
    }
    reaction_ids_by_family = {
        family: {row["id"] for row in reactions if row["family"] == family}
        for family in family_files
    }
    for family, filename in family_files.items():
        with (first / filename).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        assert reader.fieldnames == list(reactions[0])
        assert {row["id"] for row in rows} == reaction_ids_by_family[family]
    argon_ion = next(row for row in states if row["id"] == "Ar+@ground")
    assert argon_ion["species"] == "Ar+"
    argon_metastable = next(row for row in states if row["id"] == "Ar@metastable")
    assert (
        argon_metastable["species"],
        argon_metastable["state_label"],
        argon_metastable["state_symbol"],
    ) == (
        "Ar(m)",
        "metastable",
        "m",
    )
    assert (argon_metastable["excitation"], argon_metastable["lifetime_class"]) == (
        "electronic",
        "metastable",
    )
    assert argon_metastable["state_meaning"] == ("metastable electronic-state manifold (lumped)")
    argon_resonant = next(row for row in states if row["id"] == "Ar@resonant")
    assert (
        argon_resonant["species"],
        argon_resonant["state_label"],
        argon_resonant["state_symbol"],
    ) == (
        "Ar(r)",
        "resonant",
        "r",
    )
    assert all("@" not in row["equation"] for row in reactions)
    assert all(row["reaction_type"] for row in reactions)
    assert any(row["reaction_type"] == "Electron-impact ionization" for row in reactions)

    with (first / "assessments/state/states.csv").open(encoding="utf-8", newline="") as stream:
        state_layer = list(csv.DictReader(stream))
    assert len(state_layer) == len(states)
    assert list(state_layer[0]) == [
        "candidate",
        "excitation",
        "resolution",
        "lifetime_class",
        "state_meaning",
        "alternative_resolution_states",
        "evidence",
        "verdict",
        "reason",
        "id",
    ]
    assessment_expectations = {
        "consistency": (
            [
                "candidate",
                "excitation",
                "resolution",
                "lifetime_class",
                "state_meaning",
                "alternative_resolution_states",
                "verdict",
                "reason",
                "id",
            ],
            ["candidate", "reaction_type", "verdict", "reason", "id"],
            len(states),
        ),
        "state": (
            [
                "candidate",
                "excitation",
                "resolution",
                "lifetime_class",
                "state_meaning",
                "alternative_resolution_states",
                "evidence",
                "verdict",
                "reason",
                "id",
            ],
            ["candidate", "reaction_type", "verdict", "reason", "id"],
            len(states),
        ),
        "thermochemistry": (
            [
                "candidate",
                "excitation",
                "resolution",
                "lifetime_class",
                "state_meaning",
                "alternative_resolution_states",
                "verdict",
                "reason",
                "id",
            ],
            [
                "candidate",
                "reaction_type",
                "delta_h_eV",
                "delta_g_eV",
                "threshold_eV",
                "verdict",
                "reason",
                "id",
            ],
            len(states),
        ),
        "reaction_evidence": (
            None,
            [
                "candidate",
                "reaction_type",
                "matched_source",
                "channel_scope",
                "verdict",
                "reason",
                "id",
            ],
            0,
        ),
        "kinetics": (
            None,
            [
                "candidate",
                "reaction_type",
                "data_kind",
                "unit",
                "applicable_range",
                "dataset_id",
                "verdict",
                "reason",
                "id",
            ],
            0,
        ),
    }
    for layer, (state_header, reaction_header, state_count) in assessment_expectations.items():
        directory = first / "assessments" / layer
        state_path = directory / "states.csv"
        if state_header is None:
            assert not state_path.exists()
        else:
            with state_path.open(encoding="utf-8", newline="") as stream:
                state_reader = csv.DictReader(stream)
                state_rows = list(state_reader)
            assert len(state_rows) == state_count
            assert state_reader.fieldnames == state_header
        with (directory / "reactions.csv").open(encoding="utf-8", newline="") as stream:
            reaction_reader = csv.DictReader(stream)
            reaction_rows = list(reaction_reader)
        assert len(reaction_rows) == len(reactions)
        assert reaction_reader.fieldnames == reaction_header
        for family, filename in family_files.items():
            with (directory / filename).open(encoding="utf-8", newline="") as stream:
                family_reader = csv.DictReader(stream)
                family_rows = list(family_reader)
            assert family_reader.fieldnames == reaction_header
            assert {row["id"] for row in family_rows} == reaction_ids_by_family[family]
        assert not (directory / "assessment.csv").exists()
        with (directory / "summary.csv").open(encoding="utf-8", newline="") as stream:
            summary = {row["entity"]: row for row in csv.DictReader(stream)}
        assert int(summary["state"]["total"]) == state_count
        assert int(summary["reaction"]["total"]) == len(reactions)
        assert int(summary["all"]["total"]) == state_count + len(reactions)
        for chart in (
            "verdict_counts.svg",
            "reaction_family.svg",
        ):
            svg = (directory / chart).read_text(encoding="utf-8")
            assert svg.startswith("<svg")
            assert layer.replace("_", " ").title() in svg
        with (directory / "family_summary.csv").open(encoding="utf-8", newline="") as stream:
            family_summary = list(csv.DictReader(stream))
        assert family_summary
        assert list(family_summary[0]) == [
            "family",
            "pass",
            "fail",
            "unknown",
            "not_applicable",
            "total",
        ]
        assert sum(int(row["total"]) for row in family_summary) == len(reactions)

    screening_expectations = (
        ("state_consistency", (("state",), ("consistency",))),
        (
            "state_consistency_thermochemistry",
            (("state",), ("consistency",), ("thermochemistry",)),
        ),
        (
            "state_consistency_thermochemistry_kinetics_or_reaction_evidence",
            (
                ("state",),
                ("consistency",),
                ("thermochemistry",),
                ("kinetics", "reaction_evidence"),
            ),
        ),
    )
    for stage, gates in screening_expectations:
        directory = first / "assessments" / "screening" / stage
        with (directory / "states.csv").open(encoding="utf-8", newline="") as stream:
            screened_state_reader = csv.DictReader(stream)
            screened_states = list(screened_state_reader)
        with (directory / "reactions.csv").open(encoding="utf-8", newline="") as stream:
            screened_reaction_reader = csv.DictReader(stream)
            screened_reactions = list(screened_reaction_reader)
        expected_state_ids = {
            state_id
            for state_id, assessed in result.evaluation.state_assessments.items()
            if all(
                not any(layer in assessed for layer in gate)
                or any(layer in assessed and assessed[layer].verdict == "pass" for layer in gate)
                for gate in gates
            )
        }
        expected_reaction_ids = {
            reaction_id
            for reaction_id, assessed in result.evaluation.reaction_assessments.items()
            if all(any(assessed[layer].verdict == "pass" for layer in gate) for gate in gates)
        }
        assert {row["id"] for row in screened_states} == expected_state_ids
        assert all(row["state_meaning"] for row in screened_states)
        assert screened_state_reader.fieldnames is not None
        assert "passed_layers" not in screened_state_reader.fieldnames
        assert {row["id"] for row in screened_reactions} == expected_reaction_ids
        for family, filename in family_files.items():
            with (directory / filename).open(encoding="utf-8", newline="") as stream:
                family_reader = csv.DictReader(stream)
                family_rows = list(family_reader)
            assert family_reader.fieldnames == screened_reaction_reader.fieldnames
            assert {row["id"] for row in family_rows} == (
                expected_reaction_ids & reaction_ids_by_family[family]
            )
        assert screened_reaction_reader.fieldnames is not None
        assert {
            "kinetics_verdict",
            "reaction_evidence_verdict",
            "kinetics_or_reaction_evidence_verdict",
            "accepted_by",
        } <= set(screened_reaction_reader.fieldnames)
        assert "screen_rule" not in screened_reaction_reader.fieldnames
        with (directory / "summary.csv").open(encoding="utf-8", newline="") as stream:
            screening_summary = list(csv.DictReader(stream))
        assert len(screening_summary) == 2 * (len(gates) + 1)
        assert [row["step"] for row in screening_summary if row["entity"] == "reaction"] == [
            "all",
            *("_or_".join(gate) for gate in gates),
        ]
        svg = (directory / "retention.svg").read_text(encoding="utf-8")
        assert svg.startswith("<svg")
        assert "screening" in svg.lower()

    explorer = first / "assessments" / "network.html"
    html = explorer.read_text(encoding="utf-8")
    payload = _network_payload(html)
    assert payload["case"] == "test"
    assert len(payload["states"]) == len(states)
    assert len(payload["reactions"]) == len(reactions)
    assert {reaction["id"] for reaction in payload["reactions"]} == {
        reaction["id"] for reaction in reactions
    }
    assert len(payload["views"]) == 8
    assert "click a state node" in html.lower()
    assert "Reaction-state stoichiometric matrix" in html
    assert "one reaction per column" in html.lower()
    assert "Hierarchical pathways" in html
    assert "all reactants" in html.lower()
    assert "candidate generation depth is not used" in html.lower()
    assert payload["seed_state_ids"] == ["Ar@ground", "e"]
    assert payload["pathway_default_target"] is None or payload["pathway_default_target"] in {
        state["id"] for state in payload["states"]
    }
    assert "Net producers" in html
    assert "Zero-net participants" in html
    assert "independent paging" in html
    assert not list(first.rglob("network*.svg"))
    assert not [path for path in first.rglob("network") if path.is_dir()]

    with (first / "assessments/statistics.csv").open(encoding="utf-8", newline="") as stream:
        statistics = list(csv.DictReader(stream))
    assert list(statistics[0]) == ["metric", "layer", "entity", "category", "count", "total"]
    assert {row["layer"] for row in statistics if row["metric"] == "assessment_verdict"} == set(
        assessment_expectations
    )
    assert {row["metric"] for row in statistics} >= {
        "reaction_readiness",
        "state_charge",
        "state_excitation",
        "state_resolution",
        "state_lifetime_class",
        "reaction_family",
        "reaction_depth",
    }
    statistics_svg = (first / "assessments/statistics.svg").read_text(encoding="utf-8")
    assert "Overall assessment" in statistics_svg
    assert "Cumulative pass-only coverage" in statistics_svg
    assert "Independent reaction verdicts" in statistics_svg
    composition_svg = (first / "assessments/composition.svg").read_text(encoding="utf-8")
    assert "Generated candidate composition" in composition_svg
    assert "States by charge" in composition_svg
    assert "States by excitation" in composition_svg
    assert "States by resolution" in composition_svg
    assert "States by lifetime class" in composition_svg
    assert "Reactions by family" in composition_svg
    assert "Reactions by generation depth" in composition_svg

    export.write(first, result)
    assert sorted(path.name for path in first.iterdir()) == [
        "reactions.yaml",
        "selected.yaml",
        "states.yaml",
    ]


def test_single_network_explorer_contains_every_reaction_without_image_pages(
    tmp_path: Path,
) -> None:
    result = run(_case(("O2",)), EvidenceCatalog.load(None))
    out = tmp_path / "oxygen"
    export.write(out, result, include_csv=True)
    explorers = list(out.rglob("network.html"))
    assert explorers == [out / "assessments" / "network.html"]
    payload = _network_payload(explorers[0].read_text(encoding="utf-8"))
    assert len(payload["reactions"]) == len(result.candidates.reactions)
    assert {reaction["id"] for reaction in payload["reactions"]} == set(result.candidates.reactions)
    assert not list(out.rglob("page_*.svg"))
    png = out / "assessments" / "network.png"
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(png) as image:
        assert image.info["reactgen.reaction_count"] == str(len(result.candidates.reactions))
        assert image.info["reactgen.scope"] == "all_candidates_no_sampling"
    pathway = out / "assessments" / "pathways.png"
    assert pathway.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(pathway) as image:
        assert image.info["reactgen.scope"] == "target_centered_canonical_hyperpath"
        assert int(image.info["reactgen.path_reaction_count"]) > 0


def test_state_csv_separates_identity_display_lifetime_and_resolution(tmp_path: Path) -> None:
    result = run(
        _case(("Ar", "O2")),
        EvidenceCatalog.load(Path("registry")),
    )
    out = tmp_path / "bundle"
    export.write(out, result, include_csv=True)
    with (out / "states.csv").open(encoding="utf-8", newline="") as stream:
        states = {row["id"]: row for row in csv.DictReader(stream)}

    assert states["Ar@4s"]["species"] == "Ar(4s)"
    assert states["Ar@4s"]["lifetime_class"] == "mixed_metastable_resonant"
    assert states["Ar@4s"]["state_energy_eV"] == "11.6"
    for state_id in ("Ar@metastable", "Ar@resonant"):
        assert states[state_id]["state_energy_eV"] == ""

    assert "O2(a¹Δg)" in states["O2@electronic"]["alternative_resolution_states"]
    assert "O2(b¹Σg+)" in states["O2@electronic"]["alternative_resolution_states"]
    assert states["O2@a1dg"]["alternative_resolution_states"] == "O2*"
    assert states["O2@electronic"]["structure_scope"] == "formula_determined"

    with (out / "reactions.csv").open(encoding="utf-8", newline="") as stream:
        reactions = list(csv.DictReader(stream))
    equations = {row["equation"] for row in reactions}
    assert "e + Ar -> Ar(4s) + e" in equations
    assert "Ar + e -> Ar(4s) + e" not in equations

    reaction_document = yaml.safe_load((out / "reactions.yaml").read_text(encoding="utf-8"))
    for reaction in reaction_document["reactions"]:
        if reaction["family"] == "electron":
            assert reaction["reactants"][0]["species"] == "e"
            product_ids = [term["species"] for term in reaction["products"]]
            if "e" in product_ids:
                assert product_ids[-1] == "e"
        if reaction["family"] == "ion":
            first = reaction["reactants"][0]["species"]
            assert result.candidates.states[first].charge != 0


def test_cumulative_screen_accepts_kinetics_or_reaction_evidence(tmp_path: Path) -> None:
    result = run(_case(), EvidenceCatalog.load(None))
    reaction_id = next(iter(result.candidates.reactions))
    assessed = result.evaluation.reaction_assessments[reaction_id]
    for layer in ("state", "consistency", "thermochemistry"):
        assessed[layer] = Assessment("pass")

    final_stage = (
        "assessments/screening/"
        "state_consistency_thermochemistry_kinetics_or_reaction_evidence/reactions.csv"
    )
    for accepted_layer in ("kinetics", "reaction_evidence"):
        assessed["kinetics"] = Assessment("unknown")
        assessed["reaction_evidence"] = Assessment("unknown")
        assessed[accepted_layer] = Assessment("pass")
        out = tmp_path / accepted_layer
        export.write(out, result, include_csv=True)
        with (out / final_stage).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        selected = next(row for row in rows if row["id"] == reaction_id)
        assert selected["kinetics_or_reaction_evidence_verdict"] == "pass"
        assert selected["accepted_by"] == accepted_layer

    assessed["kinetics"] = Assessment("unknown")
    assessed["reaction_evidence"] = Assessment("unknown")
    out = tmp_path / "neither"
    export.write(out, result, include_csv=True)
    with (out / final_stage).open(encoding="utf-8", newline="") as stream:
        assert reaction_id not in {row["id"] for row in csv.DictReader(stream)}


def test_cli_csv_flag_adds_compact_csv_views(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    case_path.write_text("name: argon\ngases: [Ar]\n", encoding="utf-8")
    out = tmp_path / "outputs"
    assert main(["generate", str(case_path), "--out", str(out), "--csv"]) == 0
    assert _relative_files(out) == _expected_review_files()


def _relative_files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def test_cli_generates_without_a_registry_and_has_no_discover_command(
    tmp_path: Path,
) -> None:
    case_path = tmp_path / "case.yaml"
    case_path.write_text("name: argon\ngases: [Ar]\n", encoding="utf-8")
    out = tmp_path / "outputs"
    assert (
        main(
            [
                "generate",
                str(case_path),
                "--registry",
                str(tmp_path / "missing"),
                "--out",
                str(out),
            ]
        )
        == 0
    )


def _expected_review_files() -> list[str]:
    files = [
        "assessments/composition.svg",
        "assessments/network.html",
        "assessments/network.png",
        "assessments/pathways.png",
        "assessments/statistics.csv",
        "assessments/statistics.svg",
        "reactions.csv",
        "reactions_electron.csv",
        "reactions_ion.csv",
        "reactions_neutral.csv",
        "reactions_surface.csv",
        "reactions.yaml",
        "selected.yaml",
        "states.csv",
        "states.yaml",
    ]
    for layer in (
        "consistency",
        "state",
        "thermochemistry",
        "reaction_evidence",
        "kinetics",
    ):
        files.extend(
            f"assessments/{layer}/{filename}"
            for filename in (
                "family_summary.csv",
                "reaction_family.svg",
                "reactions.csv",
                "reactions_electron.csv",
                "reactions_ion.csv",
                "reactions_neutral.csv",
                "reactions_surface.csv",
                "summary.csv",
                "verdict_counts.svg",
            )
        )
        if layer in ("consistency", "state", "thermochemistry"):
            files.append(f"assessments/{layer}/states.csv")
    for stage in (
        "state_consistency",
        "state_consistency_thermochemistry",
        "state_consistency_thermochemistry_kinetics_or_reaction_evidence",
    ):
        files.extend(
            f"assessments/screening/{stage}/{filename}"
            for filename in (
                "reactions.csv",
                "reactions_electron.csv",
                "reactions_ion.csv",
                "reactions_neutral.csv",
                "reactions_surface.csv",
                "retention.svg",
                "states.csv",
                "summary.csv",
            )
        )
    return sorted(files)


def _network_payload(html: str) -> dict:
    marker = '<script id="network-data" type="application/json">'
    encoded = html.split(marker, maxsplit=1)[1].split("</script>", maxsplit=1)[0]
    return json.loads(encoded)


def test_removed_discover_cli_is_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        main(["discover"])
    assert error.value.code == 2


def test_cli_rejects_invalid_gas_with_exit_2(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    case_path.write_text("gases: [Ar+]\n", encoding="utf-8")
    assert main(["generate", str(case_path), "--out", str(tmp_path / "out")]) == 2


def test_cli_rejects_removed_fraction_input(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    case_path.write_text("gases: [Ar, O2]\nfractions: [0.8, 0.2]\n", encoding="utf-8")
    assert main(["generate", str(case_path), "--out", str(tmp_path / "out")]) == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("pressure_Pa", 0.0),
        ("gas_temperature_K", -1.0),
        ("electron_temperature_eV", 0.0),
        ("electron_density_m3", -1.0),
        ("reduced_field_Td", -1.0),
        ("volume_m3", 0.0),
        ("surface_area_m2", -1.0),
        ("residence_time_s", 0.0),
    ],
)
def test_case_rejects_nonphysical_conditions(name: str, value: float) -> None:
    with pytest.raises(ValueError, match=name):
        Conditions(**{name: value})  # type: ignore[arg-type]


def test_cli_reports_nonphysical_conditions_as_input_error(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    case_path.write_text(
        "gases: [Ar]\nconditions:\n  gas_temperature_K: -300\n",
        encoding="utf-8",
    )
    assert main(["generate", str(case_path), "--out", str(tmp_path / "out")]) == 2


def test_cli_returns_1_when_three_file_bundle_cannot_be_written(tmp_path: Path) -> None:
    case_path = tmp_path / "case.yaml"
    case_path.write_text("gases: [Ar]\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "unrelated.txt").write_text("keep", encoding="utf-8")
    assert main(["generate", str(case_path), "--out", str(out)]) == 1
    assert (out / "unrelated.txt").read_text(encoding="utf-8") == "keep"


def test_ingest_matches_bundle_index_and_queues_total_process(tmp_path: Path) -> None:
    result = run(_case(), EvidenceCatalog.load(None))
    bundle = tmp_path / "bundle"
    export.write(bundle, result)
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text(
        yaml.safe_dump(
            {
                "kind": "cross_section",
                "source": {"source_id": "test"},
                "records": [
                    {
                        "reaction": "e + Ar -> e + Ar",
                        "type": "elastic",
                        "form": "table",
                        "unit": "m2",
                        "independent_variable": "electron_energy",
                        "observable": "elastic",
                        "asset": "elastic.csv",
                    },
                    {
                        "reaction": "e + Ar -> 2 e + Ar+",
                        "type": "ionization",
                        "form": "table",
                        "unit": "m2",
                        "independent_variable": "electron_energy",
                        "observable": "reaction",
                        "channel_scope": "total",
                        "asset": "total.csv",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    report = ingest.ingest(snapshot, bundle, tmp_path / "overlay.yaml")
    assert report.accepted == 1
    assert [item["reason"] for item in report.review] == [
        "total process cannot be assigned to a product-resolved channel"
    ]
    repeated = ingest.ingest(snapshot, bundle, tmp_path / "overlay.yaml")
    overlay = yaml.safe_load((tmp_path / "overlay.yaml").read_text(encoding="utf-8"))
    assert repeated.accepted == 1
    assert len(next(iter(overlay["datasets"].values()))) == 1


def test_truncation_propagates_to_selection_metadata() -> None:
    result = run(
        _case(("SF6",), Limits(max_depth=1)),
        EvidenceCatalog.load(None),
    )
    assert not result.candidates.complete
    assert result.metadata["stop_reason"] == "max_depth=1"


def test_only_adopt_promotes_canonical_overlay_ids_into_registry(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry"
    shutil.copytree(FIXTURE, registry_path)
    catalog = EvidenceCatalog.load(registry_path)
    result = run(_case(), catalog)
    elastic_id = next(
        reaction.id
        for reaction in result.candidates.reactions.values()
        if reaction.equation == "e + Ar@ground -> e + Ar@ground"
    )
    asset = tmp_path / "elastic.csv"
    asset.write_text("energy,cross_section\n1,1e-20\n10,2e-20\n", encoding="utf-8")
    overlay = {
        "properties": {
            "Ar@ground": {
                "test_property": {
                    "value": 1.0,
                    "unit": "1",
                    "source": "reviewed test",
                }
            }
        },
        "datasets": {
            elastic_id: [
                {
                    "id": "reviewed_elastic_cross_section",
                    "kind": "cross_section",
                    "form": "table",
                    "unit": "m2",
                    "independent_variable": "electron_energy",
                    "observable": "elastic",
                    "asset": {"path": asset.name},
                    "validity": {
                        "quantity": "collision_energy",
                        "minimum": 1.0,
                        "maximum": 10.0,
                        "unit": "eV",
                    },
                    "status": "reviewed",
                }
            ]
        },
    }
    overlay_path = tmp_path / "overlay.yaml"
    overlay_path.write_text(yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")
    report = adopt.adopt(overlay_path, registry_path)
    assert report.values == 2
    promoted = Registry.load(registry_path)
    assert promoted.species["Ar"].value("test_property") == 1.0
    elastic = next(
        reaction
        for group in promoted.channels.values()
        for reaction in group
        if reaction.id == "e_Ar_elastic"
    )
    assert {dataset.id for dataset in elastic.datasets} == {"reviewed_elastic_cross_section"}
    adopted_asset = elastic.datasets[0].asset
    assert adopted_asset is not None
    assert adopted_asset.local_path is not None
    assert adopted_asset.local_path.read_bytes() == asset.read_bytes()


def test_exploratory_selection_does_not_mix_lumped_and_resolved_states(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "cross_section.csv"
    asset.write_text(
        "energy_eV,cross_section_m2\n1,1e-20\n10,2e-20\n",
        encoding="utf-8",
    )
    snapshot = tmp_path / "states_and_channels.yaml"
    records = [
        {
            "id": name,
            "reaction": equation,
            "family": "electron",
            "type": "excitation",
            "form": "table",
            "unit": "m2",
            "independent_variable": "electron_energy",
            "observable": "reaction",
            "asset": asset.name,
            "validity": {
                "quantity": "electron_temperature",
                "minimum": 1.0,
                "maximum": 10.0,
                "unit": "eV",
            },
            "status": "reviewed",
        }
        for name, equation in (
            ("lumped", "e + O2 -> e + O2*"),
            ("resolved", "e + O2 -> e + O2(a1Delta_g)"),
        )
    ]
    snapshot.write_text(
        yaml.safe_dump(
            {
                "kind": "cross_section",
                "source": {"source_id": "reviewed-test"},
                "records": records,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    case = Case(
        "oxygen",
        ("O2",),
        conditions=Conditions(electron_temperature_eV=3.0),
    )
    result = run(
        case,
        EvidenceCatalog.load(None, known=(snapshot,)),
        "exploratory_simulation",
    )
    selected_states = {
        term.species
        for reaction_id in result.selection.reaction_ids
        for term in (
            *result.candidates.reactions[reaction_id].reactants,
            *result.candidates.reactions[reaction_id].products,
        )
    }
    assert "O2@a1dg" in selected_states
    assert "O2@electronic" not in selected_states
