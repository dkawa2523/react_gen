"""A source record cannot silently move to another physical target.

ID consistency is an input-format property, not evidence for or against a
physical phenomenon. Quantities on the same target retain their own review.
"""

from copy import deepcopy
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.pipeline import analyze
from reactgen.records import StateRecord

SOURCE = {"provider": "laboratory", "collection": "observations", "release": "1"}


def record(kind: str, gas: str) -> dict:
    common = {
        "record_id": "native-1",
        "status": "reviewed",
        "method": "measured",
    }
    if kind == "state":
        return common | {
            "species": f"{gas}@ground",
            "phase": "gas",
            "existence": "confirmed",
            "existence_source": "independent source assertion",
            "properties": {
                "ionization_energy_eV": {"value": 10.0, "unit": "eV", "tier": "reviewed"}
            },
        }
    return common | {
        "reaction": f"e + {gas} -> e + {gas}",
        "type": "elastic",
        "review_scope": ["channel_assertion", "threshold_eV"],
        "threshold_eV": 0.0,
    }


def write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(body), encoding="utf-8")
    return path


def snapshot(
    path: Path,
    kind: str,
    records: list[dict],
    source: dict | None = None,
) -> Path:
    return write(
        path,
        {
            "snapshot_version": 1,
            "kind": "state_property" if kind == "state" else "rate_coefficient",
            "source": source or SOURCE,
            "records": records,
        },
    )


def records(catalog: EvidenceCatalog, kind: str):
    return catalog.state_records if kind == "state" else catalog.reaction_records


@pytest.mark.parametrize("kind", ["state", "reaction"])
def test_one_snapshot_rejects_one_native_record_id_assigned_to_different_targets(tmp_path, kind):
    entries = [record(kind, "Ar"), record(kind, "Ne")]
    for index, ordered in enumerate((entries, list(reversed(entries)))):
        source = snapshot(tmp_path / f"source-{index}.yaml", kind, ordered)
        with pytest.raises(ValueError, match="record ID.*different physical targets"):
            EvidenceCatalog.load_paths((source,))


@pytest.mark.parametrize("kind", ["state", "reaction"])
def test_multiple_sources_reject_the_same_source_record_moved_to_another_target(tmp_path, kind):
    first = snapshot(tmp_path / "first.yaml", kind, [record(kind, "Ar")])
    second = snapshot(tmp_path / "second.yaml", kind, [record(kind, "Ne")])
    assert len(records(EvidenceCatalog.load_paths((first,)), kind)) == 1
    assert len(records(EvidenceCatalog.load_paths((second,)), kind)) == 1
    for ordered in ((first, second), (second, first), (first, second, second)):
        with pytest.raises(ValueError, match="record ID.*different physical targets"):
            EvidenceCatalog.load_paths(ordered)


@pytest.mark.parametrize("kind", ["state", "reaction"])
def test_source_namespaces_remain_independent_even_when_native_ids_match(tmp_path, kind):
    first = snapshot(tmp_path / "first.yaml", kind, [record(kind, "Ar")])
    second = snapshot(
        tmp_path / "second.yaml", kind, [record(kind, "Ne")], SOURCE | {"provider": "another"}
    )
    catalog = EvidenceCatalog.load_paths((first, second))
    assert len(records(catalog, kind)) == 2


@pytest.mark.parametrize("kind", ["state", "reaction"])
def test_reacquisition_on_the_same_target_retains_both_original_declarations(tmp_path, kind):
    first = snapshot(
        tmp_path / "first.yaml",
        kind,
        [record(kind, "Ar")],
        SOURCE | {"acquisition": {"retrieved_at": "first"}},
    )
    second = snapshot(
        tmp_path / "second.yaml",
        kind,
        [record(kind, "Ar")],
        SOURCE | {"acquisition": {"retrieved_at": "second"}},
    )
    catalog = EvidenceCatalog.load_paths((first, second, second))
    declarations = records(catalog, kind)
    assert len(declarations) == 2
    assert declarations[0].source_declaration != declarations[1].source_declaration
    identifiers = {item.record_id if kind == "state" else item.id for item in declarations}
    assert len(identifiers) == 1


@pytest.mark.parametrize("kind", ["state", "reaction"])
def test_same_target_different_quantities_remain_available_for_claim_evaluation(tmp_path, kind):
    first = record(kind, "Ar")
    second = deepcopy(first)
    if kind == "state":
        second["properties"]["ionization_energy_eV"]["value"] = 11.0
    else:
        second["threshold_eV"] = 1.0
    source = snapshot(tmp_path / "source.yaml", kind, [first, second])
    assert len(records(EvidenceCatalog.load_paths((source,)), kind)) == 2


def test_legacy_registry_state_records_without_scientific_ids_do_not_collide():
    first, second = (candidate_state({gas: 1}, 0) for gas in ("Ar", "Ne"))
    catalog = EvidenceCatalog(
        state_records=(StateRecord("container", first), StateRecord("container", second))
    )
    assert len(catalog.state_records) == 2


def registry(root: Path) -> None:
    for gas in ("Ar", "Ne"):
        write(
            root / "species" / f"{gas}.yaml",
            {"id": gas, "composition": {gas: 1}, "phase": "gas", "state": {"kind": "ground"}},
        )
        write(
            root / "reactions" / "electron" / f"{gas}.yaml",
            {
                "pair": {"family": "electron", "projectile": "e", "target": gas},
                "channels": [
                    {
                        "id": f"{gas}_elastic",
                        "type": "elastic",
                        "products": [{"species": "e"}, {"species": gas}],
                    }
                ],
            },
        )


@pytest.mark.parametrize("kind", ["state", "reaction"])
def test_ingest_queues_a_cross_target_native_id_and_adoption_rejects_it_atomically(tmp_path, kind):
    root, bundle = tmp_path / "registry", tmp_path / "bundle"
    registry(root)
    export.write(bundle, analyze(Case("two targets", ("Ar", "Ne")), EvidenceCatalog.load(root)))
    first = snapshot(tmp_path / "first.yaml", kind, [record(kind, "Ar")])
    second = snapshot(tmp_path / "second.yaml", kind, [record(kind, "Ne")])
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(first, bundle, overlay).accepted == 1
    staged_before = overlay.read_bytes()
    for _ in range(2):
        queued = ingest.ingest(second, bundle, overlay)
        assert queued.accepted == 0
        assert len(queued.review) == 1
        assert overlay.read_bytes() == staged_before
    assert adopt.adopt(overlay, root).values == 1
    assert adopt.adopt(overlay, root).values == 0

    incoming_overlay = tmp_path / "incoming.yaml"
    assert ingest.ingest(second, bundle, incoming_overlay).accepted == 1
    saved_before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    for _ in range(2):
        with pytest.raises(ValueError, match="record ID"):
            adopt.adopt(incoming_overlay, root)
        assert {
            path: path.read_bytes() for path in root.rglob("*") if path.is_file()
        } == saved_before
