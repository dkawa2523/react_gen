from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def to_plain(obj: Any) -> Any:
    if is_dataclass(obj):
        return to_plain(asdict(obj))
    if isinstance(obj, dict):
        return {str(key): to_plain(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_plain(value) for value in obj]
    return obj
