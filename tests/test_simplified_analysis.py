from plasma_reactgen.application.channel_policy import is_channel_allowed
from plasma_reactgen.application.config import CaseConfig, CaseInfo, InferenceConfig
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_input_builder import build_dnt_inputs
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.models import ReactionChannel, ReactionNetwork
from plasma_reactgen.domain.models import NetworkSpeciesNode, Species


def test_generate_analysis_can_reuse_precomputed_dnt_tasks(monkeypatch):
    network = ReactionNetwork({}, {}, [], [])

    monkeypatch.setattr(
        "plasma_reactgen.application.diagnostics.build_dnt_tasks",
        lambda _: (_ for _ in ()).throw(AssertionError("DNT tasks rebuilt")),
    )
    monkeypatch.setattr(
        "plasma_reactgen.application.dnt_input_builder.build_dnt_tasks",
        lambda _: (_ for _ in ()).throw(AssertionError("DNT tasks rebuilt")),
    )

    assert build_missing_data(network, [], dnt_tasks=[]) == []
    assert build_dnt_inputs(network, dnt_tasks=[])["pairs"] == []


def test_inferred_channel_uses_normalized_confidence_field():
    config = CaseConfig(
        case=CaseInfo(name="confidence"),
        gases=["Ar"],
        inference=InferenceConfig(
            enabled=True,
            include_inferred_reactions=True,
            min_confidence=0.8,
        ),
    )
    channel = ReactionChannel(
        id="inferred",
        type="elastic",
        products=[],
        status="inferred",
        confidence={"score": 0.9},
    )

    assert is_channel_allowed(channel, config)


def test_state_projection_does_not_mutate_network_roles():
    species = Species("A", {"A": 1}, 0, {"neutral"})
    node = NetworkSpeciesNode("A", 0, roles={"input_gas"})
    network = ReactionNetwork({"A": species}, {"A": node}, [], [])

    class Rules:
        @staticmethod
        def get_role_required_properties():
            return {"roles": {}}

    build_state_list(network, Rules())

    assert node.roles == {"input_gas"}
