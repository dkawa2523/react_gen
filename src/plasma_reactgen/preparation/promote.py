from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.domain.identifiers import pair_filename, to_file_key


def promote_reviewed_registry(
    prepared_registry: Path,
    registry: Path,
    decision_file: Path,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    registry = Path(registry)
    decision_file = Path(decision_file)
    decisions = _load_decisions(decision_file)

    report: dict[str, Any] = {
        "schema_version": 1,
        "registry_mutated": False,
        "dry_run": not apply,
        "promoted_species": [],
        "promoted_channels": [],
        "rejected": [],
        "conflicts": [],
        "summary": {
            "n_promoted_species": 0,
            "n_promoted_channels": 0,
            "n_rejected": 0,
            "n_conflicts": 0,
        },
    }

    for decision in decisions:
        if not isinstance(decision, dict):
            _conflict(report, {"kind": "decision", "id": None}, "invalid_decision")
            continue
        action = decision.get("action")
        if action == "reject":
            _reject(report, decision)
            continue
        if action != "promote":
            _conflict(report, decision, "unsupported_action")
            continue

        kind = decision.get("kind")
        if kind == "species":
            mutated = _promote_species(prepared_registry, registry, decision, report, apply=apply)
        elif kind == "reaction_channel":
            mutated = _promote_reaction_channel(prepared_registry, registry, decision, report, apply=apply)
        else:
            _conflict(report, decision, "unsupported_kind")
            mutated = False
        report["registry_mutated"] = bool(report["registry_mutated"] or mutated)

    report["summary"]["n_promoted_species"] = len(report["promoted_species"])
    report["summary"]["n_promoted_channels"] = len(report["promoted_channels"])
    report["summary"]["n_rejected"] = len(report["rejected"])
    report["summary"]["n_conflicts"] = len(report["conflicts"])
    _write_report(prepared_registry.parent / "promote_report.yaml", report)
    return report


def _promote_species(
    prepared_registry: Path,
    registry: Path,
    decision: dict[str, Any],
    report: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    species_id = str(decision.get("id") or "")
    if not species_id:
        _conflict(report, decision, "missing_species_id")
        return False

    source = _find_species_file(prepared_registry, species_id)
    if source is None:
        _conflict(report, decision, "prepared_species_not_found")
        return False

    source_path, source_payload = source
    registry_existing = _find_species_file(registry, species_id)
    if registry_existing is not None:
        _conflict(
            report,
            decision,
            "curated_species_exists",
            existing=str(registry_existing[0]),
            source=str(source_path),
        )
        return False

    payload = _species_payload_for_promotion(source_payload, decision)
    target_id = str(payload.get("id") or species_id)
    target_path = registry / "species" / f"{to_file_key(target_id)}.yaml"
    if target_path.exists():
        _conflict(
            report,
            decision,
            "target_species_file_exists",
            existing=str(target_path),
            source=str(source_path),
        )
        return False

    item = {
        "kind": "species",
        "id": species_id,
        "source": str(source_path),
        "target": str(target_path),
        "dry_run": not apply,
    }
    report["promoted_species"].append(item)
    if not apply:
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    _write_yaml(target_path, payload)
    return True


def _promote_reaction_channel(
    prepared_registry: Path,
    registry: Path,
    decision: dict[str, Any],
    report: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    channel_id = str(decision.get("id") or "")
    pair = _pair_from_decision(decision)
    if not channel_id:
        _conflict(report, decision, "missing_channel_id")
        return False
    if pair is None:
        _conflict(report, decision, "missing_pair")
        return False

    found = _find_prepared_channel(prepared_registry, channel_id, pair)
    if found is None:
        _conflict(report, decision, "prepared_channel_not_found", pair=pair)
        return False

    source_path, channel = found
    target_path = _find_pair_file(registry, pair) or (
        registry / "reactions" / pair["family"] / pair_filename(pair["projectile"], pair["target"])
    )
    target_payload = _load_yaml(target_path) if target_path.exists() else _new_pair_payload(pair)
    existing_ids = {str(item.get("id")) for item in target_payload.get("channels", []) if isinstance(item, dict)}
    if channel_id in existing_ids:
        _conflict(
            report,
            decision,
            "curated_channel_exists",
            existing=str(target_path),
            source=str(source_path),
            pair=pair,
        )
        return False

    promoted_channel = _channel_payload_for_promotion(channel, decision)
    item = {
        "kind": "reaction_channel",
        "id": channel_id,
        "pair": pair,
        "source": str(source_path),
        "target": str(target_path),
        "dry_run": not apply,
    }
    report["promoted_channels"].append(item)
    if not apply:
        return False

    target_payload.setdefault("channels", []).append(promoted_channel)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _write_yaml(target_path, target_payload)
    return True


def _load_decisions(path: Path) -> list[dict[str, Any]]:
    payload = _load_yaml(path)
    decisions = payload.get("decisions", [])
    if not isinstance(decisions, list):
        raise ValueError("promotion decision file must contain a decisions list")
    return decisions


def _find_species_file(root: Path, species_id: str) -> tuple[Path, dict[str, Any]] | None:
    for path in sorted((root / "species").glob("*.yaml")):
        payload = _load_yaml(path)
        ids = {str(payload.get("id") or "")}
        if payload.get("display_id"):
            ids.add(str(payload["display_id"]))
        if species_id in ids:
            return path, payload
    fallback = root / "species" / f"{to_file_key(species_id)}.yaml"
    if fallback.exists():
        return fallback, _load_yaml(fallback)
    return None


def _find_prepared_channel(
    prepared_registry: Path,
    channel_id: str,
    pair: dict[str, str],
) -> tuple[Path, dict[str, Any]] | None:
    pair_path = prepared_registry / "reactions" / pair["family"] / pair_filename(pair["projectile"], pair["target"])
    if pair_path.exists():
        payload = _load_yaml(pair_path)
        for channel in payload.get("channels", []):
            if isinstance(channel, dict) and channel.get("id") == channel_id:
                return pair_path, channel

    reactions_dir = prepared_registry / "reactions"
    for path in sorted(reactions_dir.glob("*.yaml")):
        payload = _load_yaml(path)
        if payload.get("id") != channel_id:
            continue
        candidate_pair = payload.get("pair", {})
        if _same_pair(candidate_pair, pair):
            return path, payload
    return None


def _find_pair_file(root: Path, pair: dict[str, str]) -> Path | None:
    family_dir = root / "reactions" / pair["family"]
    for path in sorted(family_dir.glob("*.yaml")):
        payload = _load_yaml(path)
        if _same_pair(payload.get("pair", {}), pair):
            return path
    return None


def _species_payload_for_promotion(payload: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(payload)
    out.setdefault("schema_version", 1)
    out.setdefault("metadata", {})
    target_status = decision.get("target_status")
    if target_status:
        out["metadata"]["status"] = target_status
    _append_notes(out["metadata"], decision.get("notes"))
    return out


def _channel_payload_for_promotion(channel: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(channel)
    out.pop("schema_version", None)
    out.pop("kind", None)
    out.pop("pair", None)
    target_status = decision.get("target_status")
    if target_status:
        out["status"] = target_status
    _append_notes(out, decision.get("notes"))
    return out


def _new_pair_payload(pair: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pair": deepcopy(pair),
        "channels": [],
        "metadata": {
            "status": "curated",
            "notes": ["Created by promote workflow from reviewed prepared/candidate data."],
        },
    }


def _pair_from_decision(decision: dict[str, Any]) -> dict[str, str] | None:
    pair = decision.get("pair")
    if not isinstance(pair, dict):
        return None
    required = ("family", "projectile", "target")
    if any(not pair.get(key) for key in required):
        return None
    return {key: str(pair[key]) for key in required}


def _same_pair(candidate: dict[str, Any], pair: dict[str, str]) -> bool:
    return all(str(candidate.get(key) or "") == value for key, value in pair.items())


def _append_notes(payload: dict[str, Any], notes: Any) -> None:
    if not notes:
        return
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        return
    existing = payload.setdefault("notes", [])
    if not isinstance(existing, list):
        payload["notes"] = [existing]
        existing = payload["notes"]
    existing.extend(str(note) for note in notes)


def _reject(report: dict[str, Any], decision: dict[str, Any]) -> None:
    notes = decision.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        notes = []
    report["rejected"].append(
        {
            "kind": decision.get("kind"),
            "id": decision.get("id"),
            "reason": "rejected_by_decision",
            "notes": notes,
        }
    )


def _conflict(
    report: dict[str, Any],
    decision: dict[str, Any],
    reason: str,
    **extra: Any,
) -> None:
    item = {
        "kind": decision.get("kind"),
        "id": decision.get("id"),
        "reason": reason,
    }
    item.update(extra)
    report["conflicts"].append(item)


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_yaml(path, report)
