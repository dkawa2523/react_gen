"""One-time migration of schema-4 inputs/evidence; legacy judgments are never loaded.

This tool accepts version 4 only and is scheduled for removal with version 2.0.
Use a new destination. Unspecified phase and unproven existence stay unknown.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import yaml

from reactgen import export, yamlio
from reactgen.case import Case
from reactgen.chemistry import candidate_state, parse_equation, parse_state_id
from reactgen.evidence import EvidenceCatalog
from reactgen.model import ELECTRON, ReactionCandidate, Term, validate_stoichiometric_terms
from reactgen.pipeline import analyze

OBSOLETE_CONDITIONS = {
    "pressure_Pa",
    "electron_density_m3",
    "volume_m3",
    "surface_area_m2",
    "residence_time_s",
}


def migrate(input_path: Path, bundle: Path, outdir: Path, evidence: tuple[Path, ...] = ()) -> None:
    if outdir.exists():
        raise ValueError("migration requires a new destination directory")
    original_input = yamlio.load(input_path.read_text(encoding="utf-8"))
    converted = copy.deepcopy(original_input)
    if not isinstance(converted, dict):
        raise ValueError("legacy input must be a mapping")
    conditions = converted.get("conditions") or {}
    removed = {key: conditions.pop(key) for key in sorted(OBSOLETE_CONDITIONS & conditions.keys())}
    converted["conditions"] = conditions
    case = Case.from_document(converted)
    states_doc = _legacy_document(bundle / "states.yaml", "states")
    reactions_doc = _legacy_document(bundle / "reactions.yaml", "reactions")
    identities = {state["id"]: _legacy_identity(state) for state in states_doc["states"]}
    records = _state_records(states_doc["states"])
    records.extend(_reaction_records(reactions_doc["reactions"], bundle, identities))
    snapshot = {
        "source": {"source_id": "schema4_migration", "source_type": "legacy_archive"},
        "records": records,
    }
    archive = outdir / "migration"
    archive.mkdir(parents=True)
    (archive / "input_v4.yaml").write_text(
        yaml.safe_dump(original_input, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    for filename in ("states.yaml", "reactions.yaml", "selected.yaml"):
        original = bundle / filename
        if original.is_file():
            (archive / filename).write_bytes(original.read_bytes())
    snapshot_path = archive / "evidence.yaml"
    snapshot_path.write_text(
        yaml.safe_dump(snapshot, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    result = analyze(case, EvidenceCatalog.load_paths((*evidence, snapshot_path)))
    export.write(outdir, result)
    report = {
        "legacy_schema": 4,
        "new_schema": 5,
        "removed_unused_conditions": removed,
        "evidence_records_restored_as_imported": len(records),
        "judgments": "All judgments, selections and ready flags were discarded and recomputed.",
        "held": (
            "Related physical-process records without their own equation "
            "remain in the archive only."
        ),
        "next": (
            "Review identity, source qualification and relative assets; "
            "add current evidence and rerun analyze."
        ),
    }
    (archive / "report.yaml").write_text(
        yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _legacy_document(path: Path, key: str) -> dict:
    document = yamlio.load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("metadata", {}).get("schema_version") != 4
        or not isinstance(document.get(key), list)
    ):
        raise ValueError(f"{path}: only a schema-4 {key} document is supported")
    return document


def _state_records(states: list[dict]) -> list[dict]:
    result = []
    for state in states:
        _legacy_identity(state)
        for record in state.get("evidence", {}).get("records", []):
            identity = _legacy_identity(state, record.get("state"))
            base = {
                "species": identity,
                "phase": state.get("phase", "unknown"),
                "structure": state.get("structure"),
                "source": record.get("source", {}),
                "status": "imported",
            }
            for name, value in record.get("properties", {}).items():
                result.append(
                    {
                        **base,
                        **value,
                        "source": base["source"],
                        "status": "imported",
                        "evidence_tier": "imported",
                        "property": name,
                    }
                )
            if record.get("thermo"):
                thermo = {**record["thermo"], "tier": "imported"}
                result.append({**base, "thermo": thermo})
            if record.get("existence_source"):
                result.append(
                    {
                        **base,
                        "existence": record.get("existence", "unknown"),
                        "existence_source": record["existence_source"],
                    }
                )
    return result


def _legacy_identity(state: dict, declared_state: dict | None = None) -> str:
    parsed = parse_state_id(state["id"])
    if (
        parsed is None
        or parsed.composition != state["composition"]
        or parsed.charge != state["charge"]
    ):
        raise ValueError(
            f"ambiguous legacy state ID: {state['id']}; provide a corrected source identity"
        )
    declaration = (
        declared_state
        or state.get("state")
        or {
            "kind": parsed.state.kind,
            "resolution": parsed.state.resolution,
            "label": parsed.state.label,
        }
    )
    return candidate_state(
        state["composition"],
        state["charge"],
        declaration["kind"],
        label=declaration.get("label", ""),
        resolution=declaration.get("resolution"),
        phase=state.get("phase", "unknown"),
        structure=state.get("structure"),
    ).id


def _reaction_records(
    reactions: list[dict], bundle: Path, identities: dict[str, str]
) -> list[dict]:
    result = []
    for reaction in reactions:
        reactants = _mapped_terms(
            tuple((term["species"], term.get("n", 1)) for term in reaction["reactants"]),
            identities,
        )
        products = _mapped_terms(
            tuple((term["species"], term.get("n", 1)) for term in reaction["products"]),
            identities,
        )
        migrated_equation = ReactionCandidate(
            "",
            reactants,
            products,
            reaction["family"],
            reaction["process"],
            "migration",
            "migration",
            0,
            reaction.get("third_body"),
            reaction.get("surface"),
        ).equation
        evidence = reaction.get("evidence", {})
        channel_records = [
            (record, migrated_equation, False)
            for record in evidence.get("exact_channel_records", [])
        ]
        channel_records.extend(
            (record, equation, True) for record, equation in _related_targets(evidence, identities)
        )
        if evidence.get("overlay_datasets"):
            channel_records.append(
                ({"datasets": evidence["overlay_datasets"], "source": {}}, migrated_equation, False)
            )
        for record, target_equation, related in channel_records:
            datasets = record.get("datasets") or [{"kind": "reference", "form": "reference"}]
            for dataset in datasets:
                entry = copy.deepcopy(dataset)
                asset = entry.get("asset")
                if isinstance(asset, dict) and asset.get("path"):
                    path = Path(asset["path"])
                    if not path.is_absolute():
                        asset["path"] = str((bundle / path).resolve())
                entry.update(
                    {
                        "reaction": target_equation,
                        "family": record.get("family", None if related else reaction["family"]),
                        "type": record.get(
                            "process", "unknown" if related else reaction["process"]
                        ),
                        "surface": record.get(
                            "surface", None if related else reaction.get("surface")
                        ),
                        "status": "imported",
                        "tier": "imported",
                        "source": record.get("source") or entry.get("source", {}),
                        "channel_scope": record.get(
                            "channel_scope", entry.get("channel_scope", "product_resolved")
                        ),
                        "threshold_eV": record.get("threshold_eV"),
                        "deltaE_products_minus_reactants_eV": record.get("delta_e_eV"),
                    }
                )
                result.append(entry)
    return result


def _related_targets(evidence: dict, identities: dict[str, str]) -> list[tuple[dict, str]]:
    result = []
    for group in ("related_total_process_records", "related_physical_process_records"):
        for record in evidence.get(group, []):
            own_equation = _related_equation(record, identities)
            if own_equation is not None:
                identified = dict(record)
                if group == "related_total_process_records":
                    identified.setdefault("channel_scope", "total")
                result.append((identified, own_equation))
    return result


def _related_equation(record: dict, identities: dict[str, str]) -> str | None:
    """Migrate only a related record's own explicit equation, never its host channel.

    Schema-4 exports usually omitted that equation. Such records stay in the
    unchanged archive until their target is identified from the original source.
    Known participants retain the migrated phase/structure; an unknown reference
    requires a correction rather than silently assuming a gas ground state.
    """
    written = record.get("reaction", record.get("equation"))
    if written is None:
        return None
    parsed = parse_equation(written) if isinstance(written, str) else None
    if parsed is None:
        raise ValueError("related legacy record requires a valid explicit reaction equation")
    equation, _ = parsed

    return ReactionCandidate(
        "",
        _mapped_terms(equation[2], identities),
        _mapped_terms(equation[3], identities),
        record.get("family") or "",
        record.get("process") or "unknown",
        "migration",
        "migration",
        0,
        equation[0],
        record.get("surface"),
    ).equation


def _mapped_terms(
    terms: tuple[tuple[str, float], ...], identities: dict[str, str]
) -> tuple[Term, ...]:
    validate_stoichiometric_terms(terms)
    result = []
    for species, count in terms:
        if species != ELECTRON and species not in identities:
            raise ValueError(f"legacy equation references an unknown state: {species}")
        result.append(Term(ELECTRON if species == ELECTRON else identities[species], count))
    return tuple(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        migrate(args.input, args.bundle, args.out, tuple(args.evidence))
    except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(args.out / "result.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
