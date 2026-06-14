from __future__ import annotations

from pathlib import Path

from plasma_reactgen.application.dnt_input_builder import READY_STATUSES
from plasma_reactgen.infrastructure.dnt_writer import write_dnt_inputs


def write_dnt_pair_inputs(
    output_dir: str | Path,
    case_name: str,
    pair_inputs: list[dict],
) -> dict:
    """Compatibility wrapper for the normalized DNT writer."""

    _ = case_name
    dnt_inputs = {
        "schema_version": 1,
        "pairs": pair_inputs,
        "summary": {
            "total_pairs": len(pair_inputs),
            **{
                status: sum(1 for pair in pair_inputs if pair.get("status") == status)
                for status in READY_STATUSES
            },
        },
    }
    write_dnt_inputs(output_dir, dnt_inputs)
    return dnt_inputs
