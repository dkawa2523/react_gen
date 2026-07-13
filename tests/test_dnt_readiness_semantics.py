from __future__ import annotations

from pathlib import Path

import yaml

from external_data_tools.benchmark_metrics import collect_metrics
from external_data_tools.benchmark_runner import _enrichment_quality_gate
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_input_builder import build_dnt_inputs
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.domain.models import (
    GeneratedReaction,
    PropertyValue,
    ReactionNetwork,
    Species,
    SpeciesAmount,
)


def test_pair_property_and_complete_dnt_readiness_are_separate():
    network = _network_with_complete_properties_and_incomplete_channel()

    task = build_dnt_tasks(network)[0]
    pair_input = build_dnt_inputs(network)["pairs"][0]

    assert task["pair_property_readiness"]["scope"] == "pair_properties"
    assert task["pair_property_readiness"]["status"] == "ready"
    assert task["complete_readiness"]["status"] == "ready_with_warnings"
    assert task["channels"][0]["type"] == "elastic"
    assert task["channels"][0]["missing_for_complete_dnt"] == []
    assert task["channels"][1]["missing_for_complete_dnt"] == [
        "threshold_eV",
        "deltaE_products_minus_reactants_eV",
    ]

    assert pair_input["pair_property_readiness"]["status"] == "ready"
    assert pair_input["complete_readiness"]["status"] == "ready_with_warnings"
    assert pair_input["status"] == "ready_with_warnings"
    assert pair_input["target"]["properties"]["mass_amu"]["source_record"] == {
        "source_type": "test_fixture",
        "source_id": "O2:mass_amu",
    }


def test_diagnostics_reports_nonelastic_dnt_channel_gaps_but_not_elastic_threshold():
    network = _network_with_complete_properties_and_incomplete_channel()
    missing = build_missing_data(network, states=[])

    fields_by_reaction = {
        (item.subject_id, item.field)
        for item in missing
    }
    assert ("Arp_O2_charge_transfer", "threshold_eV") in fields_by_reaction
    assert (
        "Arp_O2_charge_transfer",
        "deltaE_products_minus_reactants_eV",
    ) in fields_by_reaction
    assert ("Arp_O2_elastic", "threshold_eV") not in fields_by_reaction


def test_metrics_name_property_and_complete_readiness_explicitly(tmp_path: Path):
    output = tmp_path / "outputs"
    output.mkdir()
    tasks = build_dnt_tasks(_network_with_complete_properties_and_incomplete_channel())
    _write_yaml(
        output / "dnt_tasks.yaml",
        {
            "summary": {
                "n_dnt_pairs": 1,
                "n_ready_pairs": 1,
                "n_pairs_with_missing_properties": 0,
            },
            "dnt_tasks": tasks,
        },
    )

    metrics = collect_metrics(output)

    assert metrics["n_dnt_ready_pairs"] == 1
    assert metrics["n_dnt_property_ready_pairs"] == 1
    assert metrics["n_dnt_complete_ready_pairs"] == 0
    assert metrics["n_dnt_ready_with_warnings_pairs"] == 1
    assert metrics["dnt_complete_readiness_available"] is True
    assert "legacy alias" in metrics["dnt_readiness_semantics"]["n_dnt_ready_pairs"]


def test_metrics_count_only_cross_section_assets_inside_prepared_registry(tmp_path: Path):
    output = tmp_path / "outputs"
    output.mkdir()
    prepared_registry = tmp_path / "prepared_registry"
    valid_asset = prepared_registry / "assets" / "cross_sections" / "valid.csv"
    valid_asset.parent.mkdir(parents=True)
    valid_asset.write_text("energy_eV,cross_section_m2\n1,1e-20\n", encoding="utf-8")
    outside_asset = tmp_path / "outside.csv"
    outside_asset.write_text("energy_eV,cross_section_m2\n1,1e-20\n", encoding="utf-8")
    _write_yaml(
        output / "network.reactions.yaml",
        {
            "reactions": [
                _serialized_electron_reaction("valid", "assets/cross_sections/valid.csv"),
                _serialized_electron_reaction("dangling", "assets/cross_sections/missing.csv"),
                _serialized_electron_reaction("outside", "../outside.csv"),
            ]
        },
    )

    metrics = collect_metrics(output, prepared_registry)

    assert metrics["n_cross_section_assets"] == 1
    assert metrics["n_reactions_with_cross_section_asset"] == 1
    assert metrics["cross_section_asset_coverage_fraction"] == 0.333333


def test_metrics_expose_generation_truncation(tmp_path: Path):
    output = tmp_path / "outputs"
    output.mkdir()
    _write_yaml(
        output / "network.reactions.yaml",
        {
            "summary": {"generation_complete": False},
            "truncations": [{"limit_name": "max_reactions"}],
            "reactions": [],
        },
    )

    metrics = collect_metrics(output)

    assert metrics["generation_complete"] is False
    assert metrics["n_generation_truncations"] == 1


