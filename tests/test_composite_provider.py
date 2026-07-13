from plasma_reactgen.application.config import CaseConfig, CaseInfo, InferenceConfig
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_input_builder import build_dnt_inputs
from plasma_reactgen.application.network_builder import NetworkBuilderDependencies, ReactionNetworkBuilder
from plasma_reactgen.domain.models import (
    CollisionPair,
    PropertyValue,
    ReactionChannel,
    Species,
    SpeciesAmount,
)
from plasma_reactgen.inference.provider import (
    CompositeReactionProvider,
    InferredReactionProvider,
    RegisteredReactionProvider,
)


class MemoryRegistry:
    def __init__(self, species=None, channels=None):
        self.species = species or {}
        self.channels = channels or {}

    def get_species(self, species_id):
        return self.species.get(species_id)

    def has_species(self, species_id):
        return species_id in self.species

    def get_channels(self, pair):
        return list(self.channels.get(pair.key, []))

    def has_pair(self, pair):
        return pair.key in self.channels

    def get_reaction_type_catalog(self):
        return {
            "electron": {
                "ionization": {"expands_species": True},
            },
            "ion_neutral": {
                "charge_transfer": {"expands_species": True},
            },
        }

    def get_role_required_properties(self):
        return {"roles": {}}

    def get_profile(self, profile_name):
        _ = profile_name
        return {}


class InvalidInferredProvider:
    def get_channels(self, pair, context=None):
        _ = context
        if pair.family != "electron" or pair.target != "CF4":
            return []
        return [
            ReactionChannel(
                id="inferred_invalid_unbalanced",
                type="ionization",
                products=[SpeciesAmount("e", 2.0), SpeciesAmount("Ar", 1.0)],
                data={"confidence": {"score": 0.9, "basis": ["test_invalid"]}},
                status="inferred",
            )
        ]

    def get_species(self, species_id):
        _ = species_id
        return None


def test_disabled_composite_provider_returns_registered_channels_only():
    pair = CollisionPair("electron", "e", "CF4")
    registered_channel = ReactionChannel(
        id="registered_e_CF4_elastic",
        type="elastic",
        products=[SpeciesAmount("e"), SpeciesAmount("CF4")],
        status="curated",
    )
    registry = MemoryRegistry(_base_species(), {pair.key: [registered_channel]})
    provider = CompositeReactionProvider(
        RegisteredReactionProvider(registry),
        InferredReactionProvider(species_repo=registry),
        _config(inference_enabled=False),
    )

    assert provider.get_channels(pair) == [registered_channel]


def test_enabled_composite_provider_appends_inferred_channel_for_missing_pair():
    pair = CollisionPair("electron", "e", "CF4")
    registry = MemoryRegistry(_base_species())
    inferred = InferredReactionProvider(species_repo=registry)
    provider = CompositeReactionProvider(
        RegisteredReactionProvider(registry),
        inferred,
        _config(inference_enabled=True),
    )

    channels = provider.get_channels(pair)

    assert len(channels) == 1
    assert channels[0].status == "inferred"
    assert channels[0].type == "ionization"
    assert provider.get_species("CF4+").status == "inferred"


def test_registered_duplicate_id_wins_over_inferred_channel():
    pair = CollisionPair("electron", "e", "CF4")
    registered_channel = ReactionChannel(
        id="inferred_e_CF4_ionization_parent",
        type="ionization",
        products=[SpeciesAmount("e", 2.0), SpeciesAmount("CF4+", 1.0)],
        status="curated",
    )
    registry = MemoryRegistry(_base_species(), {pair.key: [registered_channel]})
    provider = CompositeReactionProvider(
        RegisteredReactionProvider(registry),
        InferredReactionProvider(species_repo=registry),
        _config(inference_enabled=True),
    )

    channels = provider.get_channels(pair)

    assert len(channels) == 1
    assert channels[0].id == registered_channel.id
    assert channels[0].status == "curated"


def test_inferred_provider_does_not_overwrite_registered_species():
    pair = CollisionPair("electron", "e", "CF4")
    species = _base_species()
    species["CF4+"] = _species("CF4+", {"C": 1, "F": 4}, 1, {"positive_ion"}, status="curated")
    registry = MemoryRegistry(species)
    inferred = InferredReactionProvider(species_repo=registry)
    provider = CompositeReactionProvider(
        RegisteredReactionProvider(registry),
        inferred,
        _config(inference_enabled=True),
    )

    assert provider.get_channels(pair)
    assert provider.get_species("CF4+").status == "curated"


