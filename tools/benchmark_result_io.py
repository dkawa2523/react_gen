"""Measure a saved result's read/validation cost without rerunning chemistry."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import time
from pathlib import Path

import yaml

from reactgen import export, yamlio


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--compare-python-parser", action="store_true")
    args = parser.parse_args()
    path = args.result / "result.yaml" if args.result.is_dir() else args.result
    text = path.read_text(encoding="utf-8")
    measurements = []
    loaders = [("selected_safe_parser", yamlio.load)]
    if args.compare_python_parser:
        loaders.insert(0, ("python_safe_parser", yaml.safe_load))
    for name, loader in loaders:
        gc.collect()
        start = time.perf_counter()
        document = loader(text)
        parsed = time.perf_counter()
        export.validate(document)
        validated = time.perf_counter()
        measurements.append(
            {
                "parser": name,
                "parse_seconds": parsed - start,
                "validate_seconds": validated - parsed,
                "state_count": len(document["states"]),
                "reaction_count": len(document["reactions"]),
            }
        )
        del document
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "libyaml_available": yaml.__with_libyaml__,
                "file_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "measurements": measurements,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
