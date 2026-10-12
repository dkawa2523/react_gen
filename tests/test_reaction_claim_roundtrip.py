"""A physical reaction declaration retains its meaning at every local boundary."""

from copy import deepcopy
from pathlib import Path

import pytest

from reactgen import adopt, export, ingest, yamlio
from reactgen.case import Case
from reactgen.evidence import EvidenceCatalog, reaction_record_candidate, snapshot_reaction
from reactgen.pipeline import analyze
from reactgen.records import reaction_record_payload, scientific_reaction_content


def declaration(**changes) -> dict:
    return {
        "record_id": "native-channel-4",
        "reaction": "e + Ar -> e + e + Ar+",
        "type": "ionization",
        "status": "reviewed",
        "method": "measured",
        "review_scope": ["channel_assertion", "threshold_eV", "delta_e_eV"],
        "threshold_eV": 16.0,
        "deltaE_products_minus_reactants_eV": 15.0,
        "source": {"provider": "laboratory", "collection": "channels", "release": "1"},
        **changes,
    }


def write(path: Path, document: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump(document), encoding="utf-8")
    return path


def selected(analysis):
    return next(
        reaction
        for reaction in analysis.candidates.reactions.values()
        if reaction.process == "ionization"
        and {term.species for term in reaction.reactants} == {"e", "Ar@ground"}
        and {term.species for term in reaction.products} == {"e", "Ar+@ground"}
    )


@pytest.mark.parametrize(
    "scope", [["channel_assertion"], ["threshold_eV"], ["delta_e_eV"], ["rate_coefficient"]]
)
def test_claim_and_energy_have_the_same_judgment_after_portable_roundtrip(tmp_path, scope):
    entry = declaration(review_scope=scope)
    source = write(tmp_path / "snapshot.yaml", {"records": [entry]})
    direct_catalog = EvidenceCatalog.load_paths((source,))
    record = direct_catalog.reaction_records[0]
    target = reaction_record_candidate(record)
    overlay = write(
        tmp_path / "overlay.yaml",
        {"reaction_records": {target.id: [reaction_record_payload(record)]}},
    )
    staged_catalog = EvidenceCatalog.load_paths((overlay,))
    saved = staged_catalog.reaction_records[0]
    assert saved.id == record.id
    assert saved.provenance == record.provenance
    assert saved.source_declaration == record.source_declaration
    assert saved.review_scope == record.review_scope
    assert saved.method == record.method
    case = Case("same claims", ("Ar",))
    direct, staged = analyze(case, direct_catalog), analyze(case, staged_catalog)
    reaction = selected(direct)
    assert (
        staged.evaluation.reaction_assessments[reaction.id]["reaction_evidence"]
        == (direct.evaluation.reaction_assessments[reaction.id]["reaction_evidence"])
    )
    assert staged.evaluation.thermochemistry.get(reaction.id, {}) == (
        direct.evaluation.thermochemistry.get(reaction.id, {})
    )


def test_channel_records_preserve_independent_sources_and_same_id_disagreements(tmp_path):
    first = snapshot_reaction(declaration(), datasets=())
    changed = snapshot_reaction(declaration(threshold_eV=17.0), datasets=())
    other = snapshot_reaction(
        declaration(source={"provider": "other", "collection": "channels", "release": "1"}),
        datasets=(),
    )
    assert first is not None
    assert changed is not None
    assert other is not None
    assert first.id == changed.id != other.id
    target = reaction_record_candidate(first)
    root = tmp_path / "registry"
    for name, charge in (("Ar", 0), ("Ar+", 1)):
        write(
            root / "species" / f"{name}.yaml",
            {"id": name, "composition": {"Ar": 1}, "charge": charge, "phase": "gas"},
        )
    write(
        root / "reactions" / "electron" / "Ar.yaml",
        {
            "pair": {"family": "electron", "projectile": "e", "target": "Ar"},
            "channels": [
                {
                    "id": "container",
                    "type": "ionization",
                    "products": [{"species": "e", "n": 2}, {"species": "Ar+"}],
                    "records": [reaction_record_payload(item) for item in (first, changed, other)],
                }
            ],
        },
    )
    records = EvidenceCatalog.load(root).reaction(target).exact_records
    scientific = [record for record in records if record.id != "container"]
    assert len(scientific) == 3
    assert {record.threshold_eV for record in scientific} == {16.0, 17.0}
    assert {record.id for record in scientific} == {first.id, other.id}


def test_acquisition_changes_do_not_change_reaction_identity_or_scientific_content():
    first = declaration()
    second = deepcopy(first)
    first["source"]["acquisition"] = {"retrieved_at": "2026-01-01"}
    second["source"]["acquisition"] = {"retrieved_at": "2026-02-01"}
    a = snapshot_reaction(first, datasets=())
    b = snapshot_reaction(second, datasets=())
    assert a is not None
    assert b is not None
    assert a.id == b.id
    assert a.source_declaration != b.source_declaration
    assert scientific_reaction_content(a) == scientific_reaction_content(b)


