"""Core configuration tree model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfigNode:
    """One node in a Junos configuration hierarchy."""

    name: str
    raw_tail: list[str] | None = None   # raw tokens after the statement name (primary representation)
    props: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    children: list[ConfigNode] = field(default_factory=list)
    source_index: int = 0
    comments: list[str] = field(default_factory=list)

    @property
    def value(self) -> str | None:
        """Legacy view: joined raw_tail tokens (for single or multi-part statements)."""
        if self.raw_tail:
            return " ".join(self.raw_tail)
        return None

    def path_key(self) -> tuple[str, tuple[str, ...] | None]:
        return (self.name, tuple(self.raw_tail) if self.raw_tail else None)

    def clone(self) -> ConfigNode:
        return ConfigNode(
            name=self.name,
            raw_tail=list(self.raw_tail) if self.raw_tail else None,
            props=dict(self.props),
            flags=set(self.flags),
            children=[child.clone() for child in self.children],
            source_index=self.source_index,
            comments=list(self.comments),
        )

    def is_container(self) -> bool:
        return (self.raw_tail is None or len(self.raw_tail) != 1) and bool(self.children)

    def is_leaf(self) -> bool:
        return self.raw_tail is not None and not self.children
