"""Safe YAML with explicit duplicate declarations rejected before construction.

YAML merge keys retain their documented precedence; an explicit declaration may
override an inherited value. Duplicate keys written in the same mapping are not
such an override and must not silently select a physical target or quality tier.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any, TextIO

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode

BaseSafeLoader: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
SafeDumper: Any = getattr(yaml, "CSafeDumper", yaml.SafeDumper)

_MERGE_KEY = object()


class SafeLoader(BaseSafeLoader):
    def __init__(self, stream: str | bytes | TextIO) -> None:
        super().__init__(stream)
        self._checked_mappings: set[MappingNode] = set()

    def flatten_mapping(self, node: MappingNode) -> None:
        # Check before PyYAML flattens inherited mappings into node.value.
        # A merged node may be visited again, so retain which nodes were checked.
        if node not in self._checked_mappings:
            self._checked_mappings.add(node)
            keys: dict[Hashable, Any] = {}
            for key_node, _ in node.value:
                if key_node.tag == "tag:yaml.org,2002:merge":
                    key: Hashable = _MERGE_KEY
                else:
                    if key_node.tag == "tag:yaml.org,2002:value":
                        key_node.tag = "tag:yaml.org,2002:str"
                    key = self.construct_object(key_node)
                    if not isinstance(key, Hashable):
                        raise ConstructorError(
                            "while constructing a mapping",
                            node.start_mark,
                            "found unhashable key",
                            key_node.start_mark,
                        )
                if key in keys:
                    raise ConstructorError(
                        "while constructing a mapping",
                        keys[key],
                        f"duplicate key {key_node.value!r}",
                        key_node.start_mark,
                    )
                keys[key] = key_node.start_mark
        super().flatten_mapping(node)


def load(stream: str | bytes | TextIO) -> Any:
    """Read one document without arbitrary Python tags or silent key overrides."""
    loader = SafeLoader(stream)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def dump(data: Any, **options: Any) -> str:
    """Serialize ordinary data using the available safe emitter."""
    return yaml.dump(data, Dumper=SafeDumper, **options)
