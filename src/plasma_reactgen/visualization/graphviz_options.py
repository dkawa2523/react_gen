from dataclasses import dataclass


@dataclass(frozen=True)
class GraphvizOptions:
    """Options shared by reaction-network and lineage graphs."""

    include_self_loops: bool = False
    include_non_expanding: bool = False
    max_reactions: int | None = 250
    render_formats: tuple[str, ...] = ("svg", "png")


__all__ = ["GraphvizOptions"]
