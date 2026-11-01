"""Source conversion keeps identity, quantity and raw declarations independent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from acquire import collisiondb, nasa, targets, webbook
from acquire.cli import main
from reactgen.assessment import assess_state_thermochemistry
from reactgen.evidence import EvidenceCatalog, snapshot_state
from reactgen.records import normalized_dataset, normalized_property, state_record_id


def page(formula: str = "CO2", cas: str = "124-38-9") -> str:
    identity = {"@type": "MolecularEntity", "name": "Carbon dioxide", "molecularFormula": formula}
    return f"""<html><script type="application/ld+json">{json.dumps(identity)}</script>
<strong>CAS Registry Number:</strong> {cas}
<table aria-label="One dimensional data">
<tr><th>Quantity</th><th>Value</th><th>Units</th><th>Method</th><th>Reference</th><th>Comment</th></tr>
<tr><td>Δ<sub>f</sub>H°<sub>gas</sub></td><td>-393.51 &plusmn; 0.13</td>
<td>kJ/mol</td><td>Review</td><td><a href="#ref-1">review</a></td><td>standard</td></tr>
<tr><td>IE (evaluated)</td><td>13.777 &plusmn; 0.001</td>
<td>eV</td><td>N/A</td><td>N/A</td><td>L</td></tr>
</table>
<table aria-label="Ionization energy determinations">
<tr><td>14.1</td><td>PE</td><td>source</td><td>Vertical value</td></tr>
</table>
<table aria-label="Appearance energy determinations">
<tr><td>O+</td><td>19</td><td>CO</td><td>EI</td><td>source</td><td>fragment</td></tr>
</table></html>"""


def request(formula="CO2", query="C124389"):
    return targets.requests([{"id": formula, "query": query}])[0][0]


def test_webbook_retains_alternative_values_and_definitions():
    parsed = webbook.parse(page())
    records = webbook.records(parsed, request(), webbook.url("124-38-9"))
    assert len(records) == 3
    assert records[0]["value"] == pytest.approx(-393510 / 96485.33212)
    assert records[0]["uncertainty"]["absolute"] == pytest.approx(130 / 96485.33212)
    assert records[0]["formation_reference"]["temperature_K"] is None
    assert records[0]["source_declaration"]["method"] == "Review"
    assert records[0]["source_declaration"]["links"] == ["#ref-1"]
    assert records[2]["definition"] == "vertical"
    assert records[2]["qualifier"] == "source_state_unconfirmed"
    assert all("record_id" not in record["source"] for record in records)
    assert len({state_record_id(record) for record in records}) == 3
    assert all(
        record["source_declaration"]["native_quantity_record_id"] is None for record in records
    )
    assert normalized_property(records[0]).tier == "imported"
    assert normalized_property(records[2], quantity="ionization_energy_eV").definition == "vertical"


def test_webbook_identity_is_not_a_formula_match_only():
    with pytest.raises(ValueError, match="composition differs"):
        webbook.records(webbook.parse(page("CO")), request(), webbook.url("C124389"))
    with pytest.raises(ValueError, match="explicit source query"):
        webbook.records(webbook.parse(page(cas="111-11-1")), request(), webbook.url("C124389"))
    with pytest.raises(ValueError, match="identify one species"):
        webbook.parse("<html>several matching species</html>")
    with pytest.raises(ValueError, match="explicit CAS"):
        webbook.url("CO2")


def test_webbook_does_not_transfer_an_isomer_to_a_different_requested_structure():
    parsed = webbook.parse(page("C2H6O", "115-10-6"))
    parsed.identity.update({"name": "Dimethyl ether", "inChI": "InChI=1S/C2H6O/c1-3-2/h1-2H3"})
    wrong = targets.requests([{"id": "C2H6O", "structure": "ethanol", "query": "C115106"}])[0][0]
    with pytest.raises(ValueError, match="source structure differs"):
        webbook.records(parsed, wrong, webbook.url("C115106"))
    formula_only = request("C2H6O", "C115106")
    records = webbook.records(parsed, formula_only, webbook.url("C115106"))
    assert records[0]["structure"] == parsed.identity["inChI"]
    matched = targets.requests(
        [{"id": "C2H6O", "structure": "Dimethyl ether", "query": "C115106"}]
    )[0][0]
    assert (
        webbook.records(parsed, matched, webbook.url("C115106"))[0]["structure"]
        == parsed.identity["inChI"]
    )


def test_diatomic_isotope_identity_is_kept_separate_from_unqualified_formula():
    parsed = webbook.parse(page("N2", "7727-37-9"))
    parsed.identity.update({"name": "Nitrogen", "inChI": "InChI=1S/N2/c1-2/i1+1,2+1"})
    record = webbook.records(parsed, request("N2", "C7727379"), webbook.url("C7727379"))[0]
    assert record["structure"] == parsed.identity["inChI"]


@pytest.mark.parametrize("bad", ["not a value", "-393 ± -0.1", "-393 kcal/mol"])
def test_webbook_numeric_layout_errors_are_not_missing_data(bad):
    with pytest.raises(ValueError, match="WebBook"):
        webbook.parse(page().replace("-393.51 &plusmn; 0.13", bad))


def test_saved_webbook_conversion_keeps_original_bytes(tmp_path):
    species = tmp_path / "species.yaml"
    species.write_text("- id: CO2\n  query: 124-38-9\n", encoding="utf-8")
    raw = tmp_path / "source.html"
    raw.write_text(page(), encoding="utf-8")
    out = tmp_path / "converted"
    assert main(["webbook", str(species), "--page", str(raw), "--out", str(out)]) == 0
    document = yaml.safe_load((out / "snapshot.yaml").read_text(encoding="utf-8"))
    for record in document["records"]:
        acquisition = record["source_declaration"]["acquisition"]
        assert acquisition["sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
        assert (out / acquisition["raw_path"]).read_bytes() == raw.read_bytes()
        assert record["status"] == "imported"


def collision_file(tmp_path: Path, **changed) -> Path:
    metadata = {
        "qid": "D123",
        "reaction": "e- + H 1s -> H n=2 + e-",
        "data_type": "cross section",
        "method": "theory",
        "columns": [{"name": "E", "units": "keV"}, {"name": "sigma", "units": "cm2"}],
        "refs": {"B1": {"doi": "10.3390/atoms12030020"}},
        "threshold": 10.2,
        "unc_perc": 5,
        "recommended": True,
    } | changed
    path = tmp_path / "dataset.txt"
    path.write_text(
        json.dumps(metadata) + "\n-----\n0.02 1e-16:1e-17\n0.03 2e-16:1e-17:3e-17\n",
        encoding="utf-8",
    )
    return path


def test_collisiondb_converts_units_and_keeps_point_uncertainties(tmp_path):
    item = collisiondb.parse(collision_file(tmp_path))
    for actual, expected in zip(item.rows, [(20.0, 1e-20), (30.0, 2e-20)], strict=True):
        assert actual == pytest.approx(expected)
    record = collisiondb.record(item, tmp_path / "out")
    dataset = normalized_dataset(record, default_kind="cross_section", base=tmp_path / "out")
    assert dataset.status == "imported"
    assert dataset.channel_scope == "unknown"
    assert dataset.independent_variable is None
    assert dataset.observable is None
    assert dataset.uncertainty.relative == 0.05
    assert record["source_declaration"]["metadata"]["recommended"] is True
    assert record["source_declaration"]["point_uncertainties"][1]["absolute_m2"] == pytest.approx(
        [1e-21, 3e-21]
    )


def test_collisiondb_explicit_mapping_does_not_erase_stateful_source(tmp_path):
    item = collisiondb.parse(collision_file(tmp_path, frame="target", channel="several channels"))
    record = collisiondb.record(
        item,
        tmp_path / "out",
        reaction="e + H -> e + H*",
        process_type="excitation",
        independent_variable="electron_energy",
        observable="reaction",
        channel_scope="total_process",
    )
    assert record["reaction"] == "e + H -> e + H*"
    assert record["source_declaration"]["metadata"]["reaction"] == item.metadata["reaction"]
    assert record["validity"]["unresolved_conditions"] == {
        "energy_frame": "target",
        "composite_channels": "several channels",
    }


@pytest.mark.parametrize(
    "changed",
    [
        {"data_type": "differential cross section"},
        {"data_type": "rate coefficient"},
        {"columns": [{"name": "E", "units": "eV/u"}, {"name": "sigma", "units": "cm2"}]},
    ],
)
def test_collisiondb_other_observables_are_not_relabelled(tmp_path, changed):
    with pytest.raises(ValueError, match="CollisionDB"):
        collisiondb.parse(collision_file(tmp_path, **changed))


def test_collisiondb_malformed_and_missing_points_are_errors(tmp_path):
    path = collision_file(tmp_path)
    original = path.read_text(encoding="utf-8")
    for replacement in ("*", "nan", "-1", "1e-20:abc"):
        path.write_text(original.replace("2e-16:1e-17:3e-17", replacement), encoding="utf-8")
        with pytest.raises(ValueError, match="CollisionDB"):
            collisiondb.parse(path)


def test_collisiondb_invalid_metadata_does_not_write_assets(tmp_path):
    item = collisiondb.parse(collision_file(tmp_path, threshold="10 eV"))
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="threshold"):
        collisiondb.record(item, out)
    assert not out.exists()


def test_heavy_particle_collision_requires_source_energy_frame(tmp_path):
    path = collision_file(tmp_path, reaction="He+ + H 1s -> He + H+")
    with pytest.raises(ValueError, match="requires its source energy frame"):
        collisiondb.parse(path)
    item = collisiondb.parse(
        collision_file(tmp_path, reaction="He+ + H 1s -> He + H+", frame="com")
    )
    record = collisiondb.record(item, tmp_path / "out", independent_variable="ion_energy")
    assert record["validity"]["unresolved_conditions"] == {"energy_frame": "com"}


def test_collisiondb_fit_scope_and_origin_are_not_measurement_uncertainty(tmp_path):
    item = collisiondb.parse(
        collision_file(
            tmp_path,
            columns=[{"name": "E", "units": "eV"}, {"name": "sigma", "units": "cm2"}],
            data_from_fit=True,
            method="experimental",
            fit={"Elo": 0.021, "fit_unc_perc": 1.3},
            threshold="0.02",
        )
    )
    record = collisiondb.record(item, tmp_path / "out")
    assert record["method"] == "calculated"
    assert record["validity"]["minimum"] == 0.021
    assert record["threshold_eV"] == 0.02
    assert record["uncertainty"] == {"relative": 0.05}
    assert record["source_declaration"]["metadata"]["fit"]["fit_unc_perc"] == 1.3


def test_nasa_compilation_pressure_is_distinct_from_software_default():
    key = ((("Ar", 1),), 0)
    row = {
        "name": "Ar",
        "origin": "nasa_gas.yaml",
        "composition": {"Ar": 1},
        "thermo": {
            "model": "NASA7",
            "temperature-ranges": [200, 1000],
            "data": [[1, 2, 3, 4, 5, 6, 7]],
        },
    }
    item = {"id": "Ar", "composition": {"Ar": 1}, "charge": 0}
    result = nasa._one(item, {key: [row]})
    assert result.standard_pressure_Pa == 100000
    assert result.source_declaration["declared_reference_pressure"] is None
    assert result.source_declaration["cantera_omitted_reference_pressure_default_Pa"] == 101325
    explicit = row | {"thermo": row["thermo"] | {"reference-pressure": "1 atm"}}
    assert nasa._one(item, {key: [explicit]}).standard_pressure_Pa == 101325
    other = row | {"origin": "another.yaml"}
    assert nasa._one(item, {key: [other]}).standard_pressure_Pa is None


def test_nasa_canonical_structure_and_source_selector_identify_the_same_target():
    key = ((("C", 1), ("H", 4)), 0)
    row = {
        "name": "CH4",
        "thermo": {
            "model": "NASA7",
            "temperature-ranges": [200, 1000],
            "data": [[1, 2, 3, 4, 5, 6, 7]],
        },
    }
    result = nasa._one({"id": "CH4@ground;structure=CH4"}, {key: [row]})
    assert result.known
    record = nasa.records([result], "source")[0]
    assert record["structure"] == "CH4"
    assert snapshot_state(record, {}).candidate.structure == "CH4"
    wrong = nasa._one({"id": "CH4@ground;structure=another", "source_species": "CH4"}, {key: [row]})
    assert not wrong.known
    assert "source structure" in wrong.error


def test_unique_nasa_entry_keeps_its_source_structure_for_formula_only_requests():
    key = ((("C", 1), ("H", 2), ("O", 1)), 0)
    row = {
        "name": "formaldehyde",
        "thermo": {
            "model": "NASA7",
            "temperature-ranges": [200, 1000],
            "data": [[1, 2, 3, 4, 5, 6, 7]],
        },
    }
    result = nasa._one({"id": "CH2O"}, {key: [row]})
    record = snapshot_state(nasa.records([result], "source")[0], {})
    catalog = EvidenceCatalog(state_records=(record,))
    evidence = catalog.state(targets.requests(["CH2O"])[0][0].target)
    assert evidence.match == "compatible"
    assert evidence.records[0].candidate.structure == "formaldehyde"
    judgment = assess_state_thermochemistry(targets.requests(["CH2O"])[0][0].target, evidence)
    assert judgment.verdict == "unknown"
    assert any(item.responsibility == "identity" for item in judgment.requirements)
