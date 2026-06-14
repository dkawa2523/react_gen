from __future__ import annotations

from pathlib import Path
import yaml


def write_dnt_inputs(output_dir: str | Path, dnt_inputs: dict) -> None:
    """Write normalized DNT input files under an output directory."""

    output_dir = Path(output_dir)
    pair_dir = output_dir / "dnt_inputs"
    pair_dir.mkdir(parents=True, exist_ok=True)

    pairs = list(dnt_inputs.get("pairs", []))
    for pair in pairs:
        _write_pair_input(pair_dir, pair)

    _write_yaml(output_dir / "dnt_manifest.yaml", _manifest_payload(dnt_inputs, pairs))


def _write_pair_input(pair_dir: Path, pair: dict) -> None:
    pair_id = pair["pair_id"]
    _write_yaml(pair_dir / f"{pair_id}.yaml", pair)


def _manifest_payload(dnt_inputs: dict, pairs: list[dict]) -> dict:
    return {
        "schema_version": dnt_inputs.get("schema_version", 1),
        "pairs": [_manifest_pair(pair) for pair in pairs],
        "summary": dnt_inputs.get("summary", {}),
    }


def _manifest_pair(pair: dict) -> dict:
    pair_id = pair["pair_id"]
    return {
        "pair_id": pair_id,
        "file": f"dnt_inputs/{pair_id}.yaml",
        "model_variant": pair.get("model_variant"),
        "status": pair.get("status"),
        "missing_required_properties": pair.get("pair_properties", {}).get(
            "missing_required_properties",
            [],
        ),
    }


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
