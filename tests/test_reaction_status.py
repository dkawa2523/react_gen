from plasma_reactgen.application.reaction_factory import reaction_data_status
from plasma_reactgen.domain.datasets import ReactionDataset
from plasma_reactgen.domain.models import ReactionChannel


def test_electron_reaction_status_distinguishes_missing_and_reference_only_data():
    missing = ReactionChannel(id="missing", type="elastic", products=[])
    legacy_reference = ReactionChannel(
        id="legacy",
        type="elastic",
        products=[],
        data={"cross_section": {"status": "literature_reference"}},
    )
    normalized_reference = ReactionChannel(
        id="normalized",
        type="elastic",
        products=[],
        datasets=[
            ReactionDataset(
                id="reference",
                reaction_id="normalized",
                kind="cross_section",
            )
        ],
    )

    assert reaction_data_status(missing, "electron")["cross_section"] == "missing"
    assert (
        reaction_data_status(legacy_reference, "electron")["cross_section"]
        == "literature_reference"
    )
    assert (
        reaction_data_status(normalized_reference, "electron")["cross_section"]
        == "reference_only_needs_import"
    )


def test_ion_reaction_status_marks_inferred_dnt_class():
    channel = ReactionChannel(
        id="inferred",
        type="charge_transfer",
        products=[],
        status="inferred",
    )

    assert reaction_data_status(channel, "ion_neutral") == {
        "reaction": "inferred",
        "dnt_class": "inferred",
    }