@pytest.mark.parametrize("changes", [{"surface": "different"}, {"type": "elastic"}])
def test_overlay_rejects_a_declaration_for_a_different_target(tmp_path, changes):
    record = snapshot_reaction(declaration(), datasets=())
    assert record is not None
    target = reaction_record_candidate(record)
    payload = reaction_record_payload(record) | changes
    path = write(tmp_path / "overlay.yaml", {"reaction_records": {target.id: [payload]}})
    with pytest.raises(ValueError, match="contradicts its target"):
        EvidenceCatalog.load_paths((path,))


def test_numeric_only_review_does_not_become_channel_review_when_saved():
    record = snapshot_reaction(
        declaration(
            review_scope=[],
            form="constant",
            parameters={"value": 1e-15},
            unit="m3/s",
            kind="rate_coefficient",
        )
    )
    assert record is not None
    saved = snapshot_reaction(reaction_record_payload(record), preserved_record_id=True)
    assert saved is not None
    assert saved.review_scope == record.review_scope == ("rate_coefficient",)
    assert not saved.reviewed_for("channel_assertion")
    assert not saved.reviewed_for("threshold_eV")


def test_overlay_rejects_embedded_numbers_instead_of_discarding_them(tmp_path):
    record = snapshot_reaction(declaration(), datasets=())
    assert record is not None
    target = reaction_record_candidate(record)
    payload = reaction_record_payload(record) | {"datasets": [{"id": "embedded"}]}
    path = write(tmp_path / "overlay.yaml", {"reaction_records": {target.id: [payload]}})
    with pytest.raises(ValueError, match="use overlay.datasets"):
        EvidenceCatalog.load_paths((path,))


def test_surface_claim_target_retains_its_physical_family():
    record = snapshot_reaction(
        declaration(reaction="F -> F", type="sticking", surface="Si"), datasets=()
    )
    assert record is not None
    target = reaction_record_candidate(record)
    assert target.surface == "Si"
    assert target.family == "surface"


def test_asset_quantity_and_claim_are_idempotent_in_a_relocated_overlay(tmp_path):
    assets = tmp_path / "acquired" / "assets"
    assets.mkdir(parents=True)
    (assets / "curve.csv").write_text("energy_eV,cross_section_m2\n0,0\n1,1e-20\n")
    entry = declaration(
        reaction="e + Ar -> e + Ar",
        type="elastic",
        kind="cross_section",
        representation="table",
        asset="assets/curve.csv",
        unit="m2",
        observable="momentum_transfer",
        review_scope=["cross_section"],
    )
    source = write(assets.parent / "snapshot.yaml", {"records": [entry]})
    bundle = tmp_path / "bundle"
    export.write(bundle, analyze(Case("asset", ("Ar",)), EvidenceCatalog.load_paths((source,))))
    overlay = tmp_path / "elsewhere" / "overlay.yaml"
    assert ingest.ingest(source, bundle, overlay).accepted == 1
    saved = overlay.read_bytes()
    assert ingest.ingest(source, bundle, overlay).accepted == 1
    assert overlay.read_bytes() == saved


@pytest.mark.parametrize(
    "scope", [["channel_assertion"], ["threshold_eV"], ["delta_e_eV"], ["rate_coefficient"]]
)
def test_snapshot_ingest_adopt_share_channel_claims_and_energy_qualification(tmp_path, scope):
    root = tmp_path / "registry"
    for name, charge in (("Ar", 0), ("Ar+", 1)):
        write(
            root / "species" / f"{name}.yaml",
            {"id": name, "composition": {"Ar": 1}, "charge": charge, "phase": "gas"},
        )
    write(
        root / "reactions" / "electron" / "Ar.yaml",
        {
            "pair": {"family": "electron", "projectile": "e", "target": "Ar"},
            "channels": [
                {
                    "id": "container",
                    "type": "ionization",
                    "products": [{"species": "e", "n": 2}, {"species": "Ar+"}],
                }
            ],
        },
    )
    source = write(tmp_path / "snapshot.yaml", {"records": [declaration(review_scope=scope)]})
    case = Case("same reaction claims", ("Ar",))
    direct_catalog = EvidenceCatalog.load_paths((root, source))
    direct = analyze(case, direct_catalog)
    bundle = tmp_path / "bundle"
    export.write(bundle, direct)
    overlay = tmp_path / "overlay.yaml"
    assert ingest.ingest(source, bundle, overlay).accepted == 1
    staged = analyze(case, EvidenceCatalog.load_paths((root, overlay)))
    assert adopt.adopt(overlay, root).values == 1
    adopted_catalog = EvidenceCatalog.load(root)
    adopted = analyze(case, adopted_catalog)
    reaction = selected(direct)
    original_record = next(
        record for record in direct_catalog.reaction_records if record.origin == "snapshot"
    )
    saved_record = next(
        record for record in adopted_catalog.reaction_records if record.id == original_record.id
    )
    assert saved_record.source_declaration == original_record.source_declaration
    assert saved_record.provenance == original_record.provenance
    assert saved_record.review_scope == original_record.review_scope
    assert saved_record.method == original_record.method
    for analysis in (staged, adopted):
        assert analysis.evaluation.reaction_assessments[reaction.id][
            "reaction_evidence"
        ].verdict == (
            direct.evaluation.reaction_assessments[reaction.id]["reaction_evidence"].verdict
        )
        assert analysis.evaluation.thermochemistry.get(reaction.id, {}) == (
            direct.evaluation.thermochemistry.get(reaction.id, {})
        )
