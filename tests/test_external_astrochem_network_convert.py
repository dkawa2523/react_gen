from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from external_data_tools.astrochem_network_convert import convert_astrochem_network, main
from external_data_tools.astrochem_reaction import (
    convert_reaction_row,
    normalize_species,
    reaction_pair_key,
)

FIELDS = [
    "reactant1",
    "reactant2",
    "product1",
    "product2",
    "product3",
    "alpha",
    "beta",
    "gamma",
    "temperature_min_K",
    "temperature_max_K",
    "source",
    "reference",
]


def test_converts_simple_ion_neutral_row(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "Ar+",
                "reactant2": "CF4",
                "product1": "Ar",
                "product2": "CF4+",
                "product3": "",
                "alpha": "1.2e-9",
                "beta": "0.0",
                "gamma": "10.0",
                "temperature_min_K": "10",
                "temperature_max_K": "300",
                "source": "KIDA:row1",
                "reference": "Example reference",
            }
        ],
    )
    output = tmp_path / "external_data" / "snapshots" / "kida_converted_ion_neutral.yaml"

    report = convert_astrochem_network(network, database="KIDA", output=output)
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    reaction = payload["reactions"][0]

    assert report["total_rows"] == 1
    assert report["ion_neutral_rows"] == 1
    assert report["converted"] == 1
    assert report["skipped"] == 0
    assert report["unresolved"] == []
    assert payload["source"]["database"] == "KIDA"
    assert payload["source"]["review_required"] is True
    assert reaction["projectile"] == "Ar+"
    assert reaction["target"] == "CF4"
    assert reaction["family"] == "ion_neutral"
    assert reaction["type"] == "reactive_scattering"
    assert reaction["status"] == "imported"
    assert reaction["dnt_class"] == "long_range_charge_exchange"
    assert reaction["products"] == [{"species": "Ar", "n": 1}, {"species": "CF4+", "n": 1}]


def test_converts_neutral_neutral_row_and_writes_rate_candidate(tmp_path):
    network = _write_network(
        tmp_path / "umist.tsv",
        [
            {
                "reactant1": "H2",
                "reactant2": "CO",
                "product1": "HCO",
                "product2": "",
                "product3": "",
                "alpha": "1e-10",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "100",
                "source": "UMIST:row1",
                "reference": "Neutral-neutral",
            }
        ],
        delimiter="\t",
    )

    output = tmp_path / "external_data" / "snapshots" / "umist.yaml"
    report = convert_astrochem_network(
        network,
        database="UMIST",
        output=output,
    )

    assert report["total_rows"] == 1
    assert report["ion_neutral_rows"] == 0
    assert report["converted"] == 1
    assert report["converted_by_family"] == {"neutral_neutral": 1}
    assert report["skipped"] == 0
    reaction = yaml.safe_load(output.read_text(encoding="utf-8"))["reactions"][0]
    assert reaction["family"] == "neutral_neutral"
    rates = yaml.safe_load(output.with_suffix(".rate_candidates.yaml").read_text(encoding="utf-8"))
    assert rates["records"][0]["equation"] == "H2 + CO -> HCO"
    assert rates["records"][0]["parameters"]["gamma_K"] == 0.0


def test_classifies_electron_ion_and_opposite_ion_rows(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "e-",
                "reactant2": "O2+",
                "product1": "O",
                "product2": "O",
                "product3": "",
                "alpha": "1e-7",
                "beta": "-0.5",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "1000",
                "source": "KIDA:dr",
                "reference": "DR reference",
            },
            {
                "reactant1": "O+",
                "reactant2": "F-",
                "product1": "O",
                "product2": "F",
                "product3": "",
                "alpha": "2e-7",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "1000",
                "source": "KIDA:mn",
                "reference": "MN reference",
            },
        ],
    )
    output = tmp_path / "candidates.yaml"

    report = convert_astrochem_network(network, database="KIDA", output=output)
    reactions = yaml.safe_load(output.read_text(encoding="utf-8"))["reactions"]

    assert report["converted_by_family"] == {"electron_ion": 1, "ion_ion": 1}
    assert reactions[0]["projectile"] == "e"
    assert reactions[0]["type"] == "dissociative_recombination"
    assert reactions[1]["type"] == "mutual_neutralization"


