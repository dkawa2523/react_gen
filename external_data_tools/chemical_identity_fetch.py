from __future__ import annotations

from pathlib import Path
from typing import Any

from .chemical_identity_artifacts import (
    dry_run_plan,
    load_species_entries,
    write_identity_artifacts,
)
from .chemical_identity_sources import PROVIDERS, collect_identity_records


def fetch_chemical_identity(
    species_list_path: Path,
    *,
    output_root: Path,
    snapshot_path: Path,
    provider: str = "chebi",
    dry_run: bool = False,
    local_snapshot: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ValueError(f"unsupported identity provider: {provider}")

    species_entries = load_species_entries(species_list_path)
    output_root = Path(output_root)
    snapshot_path = Path(snapshot_path)
    if not dry_run and snapshot_path.exists() and not overwrite:
        raise FileExistsError(f"snapshot already exists: {snapshot_path}")
    if dry_run:
        return dry_run_plan(species_entries, provider)

    records, unresolved = collect_identity_records(
        provider,
        species_entries,
        output_root,
        local_snapshot,
    )
    return write_identity_artifacts(
        output_root,
        snapshot_path,
        provider,
        records,
        unresolved,
    )


def main(argv: list[str] | None = None) -> int:
    from external_data_tools.chemical_identity_cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
