from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

_LOCAL_SRC = Path(__file__).resolve().parents[1] / "src"
if _LOCAL_SRC.exists() and str(_LOCAL_SRC) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SRC))


def run_reactgen(args: list[str]) -> dict[str, Any]:
    reactgen_main = importlib.import_module("plasma_reactgen.interface.cli").main
    return_code = reactgen_main(args)
    step = {
        "command": "reactgen " + " ".join(args),
        "return_code": return_code,
    }
    if return_code != 0:
        raise RuntimeError(f"benchmark command failed: {step['command']}")
    return step


__all__ = ["run_reactgen"]
