from pathlib import Path

import yaml

from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks, build_required_properties
from plasma_reactgen.application.dnt_input_builder import build_dnt_inputs
from plasma_reactgen.application.reaction_catalog import reaction_available_data
from plasma_reactgen.domain.datasets import DatasetAsset, ReactionDataset, reaction_datasets_from_channel
from plasma_reactgen.domain.models import GeneratedReaction, PropertyValue, ReactionNetwork, Species, SpeciesAmount
from plasma_reactgen.interface.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_cross_section_is_emitted_in_available_data():
    reaction = _ion_neutral_network().reactions[0]
    reaction.datasets = reaction_datasets_from_channel(
        {
            "id": reaction.id,
            "data": {
                "cross_section": {
                    "path": "assets/cross_sections/legacy.csv",
                    "source": "lxcat_offline",
                    "status": "local_file_registered",
                }
            },
        }
    )

    payload = reaction_available_data(reaction)["cross_sections"]

    assert payload[0]["asset"]["path"] == "assets/cross_sections/legacy.csv"
    assert payload[0]["available"] is True


def test_dnt_task_contains_properties_datasets_and_mass_fallback():
    network = _ion_neutral_network()
    task = build_dnt_tasks(network)[0]

    assert task["reaction_ids"] == ["Arp_O2_ct"]
    assert task["required_properties"]["ion"]["mass_amu"]["source"] == "computed_from_composition"
    assert task["required_properties"]["neutral"]["polarizability_A3"]["value"] == 1.58
    assert [item["id"] for item in task["existing_datasets"]["cross_sections"]] == ["ds_ion_cross_section"]
    assert [item["id"] for item in task["existing_datasets"]["rate_coefficients"]] == ["ds_ion_rate"]
    assert task["data_choice"]["status"] == "existing_cross_section_available"


def test_missing_table_asset_is_not_reported_as_available():
    network = _ion_neutral_network()

    task = build_dnt_tasks(network, asset_exists=lambda _: False)[0]
    cross_section = task["existing_datasets"]["cross_sections"][0]

    assert cross_section["available"] is False
    assert task["data_choice"]["status"] == "existing_rate_coefficient_available"


def test_dnt_input_reuses_mass_computed_by_task_builder():
    network = _ion_neutral_network()
    tasks = build_dnt_tasks(network)

    pair = build_dnt_inputs(network, dnt_tasks=tasks)["pairs"][0]

    assert pair["projectile"]["mass_amu"] == 39.948
    assert pair["target"]["mass_amu"] == 31.998
    assert pair["projectile"]["properties"]["mass_amu"]["source"] == (
        "computed_from_composition"
    )


def test_sf6_mass_can_be_computed_without_user_property_input():
    ion = Species(id="Ar+", composition={"Ar": 1}, charge=1, classes={"positive_ion"})
    neutral = Species(id="SF6", composition={"S": 1, "F": 6}, charge=0, classes={"neutral"})

    properties = build_required_properties(ion, neutral)

    assert properties["neutral"]["mass_amu"]["available"] is True
    assert properties["neutral"]["mass_amu"]["source"] == "computed_from_composition"


def test_ar_cf4_existing_outputs_are_enhanced_and_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    args = ["generate", str(ROOT / "cases" / "ar_cf4" / "input.yaml"), "--registry", str(ROOT / "registry")]

    assert main([*args, "--output", str(first)]) == 0
    assert main([*args, "--output", str(second)]) == 0

    for name in ("network.reactions.yaml", "network.reactions.csv", "dnt_tasks.yaml", "missing_data.yaml"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert not (first / "reaction_list.yaml").exists()

    payload = yaml.safe_load((first / "network.reactions.yaml").read_text(encoding="utf-8"))
    assert payload["reactions"]
    reaction = payload["reactions"][0]
    assert "precursor_reaction_ids" in reaction
    assert set(reaction["available_data"]) == {"cross_sections", "rate_coefficients", "mobility"}
    assert "provenance_summary" in reaction


def _ion_neutral_network() -> ReactionNetwork:
    ion = Species(id="Ar+", composition={"Ar": 1}, charge=1, classes={"positive_ion"})
    neutral = Species(
        id="O2", composition={"O": 2}, charge=0, classes={"neutral"},
        properties={
            "polarizability_A3": PropertyValue(1.58, "A3", "test"),
            "dipole_moment_D": PropertyValue(0.0, "D", "test"),
            "collision_radius_A": PropertyValue(1.73, "A", "test"),
        },
    )
    reaction = GeneratedReaction(
        id="Arp_O2_ct", depth=0, family="ion_neutral", type="charge_transfer",
        equation="Ar+ + O2 -> Ar + O2+", reactants=[SpeciesAmount("Ar+"), SpeciesAmount("O2")],
        products=[SpeciesAmount("Ar"), SpeciesAmount("O2+")], source_pair_key="ion_neutral|Ar+|O2",
        source_pair_label="Ar+ + O2", introduced_species=["Ar", "O2+"],
        validation={"charge_balance": "ok", "element_balance": "ok"}, data_status={"reaction": "curated"},
        threshold_eV=0.2, deltaE_products_minus_reactants_eV=0.1, dnt_class="charge_transfer",
        datasets=[
            ReactionDataset(id="ds_ion_cross_section", reaction_id="Arp_O2_ct", kind="cross_section", representation="table", asset=DatasetAsset(path="assets/cross_sections/x.csv"), status="imported"),
            ReactionDataset(id="ds_ion_rate", reaction_id="Arp_O2_ct", kind="rate_coefficient", representation="constant", parameters={"k": 1e-15}, status="literature_supported"),
        ],
    )
    return ReactionNetwork(species={"Ar+": ion, "O2": neutral}, species_nodes={}, reactions=[reaction], coverage=[])
