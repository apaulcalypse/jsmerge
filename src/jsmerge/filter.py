"""Tree filtering helpers for extracting sub-hierarchies."""

from __future__ import annotations

from jsmerge.models import ConfigNode
from jsmerge.normalize import coalesce_duplicate_containers


def _split_filter_path(path_str: str) -> list[str]:
    """Split a filter string on whitespace, e.g. 'protocols bgp' -> ['protocols', 'bgp']."""
    return path_str.strip().split()


def _child_matches_segment(child: ConfigNode, segment: str, parent: ConfigNode | None) -> bool:
    """Match a path segment against a child by name or list-key (raw_tail)."""
    if child.name == segment:
        return True
    if child.raw_tail:
        joined = " ".join(child.raw_tail)
        if segment == joined or segment == child.raw_tail[0]:
            return True
    # Normalized interfaces: name='interface', raw_tail=['ge-0/0/0']
    if (
        parent is not None
        and parent.name == "interfaces"
        and child.name == "interface"
        and child.raw_tail
        and child.raw_tail[0] == segment
    ):
        return True
    return False


def _find_first_subtree(root: ConfigNode, path: list[str]) -> ConfigNode | None:
    """Return the first matching subtree for the given path, wrapped in its ancestor chain.

    This ensures the result can be placed under a 'configuration' root while preserving
    the original hierarchy (e.g. filter "protocols mpls" yields protocols { mpls { ... } }).

    Path segments match child.name or list-entry keys in raw_tail (e.g. interfaces ge-0/0/0).
    """
    if not path:
        return root.clone()

    current = root
    ancestors: list[ConfigNode] = []

    for name in path:
        found = None
        for child in current.children:
            if _child_matches_segment(child, name, current):
                found = child
                break
        if found is None:
            return None
        ancestors.append(found)
        current = found

    # Clone the deepest match (keeps interface+raw_tail form when normalized)
    node = ancestors[-1].clone()

    # Rebuild ancestor wrappers from the inside out so the hierarchy is preserved
    for ancestor in reversed(ancestors[:-1]):
        wrapper = ConfigNode(
            name=ancestor.name,
            raw_tail=list(ancestor.raw_tail) if ancestor.raw_tail else None,
            props=dict(ancestor.props),
            flags=set(ancestor.flags),
            children=[node],
            source_index=ancestor.source_index,
            comments=list(ancestor.comments),
        )
        node = wrapper

    return node


def filter_config(root: ConfigNode, filters: list[str]) -> ConfigNode:
    """Return a new configuration tree containing only the first match for each filter.

    The returned tree always has a 'configuration' root so the output is valid Junos.
    Multiple filters under the same parent are coalesced into a single stanza.
    """
    if not filters:
        return root.clone()

    result = ConfigNode(name="configuration")
    for f in filters:
        path = _split_filter_path(f)
        subtree = _find_first_subtree(root, path)
        if subtree is not None:
            result.children.append(subtree)

    coalesce_duplicate_containers(result)
    return result


def strip_comments(root: ConfigNode) -> ConfigNode:
    """Return a deep clone with all comments removed."""
    clone = root.clone()

    def _strip(n: ConfigNode) -> None:
        n.comments = []
        for c in n.children:
            _strip(c)

    _strip(clone)
    return clone


def strip_replace(root: ConfigNode) -> ConfigNode:
    """Return a deep clone with all 'replace:' flags removed."""
    clone = root.clone()

    def _strip(n: ConfigNode) -> None:
        n.flags.discard("replace")
        for c in n.children:
            _strip(c)

    _strip(clone)
    return clone
