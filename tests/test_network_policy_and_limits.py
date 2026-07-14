from __future__ import annotations

import json

import pytest

from plasma_reactgen.application.config import (
    CaseConfig,
    CaseInfo,
    CollisionConfig,
    DataPolicyConfig,
    ElectronCollisionConfig,
    ExpansionConfig,
    IonNeutralCollisionConfig,
    LimitsConfig,
)
from plasma_reactgen.application.network_builder import (
    NetworkBuilderDependencies,
    ReactionNetworkBuilder,
)
from plasma_reactgen.domain.datasets import DatasetAsset, ReactionDataset
from plasma_reactgen.domain.models import CollisionPair, PropertyValue, ReactionChannel, Species, SpeciesAmount
from plasma_reactgen.infrastructure.yaml_writer import write_yaml_outputs


class MemoryRegistry:
    def __init__(self, species=None, channels=None, assets=None):
        self.species = species or {}
        self.channels = channels or {}
        self.assets = set(assets or ())

    def get_species(self, species_id):
        return self.species.get(species_id)

    def has_species(self, species_id):
        return species_id in self.species

    def get_channels(self, pair):
        return list(self.channels.get(pair.key, []))

    def find_pairs_involving(self, active_species_ids, frontier_species_ids):
        pairs = []
        for key in sorted(self.channels):
            family, projectile, target = key.split("|", 2)
            if (
                projectile in active_species_ids
                and target in active_species_ids
                and {projectile, target}.intersection(frontier_species_ids)
            ):
                pairs.append(CollisionPair(family, projectile, target))
        return pairs

    def has_pair(self, pair):
        return pair.key in self.channels

    def asset_exists(self, relative_path):
        return relative_path in self.assets

    def get_reaction_type_catalog(self):
        return {
            "electron": {
                "elastic": {"expands_species": False},
                "dissociation": {"expands_species": True},
                "ionization": {"expands_species": True},
            },
            "ion_neutral": {
                "elastic": {"expands_species": False},
                "charge_transfer": {"expands_species": True},
            },
        }

    def get_role_required_properties(self):
        return {"roles": {}}

    def get_profile(self, profile_name):
        _ = profile_name
        return {}


def test_strict_incomplete_policy_rejects_unknown_product_species():
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    channel = ReactionChannel(
        id="e_A_unknown",
        type="elastic",
        products=[SpeciesAmount("e"), SpeciesAmount("unknown")],
        status="curated",
    )
    registry = MemoryRegistry(species, {"electron|e|A": [channel]})

    permissive = _generate(registry, _config(["A"]))
    strict = _generate(
        registry,
        _config(
            ["A"],
            data_policy=DataPolicyConfig(include_incomplete_reactions=False),
        ),
    )

    assert [reaction.id for reaction in permissive.reactions] == ["e_A_unknown"]
    assert permissive.reactions[0].validation["species_reference"] == "unknown_species"
    assert strict.reactions == []


def test_strict_cross_section_policy_requires_a_verified_local_asset():
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    channels = [
        _elastic_channel("missing", data={}),
        _elastic_channel(
            "dangling",
            data={"cross_section": {"path": "cross_sections/missing.csv"}},
        ),
        _elastic_channel(
            "outside",
            data={"cross_section": {"path": "../outside.csv"}},
        ),
        _elastic_channel(
            "available",
            data={"cross_section": {"path": "cross_sections/A.csv"}},
        ),
    ]
    registry = MemoryRegistry(
        species,
        {"electron|e|A": channels},
        assets={"cross_sections/A.csv"},
    )
    policy = DataPolicyConfig(include_reactions_without_cross_section=False)

    network = _generate(registry, _config(["A"], data_policy=policy))

    assert [reaction.id for reaction in network.reactions] == ["available"]
    assert network.reactions[0].data_status["cross_section"] == "local_file_registered"
    assert network.coverage[0].status == "found"
    assert network.coverage[0].n_channels == 1


def test_strict_cross_section_policy_accepts_new_dataset_format():
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    channel = _elastic_channel("dataset_only")
    channel.datasets = [
        ReactionDataset(
            id="ds_dataset_only",
            reaction_id=channel.id,
            kind="cross_section",
            representation="table",
            asset=DatasetAsset(path="cross_sections/A.csv"),
            status="imported",
        )
    ]
    registry = MemoryRegistry(
        species,
        {"electron|e|A": [channel]},
        assets={"cross_sections/A.csv"},
    )
    policy = DataPolicyConfig(include_reactions_without_cross_section=False)

    network = _generate(registry, _config(["A"], data_policy=policy))

    assert [reaction.id for reaction in network.reactions] == ["dataset_only"]
    assert network.reactions[0].data_status["cross_section"] == "local_file_registered"


