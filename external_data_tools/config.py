from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os


DEFAULT_DATA_HOME = Path("external_data")
DEFAULT_CACHE_DIR = DEFAULT_DATA_HOME / "raw"
DEFAULT_USER_AGENT = "react_gen_external_data_tools/0.1"
DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_HTTP_SLEEP_SECONDS = 1.0


@dataclass(frozen=True)
class ExternalDataConfig:
    data_home: Path = DEFAULT_DATA_HOME
    cache_dir: Path = DEFAULT_CACHE_DIR
    user_agent: str = DEFAULT_USER_AGENT
    http_timeout: float = DEFAULT_HTTP_TIMEOUT
    http_sleep_seconds: float = DEFAULT_HTTP_SLEEP_SECONDS


def load_config(env: Mapping[str, str] | None = None) -> ExternalDataConfig:
    values = env if env is not None else os.environ
    data_home = Path(values.get("REACTGEN_DATA_HOME", str(DEFAULT_DATA_HOME)))
    cache_dir = Path(values.get("REACTGEN_EXTERNAL_CACHE", str(data_home / "raw")))
    return ExternalDataConfig(
        data_home=data_home,
        cache_dir=cache_dir,
        user_agent=values.get("REACTGEN_USER_AGENT", DEFAULT_USER_AGENT),
        http_timeout=_float_env(values.get("REACTGEN_HTTP_TIMEOUT"), DEFAULT_HTTP_TIMEOUT),
        http_sleep_seconds=_float_env(
            values.get("REACTGEN_HTTP_SLEEP_SECONDS"),
            DEFAULT_HTTP_SLEEP_SECONDS,
        ),
    )


def _float_env(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default

