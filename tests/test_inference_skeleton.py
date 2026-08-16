from plasma_reactgen.application.config import case_config_from_dict, load_case_config
from plasma_reactgen.inference import (
    InferredReactionProvider,
    confidence,
    passes_hard_filters,
)


def test_existing_case_config_defaults_inference_disabled():
    config = load_case_config("cases/ar_cf4/input.yaml", "registry")
    assert config.inference.enabled is False
    assert config.inference.include_inferred_species is True
    assert config.inference.include_inferred_reactions is False
    assert config.inference.min_confidence == 0.4


def test_empty_inference_block_uses_defaults():
    config = case_config_from_dict({"case": {"name": "x"}, "gases": ["Ar"], "inference": {}})
    assert config.inference.enabled is False
    assert config.inference.max_products == 3
    assert config.inference.max_fragment_depth == 1


def test_inference_block_parses_all_phase2_fields():
    config = case_config_from_dict(
        {
            "case": {"name": "x"},
            "gases": ["Ar"],
            "inference": {
                "enabled": True,
                "include_inferred_species": False,
                "include_inferred_reactions": True,
                "min_confidence": 0.7,
                "max_products": 2,
                "max_fragment_depth": 0,
            },
        }
    )

    assert config.inference.enabled is True
    assert config.inference.include_inferred_species is False
    assert config.inference.include_inferred_reactions is True
    assert config.inference.min_confidence == 0.7
    assert config.inference.max_products == 2
    assert config.inference.max_fragment_depth == 0


def test_inferred_reaction_provider_requires_explicit_config():
    assert InferredReactionProvider().get_channels(pair=object(), context={"inference": "off"}) == []


def test_inference_scoring_and_screening_are_small_helpers():
    assert confidence(1.5, ["template"]) == {"score": 1.0, "basis": ["template"]}
    assert confidence(-0.5)["score"] == 0.0
    assert passes_hard_filters({"status": "inferred"}) is True
