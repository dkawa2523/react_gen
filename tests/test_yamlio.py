"""YAML boundary semantics are identical with and without LibYAML."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from reactgen import yamlio
from reactgen.case import Case
from reactgen.cli import main


@pytest.mark.parametrize(
    "text",
    [
        "gases: [Ar]\ngases: [CF4]\n",
        "property: {tier: imported, tier: reviewed}",
        "property:\n  value: 1\n  'value': 2\n",
        "a: &a {x: 1, x: 2}\nb: {<<: *a}",
        "a: &a {x: 1}\nb: {<<: *a, <<: *a}",
    ],
)
def test_duplicate_declarations_are_rejected(text: str) -> None:
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        yamlio.load(text)


def test_documented_merge_precedence_and_nested_aliases_are_preserved() -> None:
    text = """
base: &base {x: 1, y: 2}
other: &other {x: 9, z: 3}
combined: &combined {<<: [*base, *other], y: 5}
outer: {<<: *combined, x: 7}
alias: *combined
"""
    actual = yamlio.load(text)
    assert actual == yaml.safe_load(text)
    assert actual["outer"] == {"x": 7, "y": 5, "z": 3}
    assert actual["alias"] is actual["combined"]


def test_python_object_tags_are_not_constructed() -> None:
    with pytest.raises(yaml.YAMLError, match="constructor"):
        yamlio.load("!!python/object/apply:builtins.print [unexpected]")


def test_safe_values_round_trip_without_unit_or_declaration_changes() -> None:
    values = {"value": 1.23e-25, "unit": "m3/s", "note": "相と準位", "empty": None}
    assert yamlio.load(yamlio.dump(values, allow_unicode=True)) == values


def test_input_file_rejects_silent_target_override(tmp_path) -> None:
    path = tmp_path / "input.yaml"
    path.write_text("gases: [Ar]\ngases: [CF4]\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError, match="duplicate key"):
        Case.load(path)


@pytest.mark.parametrize(
    "text",
    [
        "properties: {}\nproperties: {Ar: {mass_amu: {value: 1}}}\n",
        "[]",
        "false",
        "0",
        "properties: []",
        "properties: {Ar: false}",
        "thermo: false",
    ],
)
def test_derive_overlay_rejects_invalid_declarations_before_output(tmp_path, capsys, text) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(text, encoding="utf-8")
    output = tmp_path / "derived.yaml"
    assert (
        main(
            [
                "derive",
                "--registry",
                str(Path(__file__).parent / "fixtures" / "mini"),
                "--overlay",
                str(overlay),
                "--out",
                str(output),
            ]
        )
        == 2
    )
    assert "error:" in capsys.readouterr().err
    assert not output.exists()


def test_pure_python_fallback_preserves_validation() -> None:
    script = """
import yaml
for name in ('CSafeLoader', 'CSafeDumper'):
    if hasattr(yaml, name):
        delattr(yaml, name)
from reactgen import yamlio
assert yamlio.load('a: &a {x: 1}\\nb: {<<: *a, x: 2}')['b']['x'] == 2
assert yamlio.load(yamlio.dump({'value': 1e-25})) == {'value': 1e-25}
try:
    yamlio.load('a: 1\\na: 2')
except yaml.YAMLError:
    pass
else:
    raise AssertionError('duplicate key accepted')
"""
    # The child executes only this fixed script, without user-provided arguments.
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
