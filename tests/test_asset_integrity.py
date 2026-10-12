"""A qualified table refers to observed bytes, independently of storage location."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, numeric, yamlio
from reactgen.case import Case, Conditions
from reactgen.evidence import (
    EvidenceCatalog,
    ReactionEvidence,
    registry_reaction_candidate,
    snapshot_reaction,
)
from reactgen.model import ReactionCandidate, Term
from reactgen.numeric import data_use, table_points
from reactgen.pipeline import analyze
from reactgen.records import AssetReference, dataset_payload, normalized_dataset
from reactgen.registry import Registry

TABLE = b"temperature_K,k_m3_s\n300,1e-15\n500,2e-15\n"
CHANGED = b"temperature_K,k_m3_s\n300,8e-15\n500,9e-15\n"
SOURCE = {"provider": "laboratory", "collection": "rates", "record_id": "native-1"}
REACTION = ReactionCandidate(
    "test",
    (Term("Ar@ground", 2),),
    (Term("Ar@ground", 2),),
    "neutral",
    "elastic",
    "test",
    "test",
    0,
)


def record(asset: object) -> dict:
    return {
        "reaction": "Ar + Ar -> Ar + Ar",
        "type": "elastic",
        "source": SOURCE,
        "status": "reviewed",
        "review_scope": ["rate_coefficient"],
        "kind": "rate_coefficient",
        "form": "table",
        "unit": "m3/s",
        "reaction_order": 2,
        "independent_variable": "gas_temperature",
        "asset": asset,
        "validity": {
            "quantity": "gas_temperature",
            "minimum": 300,
            "maximum": 500,
            "unit": "K",
        },
    }


def use(*datasets):
    evidence = ReactionEvidence(overlay_datasets=tuple(datasets))
    return data_use(REACTION, evidence, Conditions(gas_temperature_K=350))


def write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


def registry(root: Path) -> Path:
    write(root / "species" / "Ar.yaml", {"id": "Ar", "composition": {"Ar": 1}, "phase": "gas"})
    write(
        root / "reactions" / "neutral" / "Ar.yaml",
        {
            "pair": {"family": "neutral", "projectile": "Ar", "target": "Ar"},
            "channels": [
                {"id": "container", "type": "elastic", "products": [{"species": "Ar", "n": 2}]}
            ],
        },
    )
    return root


@pytest.mark.parametrize("when", ["after_loading", "after_saving"])
def test_table_changes_cannot_inherit_the_saved_qualification(tmp_path, when):
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    dataset = normalized_dataset(record(path.name), base=tmp_path)
    payload = dataset_payload(dataset)
    assert payload["asset"] == {
        "path": path.name,
        "sha256": sha256(TABLE).hexdigest(),
        "declared_sha256": None,
    }
    assert use(dataset).value == pytest.approx(1.25e-15)
    path.write_bytes(CHANGED)
    if when == "after_saving":
        dataset = normalized_dataset(payload, base=tmp_path)
    assert dataset.asset.sha256 == sha256(TABLE).hexdigest()
    assert not dataset.asset.integrity_ok
    assert table_points(dataset) is None
    assert use(dataset).value is None
    assert use(dataset).datasets[0].status == "invalid"
    assert dataset_payload(dataset)["asset"] == payload["asset"]


def test_table_parses_the_same_bytes_that_were_checked(tmp_path, monkeypatch):
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    dataset = normalized_dataset(record(path.name), base=tmp_path)
    original = Path.read_bytes

    def read_and_change(target):
        content = original(target)
        if target == path:
            path.write_bytes(CHANGED)
        return content

    monkeypatch.setattr(Path, "read_bytes", read_and_change)
    assert table_points(dataset) == [(300, 1e-15), (500, 2e-15)]
    assert table_points(dataset) is None


def test_change_during_evaluation_is_invalid_rather_than_missing_user_input(tmp_path, monkeypatch):
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    dataset = normalized_dataset(record(path.name), base=tmp_path)
    original = numeric._value

    def change_before_evaluation(dataset, conditions):
        path.write_bytes(CHANGED)
        return original(dataset, conditions)

    monkeypatch.setattr(numeric, "_value", change_before_evaluation)
    result = use(dataset)
    assert result.value is None
    assert result.datasets[0].status == "invalid"
    assert not result.required_inputs


def test_direct_python_asset_requires_an_observed_checksum(tmp_path):
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    dataset = normalized_dataset(record(path.name), base=tmp_path)
    unobserved = replace(dataset, asset=AssetReference(path.name, path))
    assert table_points(unobserved) is None
    assert use(unobserved).datasets[0].status == "invalid"
    with pytest.raises(ValueError, match="AssetReference"):
        replace(dataset, asset={"path": path.name})


def test_fresh_declaration_and_saved_missing_observation_remain_distinct(tmp_path):
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    fresh = normalized_dataset(record({"path": path.name, "declared_sha256": None}), base=tmp_path)
    assert fresh.asset.sha256 == sha256(TABLE).hexdigest()
    assert use(fresh).status == "coefficient"
    saved_without_bytes = normalized_dataset(
        record({"path": path.name, "sha256": None, "declared_sha256": None}), base=tmp_path
    )
    assert saved_without_bytes.asset.sha256 is None
    assert use(saved_without_bytes).datasets[0].status == "invalid"


@pytest.mark.parametrize("reverse", [False, True])
def test_verified_copies_do_not_conflict_and_keep_their_original_paths(tmp_path, reverse):
    paths = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for path in paths:
        path.write_bytes(TABLE)
    datasets = [normalized_dataset(record(path.name), base=tmp_path) for path in paths]
    result = use(*(reversed(datasets) if reverse else datasets))
    assert result.status == "coefficient"
    assert result.value == pytest.approx(1.25e-15)
    assert len(result.datasets) == 1
    assert [dataset_payload(item)["source_declaration"]["asset"] for item in datasets] == [
        path.name for path in paths
    ]


@pytest.mark.parametrize("change", ["bytes", "unit", "conditions", "unknown_asset_field"])
def test_equal_ids_still_conflict_when_scientific_content_changes(tmp_path, change):
    first, second = tmp_path / "first.csv", tmp_path / "second.csv"
    first.write_bytes(TABLE)
    second.write_bytes(CHANGED if change == "bytes" else TABLE)
    changed = record(second.name)
    if change == "unit":
        changed["unit"] = "cm3/s"
    elif change == "conditions":
        changed["validity"]["minimum"] = 320
    elif change == "unknown_asset_field":
        changed["asset"] = {"path": second.name, "column_semantics": "different observable"}
    result = use(
        normalized_dataset(record(first.name), base=tmp_path),
        normalized_dataset(changed, base=tmp_path),
    )
    assert result.status == "conflict"
    assert result.value is None


def test_unknown_bytes_at_different_locations_do_not_establish_equivalence(tmp_path):
    datasets = [normalized_dataset(record(name), base=tmp_path) for name in ("one.csv", "two.csv")]
    assert use(*datasets).status == "conflict"


def test_anonymous_identity_uses_verified_bytes_without_inventing_unknown_equivalence(tmp_path):
    entries = []
    for name in ("one.csv", "two.csv"):
        (tmp_path / name).write_bytes(TABLE)
        entries.append(record(name) | {"source": {"provider": "laboratory"}})
    datasets = [normalized_dataset(entry, base=tmp_path) for entry in entries]
    assert datasets[0].id == datasets[1].id
    assert use(*datasets).status == "coefficient"
    missing = [normalized_dataset(entry, base=tmp_path / "missing") for entry in entries]
    assert missing[0].id != missing[1].id


@pytest.mark.parametrize("native", [False, True])
def test_mixed_ingest_and_adoption_preserve_relocated_acquisitions_and_repeat(tmp_path, native):
    root = registry(tmp_path / "registry")
    bundle = tmp_path / "bundle"
    export.write(bundle, analyze(Case("argon", ("Ar",)), EvidenceCatalog.load(root)))
    paths = []
    for index, name in enumerate(("first.csv", "second.csv")):
        (tmp_path / name).write_bytes(TABLE)
        entry = record(name)
        if not native:
            entry["source"] = {"provider": "laboratory", "collection": "rates"}
        paths.append(write(tmp_path / f"snapshot-{index}.yaml", {"records": [entry]}))
    direct = EvidenceCatalog.load_paths(tuple(paths))
    assert len({item.id for item in direct.reaction_records}) == 1
    assert len({item.id for item in direct.reaction(REACTION).datasets}) == 1
    overlay = tmp_path / "output" / "overlay.yaml"
    for path in (*paths, paths[1]):
        assert ingest.ingest(path, bundle, overlay).accepted == 1
    catalog = EvidenceCatalog.load(None, overlay)
    datasets = next(iter(catalog.overlay_datasets.values()))
    assert len(datasets) == 2
    assert use(*datasets).status == "coefficient"
    public = tmp_path / "public"
    export.write(
        public,
        analyze(Case("argon", ("Ar",), conditions=Conditions(gas_temperature_K=350)), catalog),
    )
    saved = export.read(public, verify_views=True)
    selected = [item for item in saved["reactions"] if item["data_use"]["status"] == "coefficient"]
    assert selected[0]["data_use"]["value"] == pytest.approx(1.25e-15)
    assert adopt.adopt(overlay, root).values == 4
    assert adopt.adopt(overlay, root).values == 0
    datasets = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets
    assert len(datasets) == 2
    assert len(list((root / "assets" / "adopted").glob("*.csv"))) == 1
    assert {item.source_declaration["asset"] for item in datasets} == {"first.csv", "second.csv"}
    assert use(*datasets).value == pytest.approx(1.25e-15)
    if native:
        (tmp_path / "second.csv").write_bytes(CHANGED)
        before = overlay.read_bytes()
        rejected = ingest.ingest(paths[1], bundle, overlay)
        assert rejected.accepted == 0
        assert overlay.read_bytes() == before


@pytest.mark.parametrize(
    "changed",
    [
        {"threshold_eV": 1},
        {"deltaE_products_minus_reactants_eV": 1},
        {"status": "curated"},
        {"method": "calculated"},
        {"review_scope": ["channel_assertion"]},
        {"source_condition": {"bath_gas": "helium"}},
    ],
)
def test_anonymous_mixed_claims_keep_scientific_differences_in_their_identity(changed):
    entry = record("curve.csv") | {"source": {"provider": "laboratory"}}
    first = snapshot_reaction(entry, datasets=())
    second = snapshot_reaction(entry | changed, datasets=())
    assert first.id != second.id


def test_anonymous_mixed_claim_identity_ignores_only_independent_quantity_fields():
    entry = record("first.csv") | {"source": {"provider": "laboratory"}}
    first = snapshot_reaction(entry, datasets=())
    second = snapshot_reaction(
        entry | {"asset": "second.csv", "parameters": {"value": 99}}, datasets=()
    )
    assert first.id == second.id
    assert first.source_declaration != second.source_declaration


def test_changed_saved_asset_is_rejected_before_adoption_mutates_files(tmp_path):
    root = registry(tmp_path / "registry")
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    dataset = normalized_dataset(record(path.name), base=tmp_path)
    loaded = Registry.load(root)
    candidate = next(iter(loaded.channels.values()))[0]
    target = registry_reaction_candidate(candidate, loaded.species).id
    overlay = write(tmp_path / "overlay.yaml", {"datasets": {target: [dataset_payload(dataset)]}})
    before = {
        item.relative_to(root): item.read_bytes() for item in root.rglob("*") if item.is_file()
    }
    path.write_bytes(CHANGED)
    with pytest.raises(ValueError, match="recorded checksum"):
        adopt.adopt(overlay, root)
    assert {
        item.relative_to(root): item.read_bytes() for item in root.rglob("*") if item.is_file()
    } == before


def test_adoption_copies_the_checked_bytes_even_if_the_source_changes_after_read(
    tmp_path, monkeypatch
):
    root = registry(tmp_path / "registry")
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    dataset = normalized_dataset(record(path.name), base=tmp_path)
    loaded = Registry.load(root)
    candidate = next(iter(loaded.channels.values()))[0]
    target = registry_reaction_candidate(candidate, loaded.species).id
    overlay = write(tmp_path / "overlay.yaml", {"datasets": {target: [dataset_payload(dataset)]}})
    original = AssetReference.read_bytes

    def read_and_change(asset, check_declaration=True):
        content = original(asset, check_declaration)
        if asset.local_path == path and content is not None:
            path.write_bytes(CHANGED)
        return content

    monkeypatch.setattr(AssetReference, "read_bytes", read_and_change)
    assert adopt.adopt(overlay, root).values == 1
    adopted = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets[0]
    assert adopted.asset.local_path.read_bytes() == TABLE
    assert use(adopted).value == pytest.approx(1.25e-15)
    assert path.read_bytes() == CHANGED


def test_invalid_author_checksum_is_preserved_when_copied_and_repeated(tmp_path):
    root = registry(tmp_path / "registry")
    path = tmp_path / "curve.csv"
    path.write_bytes(TABLE)
    entry = record({"path": path.name, "sha256": "0" * 64})
    dataset = normalized_dataset(entry, base=tmp_path)
    loaded = Registry.load(root)
    candidate = next(iter(loaded.channels.values()))[0]
    target = registry_reaction_candidate(candidate, loaded.species).id
    overlay = write(tmp_path / "overlay.yaml", {"datasets": {target: [dataset_payload(dataset)]}})
    assert adopt.adopt(overlay, root).values == 1
    assert adopt.adopt(overlay, root).values == 0
    adopted = Registry.load(root).channels[("neutral", "Ar", "Ar")][0].datasets[0]
    assert adopted.asset.sha256 == sha256(TABLE).hexdigest()
    assert adopted.asset.declared_sha256 == "0" * 64
    assert not adopted.asset.integrity_ok
    assert use(adopted).value is None
