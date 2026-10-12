"""Independent energy declarations retain meaning at normalization boundaries."""

from dataclasses import asdict, replace

import pytest

from reactgen import yamlio
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, snapshot_reaction
from reactgen.records import (
    Property,
    ReactionRecord,
    Uncertainty,
    energy_properties_equivalent,
    normalized_property,
    normalized_reaction_record,
    normalized_state_record,
    normalized_thermo,
    reaction_record_payload,
    scientific_reaction_content,
)
from reactgen.registry import Registry
from reactgen.units import AVOGADRO, JOULE_PER_EV


def normalize(entry: dict) -> ReactionRecord:
    parent = candidate_state({"Ar": 1}, 0)
    ion = candidate_state({"Ar": 1}, 1)
    return normalized_reaction_record(
        {"type": "ionization", **entry},
        (None, None, (("e", 1.0), (parent.id, 1.0)), (("e", 2.0), (ion.id, 1.0))),
        (parent, ion),
    )


def test_explicit_energy_review_does_not_inherit_channel_qualification() -> None:
    record = normalize(
        {
            "status": "reviewed",
            "review_scope": ["channel_assertion"],
            "energy_properties": {"threshold_eV": {"value": 16, "unit": "eV"}},
        }
    )
    assert record.reviewed_for("channel_assertion")
    assert not record.energy_properties["threshold_eV"].reviewed_for("threshold_eV")
    qualified = normalize(
        {
            "status": "imported",
            "energy_properties": {
                "threshold_eV": {
                    "value": 16,
                    "unit": "eV",
                    "tier": "reviewed",
                    "definition": "channel_threshold",
                    "review_scope": ["threshold_eV"],
                }
            },
        }
    )
    assert not qualified.reviewed_for("channel_assertion")
    assert qualified.energy_properties["threshold_eV"].reviewed_for("threshold_eV")


def test_legacy_scalar_adapter_keeps_qualification_without_inventing_definition() -> None:
    record = normalize(
        {
            "threshold_eV": 16,
            "deltaE_products_minus_reactants_eV": -2,
            "status": "reviewed",
            "method": "measured",
            "review_scope": ["threshold_eV"],
            "source": {"citation": "legacy laboratory"},
        }
    )
    threshold = record.energy_properties["threshold_eV"]
    assert threshold.value == 16
    assert threshold.definition is None
    assert threshold.uncertainty is None
    assert threshold.method == "measured"
    assert threshold.source_declaration["legacy_scalar"] == "threshold_eV"
    assert threshold.reviewed_for("threshold_eV")
    assert not record.energy_properties["delta_e_eV"].reviewed_for("delta_e_eV")
    assert record.threshold_eV == 16
    assert record.delta_e_eV == -2
    assert "threshold_eV" not in asdict(record)
    assert "delta_e_eV" not in asdict(record)


def test_portable_energy_roundtrip_preserves_independent_source_and_uncertainty() -> None:
    record = normalize(
        {
            "energy_properties": {
                "threshold_eV": {
                    "value": 16,
                    "unit": "eV",
                    "definition": "appearance_energy",
                    "tier": "reviewed",
                    "method": "measured",
                    "review_scope": ["threshold_eV"],
                    "uncertainty": {"absolute": 0.2},
                    "source": {"provider": "laboratory", "record_id": "measurement-1"},
                }
            }
        }
    )
    payload = reaction_record_payload(record)
    assert "threshold_eV" not in payload
    restored = normalized_reaction_record(
        payload, record.equation_key, record.states, preserved_record_id=True
    )
    assert restored.energy_properties == record.energy_properties
    assert restored.source_declaration == record.source_declaration
    changed = replace(
        record,
        energy_properties={
            "threshold_eV": replace(record.energy_properties["threshold_eV"], value=17)
        },
    )
    assert changed.threshold_eV == 17
    assert record.threshold_eV == 16


def test_scalar_and_property_duplicates_require_agreement_after_conversion() -> None:
    property_entry = {"value": 16 * JOULE_PER_EV * AVOGADRO, "unit": "J/mol"}
    record = normalize(
        {
            "threshold_eV": 16,
            "energy_properties": {
                "threshold_eV": property_entry,
            },
        }
    )
    assert record.threshold_eV == pytest.approx(16)
    assert record.energy_properties["threshold_eV"].unit == "J/mol"
    with pytest.raises(ValueError, match="disagree"):
        normalize({"threshold_eV": 17, "energy_properties": {"threshold_eV": property_entry}})


def test_legacy_portable_scalar_compares_as_the_same_declaration() -> None:
    record = normalize({"threshold_eV": 16, "status": "reviewed"})
    payload = reaction_record_payload(record)
    legacy = dict(payload)
    legacy.pop("energy_properties")
    legacy["threshold_eV"] = 16
    assert scientific_reaction_content(legacy) == scientific_reaction_content(record)


