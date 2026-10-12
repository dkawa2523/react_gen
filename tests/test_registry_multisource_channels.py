"""Registry additions preserve channels and never resolve identity by file order."""

from copy import deepcopy
from pathlib import Path

import pytest

from reactgen import yamlio
from reactgen.case import Conditions
from reactgen.evidence import EvidenceCatalog, registry_reaction_candidate
from reactgen.numeric import data_use
from reactgen.registry import Registry

PAIR = {"family": "neutral_neutral", "projectile": "Ar", "target": "O2"}


def _registry(root: Path) -> Path:
    directory = root / "species"
    directory.mkdir(parents=True)
    for name, composition in (("Ar", {"Ar": 1}), ("O2", {"O": 2})):
        (directory / f"{name}.yaml").write_text(
            yamlio.dump({"id": name, "composition": composition, "phase": "gas"}),
            encoding="utf-8",
        )
    return root


def _channel(identifier: str, value: float = 1e-16) -> dict:
    return {
        "id": identifier,
        "type": "elastic",
        "products": [{"species": "Ar"}, {"species": "O2"}],
        "source_record": {"source_id": identifier, "citation": f"measurement {identifier}"},
        "data": {
            "datasets": [
                {
                    "id": f"{identifier}-rate",
                    "kind": "rate_coefficient",
                    "representation": "constant",
                    "unit": "m3/s",
                    "parameters": {"value": value},
                    "validity": {
                        "quantity": "gas_temperature",
                        "minimum": 300,
                        "maximum": 500,
                        "unit": "K",
                    },
                    "status": "reviewed",
                }
            ]
        },
    }


def _pair_file(root: Path, name: str, channels: list[dict], pair: dict | None = None) -> Path:
    path = root / "reactions" / "neutral_neutral" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yamlio.dump({"pair": pair or PAIR, "channels": channels}), encoding="utf-8")
    return path


def test_multiple_files_retain_all_channels_and_source_records(tmp_path: Path) -> None:
    root = _registry(tmp_path / "registry")
    _pair_file(root, "a.yaml", [_channel("source-z")])
    _pair_file(root, "b.yaml", [_channel("source-a"), _channel("source-m")])
    registry = Registry.load(root)
    group = registry.channels[("neutral_neutral", "Ar", "O2")]
    assert [record.id for record in group] == ["source-a", "source-m", "source-z"]
    candidate = registry_reaction_candidate(group[0], registry.species)
    assert candidate is not None
    evidence = EvidenceCatalog.load(root).reaction(candidate)
    assert {record.source["source_id"] for record in evidence.records} == {
        "source-a",
        "source-m",
        "source-z",
    }
    assert {dataset.id for dataset in evidence.datasets} == {
        "source-a-rate",
        "source-m-rate",
        "source-z-rate",
    }
    assert data_use(candidate, evidence, Conditions(gas_temperature_K=350)).value == 1e-16


def test_file_names_and_channel_order_do_not_select_a_source(tmp_path: Path) -> None:
    first = _registry(tmp_path / "first")
    second = _registry(tmp_path / "second")
    offered = [_channel("source-z"), _channel("source-a"), _channel("source-m")]
    _pair_file(first, "a.yaml", offered[:2])
    _pair_file(first, "b.yaml", offered[2:])
    _pair_file(second, "a.yaml", offered[2:])
    _pair_file(second, "z.yaml", list(reversed(offered[:2])))
    held = Registry.load(first)
    reordered = Registry.load(second)
    assert held.channels == reordered.channels
    channel = held.channels[("neutral_neutral", "Ar", "O2")][0]
    candidate = registry_reaction_candidate(channel, held.species)
    assert candidate is not None
    evidence = [EvidenceCatalog.load(root).reaction(candidate) for root in (first, second)]
    assert evidence[0] == evidence[1]
    assert data_use(candidate, evidence[0], Conditions(gas_temperature_K=350)) == data_use(
        candidate, evidence[1], Conditions(gas_temperature_K=350)
    )


def test_conflicting_sources_remain_unselected_after_reordering(tmp_path: Path) -> None:
    first = _registry(tmp_path / "first")
    second = _registry(tmp_path / "second")
    offered = [_channel("source-z"), _channel("source-a", value=2e-16)]
    _pair_file(first, "a.yaml", offered[:1])
    _pair_file(first, "b.yaml", offered[1:])
    _pair_file(second, "a.yaml", list(reversed(offered)))
    held = Registry.load(first)
    reordered = Registry.load(second)
    assert held.channels == reordered.channels
    channel = held.channels[("neutral_neutral", "Ar", "O2")][0]
    candidate = registry_reaction_candidate(channel, held.species)
    assert candidate is not None
    evidence = [EvidenceCatalog.load(root).reaction(candidate) for root in (first, second)]
    assert evidence[0] == evidence[1]
    uses = [data_use(candidate, records, Conditions(gas_temperature_K=350)) for records in evidence]
    assert uses[0] == uses[1]
    assert uses[0].status == "conflict"
    assert uses[0].dataset_id is None
    assert uses[0].value is None
    assert {record.id for record in evidence[0].datasets} == {"source-z-rate", "source-a-rate"}


