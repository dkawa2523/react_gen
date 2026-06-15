from pathlib import Path

import yaml

from plasma_reactgen.interface.cli import main
from plasma_reactgen.preparation.promote import promote_reviewed_registry


def test_cli_promote_defaults_to_dry_run_and_does_not_mutate_registry(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    registry = tmp_path / "registry"
    _make_prepared_species(prepared_registry, "CF3")
    decision = _make_decision(
        tmp_path / "review_decisions.yaml",
        [{"kind": "species", "id": "CF3", "action": "promote"}],
    )

    rc = main(["promote", str(prepared_registry), "--registry", str(registry), "--decision", str(decision)])

    report = _read_yaml(tmp_path / "workspace" / "promote_report.yaml")
    assert rc == 0
    assert report["dry_run"] is True
    assert report["registry_mutated"] is False
    assert report["summary"]["n_promoted_species"] == 1
    assert not (registry / "species" / "CF3.yaml").exists()


def test_apply_promotes_new_species_with_status_notes_and_provenance(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    registry = tmp_path / "registry"
    _make_prepared_species(
        prepared_registry,
        "CF3",
        metadata={"status": "imported", "source_record": {"source_type": "internal_file_db"}, "notes": ["seeded"]},
        extra={"confidence": {"score": 0.9}, "inference": {"rule": "reviewed_seed"}},
    )
    decision = _make_decision(
        tmp_path / "review_decisions.yaml",
        [
            {
                "kind": "species",
                "id": "CF3",
                "action": "promote",
                "target_status": "literature_supported",
                "notes": ["reviewed by domain expert"],
            }
        ],
    )

    report = promote_reviewed_registry(prepared_registry, registry, decision, apply=True)

    promoted = _read_yaml(registry / "species" / "CF3.yaml")
    assert report["registry_mutated"] is True
    assert promoted["metadata"]["status"] == "literature_supported"
    assert promoted["metadata"]["source_record"] == {"source_type": "internal_file_db"}
    assert promoted["metadata"]["notes"] == ["seeded", "reviewed by domain expert"]
    assert promoted["confidence"] == {"score": 0.9}
    assert promoted["inference"] == {"rule": "reviewed_seed"}


def test_apply_promotes_new_channel_into_registry_pair(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    registry = tmp_path / "registry"
    _make_prepared_reaction(prepared_registry, "e_CF4_new", threshold=12.5)
    _make_registry_reaction(registry, "e_CF4_elastic", threshold=0.0)
    decision = _make_decision(
        tmp_path / "review_decisions.yaml",
        [
            {
                "kind": "reaction_channel",
                "id": "e_CF4_new",
                "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
                "action": "promote",
                "target_status": "literature_supported",
                "notes": ["reviewed channel"],
            }
        ],
    )

    report = promote_reviewed_registry(prepared_registry, registry, decision, apply=True)

    payload = _read_yaml(registry / "reactions" / "electron" / "e__CF4.yaml")
    channels = {channel["id"]: channel for channel in payload["channels"]}
    assert report["summary"]["n_promoted_channels"] == 1
    assert channels["e_CF4_elastic"]["threshold_eV"] == 0.0
    assert channels["e_CF4_new"]["status"] == "literature_supported"
    assert channels["e_CF4_new"]["threshold_eV"] == 12.5
    assert channels["e_CF4_new"]["data"]["source_record"] == {"source_type": "internal_file_db"}
    assert channels["e_CF4_new"]["confidence"] == {"score": 0.8}
    assert channels["e_CF4_new"]["notes"] == ["prepared note", "reviewed channel"]


def test_existing_curated_channel_is_not_overwritten(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    registry = tmp_path / "registry"
    _make_prepared_reaction(prepared_registry, "e_CF4_elastic", threshold=99.0)
    _make_registry_reaction(registry, "e_CF4_elastic", threshold=0.0)
    decision = _make_decision(
        tmp_path / "review_decisions.yaml",
        [
            {
                "kind": "reaction_channel",
                "id": "e_CF4_elastic",
                "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
                "action": "promote",
                "target_status": "literature_supported",
            }
        ],
    )

    report = promote_reviewed_registry(prepared_registry, registry, decision, apply=True)

    payload = _read_yaml(registry / "reactions" / "electron" / "e__CF4.yaml")
    assert report["registry_mutated"] is False
    assert report["conflicts"][0]["reason"] == "curated_channel_exists"
    assert payload["channels"] == [
        {
            "id": "e_CF4_elastic",
            "type": "elastic",
            "products": [{"species": "e", "n": 1}, {"species": "CF4", "n": 1}],
            "threshold_eV": 0.0,
            "status": "curated",
            "data": {"source_record": {"source_type": "curated_registry"}},
        }
    ]


def test_reject_action_is_reported_and_not_copied(tmp_path):
    prepared_registry = tmp_path / "workspace" / "prepared_registry"
    registry = tmp_path / "registry"
    _make_prepared_species(prepared_registry, "speculative_fragment")
    decision = _make_decision(
        tmp_path / "review_decisions.yaml",
        [{"kind": "species", "id": "speculative_fragment", "action": "reject"}],
    )

    report = promote_reviewed_registry(prepared_registry, registry, decision, apply=True)

    assert report["registry_mutated"] is False
    assert report["rejected"] == [
        {
            "kind": "species",
            "id": "speculative_fragment",
            "reason": "rejected_by_decision",
            "notes": [],
        }
    ]
    assert not (registry / "species" / "speculative_fragment.yaml").exists()


def _make_prepared_species(
    prepared_registry: Path,
    species_id: str,
    *,
    metadata: dict | None = None,
    extra: dict | None = None,
) -> None:
    payload = {
        "schema_version": 1,
        "id": species_id,
        "composition": {"C": 1, "F": 3},
        "charge": 0,
        "classes": ["neutral", "radical"],
        "properties": {},
        "metadata": metadata or {"status": "imported"},
    }
    payload.update(extra or {})
    _write_yaml(prepared_registry / "species" / f"{species_id}.yaml", payload)


def _make_prepared_reaction(prepared_registry: Path, channel_id: str, *, threshold: float) -> None:
    _write_yaml(
        prepared_registry / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
            "channels": [
                {
                    "id": channel_id,
                    "type": "dissociation",
                    "products": [{"species": "e", "n": 1}, {"species": "CF3", "n": 1}, {"species": "F", "n": 1}],
                    "threshold_eV": threshold,
                    "status": "imported",
                    "data": {"source_record": {"source_type": "internal_file_db"}},
                    "confidence": {"score": 0.8},
                    "notes": ["prepared note"],
                }
            ],
        },
    )


def _make_registry_reaction(registry: Path, channel_id: str, *, threshold: float) -> None:
    _write_yaml(
        registry / "reactions" / "electron" / "e__CF4.yaml",
        {
            "schema_version": 1,
            "pair": {"family": "electron", "projectile": "e", "target": "CF4"},
            "channels": [
                {
                    "id": channel_id,
                    "type": "elastic",
                    "products": [{"species": "e", "n": 1}, {"species": "CF4", "n": 1}],
                    "threshold_eV": threshold,
                    "status": "curated",
                    "data": {"source_record": {"source_type": "curated_registry"}},
                }
            ],
        },
    )


def _make_decision(path: Path, decisions: list[dict]) -> Path:
    _write_yaml(path, {"schema_version": 1, "decisions": decisions})
    return path


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_yaml(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