def test_preserves_rate_coefficients_separately_from_cross_sections(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "H+",
                "reactant2": "H",
                "product1": "H",
                "product2": "H+",
                "product3": "",
                "alpha": "2.0e-9",
                "beta": "-0.5",
                "gamma": "0.1",
                "temperature_min_K": "5",
                "temperature_max_K": "500",
                "source": "KIDA:ct",
                "reference": "Rate reference",
            }
        ],
    )
    output = tmp_path / "snapshot.yaml"

    convert_astrochem_network(network, database="KIDA", output=output)
    reaction = yaml.safe_load(output.read_text(encoding="utf-8"))["reactions"][0]

    assert reaction["data"]["rate_form"] == {
        "alpha": 2.0e-9,
        "beta": -0.5,
        "gamma": 0.1,
        "temperature_min_K": 5.0,
        "temperature_max_K": 500.0,
    }
    assert reaction["data"]["provenance"] == {
        "database": "KIDA",
        "original_source": "KIDA:ct",
        "reference": "Rate reference",
    }
    assert reaction["data"]["review_status"] == "astrochem_candidate_not_semiconductor_validated"
    assert "cross_section" not in reaction["data"]
    assert reaction["source_record"]["review_required"] is True


def test_invalid_notation_reports_unresolved(tmp_path):
    network = _write_network(
        tmp_path / "kida.csv",
        [
            {
                "reactant1": "C?+",
                "reactant2": "CF4",
                "product1": "C",
                "product2": "CF4+",
                "product3": "",
                "alpha": "1e-9",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "300",
                "source": "bad",
                "reference": "bad notation",
            }
        ],
    )

    report = convert_astrochem_network(network, database="KIDA", output=tmp_path / "out.yaml")

    assert report["converted"] == 0
    assert report["unresolved"] == [
        {
            "line": 2,
            "reason": "invalid_notation",
            "message": "reactant notation could not be normalized",
            "reactants": ["C?+", "CF4"],
        }
    ]


def test_normalizes_charge_notation_and_rejects_unsupported_magnitude():
    assert normalize_species("electron") == "e"
    assert normalize_species("Ar(+)") == "Ar+"
    assert normalize_species("Ar_p") == "Ar+"
    assert normalize_species("F_m") == "F-"
    assert normalize_species("Ar+2") is None
    assert reaction_pair_key({"reactant1": "bad species", "reactant2": "Ar"}) is None
    assert reaction_pair_key({"reactant1": "Ar+", "reactant2": "O+"}) is None


@pytest.mark.parametrize(
    ("reactants", "products", "expected_family", "expected_type"),
    [
        (("e", "CF4"), ("CF3", "F-"), "electron", "attachment"),
        (("e", "CF4"), ("CF3", "F"), "electron", "dissociation"),
        (("e", "CF4"), ("CF4",), "electron", "excitation"),
        (("e", "Ar+"), ("Ar",), "electron_ion", "recombination"),
    ],
)
def test_classifies_electron_reaction_boundaries(
    reactants, products, expected_family, expected_type
):
    row = _reaction_row(reactants, products)

    reaction = convert_reaction_row(row, database="UMIST", line_number=1)

    assert reaction is not None
    assert reaction["family"] == expected_family
    assert reaction["type"] == expected_type


def test_invalid_product_notation_is_rejected():
    row = _reaction_row(("Ar+", "CF4"), ("bad product",))

    with pytest.raises(ValueError, match="product notation"):
        convert_reaction_row(row, database="UMIST", line_number=1)


def test_cli_writes_output_and_report(tmp_path):
    network = _write_network(
        tmp_path / "umist.csv",
        [
            {
                "reactant1": "C+",
                "reactant2": "O",
                "product1": "C",
                "product2": "O+",
                "product3": "",
                "alpha": "1e-9",
                "beta": "0",
                "gamma": "0",
                "temperature_min_K": "10",
                "temperature_max_K": "300",
                "source": "UMIST:ct",
                "reference": "UMIST ref",
            }
        ],
    )
    output = tmp_path / "external_data" / "snapshots" / "umist_converted_ion_neutral.yaml"

    exit_code = main([str(network), "--database", "UMIST", "--output", str(output)])

    report_path = output.with_suffix(".conversion_report.yaml")
    report = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert output.exists()
    assert report["converted"] == 1


def _write_network(path: Path, rows: list[dict[str, str]], delimiter: str = ",") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter=delimiter)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _reaction_row(reactants, products):
    padded_products = [*products, "", "", ""]
    return {
        "reactant1": reactants[0],
        "reactant2": reactants[1],
        "product1": padded_products[0],
        "product2": padded_products[1],
        "product3": padded_products[2],
        "product4": padded_products[3],
        "alpha": "1e-9",
        "beta": "0",
        "gamma": "0",
        "temperature_min_K": "10",
        "temperature_max_K": "300",
        "source": "test",
        "reference": "test",
    }
