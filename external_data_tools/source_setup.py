"""CLI and report assembly for explicit external-source setup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.source_setup_actions import (
    chemicals_report,
    downloads_report,
)
from external_data_tools.source_setup_io import (
    catalog_report,
    default_report_path,
    read_yaml,
    source_records,
    write_yaml,
)
from external_data_tools.source_setup_report import (
    build_source_setup_report,
    source_setup_exit_code,
)
from external_data_tools.source_setup_validation import validate_access_profile


def run_source_setup(
    config_path: str | Path,
    *,
    check: bool = False,
    install_chemicals: bool = False,
    download_explicit_data: bool = False,
    write_report: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    config_path = Path(config_path)
    config = read_yaml(config_path)
    validation = validate_access_profile(config, config_path=config_path)
    sources = source_records(config, config_path)
    chemicals = chemicals_report(config, config_path, install=install_chemicals)
    downloads = downloads_report(
        config,
        config_path,
        requested=download_explicit_data,
    )
    catalog = catalog_report(config, config_path)
    report = build_source_setup_report(
        config_path=config_path,
        check=check,
        install_chemicals=install_chemicals,
        download_explicit_data=download_explicit_data,
        validation=validation,
        sources=sources,
        chemicals=chemicals,
        downloads=downloads,
        catalog=catalog,
    )
    report_path = (
        Path(write_report) if write_report is not None else default_report_path(config, config_path)
    )
    write_yaml(report_path, report)
    return report, source_setup_exit_code(report)


def main(argv: list[str] | None = None) -> int:
    from external_data_tools.source_setup_cli import main as cli_main

    return cli_main(argv)


__all__ = ["run_source_setup", "validate_access_profile"]


if __name__ == "__main__":
    raise SystemExit(main())
