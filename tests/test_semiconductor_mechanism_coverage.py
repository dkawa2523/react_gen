from pathlib import Path

from plasma_reactgen.application.config import case_config_from_dict
from plasma_reactgen.application.mechanism_coverage import build_mechanism_coverage
from plasma_reactgen.application.network_builder import (
    NetworkBuilderDependencies,
    ReactionNetworkBuilder,
)
from plasma_reactgen.infrastructure.file_registry import FileRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_cf4_o2_source_table_is_covered_without_a_mixture_pack() -> None:
    network, coverage = _generate(["Ar", "CF4", "O2"])
    mechanism = _by_id(coverage)["son_2014_cf4_o2_volume"]

    assert network.generation_complete
    assert mechanism["complete"] is True
    assert mechanism["n_covered_records"] == mechanism["n_expected_records"] == 60
    assert mechanism["missing_record_ids"] == []


def test_sf6_o2_source_tables_are_covered_and_unary_reaction_is_physical() -> None:
    network, coverage = _generate(["Ar", "SF6", "O2"])
    mechanisms = _by_id(coverage)
    reactions = {reaction.id: reaction for reaction in network.reactions}

    assert network.generation_complete
    assert mechanisms["pateau_2014_sf6_volume"]["complete"] is True
    assert mechanisms["pateau_2014_sf6_volume"]["n_expected_records"] == 50
    assert mechanisms["pateau_2014_sf6_o2_cross_chemistry"]["complete"] is True
    assert mechanisms["pateau_2014_sf6_o2_cross_chemistry"]["n_expected_records"] == 20
    reaction = reactions["SOF4_dissociation_SOF3_F"]
    assert reaction.equation == "SOF4 -> SOF3 + F"
    assert reaction.validation == {
        "species_reference": "ok",
        "charge_balance": "ok",
        "element_balance": "ok",
    }


def test_known_feedstock_without_chemistry_is_an_explicit_gap() -> None:
    network, coverage = _generate(["NF3"])

    assert network.reactions == []
    assert coverage["summary"]["n_applicable_mechanisms"] == 0
    assert any(
        item.pair_key == "electron|e|NF3" and item.status == "missing" for item in network.coverage
    )
    assert any(
        item.subject_id == "NF3"
        and item.required_by == "chemical_reaction_list"
        and item.severity == "error"
        for item in network.missing_data
    )


def _generate(gases: list[str]):
    registry = FileRegistry(ROOT / "registry")
    config = case_config_from_dict(
        {
            "case": {"name": "mechanism_coverage"},
            "gases": gases,
            "expansion": {"max_depth": None, "propagate_excited_states": True},
            "data_policy": {"allowed_status": ["curated", "literature_supported"]},
        }
    )
    dependencies = NetworkBuilderDependencies(registry, registry, registry)
    network = ReactionNetworkBuilder(dependencies).generate(config)
    return network, build_mechanism_coverage(gases, network, registry.root)


def _by_id(coverage: dict) -> dict:
    return {item["id"]: item for item in coverage["mechanisms"]}
