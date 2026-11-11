"""Convert selected levels of one neutral ExoMol diatomic spectrum.

The official definition supplies the isotopologue and column meanings. The
caller identifies the physical ground reference and a finite set of row IDs.
The resulting declarations enter the same review path as other excitation data.
"""

from __future__ import annotations

import bz2
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from acquire import snapshot
from reactgen import yamlio
from reactgen.chemistry import parse_state_id, state_id
from reactgen.model import StateCandidate
from reactgen.structure import bind_structure

_ISOTOPE_GROUP = re.compile(r"\(([1-9][0-9]*)([A-Z][a-z]?)\)([1-9][0-9]*)?")
_SMILES_ISOTOPE = re.compile(r"\[([1-9][0-9]*)([A-Z][a-z]?)")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_CORE_COLUMNS = ("ID", "E", "gtot", "J", "v")


@dataclass(frozen=True)
class Definition:
    isotopes: Counter[tuple[str, str]]
    slug: str
    dataset: str
    release: int
    count: int
    parity: bool


@dataclass(frozen=True)
class Level:
    id: int
    energy: float
    degeneracy: int
    j: int
    v: int
    parity: str
    raw: str

    @property
    def assignment(self) -> tuple[int, int, str]:
        return self.v, self.j, self.parity


def records(
    definition_file: Path,
    states_file: Path,
    ground_id: str,
    ground_row: int,
    selected_rows: list[int],
) -> tuple[dict, list[dict]]:
    """Read local official files and preserve selected rows and their reference."""
    requested = set(selected_rows)
    if (
        not requested
        or len(requested) != len(selected_rows)
        or min(requested | {ground_row}) <= 0
        or ground_row in requested
    ):
        raise ValueError("select unique positive excited row IDs separately from the ground row")
    definition_bytes, definition_acquisition = snapshot.input_acquisition(definition_file)
    definition = _definition(yamlio.load(definition_bytes.decode("utf-8")))
    stem = f"{definition.slug}__{definition.dataset}"
    if definition_file.name != stem + ".def.json" or states_file.name not in {
        stem + ".states",
        stem + ".states.bz2",
    }:
        raise ValueError(
            "ExoMol definition and states filenames must match the isotope and dataset"
        )
    ground = _ground(ground_id, definition.isotopes)
    states_bytes, states_acquisition = snapshot.input_acquisition(states_file)
    levels, count = _read_levels(
        states_bytes, states_file.suffix == ".bz2", definition, requested | {ground_row}
    )
    reference = levels[ground_row]
    if reference.energy != 0 or reference.assignment[:2] != (0, 0):
        raise ValueError("the specified ground row must be the unique E=0, v=0, J=0 level")
    source = {
        "source_type": "exomol",
        "provider": "exomol",
        "collection": definition.dataset,
        "release": str(definition.release),
        "citation": f"ExoMol {definition.slug} {definition.dataset}",
        "url": (
            f"https://exomol.com/data/molecules/{ground.id.split('@', 1)[0]}/"
            f"{definition.slug}/{definition.dataset}/"
        ),
    }
    # The caller keeps the original files; the snapshot contains only row
    # evidence and identification of the original bytes, without a raw copy.
    for acquisition in (definition_acquisition, states_acquisition):
        acquisition.pop("raw_path")
    declaration = {
        "isotopologue": definition.slug,
        "ground": {"state": ground.id, "row_id": reference.id, "row": reference.raw},
        "definition_file": definition_acquisition,
        "states_file": states_acquisition
        | {"declared_rows": definition.count, "parsed_rows": count},
    }
    return source, [_record(ground, levels[row], declaration) for row in sorted(requested)]


def _mapping(parent: object, field: str) -> dict:
    child = parent.get(field) if isinstance(parent, dict) else None
    if not isinstance(child, dict):
        raise ValueError(f"ExoMol definition needs a {field} mapping")
    return child


def _definition(document: object) -> Definition:
    isotope = _mapping(document, "isotopologue")
    dataset = _mapping(document, "dataset")
    states = _mapping(dataset, "states")
    fields = states.get("states_file_fields")
    if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
        raise ValueError("ExoMol definition needs named states_file_fields")
    names = tuple(field.get("name") for field in fields)
    if (
        states.get("quantum_case_label") != "dcs"
        or states.get("hyperfine_resolved_dataset") is not False
        or names not in (_CORE_COLUMNS, (*_CORE_COLUMNS, "e/f"))
    ):
        raise ValueError(
            "supported ExoMol spectra have diatomic ID/E/gtot/J/v columns and optional e/f"
        )
    slug = _dataset_name(isotope, "iso_slug")
    name = _dataset_name(dataset, "name")
    count, release = states.get("number_of_states"), dataset.get("version")
    if type(count) is not int or count <= 0 or type(release) is not int or release <= 0:
        raise ValueError("ExoMol definition needs a positive states count and dataset version")
    inchi = isotope.get("inchi")
    if (
        not isinstance(inchi, str)
        or not inchi.startswith("InChI=1S/")
        or re.search(r"/[qp][^/]+", inchi)
    ):
        raise ValueError("ExoMol definition must identify a neutral isotopologue")
    return Definition(
        _isotope_formula(isotope.get("iso_formula")), slug, name, release, count, "e/f" in names
    )


