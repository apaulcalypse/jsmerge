"""Normalize Junos CLI shorthand into schema-aligned list nodes."""

from __future__ import annotations

import re

from jsmerge.models import ConfigNode

_INTERFACE_NAME = re.compile(r"^[a-z]+-\d+/\d+/\d+", re.IGNORECASE)
_BARE_PREFIX = re.compile(r"^\d+\.\d+")


def normalize_tree(root: ConfigNode) -> ConfigNode:
    node = root.clone()
    _normalize_node(node, parent=None)
    coalesce_duplicate_containers(node)
    return node


def denormalize_tree(root: ConfigNode) -> ConfigNode:
    node = root.clone()
    _denormalize_node(node, parent=None)
    return node


def _normalize_node(node: ConfigNode, parent: ConfigNode | None) -> None:
    if node.name == "interfaces":
        normalized: list[ConfigNode] = []
        for child in node.children:
            if child.name == "interface":
                normalized.append(child)
            elif child.raw_tail is None and _INTERFACE_NAME.match(child.name):
                normalized.append(
                    ConfigNode(
                        name="interface",
                        raw_tail=[child.name],
                        children=child.children,
                        props=dict(child.props),
                        flags=set(child.flags),
                        source_index=child.source_index,
                        comments=list(child.comments),
                    )
                )
            else:
                normalized.append(child)
        node.children = normalized

    if node.name == "prefix-list" and node.value is not None:
        normalized_items: list[ConfigNode] = []
        for child in node.children:
            if child.name == "prefix-list-item":
                normalized_items.append(child)
            elif child.value is None and _BARE_PREFIX.match(child.name):
                normalized_items.append(
                    ConfigNode(
                        name="prefix-list-item",
                        raw_tail=[child.name],
                        source_index=child.source_index,
                        comments=list(child.comments),
                    )
                )
            else:
                normalized_items.append(child)
        node.children = normalized_items

    for child in node.children:
        _normalize_node(child, node)


def _denormalize_node(node: ConfigNode, parent: ConfigNode | None) -> None:
    if parent is not None and parent.name == "interfaces" and node.name == "interface" and node.raw_tail:
        node.name = node.raw_tail[0]
        node.raw_tail = None

    if parent is not None and parent.name == "prefix-list" and node.name == "prefix-list-item" and node.raw_tail:
        node.name = node.raw_tail[0]
        node.raw_tail = None

    for child in list(node.children):
        _denormalize_node(child, node)


def coalesce_duplicate_containers(node: ConfigNode) -> None:
    """In-place coalescing of duplicate sibling containers (e.g. multiple 'groups {}' blocks).

    When the same container name (+ raw_tail) appears multiple times at the same level,
    their children are merged into the first occurrence. This handles config generators
    that import many Jinja2 templates, each contributing fragments to the same top-level
    stanza (common with 'groups', 'interfaces', 'policy-options', etc.).
    """
    if not node.children:
        return

    # Group children by their identity key, preserving first-seen order
    seen: dict[tuple, ConfigNode] = {}
    new_children: list[ConfigNode] = []

    for child in node.children:
        key = child.path_key()
        if key in seen:
            existing = seen[key]
            # Merge children from the duplicate into the first one
            for sub in child.children:
                existing.children.append(sub)
            # Also carry over any comments/flags from duplicates
            existing.comments.extend(child.comments)
            existing.flags.update(child.flags)
        else:
            seen[key] = child
            new_children.append(child)

    node.children = new_children

    # Recurse so nested duplicates are also handled
    for child in node.children:
        coalesce_duplicate_containers(child)