def test_network_generation_can_include_inferred_channels_and_species():
    registry = MemoryRegistry(_base_species())
    config = _config(inference_enabled=True)
    deps = _deps(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)
    inferred = [reaction for reaction in network.reactions if reaction.data_status["reaction"] == "inferred"]

    assert any(reaction.id == "inferred_e_CF4_ionization_parent" for reaction in inferred)
    assert any(
        reaction.id == "inferred_Ar_p_CF4_charge_transfer_parent"
        for reaction in inferred
    )
    assert network.species["CF4+"].status == "inferred"
    assert all(reaction.validation["charge_balance"] == "ok" for reaction in inferred)
    assert all(reaction.validation["element_balance"] == "ok" for reaction in inferred)
    assert any(
        reaction.id == "inferred_Ar_p_CF4_charge_transfer_parent"
        and reaction.data_status["dnt_class"] == "inferred"
        for reaction in inferred
    )


def test_default_generation_without_inference_does_not_change_behavior():
    registry = MemoryRegistry(_base_species())
    config = _config(inference_enabled=False)
    deps = _deps(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)

    assert network.reactions == []
    assert "CF4+" not in network.species


def test_enabled_without_inferred_reactions_keeps_generation_registry_only():
    registry = MemoryRegistry(_base_species())
    config = _config(inference_enabled=True, include_inferred_reactions=False)
    deps = _deps(registry, config)

    network = ReactionNetworkBuilder(deps).generate(config)

    assert network.reactions == []
    assert "CF4+" not in network.species


def test_invalid_inferred_channel_is_rejected_by_validation():
    registry = MemoryRegistry(_base_species())
    config = _config(inference_enabled=True)
    provider = CompositeReactionProvider(
        RegisteredReactionProvider(registry),
        InvalidInferredProvider(),
        config,
    )
    deps = NetworkBuilderDependencies(provider, provider, registry)

    network = ReactionNetworkBuilder(deps).generate(config)

    assert all(reaction.id != "inferred_invalid_unbalanced" for reaction in network.reactions)
    assert any(
        item.subject_id == "inferred_invalid_unbalanced"
        and item.field == "validation"
        for item in network.missing_data
    )


def test_missing_data_reports_inferred_cross_section_and_dnt_energy():
    registry = MemoryRegistry(_base_species())
    config = _config(inference_enabled=True)
    deps = _deps(registry, config)
    network = ReactionNetworkBuilder(deps).generate(config)

    missing = build_missing_data(network, states=[])

    assert any(
        item.subject_id == "inferred_e_CF4_ionization_parent"
        and item.field == "data.cross_section"
        for item in missing
    )
    assert any(
        item.subject_id == "inferred_Ar_p_CF4_charge_transfer_parent"
        and item.field == "deltaE_products_minus_reactants_eV"
        for item in missing
    )


def test_dnt_inputs_preserve_inferred_channel_provenance():
    registry = MemoryRegistry(_base_species())
    config = _config(inference_enabled=True)
    deps = _deps(registry, config)
    network = ReactionNetworkBuilder(deps).generate(config)

    dnt_inputs = build_dnt_inputs(network)
    channels = [
        channel
        for pair in dnt_inputs["pairs"]
        for channel in pair["channels"]
    ]

    assert any(
        channel["reaction_id"] == "inferred_Ar_p_CF4_charge_transfer_parent"
        and channel["provenance"]["source_type"] == "inference"
        for channel in channels
    )


def _deps(registry, config):
    if not (config.inference.enabled and config.inference.include_inferred_reactions):
        return NetworkBuilderDependencies(registry, registry, registry)
    provider = CompositeReactionProvider(
        RegisteredReactionProvider(registry),
        InferredReactionProvider(species_repo=registry),
        config,
    )
    return NetworkBuilderDependencies(provider, provider, registry)


def _config(inference_enabled, include_inferred_reactions=None):
    if include_inferred_reactions is None:
        include_inferred_reactions = inference_enabled
    return CaseConfig(
        case=CaseInfo(name="x"),
        gases=["Ar", "CF4"],
        inference=InferenceConfig(
            enabled=inference_enabled,
            include_inferred_reactions=include_inferred_reactions,
            include_inferred_species=True,
            min_confidence=0.4,
        ),
    )


def _base_species():
    return {
        "Ar": _species("Ar", {"Ar": 1}, 0, {"neutral", "atom"}, mass=39.948),
        "CF4": _species("CF4", {"C": 1, "F": 4}, 0, {"neutral", "molecule"}, mass=88.004),
    }


def _species(species_id, composition, charge, classes, *, mass=None, status="curated"):
    properties = {}
    if mass is not None:
        properties["mass_amu"] = PropertyValue(value=mass, unit="amu", source="test")
    return Species(
        id=species_id,
        composition=composition,
        charge=charge,
        classes=classes,
        properties=properties,
        status=status,
    )