@pytest.mark.parametrize("same_content", [True, False])
def test_duplicate_channel_id_reports_both_files_and_content(
    tmp_path: Path, same_content: bool
) -> None:
    root = _registry(tmp_path / "registry")
    original = _channel("duplicated")
    offered = deepcopy(original)
    if not same_content:
        offered["data"]["datasets"][0]["parameters"]["value"] = 2e-16
    first = _pair_file(root, "a.yaml", [original])
    second = _pair_file(root, "b.yaml", [offered])
    with pytest.raises(ValueError, match="duplicate channel id 'duplicated'") as error:
        Registry.load(root)
    message = str(error.value)
    assert str(first) in message
    assert str(second) in message
    expected = "same declaration" if same_content else "different declarations"
    assert expected in message
    assert "distinct IDs" in message


def test_duplicate_id_within_one_file_reports_both_channel_positions(tmp_path: Path) -> None:
    root = _registry(tmp_path / "registry")
    _pair_file(root, "source.yaml", [_channel("duplicated"), _channel("duplicated")])
    with pytest.raises(ValueError, match="duplicate channel id") as error:
        Registry.load(root)
    assert "channel 1" in str(error.value)
    assert "channel 2" in str(error.value)


def test_same_id_for_another_pair_is_not_the_same_declaration(tmp_path: Path) -> None:
    root = _registry(tmp_path / "registry")
    _pair_file(root, "a.yaml", [_channel("duplicated")])
    _pair_file(
        root,
        "b.yaml",
        [_channel("duplicated")],
        {"family": "neutral_neutral", "projectile": "O2", "target": "O2"},
    )
    with pytest.raises(ValueError, match="duplicate channel id .*different declarations"):
        Registry.load(root)


def test_dataset_id_conflict_is_retained_for_numerical_assessment(tmp_path: Path) -> None:
    root = _registry(tmp_path / "registry")
    offered = [_channel("source-a"), _channel("source-b", value=2e-16)]
    for channel in offered:
        channel["data"]["datasets"][0]["id"] = "same-dataset-id"
    _pair_file(root, "a.yaml", offered[:1])
    _pair_file(root, "b.yaml", offered[1:])
    registry = Registry.load(root)
    group = registry.channels[("neutral_neutral", "Ar", "O2")]
    candidate = registry_reaction_candidate(group[0], registry.species)
    assert candidate is not None
    evidence = EvidenceCatalog.load(root).reaction(candidate)
    assert [dataset.params["value"] for dataset in evidence.datasets] == [1e-16, 2e-16]
    use = data_use(candidate, evidence, Conditions(gas_temperature_K=350))
    assert use.status == "conflict"
    assert use.dataset_id is None
    assert use.value is None
    assert use.datasets[0].reason == "same ID has different content"


@pytest.mark.parametrize("identifier", [None, 12, "", "  "])
def test_channel_identity_requires_nonempty_text(tmp_path: Path, identifier: object) -> None:
    root = _registry(tmp_path / "registry")
    channel = _channel("valid")
    channel["id"] = identifier
    _pair_file(root, "source.yaml", [channel])
    with pytest.raises(ValueError, match="channel 1 id must be nonempty text"):
        Registry.load(root)


def test_missing_channel_id_is_a_located_input_error(tmp_path: Path) -> None:
    root = _registry(tmp_path / "registry")
    channel = _channel("valid")
    del channel["id"]
    path = _pair_file(root, "source.yaml", [channel])
    with pytest.raises(ValueError, match="channel 1 id must be nonempty text") as error:
        Registry.load(root)
    assert str(path) in str(error.value)


def test_current_registry_keeps_every_declared_channel() -> None:
    root = Path(__file__).resolve().parents[1] / "registry"
    declared = [
        channel["id"]
        for path in (root / "reactions").glob("*/*.yaml")
        for channel in yamlio.load(path.read_text(encoding="utf-8")).get("channels", [])
    ]
    loaded = [channel.id for group in Registry.load(root).channels.values() for channel in group]
    assert sorted(loaded) == sorted(declared)