def test_permissive_dangling_cross_section_is_not_counted_as_an_asset(tmp_path):
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    channel = _elastic_channel(
        "dangling",
        data={"cross_section": {"path": "cross_sections/missing.csv"}},
    )
    registry = MemoryRegistry(species, {"electron|e|A": [channel]})
    config = _config(["A"])

    network = _generate(registry, config)
    write_yaml_outputs(tmp_path, config, network, [], [], network.missing_data)
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))

    assert [reaction.id for reaction in network.reactions] == ["dangling"]
    assert (
        network.reactions[0].data_status["cross_section"]
        == "path_registered_but_missing"
    )
    assert summary["n_reactions_with_cross_section_asset"] == 0
    assert summary["n_reactions_missing_cross_section"] == 1


def test_strict_dnt_policy_uses_pair_property_readiness():
    channel = ReactionChannel(
        id="Arp_Ar_elastic",
        type="elastic",
        products=[SpeciesAmount("Ar+"), SpeciesAmount("Ar")],
        status="curated",
    )
    incomplete_species = {
        "Ar+": _species("Ar+", {"Ar": 1}, 1, {"positive_ion"}, mass_amu=39.948),
        "Ar": _species("Ar", {"Ar": 1}, 0, {"neutral"}, mass_amu=39.948),
    }
    ready_species = {
        **incomplete_species,
        "Ar": _species(
            "Ar",
            {"Ar": 1},
            0,
            {"neutral"},
            mass_amu=39.948,
            polarizability_A3=1.641,
            dipole_moment_D=0.0,
            collision_radius_A=1.88,
        ),
    }
    policy = DataPolicyConfig(include_reactions_without_dnt_ready_properties=False)
    config = _config(
        ["Ar+", "Ar"],
        data_policy=policy,
        electron_enabled=False,
        ion_neutral_enabled=True,
    )

    incomplete = _generate(
        MemoryRegistry(incomplete_species, {"ion_neutral|Ar+|Ar": [channel]}),
        config,
    )
    ready = _generate(
        MemoryRegistry(ready_species, {"ion_neutral|Ar+|Ar": [channel]}),
        config,
    )

    assert incomplete.reactions == []
    assert incomplete.coverage[0].status == "filtered"
    assert [reaction.id for reaction in ready.reactions] == ["Arp_Ar_elastic"]


def test_pair_limit_records_exact_truncation():
    species = {
        "A": _species("A", {"A": 1}, 0, {"neutral"}),
        "B": _species("B", {"B": 1}, 0, {"neutral"}),
    }
    limits = LimitsConfig(max_pairs_per_depth=1, max_missing_pairs_per_depth=10)

    registry = MemoryRegistry(
        species,
        {"electron|e|A": [], "electron|e|B": []},
    )
    network = _generate(registry, _config(["A", "B"], limits=limits))

    event = _event(network, "max_pairs_per_depth")
    assert (event.depth, event.observed_count, event.retained_count, event.omitted_count) == (
        0,
        2,
        1,
        1,
    )
    assert len(network.coverage) == 1
    assert network.generation_complete is False


def test_missing_pair_report_limit_records_exact_truncation():
    species = {
        "A": _species("A", {"A": 1}, 0, {"neutral"}),
        "B": _species("B", {"B": 1}, 0, {"neutral"}),
    }
    limits = LimitsConfig(max_pairs_per_depth=10, max_missing_pairs_per_depth=1)

    registry = MemoryRegistry(
        species,
        {"electron|e|A": [], "electron|e|B": []},
    )
    network = _generate(registry, _config(["A", "B"], limits=limits))

    event = _event(network, "max_missing_pairs_per_depth")
    assert (event.depth, event.observed_count, event.retained_count, event.omitted_count) == (
        0,
        2,
        1,
        1,
    )
    assert len(network.coverage) == 1


