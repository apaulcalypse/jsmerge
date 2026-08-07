"""Minimal parser for Junos 'set' (and activate/deactivate) format.

Produces the same ConfigNode trees as the curly-brace parser so that
sort, merge, render, etc. work unchanged.

Scope (Phase 2 MVP):
- set <path> [value];
- deactivate <path>;
- activate <path>;

Does not touch the main curly-brace lexer/parser.
"""

from __future__ import annotations

import re
from typing import List

from jsmerge.models import ConfigNode

# Simple tokenizer that respects double quotes
_TOKEN_RE = re.compile(r'"[^"]*"|\S+')

# Statements whose next token is a list key (raw_tail), not a child name.
LIST_KEYED_STATEMENTS = frozenset(
    {
        "unit",
        "term",
        "area",
        "group",
        "neighbor",
        "policy-statement",
        "prefix-list",
        "as-path-group",
        "rib-group",
        "routing-instance",
        "logical-system",
        "filter",
        "prefix-list-filter",
        "route-filter-list",
        "vlan",
        "bridge-domain",
        "interface",
        "family",
        "address",
        "vrrp-group",
    }
)

# Statements whose remaining tokens are a leaf value (raw_tail), not children.
VALUE_LEAVES = frozenset(
    {
        "host-name",
        "description",
        "mtu",
        "vlan-id",
        "metric",
        "preference",
        "local-address",
        "peer-as",
        "local-as",
        "as-path",
        "community",
        "route-filter",
        "type",
        "export",
        "import",
        "apply-groups",
        "apply-groups-except",
        "location",
        "contact",
        "primary",
        "secondary",
        "port",
        "version",
        "maximum",
        "hold-time",
        "keep-alive",
        "local-preference",
        "tag",
        "metric2",
        "next-hop",
        "qualified-next-hop",
    }
)


def _tokenize(line: str) -> List[str]:
    """Split a set/deactivate line into tokens, preserving quoted strings."""
    return _TOKEN_RE.findall(line.strip().rstrip(";"))


def _strip_token(tok: str) -> str:
    """Strip surrounding quotes from a token (set format stores bare values)."""
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def _find_child(parent: ConfigNode, name: str, raw_tail: list[str] | None) -> ConfigNode | None:
    """Find a child matching name + raw_tail (path_key identity)."""
    key = (name, tuple(raw_tail) if raw_tail else None)
    for child in parent.children:
        if child.path_key() == key:
            return child
    return None


def _find_or_create(
    parent: ConfigNode,
    name: str,
    raw_tail: list[str] | None,
    source_index: int,
) -> ConfigNode:
    existing = _find_child(parent, name, raw_tail)
    if existing is not None:
        return existing
    node = ConfigNode(
        name=name,
        raw_tail=list(raw_tail) if raw_tail else None,
        source_index=source_index,
    )
    parent.children.append(node)
    return node


def _find_merge_child(parent: ConfigNode, child: ConfigNode) -> ConfigNode | None:
    """Find merge target by path_key; fall back to unique name match for deactivate."""
    existing = _find_child(parent, child.name, child.raw_tail)
    if existing is not None:
        return existing
    # deactivate/activate paths omit leaf values — match a unique same-name sibling
    if child.raw_tail is None:
        matches = [c for c in parent.children if c.name == child.name]
        if len(matches) == 1:
            return matches[0]
    return None


def parse_set_line(line: str, source_index: int = 0) -> ConfigNode | None:
    """Parse a single 'set ...' or 'deactivate/activate ...' line into a ConfigNode subtree.

    Returns the root-most node created for this line.
    Returns None for empty or comment lines.
    """
    line = line.strip()
    if not line or line.startswith("#") or line.startswith("/*"):
        return None

    tokens = _tokenize(line)
    if not tokens:
        return None

    cmd = tokens[0].lower()
    if cmd not in {"set", "deactivate", "activate"}:
        return None

    args = tokens[1:]
    if not args:
        return None

    root = ConfigNode(name="configuration")
    current = root
    i = 0
    while i < len(args):
        name = _strip_token(args[i])
        i += 1

        if name in LIST_KEYED_STATEMENTS and i < len(args):
            key = _strip_token(args[i])
            i += 1
            current = _find_or_create(current, name, [key], source_index)
            continue

        if name in VALUE_LEAVES and i < len(args):
            raw_tail = [_strip_token(t) for t in args[i:]]
            current = _find_or_create(current, name, raw_tail, source_index)
            break

        current = _find_or_create(current, name, None, source_index)

    if cmd == "deactivate":
        current.flags.add("inactive")
    elif cmd == "activate":
        current.flags.discard("inactive")

    return root


def parse_set_config(text: str) -> ConfigNode:
    """Parse a multi-line set-format configuration into a single ConfigNode tree."""
    root = ConfigNode(name="configuration")
    for idx, line in enumerate(text.splitlines()):
        node = parse_set_line(line, source_index=idx)
        if node is None:
            continue
        for child in node.children:
            existing = _find_merge_child(root, child)
            if existing is None:
                root.children.append(child)
            else:
                _merge_nodes(existing, child)
    return root


def _merge_nodes(target: ConfigNode, source: ConfigNode) -> None:
    """Merge source subtree into target, matching children by path_key."""
    if source.raw_tail:
        target.raw_tail = list(source.raw_tail)
    target.flags.update(source.flags)
    for src_child in source.children:
        existing = _find_merge_child(target, src_child)
        if existing is None:
            target.children.append(src_child)
        else:
            _merge_nodes(existing, src_child)
