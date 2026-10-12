"""Release layouts and source observables cannot silently change physical meaning."""

from pathlib import Path

import pytest
import yaml

from acquire import lxcat, umist
from acquire.cli import main
from reactgen.records import normalized_dataset


def row(fits: list[str], identifier: int = 1, kind: str = "NN") -> str:
    return f"{identifier}:{kind}:O:O2:O:O2:::{len(fits)}:" + ":".join(fits)


@pytest.mark.parametrize(("version", "width"), [("RATE12", 8), ("RATE22", 9)])
def test_every_declared_fit_and_original_method_are_preserved(
    tmp_path: Path, version: str, width: int
) -> None:
    fits = ["1e-12:0:0:10:100:M:A:reference", "2e-12:1:50:100:500:C:C:other"]
    if width == 9:
        fits = [fit + ":note" for fit in fits]
    path = tmp_path / "source.rates"
    original = row(fits)
    path.write_text(original, encoding="utf-8")
    rates = umist.parse(path, version)
    assert [(rate.t_min, rate.t_max) for rate in rates] == [(10, 100), (100, 500)]
    records = umist.records(rates)
    assert len(records) == 2
    assert {item["source"]["format_version"] for item in records} == {version}
    assert records[0]["source_declaration"]["accuracy"] == "A"
    assert records[0]["source_declaration"]["row"] == original
    assert rates[0].note == ("note" if width == 9 else "")


def test_ambiguous_trailing_empty_note_requires_format_choice(tmp_path: Path) -> None:
    path = tmp_path / "source.rates"
    path.write_text(row(["1e-12:0:0:10:100:M:A:ref:"]), encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        umist.parse(path)
    assert len(umist.parse(path, "RATE22")) == 1


def test_umist_native_fit_identity_is_scoped_by_the_stated_release(tmp_path: Path) -> None:
    path = tmp_path / "source.rates"
    path.write_text(row(["1e-12:0:0:10:100:M:A:ref:note"]), encoding="utf-8")
    record = umist.records(umist.parse(path, "RATE22"))[0]
    assert "id" not in record
    first = normalized_dataset(record, default_source={"release": "one"})
    second = normalized_dataset(record, default_source={"release": "two"})
    assert first.provenance.record_id == second.provenance.record_id
    assert first.id != second.id


def test_quoted_note_with_release_padding_preserves_the_original_row(tmp_path: Path) -> None:
    path = tmp_path / "source.rates"
    original = row(['1e-12:0:0:10:100:M:A:ref:"holding value"']) + "   "
    path.write_text(original, encoding="utf-8")
    rate = umist.parse(path, "RATE22")[0]
    assert rate.note == "holding value"
    assert rate.raw_row == original


@pytest.mark.parametrize("fit", ["bad:0:0:10:100:M:A:ref", "1e-12:0:0:500:100:M:A:ref"])
def test_invalid_second_fit_does_not_return_only_the_first(tmp_path: Path, fit: str) -> None:
    path = tmp_path / "source.rates"
    path.write_text(row(["1e-12:0:0:10:100:M:A:ref", fit]), encoding="utf-8")
    with pytest.raises(ValueError, match="line 1.*fit 2"):
        umist.parse(path, "RATE12")


def test_overlapping_rows_are_not_independent_complete_rates(tmp_path: Path) -> None:
    path = tmp_path / "source.rates"
    path.write_text(
        row(["1e-12:0:0:10:100:M:A:ref:sum term"], 1)
        + "\n"
        + row(["2e-12:0:0:10:100:C:B:ref:sum term"], 2),
        encoding="utf-8",
    )
    records = umist.records(umist.parse(path))
    assert len(records) == 2
    assert {item["form"] for item in records} == {"reference_only"}
    assert {item["source_declaration"]["fit_relation"] for item in records} == {"unresolved"}
    assert sorted(item["parameters"]["A"] for item in records) == pytest.approx([1e-18, 2e-18])


def test_equation_order_does_not_hide_overlapping_terms(tmp_path: Path) -> None:
    path = tmp_path / "source.rates"
    path.write_text(
        row(["1e-12:0:0:10:100:M:A:ref:term"], 1)
        + "\n"
        + "2:NN:O2:O:O2:O:::1:2e-12:0:0:10:100:C:B:ref:term",
        encoding="utf-8",
    )
    records = umist.records(umist.parse(path, "RATE22"))
    assert len(records) == 2
    assert {item["form"] for item in records} == {"reference_only"}


def test_malformed_quote_reports_the_source_line(tmp_path: Path) -> None:
    path = tmp_path / "source.rates"
    path.write_text(
        row(["1e-12:0:0:10:100:M:A:ref:note"], 1)
        + "\n"
        + row(['2e-12:0:0:10:100:C:B:ref:"extra quote"":'], 2),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="line 2.*invalid quoting"):
        umist.parse(path, "RATE22")


def test_scope_and_elastic_observable_are_not_invented(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text(
        "ELASTIC\nAr\nPROCESS: E + Ar -> E + Ar, Elastic\n"
        "DATABASE: actual-contributor\n-----\n0 1e-20\n1 2e-20\n-----\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert main(["lxcat", str(path), "--out", str(out)]) == 0
    document = yaml.safe_load((out / "snapshot.yaml").read_text(encoding="utf-8"))
    record = document["records"][0]
    assert record["channel_scope"] == "unknown"
    assert record["observable"] is None
    assert record["source_declaration"]["headers"]["DATABASE"] == "actual-contributor"
    assert (out / document["acquisition"]["raw_path"]).read_bytes() == path.read_bytes()
    assert len(document["acquisition"]["sha256"]) == 64


def test_explicit_scope_and_observable_survive(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text(
        "ELASTIC\nAr\nCHANNEL SCOPE: product_resolved\n"
        "OBSERVABLE: momentum_transfer\n-----\n0 1e-20\n1 2e-20\n-----\n",
        encoding="utf-8",
    )
    process = lxcat.parse(path)[0]
    assert lxcat.channel_scope(process) == "product_resolved"
    assert lxcat.observable(process.kind, process.headers) == "momentum_transfer"


def test_unclosed_table_is_an_input_error(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_text("ELASTIC\nAr\n-----\n0 1e-20\n1 2e-20", encoding="utf-8")
    with pytest.raises(ValueError, match="closing separator"):
        lxcat.parse(path)


@pytest.mark.parametrize("tail", ["EXCITATION\nAr\n", "EXCITATION\nAr\nIONIZATION\nAr\n"])
def test_complete_prefix_does_not_hide_an_incomplete_process(tmp_path: Path, tail: str) -> None:
    path = tmp_path / "source.txt"
    path.write_text(
        "ELASTIC\nAr\n-----\n0 1e-20\n1 2e-20\n-----\n" + tail,
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="process block has no table"):
        lxcat.parse(path)
