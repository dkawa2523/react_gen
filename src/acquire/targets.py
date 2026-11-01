"""Keep requested physical targets separate from upstream lookup names."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass

from reactgen.chemistry import declared_state_target, parse_state_id, state_id
from reactgen.model import StateCandidate
from reactgen.naming import parse_formula


@dataclass(frozen=True)
class GroundRequest:
    """A gas ground-state target and its explicit source lookup spelling."""

    target: StateCandidate
    query: str
    declared: dict


def ground_problem(name: str) -> str | None:
    """A recognized non-ground target cannot use this ground gas adapter."""
    state = parse_state_id(name)
    if state is not None and (state.charge or state.state.kind != "ground" or state.phase != "gas"):
        return "this source provides neutral gas ground-state quantities"
    return None


def requests(items: list) -> tuple[list[GroundRequest], list[tuple[str, str]]]:
    """Validate requested identities, returning explicit unsupported-target reasons.

    Plain formula strings use the existing gas ground-state spelling. Mapping
    fields supply identity only when the spelling does not already assert it.
    A query changes the lookup spelling, never the physical output target.
    """
    supported, excluded = [], []
    for item in items:
        entry = item if isinstance(item, dict) else {"id": item}
        written = entry.get("id")
        if not isinstance(written, str) or not written.strip():
            raise ValueError("acquisition species must have a nonempty text id")
        state = declared_state_target(written, entry, default_phase="gas")
        if state is None:
            excluded.append(
                (written, "physical target is unidentified; provide a formula id and query")
            )
            continue
        if problem := ground_problem(state.id):
            excluded.append((written, problem))
            continue
        query = (
            entry.get("query")
            or entry.get("source_species")
            or state.structure
            or written.partition("@")[0]
        )
        if not isinstance(query, str) or not query.strip():
            raise ValueError("acquisition query must be nonempty text")
        supported.append(GroundRequest(state, query, entry))
    return supported, excluded


def chemical_identity(metadata: object, cas: str) -> dict:
    """Keep the independently returned molecular identity, not the lookup spelling.

    chemicals exposes names, CAS, SMILES and InChI on its metadata record:
    https://chemicals.readthedocs.io/chemicals.identifiers.html .
    These identify a source species; they do not establish uniqueness of a
    requested molecular formula or qualify any of its numerical properties.
    """
    inchi = getattr(metadata, "InChI", None)
    return {
        "molecularFormula": getattr(metadata, "formula", None),
        "name": getattr(metadata, "common_name", None),
        "other_names": [
            getattr(metadata, "iupac_name", None),
            *(getattr(metadata, "synonyms", None) or []),
        ],
        "cas": cas,
        "inChI": "InChI=1S/" + inchi if inchi and not inchi.startswith("InChI=") else inchi,
        "inchikey": getattr(metadata, "InChI_key", None),
        "smiles": getattr(metadata, "smiles", None),
    }


def source_structure(identity: dict, request: GroundRequest | StateCandidate) -> str | None:
    """Match an asserted structure, or retain the independent source structure.

    Formula equality narrows identity. It does not identify molecular
    connectivity or isotope composition. Atoms and non-isotopic diatomics
    need no additional connectivity label. Molecular measurements retain the
    source's InChI, CAS or name when the request has no identified structure.
    """
    target = request.target if isinstance(request, GroundRequest) else request
    composition = identity.get("composition") or parse_formula(identity.get("molecularFormula"))
    if composition != target.composition:
        raise ValueError("source composition differs from the requested target")
    declared = target.structure
    if declared is not None and not _structure_matches(declared, identity):
        raise ValueError(
            "source structure differs from or does not identify the requested structure"
        )
    inchi = identity.get("inChI")
    smiles = identity.get("smiles")
    # OpenSMILES bracket_atom ::= '[' isotope? symbol ... ']'. Keep a
    # stated isotope even if InChI is unavailable; this does not parse SMILES.
    # https://github.com/opensmiles/OpenSMILES/blob/master/opensmiles.asciidoc
    isotopic = (isinstance(inchi, str) and "/i" in inchi) or (
        isinstance(smiles, str) and re.search(r"\[[0-9]+", smiles) is not None
    )
    if sum(target.composition.values()) <= 2 and not isotopic:
        return None
    native = (
        inchi
        or identity.get("inchikey")
        or identity.get("cas")
        or ("SMILES=" + smiles if isinstance(smiles, str) and smiles else None)
        or identity.get("name")
    )
    if not isinstance(native, str) or not native.strip():
        raise ValueError("molecular source structure is unidentified")
    return native


def _structure_matches(declared: str, identity: dict) -> bool:
    """Names are case-insensitive; machine structure identifiers are not."""
    identifiers = [identity.get(key) for key in ("inChI", "inchikey", "smiles", "cas")]
    for key, prefix in (("cas", "CAS="), ("inchikey", "InChIKey="), ("smiles", "SMILES=")):
        if identity.get(key):
            identifiers.append(prefix + identity[key])
    if identity.get("connectivity_smiles"):
        identifiers.append("ConnectivitySMILES=" + identity["connectivity_smiles"])
    if declared.strip() in identifiers:
        return True
    if declared.startswith(("InChI=", "InChIKey=", "SMILES=", "ConnectivitySMILES=", "CAS=")):
        return False
    names = [identity.get("name"), *(identity.get("other_names") or [])]
    return any(
        isinstance(name, str) and declared.strip().casefold() == name.strip().casefold()
        for name in names
    )


def records_for(
    request: GroundRequest, records: list[dict], *, identity: dict | None = None
) -> list[dict]:
    """Map source properties after identity comparison, preserving source declarations.

    The source identity comes from the adapter's parsed metadata, never from
    the user's query. A formula-only request may yield a structure-specific
    source record; it is not relabelled as a measurement of every isomer.
    """
    out = []
    for record in records:
        source = identity or record.get("source_identity")
        if source is None:
            source = {
                "composition": record.get("composition"),
                "molecularFormula": record.get("source_formula"),
                "name": record.get("structure"),
            }
            named = parse_state_id(str(record.get("species", "")))
            if named is not None:
                source["composition"] = source["composition"] or named.composition
                source["name"] = source["name"] or named.structure
        structure = source_structure(source, request)
        if record.get("structure") is not None and not _structure_matches(
            record["structure"], source
        ):
            raise ValueError("source record structure contradicts its independent identity")
        target = state_id(
            request.target.composition,
            request.target.charge,
            request.target.state.kind,
            request.target.state.label,
            resolution=request.target.state.resolution,
            phase=request.target.phase,
            structure=structure,
        )
        mapped = {key: value for key, value in record.items() if key != "source_query"} | {
            "species": target,
            "phase": request.target.phase,
            "structure": structure,
            "composition": dict(request.target.composition),
            "source_identity": deepcopy(source),
        }
        mapped["source_declaration"] = _request_declaration(mapped, record, request)
        out.append(mapped)
    return out


def _request_declaration(mapped: dict, original: dict, request: GroundRequest) -> dict:
    """Retain search/alias context in the existing non-scientific acquisition container."""
    declaration = deepcopy(original.get("source_declaration", mapped))
    if not isinstance(declaration, dict):
        declaration = {"record_declaration": declaration}
    acquisition = declaration.get("acquisition", {})
    if not isinstance(acquisition, dict):
        acquisition = {"source_acquisition": acquisition}
    prior_query = declaration.pop("source_query", original.get("source_query"))
    if prior_query is not None:
        acquisition["source_query"] = deepcopy(prior_query)
    offered = {
        "query": request.query,
        "target": request.target.id,
        "written_target": request.declared["id"],
    }
    if "request" in acquisition and acquisition["request"] != offered:
        raise ValueError("source acquisition request conflicts with the current lookup")
    declaration["acquisition"] = acquisition | {"request": offered}
    return declaration
