"""Core configuration tree model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfigNode:
    """One node in a Junos configuration hierarchy."""

    name: str
    value: str | None = None
    props: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    children: list[ConfigNode] = field(default_factory=list)
    source_index: int = 0
    comments: list[str] = field(default_factory=list)

    def path_key(self) -> tuple[str, str | None]:
        return (self.name, self.value)

    def clone(self) -> ConfigNode:
        return ConfigNode(
            name=self.name,
            value=self.value,
            props=dict(self.props),
            flags=set(self.flags),
            children=[child.clone() for child in self.children],
            source_index=self.source_index,
            comments=list(self.comments),
        )

    def is_container(self) -> bool:
        return self.value is None and bool(self.children)

    def is_leaf(self) -> bool:
        return self.value is not None and not self.children