def _dataset_name(declaration: dict, key: str) -> str:
    value = declaration.get(key)
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ValueError(f"invalid ExoMol definition {key}")
    return value


def _isotope_formula(formula: object) -> Counter[tuple[str, str]]:
    if not isinstance(formula, str):
        raise ValueError("ExoMol definition needs a diatomic isotope formula")
    groups = list(_ISOTOPE_GROUP.finditer(formula))
    counts: Counter[tuple[str, str]] = Counter()
    for match in groups:
        mass, symbol, number = match.groups()
        counts[mass, symbol] += int(number or 1)
    if "".join(match[0] for match in groups) != formula or sum(counts.values()) != 2:
        raise ValueError("ExoMol definition needs a neutral diatomic isotope formula")
    return counts


def _ground(identifier: str, isotopes: Counter[tuple[str, str]]) -> StateCandidate:
    state = parse_state_id(identifier)
    if (
        state is None
        or state.charge != 0
        or state.phase != "gas"
        or state.state.kind != "ground"
        or state.state.resolution != "resolved"
        or state.structure is None
        or not state.structure.startswith("smiles:")
    ):
        raise ValueError("specify a neutral gas ground state with explicit isotope SMILES")
    bound = bind_structure(state, state.structure.removeprefix("smiles:"))
    structure = bound.structure or ""
    if (
        "." in structure
        or "~" in structure
        or Counter(_SMILES_ISOTOPE.findall(structure)) != isotopes
    ):
        raise ValueError("ground SMILES must be one diatom with the ExoMol isotope inventory")
    return bound


def _read_levels(
    data: bytes, compressed: bool, definition: Definition, selected: set[int]
) -> tuple[dict[int, Level], int]:
    raw = io.BytesIO(data)
    binary = bz2.BZ2File(raw) if compressed else raw
    try:
        with io.TextIOWrapper(binary, encoding="utf-8") as stream:
            return _selected_levels(stream, definition, selected)
    except EOFError as error:
        raise ValueError("truncated ExoMol states file") from error


def _selected_levels(
    stream: io.TextIOWrapper, definition: Definition, selected: set[int]
) -> tuple[dict[int, Level], int]:
    seen: set[int] = set()
    assignments: Counter[tuple[int, int, str]] = Counter()
    found = {}
    zero = 0
    for number, raw in enumerate(stream, 1):
        if not raw.strip():
            continue
        level = _level(raw.rstrip(), number, definition.parity)
        if level.id in seen:
            raise ValueError(f"duplicate ExoMol state ID {level.id}")
        seen.add(level.id)
        assignments[level.assignment] += 1
        zero += level.energy == 0
        if level.id in selected:
            found[level.id] = level
    if zero != 1:
        raise ValueError("ExoMol states must have a unique energy zero")
    if missing := selected - found.keys():
        raise ValueError(f"ExoMol states missing requested rows: {sorted(missing)}")
    if any(assignments[level.assignment] != 1 for level in found.values()):
        raise ValueError("selected ExoMol v/J/parity assignment is ambiguous")
    return found, len(seen)


def _level(raw: str, number: int, has_parity: bool) -> Level:
    cells = raw.split()
    if len(cells) != 5 + has_parity:
        raise ValueError(f"ExoMol states line {number} does not match the declared columns")
    index, energy, degeneracy, j, v = cells[:5]
    try:
        row = Level(
            int(index),
            float(energy),
            int(degeneracy),
            int(j),
            int(v),
            cells[-1] if has_parity else "",
            raw,
        )
    except ValueError as error:
        raise ValueError(f"invalid numeric value in ExoMol states line {number}") from error
    if (
        min(row.id, row.degeneracy) <= 0
        or not math.isfinite(row.energy)
        or min(row.energy, row.j, row.v) < 0
        or (has_parity and row.parity not in {"e", "f"})
    ):
        raise ValueError(f"invalid level in ExoMol states line {number}")
    return row


def _record(ground: StateCandidate, level: Level, declaration: dict) -> dict:
    label = f"v={level.v}, J={level.j}"
    if level.parity:
        label += f", {level.parity}"
    return {
        "species": state_id(
            ground.composition,
            ground.charge,
            "vibrational" if level.v else "rotational",
            label,
            resolution="resolved",
            structure=ground.structure,
        ),
        "phase": "gas",
        "property": "excitation_energy_eV",
        "value": level.energy,
        "unit": "cm^-1",
        "related_state": ground.id,
        "J": str(level.j),
        "status": "imported",
        "source_declaration": declaration | {"row_id": level.id, "row": level.raw},
    }
