from __future__ import annotations

import pytest
import yaml

from plasma_reactgen.interface.registration_templates import render_registration_template


def test_species_registration_template_contains_editable_defaults():
    payload = yaml.safe_load(render_registration_template("species", ["CF4+"]))

    assert payload["id"] == "CF4+"
    assert payload["suggested_filename"] == "CF4_p.yaml"
    assert payload["metadata"]["status"] == "draft"
    assert payload["properties"]["mass_amu"] == {
        "value": None,
        "unit": "amu",
        "source": None,
    }


@pytest.mark.parametrize(
    ("kind", "args", "family", "channel_id", "energy_field"),
    [
        ("electron-pair", ["e", "CF4"], "electron", "e_CF4_elastic", "threshold_eV"),
        (
            "ion-pair",
            ["Ar+", "CF4"],
            "ion_neutral",
            "Ar_p_CF4_elastic",
            "deltaE_products_minus_reactants_eV",
        ),
    ],
)
def test_pair_registration_templates_have_family_specific_elastic_channel(
    kind,
    args,
    family,
    channel_id,
    energy_field,
):
    payload = yaml.safe_load(render_registration_template(kind, args))
    channel = payload["channels"][0]

    assert payload["pair"] == {
        "family": family,
        "projectile": args[0],
        "target": args[1],
    }
    assert channel["id"] == channel_id
    assert channel[energy_field] == 0.0
    assert channel["status"] == "draft"


@pytest.mark.parametrize(
    ("kind", "args", "message"),
    [
        ("species", [], "template species requires: SPECIES_ID"),
        ("electron-pair", ["e"], "template electron-pair requires: e TARGET"),
        ("ion-pair", ["Ar+"], "template ion-pair requires: ION NEUTRAL"),
        ("unknown", [], "unknown template kind: unknown"),
    ],
)
def test_registration_template_rejects_unknown_kind_and_wrong_arity(kind, args, message):
    with pytest.raises(SystemExit, match=message):
        render_registration_template(kind, args)