@pytest.mark.parametrize("definition", [False, 0, "", " ", {}, []])
def test_malformed_definition_is_rejected(definition: object) -> None:
    with pytest.raises(ValueError, match="definition must be nonempty text"):
        normalized_property({"value": 1, "unit": "eV", "definition": definition})


def test_quantity_definition_is_validated_without_restricting_new_quantities() -> None:
    with pytest.raises(ValueError, match="ionization_energy_eV.definition"):
        normalized_property({"definition": "appearance_energy"}, quantity="ionization_energy_eV")
    assert (
        normalized_property({"definition": "new_observable"}, quantity="new_quantity").definition
        == "new_observable"
    )
    state = candidate_state({"Ar": 1}, 0)
    with pytest.raises(ValueError, match="electron_affinity_eV.definition"):
        normalized_state_record(
            {
                "properties": {
                    "electron_affinity_eV": {
                        "value": 1,
                        "unit": "eV",
                        "definition": "channel_threshold",
                    }
                }
            },
            state,
        )


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_threshold_cannot_bypass_normalization(value: float) -> None:
    with pytest.raises(ValueError, match="threshold_eV must be finite"):
        normalize({"threshold_eV": value})
    record = normalize({})
    with pytest.raises(ValueError, match="threshold_eV must be finite"):
        replace(record, energy_properties={"threshold_eV": Property(value, "eV")})


@pytest.mark.parametrize("entries", [False, [], {"threshold_eV": 16}, {"other": {"value": 1}}])
def test_energy_properties_shape_is_validated(entries: object) -> None:
    with pytest.raises(ValueError, match="energy_properties"):
        normalize({"energy_properties": entries})