def test_enrichment_quality_gate_ignores_property_gaps_and_fails_structural_gaps(tmp_path: Path):
    report = tmp_path / "prepare_report.yaml"
    _write_yaml(
        report,
        {
            "unresolved": [
                {
                    "kind": "missing_property",
                    "species": "O2",
                    "property": "enthalpy_formation_eV",
                }
            ],
            "unresolved_product_species": [],
            "unresolved_reactions": [],
            "reaction_channels_skipped": [],
        },
    )

    advisory_only = _enrichment_quality_gate(report)
    assert advisory_only["passed"] is True
    assert advisory_only["normal_missing_property_count"] == 1

    _write_yaml(
        report,
        {
            "unresolved": [{"kind": "unsupported_unit", "candidate_unit": "kJ/mol"}],
            "unavailable_sources": [{"source": "configured_provider", "reason": "not_available"}],
            "unresolved_product_species": [],
            "unresolved_reactions": [],
            "reaction_channels_skipped": [],
        },
    )

    provider_defects = _enrichment_quality_gate(report)
    assert provider_defects["passed"] is False
    assert provider_defects["structural_unresolved_count"] == 2
    assert provider_defects["by_category"]["non_missing_property_unresolved"] == 1
    assert provider_defects["by_category"]["unavailable_sources"] == 1

    _write_yaml(
        report,
        {
            "unresolved": [],
            "unresolved_product_species": [],
            "unresolved_reactions": [
                {"pair": "electron|e|O2", "id": None, "reason": "missing_channel_id"}
            ],
            "reaction_channels_skipped": [],
        },
    )

    structural = _enrichment_quality_gate(report)
    assert structural["passed"] is False
    assert structural["structural_unresolved_count"] == 1


def _network_with_complete_properties_and_incomplete_channel() -> ReactionNetwork:
    ion = Species(
        id="Ar+",
        composition={"Ar": 1},
        charge=1,
        classes={"positive_ion"},
        properties={"mass_amu": PropertyValue(39.948, "amu", "test")},
    )
    neutral = Species(
        id="O2",
        composition={"O": 2},
        charge=0,
        classes={"neutral"},
        properties={
            "mass_amu": PropertyValue(
                31.9988,
                "amu",
                "test",
                {"source_type": "test_fixture", "source_id": "O2:mass_amu"},
            ),
            "polarizability_A3": PropertyValue(1.58, "A3", "test"),
            "dipole_moment_D": PropertyValue(0.0, "D", "test"),
            "collision_radius_A": PropertyValue(1.73, "A", "test"),
        },
    )
    reactants = [SpeciesAmount("Ar+"), SpeciesAmount("O2")]
    reactions = [
        _reaction(
            "Arp_O2_elastic",
            "elastic",
            reactants,
            [SpeciesAmount("Ar+"), SpeciesAmount("O2")],
            dnt_class="elastic",
            threshold_eV=None,
            delta_e_eV=0.0,
        ),
        _reaction(
            "Arp_O2_charge_transfer",
            "charge_transfer",
            reactants,
            [SpeciesAmount("Ar"), SpeciesAmount("O2+")],
            dnt_class="long_range_charge_exchange",
            threshold_eV=None,
            delta_e_eV=None,
        ),
    ]
    return ReactionNetwork(
        species={"Ar+": ion, "O2": neutral},
        species_nodes={},
        reactions=reactions,
        coverage=[],
    )


def _reaction(
    reaction_id: str,
    reaction_type: str,
    reactants: list[SpeciesAmount],
    products: list[SpeciesAmount],
    *,
    dnt_class: str,
    threshold_eV: float | None,
    delta_e_eV: float | None,
) -> GeneratedReaction:
    return GeneratedReaction(
        id=reaction_id,
        depth=0,
        family="ion_neutral",
        type=reaction_type,
        equation=reaction_id,
        reactants=reactants,
        products=products,
        source_pair_key="ion_neutral|Ar+|O2",
        source_pair_label="Ar+ + O2",
        introduced_species=[],
        validation={"charge_balance": "ok", "element_balance": "ok"},
        data_status={"reaction": "curated"},
        threshold_eV=threshold_eV,
        deltaE_products_minus_reactants_eV=delta_e_eV,
        dnt_class=dnt_class,
    )


def _write_yaml(path: Path, payload) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _serialized_electron_reaction(reaction_id: str, asset_path: str) -> dict:
    return {
        "id": reaction_id,
        "family": "electron",
        "data": {"cross_section": {"path": asset_path}},
    }
