"""Acquisition boundaries preserve meaning instead of renaming source values."""

from __future__ import annotations

import hashlib
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from acquire import asd, ideal_gas, snapshot
from reactgen import yamlio
from reactgen.chemistry import parse_state_id
from reactgen.evidence import EvidenceCatalog

HEADER = "Configuration\tTerm\tJ\tPrefix\tLevel (eV)\tSuffix\tUncertainty (eV)\tReferences"
GROUND = "closed\t1S\t0\t\t0.000000000\t\t\tL1"


def acquired(monkeypatch, row, *, extra=()):
    text = "\n".join((HEADER, GROUND, row, *extra))
    monkeypatch.setattr(asd, "_request", lambda symbol: text)
    return asd.fetch(["Ar"])[0], text


@pytest.mark.parametrize(
    ("prefix", "energy", "suffix", "origin"),
    [
        ("[", "1.234567891", "]", "semi_empirical"),
        ("", "[1.234567891]", "", "semi_empirical"),
        ("(", "1.234567891", ")", "calculated"),
        ("", "(1.234567891)", "", "calculated"),
        ("", "1.234567891", "", "unknown"),
    ],
)
def test_asd_preserves_origin_reference_uncertainty_and_precision(
    monkeypatch, tmp_path, prefix, energy, suffix, origin
):
    row = f"open\t3P*\t1\t{prefix}\t{energy}\t{suffix}\t0.000000007\tL2,L3"
    found, text = acquired(monkeypatch, row)
    assert found.lowest_eV == 1.234567891
    assert found.levels[-1].energy_origin == origin
    written = asd.records([found], "NIST ASD")
    path = snapshot.write(tmp_path, "state_property", {}, written)
    stored = yamlio.load(path.read_text(encoding="utf-8"))["records"]
    raw = stored[0]["source_levels"][-1]
    assert raw["declared"]["References"] == "L2,L3"
    assert raw["declared"]["Prefix"] == prefix
    assert raw["declared"]["Level (eV)"] == energy
    assert raw["declared"]["Suffix"] == suffix
    assert raw["uncertainty"]["absolute"] == 0.000000007
    assert stored[0]["source_response"] == {
        "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    assert all(item["status"] == "imported" and "existence" not in item for item in stored)


@pytest.mark.parametrize(
    ("energy", "suffix", "reason"),
    [
        ("1.2", "+x", "unknown absolute energy offset"),
        ("1.2+y", "", "unknown absolute energy offset"),
        ("(1.2)", "+z", "unknown absolute energy offset"),
        ("1.2?", "", "doubtful"),
        ("1.2", "†", "doubtful"),
        ("1.2", "unexpected", "unsupported level annotation"),
        ("nan", "", "unsupported level declaration"),
        ("", "", "missing"),
    ],
)
def test_asd_does_not_promote_a_component_or_next_row_to_a_minimum(
    monkeypatch, energy, suffix, reason
):
    found, _ = acquired(
        monkeypatch,
        f"open\t3P*\t1\t\t{energy}\t{suffix}\t\tL2",
        extra=("other\t1P*\t1\t\t2.0\t\t\tL4",),
    )
    assert not found.known
    assert reason in found.error
    records = asd.records([found], "NIST ASD")
    assert all(item["value"] is None for item in records)
    assert len(records[0]["source_levels"]) == 3
    assert reason in records[0]["qualifier"]


def test_asd_missing_j_only_withholds_the_e1_classifications(monkeypatch):
    found, _ = acquired(monkeypatch, "open\t3P*\t1 or 2\t\t1.25\t\t\tL2")
    assert found.lowest_eV == 1.25
    assert found.resonant_eV is None
    assert found.metastable_eV is None
    assert "unresolved J" in found.notes[0]
    with pytest.raises(ValueError, match="definite absolute levels and J"):
        asd.metastable(list(found.levels))


def test_asd_grouped_configuration_and_its_doubt_are_inherited(monkeypatch):
    found, _ = acquired(
        monkeypatch,
        "open?\t3P*\t1\t\t1.25\t\t\tL2",
        extra=("\t\t2\t\t1.30\t\t\tL2",),
    )
    assert not found.known
    assert found.levels[-1].configuration == "open?"
    assert found.levels[-1].term == "3P*"
    assert "doubtful configuration" in found.levels[-1].withheld_reason


def test_asd_new_configuration_does_not_inherit_the_previous_term(monkeypatch):
    found, _ = acquired(monkeypatch, "open\t\t1\t\t1.25\t\t\tL2")
    assert not found.known
    assert found.levels[-1].term == ""
    assert "missing or doubtful configuration/term" in found.error


@pytest.mark.parametrize(
    "text",
    [
        "Configuration\tTerm\tJ\tLevel (cm-1)\nclosed\t1S\t0\t0",
        HEADER + "\nclosed\t1S\t0\t\t0",
        HEADER.replace("Uncertainty (eV)", "Uncertainty (cm-1)") + "\n" + GROUND,
        "<html>A server response is not an ASD table</html>",
    ],
)
def test_asd_unsupported_formats_return_the_response_and_a_concrete_reason(monkeypatch, text):
    monkeypatch.setattr(asd, "_request", lambda symbol: text)
    found = asd.fetch(["Ar"])[0]
    assert not found.known
    assert "unsupported ASD" in found.error
    assert asd.records([found], "NIST")[0]["source_response"]["text"] == text


def test_asd_blank_uncertainty_is_unknown_not_zero(monkeypatch):
    found, _ = acquired(monkeypatch, "open\t3P*\t1\t\t1.25\t\t\tL2")
    assert asd.records([found], "NIST")[0]["source_levels"][-1]["uncertainty"]["absolute"] is None
    query = parse_qs(urlparse(found.query_url).query)
    assert query["unc_out"] == ["1"]
    assert query["biblio"] == ["on"]


def test_asd_parser_can_read_named_reordered_columns_and_spreadsheet_text(monkeypatch):
    text = (
        'J\tTerm\tConfiguration\tLevel (eV)\tReferences\n0\t1S\tclosed\t="0"\tL1\n'
        '1\t3P*\topen\t="1.25"\tL2'
    )
    monkeypatch.setattr(asd, "_request", lambda symbol: text)
    found = asd.fetch(["Ar"])[0]
    assert found.lowest_eV == 1.25


def fake_pyromat(monkeypatch, *, enthalpy=0.054, composition=None):
    config = {"unit_energy": "J", "unit_matter": "kg", "unit_temperature": "C"}
    model = {
        "id": "ig.O2",
        "class": "ig2",
        "Tref": 298.15,
        "ho": 0.0,
        "pref": 100000.0,
        "Tlim": [200.0, 1000.0, 6000.0],
        "doc": "NASA TM-4513; source fit note",
        "C": [[1.0, 2.0]],
    }
    species = SimpleNamespace(
        data=model,
        atoms=lambda: composition if composition is not None else {"O": 2},
        h=lambda **kwargs: enthalpy,
    )
    package = SimpleNamespace(
        config=config,
        get=lambda name: species,
        utility=SimpleNamespace(PMParamError=LookupError, Error=LookupError),
    )
    monkeypatch.setitem(sys.modules, "pyromat", package)
    monkeypatch.setattr(ideal_gas, "version", lambda name: "test-release")
    return package, model


def test_pyromat_h300_preserves_model_conditions_and_never_fills_formation_energy(
    monkeypatch, tmp_path
):
    package, model = fake_pyromat(monkeypatch)
    units_before = dict(package.config)
    found = ideal_gas.fetch(["O2"], {"O2": {"O": 2}})
    assert package.config == units_before
    assert found[0].enthalpy_eV == pytest.approx(0.054 / ideal_gas.JOULE_PER_EV)
    acquired_records = ideal_gas.records(found, "PyroMat")
    record = acquired_records[0]
    assert record["property"] == "enthalpy_eV"
    assert record["temperature_K"] == 300.0
    assert record["reference_temperature_K"] == 298.15
    assert record["standard_pressure_Pa"] == 100000.0
    assert record["source_record"] == model
    assert record["package_version"] == "test-release"
    assert "formation enthalpy is not determined" in record["qualifier"]
    path = snapshot.write(tmp_path, "state_property", {}, acquired_records)
    matched = EvidenceCatalog.load_paths((path,)).state(parse_state_id("O2@ground"))
    assert matched.preferred is not None
    assert "enthalpy_formation_eV" not in matched.preferred.properties
    assert matched.preferred.properties["enthalpy_eV"].tier == "imported"
    assert matched.preferred.existence == "unknown"


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), [], [1.0, 2.0]])
def test_pyromat_non_values_do_not_become_numeric_evidence(monkeypatch, value):
    fake_pyromat(monkeypatch, enthalpy=value)
    found = ideal_gas.fetch(["O2"], {"O2": {"O": 2}})[0]
    assert not found.known
    assert found.error is not None
    assert ideal_gas.records([found], "PyroMat") == []


def test_pyromat_fractional_atoms_are_not_rounded_into_a_target_match(monkeypatch):
    fake_pyromat(monkeypatch, composition={"O": 2.5})
    found = ideal_gas.fetch(["O2"], {"O2": {"O": 2}})[0]
    assert not found.known
    assert "composition is unavailable" in found.error


def test_pyromat_restores_units_and_does_not_hide_an_implementation_failure(monkeypatch):
    package, _ = fake_pyromat(monkeypatch)
    units_before = dict(package.config)

    def broken(name, wanted):
        raise RuntimeError("implementation failure")

    monkeypatch.setattr(ideal_gas, "_one", broken)
    with pytest.raises(RuntimeError, match="implementation failure"):
        ideal_gas.fetch(["O2"])
    assert package.config == units_before