def write_registry_channel(tmp_path, channel: dict):
    root = tmp_path / "registry"
    for identifier, charge in (("Ar", 0), ("Ar+", 1)):
        path = root / "species" / f"{identifier}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yamlio.dump(
                {
                    "id": identifier,
                    "composition": {"Ar": 1},
                    "charge": charge,
                    "phase": "gas",
                }
            ),
            encoding="utf-8",
        )
    path = root / "reactions" / "electron" / "Ar.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yamlio.dump(
            {
                "pair": {"family": "electron", "projectile": "e", "target": "Ar"},
                "channels": [
                    {
                        "id": "ionization",
                        "type": "ionization",
                        "products": [{"species": "e", "n": 2}, {"species": "Ar+"}],
                        **channel,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_registry_top_channel_uses_independent_energy_and_portable_roundtrip(tmp_path) -> None:
    root = write_registry_channel(
        tmp_path,
        {
            "status": "imported",
            "review_scope": ["channel_assertion"],
            "energy_properties": {
                "threshold_eV": {
                    "value": 16,
                    "unit": "eV",
                    "tier": "reviewed",
                    "definition": "channel_threshold",
                    "source": {"provider": "energy-laboratory", "record_id": "threshold-1"},
                    "review_scope": ["threshold_eV"],
                    "uncertainty": {"absolute": 0.2},
                }
            },
        },
    )
    catalog = EvidenceCatalog.load(root)
    record = catalog.reaction_records[0]
    prop = record.energy_properties["threshold_eV"]
    assert record.threshold_eV == 16
    assert not record.reviewed_for("channel_assertion")
    assert prop.reviewed_for("threshold_eV")
    assert prop.provenance.provider == "energy-laboratory"
    assert prop.uncertainty == Uncertainty(absolute=0.2)
    channel = Registry.load(root).channels[("electron", "e", "Ar")][0]
    assert channel.energy_properties == record.energy_properties
    assert "threshold_eV" not in asdict(channel)
    restored = snapshot_reaction(
        reaction_record_payload(record), datasets=(), preserved_record_id=True
    )
    assert restored is not None
    assert restored.energy_properties == record.energy_properties


def test_registry_top_channel_does_not_promote_explicit_unreviewed_energy(tmp_path) -> None:
    root = write_registry_channel(
        tmp_path,
        {
            "status": "reviewed",
            "energy_properties": {"threshold_eV": {"value": 16, "unit": "eV"}},
        },
    )
    record = EvidenceCatalog.load(root).reaction_records[0]
    assert record.reviewed_for("channel_assertion")
    assert not record.energy_properties["threshold_eV"].reviewed_for("threshold_eV")


def test_registry_top_channel_scalar_duplicate_is_checked(tmp_path) -> None:
    root = write_registry_channel(
        tmp_path,
        {
            "threshold_eV": 17,
            "energy_properties": {"threshold_eV": {"value": 16, "unit": "eV"}},
        },
    )
    with pytest.raises(ValueError, match="disagree"):
        EvidenceCatalog.load(root)


def encoded_energy(unit: str, scale: float, **annotations) -> Property:
    return normalized_property(
        {
            "value": 10 * scale,
            "unit": unit,
            "uncertainty": {"absolute": scale},
            "definition": "channel_threshold",
            "tier": "reviewed",
            "source": {"provider": "laboratory", "record_id": "energy-1"},
            **annotations,
        },
        quantity="threshold_eV",
    )


def test_equivalent_energy_unit_copies_preserve_raw_declarations() -> None:
    first = encoded_energy("eV", 1, annotation="same experimental definition")
    second = encoded_energy("J", JOULE_PER_EV, annotation="same experimental definition")
    originals = asdict(first), asdict(second)
    assert energy_properties_equivalent(first, second)
    assert energy_properties_equivalent(second, first)
    assert (asdict(first), asdict(second)) == originals
    changed_unit = replace(
        first, value=10 * JOULE_PER_EV, unit="J", uncertainty=Uncertainty(absolute=JOULE_PER_EV)
    )
    assert energy_properties_equivalent(first, changed_unit)


@pytest.mark.parametrize(
    "changes",
    [
        {"definition": "appearance_energy"},
        {"tier": "imported"},
        {"status": "rejected"},
        {"review_scope": ("channel_assertion",)},
        {"qualifier": "upper_limit"},
        {"uncertainty": Uncertainty(absolute=JOULE_PER_EV, note="different confidence")},
        {"uncertainty": Uncertainty(relative=0.1)},
    ],
)
def test_unit_conversion_does_not_erase_quantity_qualification_or_error_definition(changes) -> None:
    first, second = encoded_energy("eV", 1), encoded_energy("J", JOULE_PER_EV)
    assert not energy_properties_equivalent(first, replace(second, **changes))


def test_source_annotations_and_inconsistent_raw_numeric_declarations_remain_distinct() -> None:
    first = encoded_energy("eV", 1, annotation="A")
    assert not energy_properties_equivalent(
        first, encoded_energy("J", JOULE_PER_EV, annotation="B")
    )
    same = encoded_energy("J", JOULE_PER_EV, annotation="A")
    raw = dict(same.source_declaration) | {"value": 11 * JOULE_PER_EV}
    assert not energy_properties_equivalent(first, replace(same, source_declaration=raw))
    raw = dict(first.source_declaration) | {"unit": False}
    assert not energy_properties_equivalent(first, replace(first, source_declaration=raw))


def test_absolute_uncertainty_annotation_is_normalized_without_losing_unknown_fields() -> None:
    first = encoded_energy("eV", 1)
    second = encoded_energy("J", JOULE_PER_EV)
    first_raw = dict(first.source_declaration)
    second_raw = dict(second.source_declaration)
    first_raw["uncertainty"] = first_raw["uncertainty"] | {"unit": "eV", "confidence": "95%"}
    second_raw["uncertainty"] = second_raw["uncertainty"] | {"unit": "J", "confidence": "95%"}
    first, second = (
        replace(first, source_declaration=first_raw),
        replace(second, source_declaration=second_raw),
    )
    assert energy_properties_equivalent(first, second)
    changed = dict(second_raw)
    changed["uncertainty"] = changed["uncertainty"] | {"confidence": "90%"}
    assert not energy_properties_equivalent(first, replace(second, source_declaration=changed))


def test_unspecified_uncertainty_is_distinct_from_explicit_zero_error() -> None:
    first = Property(10, "eV")
    assert not energy_properties_equivalent(
        first, replace(first, uncertainty=Uncertainty(absolute=0))
    )


def test_source_display_label_does_not_invent_a_missing_citation() -> None:
    prop = normalized_property(
        {
            "value": 1,
            "unit": "eV",
            "source": {"provider": "laboratory", "record_id": "native-1"},
        }
    )
    assert prop.provenance.citation is None
    assert prop.source == "native-1"
    assert replace(prop).provenance == prop.provenance
    restored = normalized_property(asdict(prop))
    assert restored.provenance == prop.provenance
    assert restored.source_declaration == prop.source_declaration
    cited = normalized_property(
        {
            "value": 1,
            "unit": "eV",
            "source": "A stated citation",
        }
    )
    assert cited.provenance.citation == "A stated citation"


def test_thermo_source_display_label_keeps_unknown_citation_unknown() -> None:
    thermo = normalized_thermo(
        {
            "low": [2.5, 0, 0, 0, 0, 0, 0],
            "high": [2.5, 0, 0, 0, 0, 0, 0],
            "t_min": 200,
            "t_mid": 1000,
            "t_max": 3000,
            "source": {"provider": "laboratory", "record_id": "fit-1"},
        }
    )
    assert thermo is not None
    assert thermo.provenance.citation is None
    assert thermo.source == "fit-1"
    restored = normalized_thermo(asdict(thermo))
    assert restored is not None
    assert restored.provenance == thermo.provenance