def test_reaction_limit_records_first_omitted_candidate():
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    channels = [_elastic_channel("first"), _elastic_channel("second")]
    registry = MemoryRegistry(species, {"electron|e|A": channels})
    limits = LimitsConfig(max_reactions=1)

    network = _generate(registry, _config(["A"], limits=limits))

    event = _event(network, "max_reactions")
    assert [reaction.id for reaction in network.reactions] == ["first"]
    assert (event.observed_count, event.retained_count, event.omitted_count) == (2, 1, None)
    assert event.details == {"first_omitted_reaction_id": "second"}


def test_zero_reaction_limit_retains_none_and_records_first_candidate():
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    registry = MemoryRegistry(species, {"electron|e|A": [_elastic_channel("first")]})

    network = _generate(
        registry,
        _config(["A"], limits=LimitsConfig(max_reactions=0)),
    )

    event = _event(network, "max_reactions")
    assert network.reactions == []
    assert (event.observed_count, event.retained_count, event.omitted_count) == (1, 0, None)
    assert event.details == {"first_omitted_reaction_id": "first"}


def test_exact_reaction_limit_without_an_omitted_candidate_is_complete():
    species = {"A": _species("A", {"A": 1}, 0, {"neutral"})}
    registry = MemoryRegistry(species, {"electron|e|A": [_elastic_channel("only")]})

    network = _generate(
        registry,
        _config(["A"], limits=LimitsConfig(max_reactions=1)),
    )

    assert [reaction.id for reaction in network.reactions] == ["only"]
    assert network.truncations == []
    assert network.generation_complete is True


def test_species_limit_skips_expansion_atomically_and_records_species():
    species = {
        "AB": _species("AB", {"A": 1, "B": 1}, 0, {"neutral"}),
        "A": _species("A", {"A": 1}, 0, {"neutral"}),
        "B": _species("B", {"B": 1}, 0, {"neutral"}),
    }
    channel = ReactionChannel(
        id="e_AB_dissociation",
        type="dissociation",
        products=[SpeciesAmount("e"), SpeciesAmount("A"), SpeciesAmount("B")],
        status="curated",
    )
    registry = MemoryRegistry(species, {"electron|e|AB": [channel]})

    network = _generate(
        registry,
        _config(["AB"], limits=LimitsConfig(max_species=2)),
    )

    event = _event(network, "max_species")
    assert network.reactions == []
    assert set(network.species_nodes) == {"AB"}
    assert (event.observed_count, event.retained_count, event.omitted_count) == (3, 1, 2)
    assert event.details == {
        "blocked_reaction_ids": ["e_AB_dissociation"],
        "blocked_species_ids": ["A", "B"],
    }


def test_negative_generation_limits_are_rejected():
    with pytest.raises(ValueError, match=r"limits\.max_species"):
        LimitsConfig(max_species=-1)


def test_species_limit_must_accommodate_unique_input_gases():
    species = {
        "A": _species("A", {"A": 1}, 0, {"neutral"}),
        "B": _species("B", {"B": 1}, 0, {"neutral"}),
    }

    with pytest.raises(ValueError, match=r"must accommodate all unique input gases"):
        _generate(
            MemoryRegistry(species),
            _config(["A", "B"], limits=LimitsConfig(max_species=1)),
        )


def _generate(registry, config):
    deps = NetworkBuilderDependencies(registry, registry, registry)
    return ReactionNetworkBuilder(deps).generate(config)


def _config(
    gases,
    *,
    data_policy=None,
    limits=None,
    electron_enabled=True,
    ion_neutral_enabled=False,
):
    return CaseConfig(
        case=CaseInfo(name="policy_limits"),
        gases=list(gases),
        expansion=ExpansionConfig(max_depth=0),
        collisions=CollisionConfig(
            electron=ElectronCollisionConfig(enabled=electron_enabled),
            ion_neutral=IonNeutralCollisionConfig(enabled=ion_neutral_enabled),
        ),
        data_policy=data_policy or DataPolicyConfig(),
        limits=limits or LimitsConfig(),
    )


def _species(species_id, composition, charge, classes, **property_values):
    return Species(
        id=species_id,
        composition=composition,
        charge=charge,
        classes=set(classes),
        properties={
            name: PropertyValue(value=value, source="test")
            for name, value in property_values.items()
        },
        status="curated",
    )


def _elastic_channel(channel_id, data=None):
    return ReactionChannel(
        id=channel_id,
        type="elastic",
        products=[SpeciesAmount("e"), SpeciesAmount("A")],
        data=data or {},
        status="curated",
    )


def _event(network, limit_name):
    return next(event for event in network.truncations if event.limit_name == limit_name)
