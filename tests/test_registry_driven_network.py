import csv
from pathlib import Path

import yaml

from plasma_reactgen.application.config import (
    CaseConfig,
    CaseInfo,
    CollisionConfig,
    ElectronCollisionConfig,
    ExpansionConfig,
    IonNeutralCollisionConfig,
)
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.infrastructure.file_registry import FileRegistry
from plasma_reactgen.infrastructure.csv_writer import write_csv_outputs
from plasma_reactgen.infrastructure.yaml_writer import write_yaml_outputs


def test_registry_pair_index_filters_active_frontier_and_dedupes_symmetry(tmp_path):
    registry = _synthetic_registry(tmp_path)

    pairs = registry.find_pairs_involving(
        {"e", "AB", "BC", "X-"},
        {"AB", "BC", "X-"},
    )

    assert [pair.key for pair in pairs] == ["electron|e|AB"]
    assert "neutral_neutral|A|BC" not in {pair.key for pair in pairs}

    symmetric = registry.find_pairs_involving(
        {"A", "BC"},
        {"A", "BC"},
    )
    assert [pair.key for pair in symmetric] == ["neutral_neutral|A|BC"]


def test_registered_families_expand_across_depths_deterministically(tmp_path):
    registry = _synthetic_registry(tmp_path)
    config = CaseConfig(
        case=CaseInfo(name="registry_driven"),
        gases=["AB", "BC", "X-"],
        expansion=ExpansionConfig(max_depth=3),
        collisions=CollisionConfig(
            electron=ElectronCollisionConfig(enabled=False),
            ion_neutral=IonNeutralCollisionConfig(enabled=False),
        ),
    )
    builder = ReactionNetworkBuilder(NetworkBuilderDependencies(registry, registry, registry))

    first = builder.generate(config)
    second = builder.generate(config)

    signature = lambda network: [
        (reaction.id, reaction.family, reaction.depth, reaction.precursor_reaction_ids)
        for reaction in network.reactions
    ]
    assert signature(first) == signature(second)

    by_id = {reaction.id: reaction for reaction in first.reactions}
    assert by_id["e_AB_dissociation"].depth == 0
    assert by_id["e_AB_dissociation"].precursor_reaction_ids == []
    assert by_id["A_BC_reaction"].depth == 1
    assert by_id["A_BC_reaction"].precursor_reaction_ids == ["e_AB_dissociation"]
    assert by_id["e_ABp_recombination"].family == "electron_ion"
    assert by_id["ABp_Xm_neutralization"].family == "ion_ion"
    assert by_id["ABp_BC_charge_transfer"].family == "ion_neutral"
    assert by_id["e_C_ionization"].depth == 2
    assert by_id["e_C_ionization"].precursor_reaction_ids == ["A_BC_reaction"]
    assert all(reaction.data == {} for reaction in first.reactions)

    output_dir = tmp_path / "outputs"
    write_yaml_outputs(output_dir, config, first, [], [], [])
    write_csv_outputs(output_dir, first, [], [])
    yaml_reactions = {
        reaction["id"]: reaction
        for reaction in yaml.safe_load(
            (output_dir / "network.reactions.yaml").read_text(encoding="utf-8")
        )["reactions"]
    }
    assert yaml_reactions["e_C_ionization"]["depth"] == 2
    assert yaml_reactions["e_C_ionization"]["precursor_reaction_ids"] == ["A_BC_reaction"]
    with (output_dir / "network.reactions.csv").open(encoding="utf-8", newline="") as handle:
        csv_reactions = {row["id"]: row for row in csv.DictReader(handle)}
    assert csv_reactions["e_C_ionization"]["depth"] == "2"
    assert csv_reactions["e_C_ionization"]["precursor_reaction_ids"] == "A_BC_reaction"


def _synthetic_registry(tmp_path: Path) -> FileRegistry:
    root = tmp_path / "registry"
    species = {
        "AB": ({"A": 1, "B": 1}, 0, ["neutral", "molecule"]),
        "BC": ({"B": 1, "C": 1}, 0, ["neutral", "molecule"]),
        "X-": ({"X": 1}, -1, ["negative_ion"]),
        "A": ({"A": 1}, 0, ["neutral", "radical"]),
        "B": ({"B": 1}, 0, ["neutral", "radical"]),
        "C": ({"C": 1}, 0, ["neutral", "radical"]),
        "X": ({"X": 1}, 0, ["neutral", "radical"]),
        "AB+": ({"A": 1, "B": 1}, 1, ["positive_ion"]),
        "BC+": ({"B": 1, "C": 1}, 1, ["positive_ion"]),
        "C+": ({"C": 1}, 1, ["positive_ion"]),
    }
    for species_id, (composition, charge, classes) in species.items():
        _write_yaml(
            root / "species" / f"{species_id.replace('+', '_p').replace('-', '_m')}.yaml",
            {"id": species_id, "composition": composition, "charge": charge, "classes": classes},
        )

    reactions = [
        ("electron", "e", "AB", "e_AB", [
            _channel("e_AB_dissociation", "dissociation", [("e", 1), ("A", 1), ("B", 1)]),
            _channel("e_AB_ionization", "ionization", [("e", 2), ("AB+", 1)]),
        ]),
        ("neutral_neutral", "A", "BC", "A_BC", [
            _channel("A_BC_reaction", "reactive_scattering", [("AB", 1), ("C", 1)]),
        ]),
        ("electron_ion", "e", "AB+", "e_ABp", [
            _channel("e_ABp_recombination", "dissociative_recombination", [("A", 1), ("B", 1)]),
        ]),
        ("ion_ion", "AB+", "X-", "ABp_Xm", [
            _channel("ABp_Xm_neutralization", "mutual_neutralization", [("AB", 1), ("X", 1)]),
        ]),
        ("ion_neutral", "AB+", "BC", "ABp_BC", [
            _channel("ABp_BC_charge_transfer", "charge_transfer", [("AB", 1), ("BC+", 1)]),
        ]),
        ("electron", "e", "C", "e_C", [
            _channel("e_C_ionization", "ionization", [("e", 2), ("C+", 1)]),
        ]),
    ]
    for family, projectile, target, filename, channels in reactions:
        _write_yaml(
            root / "reactions" / family / f"{filename}.yaml",
            {
                "pair": {"family": family, "projectile": projectile, "target": target},
                "channels": channels,
            },
        )

    _write_yaml(
        root / "rules" / "reaction_type_catalog.yaml",
        {
            "electron": {"dissociation": {"expands_species": True}, "ionization": {"expands_species": True}},
            "neutral_neutral": {"reactive_scattering": {"expands_species": True}},
            "electron_ion": {"dissociative_recombination": {"expands_species": True}},
            "ion_ion": {"mutual_neutralization": {"expands_species": True}},
            "ion_neutral": {"charge_transfer": {"expands_species": True}},
        },
    )
    return FileRegistry(root)


def _channel(channel_id: str, reaction_type: str, products: list[tuple[str, int]]) -> dict:
    return {
        "id": channel_id,
        "type": reaction_type,
        "products": [{"species": species, "n": n} for species, n in products],
        "status": "curated",
    }


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
