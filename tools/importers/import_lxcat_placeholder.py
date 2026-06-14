from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Placeholder for a future LxCat importer. "
            "No download, parsing, or file writing is implemented yet."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="previously downloaded LxCat source file to import later",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("registry"),
        help="registry root for future generated YAML/assets",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("registry/assets/external_sources/lxcat"),
        help="future destination for local imported source/assets",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.input if args.input is not None else "(no input file provided)"

    print("LxCat importer placeholder: not implemented yet.")
    print("No network access, parsing, registry writes, or asset writes were performed.")
    print("Intended input source:", _display_path(source))
    print("Intended registry root:", _display_path(args.registry))
    print("Intended asset output directory:", _display_path(args.output_dir))
    print("Future output: local registry YAML plus assets with provenance for developer review.")
    return 0


def _display_path(path: Path | str) -> str:
    return str(path).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
