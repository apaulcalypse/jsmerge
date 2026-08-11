"""Minimal parser for Junos 'set' (and activate/deactivate) format.

Produces the same ConfigNode trees as the curly-brace parser so that
sort, merge, render, etc. work unchanged.

When a SchemaIndex is provided, list keys / leaves / containers are
classified from YANG. Hard-coded frozensets remain as fallback for
schema misses and schema-less callers.

Scope (Phase 2 MVP):
- set <path> [value];
- deactivate <path>;
- activate <path>;

Does not touch the main curly-brace lexer/parser.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List

from jsmerge.models import ConfigNode
from jsmerge.schema.loader import join_schema_path

if TYPE_CHECKING:
    from jsmerge.schema.loader import SchemaIndex, SchemaPath

# Simple tokenizer that respects double quotes
_TOKEN_RE = re.compile(r'"[^"]*"|\S+')

# YANG container that Junos CLI displays as keyed (family inet { ... }).
CLI_KEYED_CONTAINERS = frozenset({"family"})

# Fallback when schema is absent or the path is unknown.
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
        "level",
    }
)

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


def _classify_with_schema(
    schema: SchemaIndex,
    path: SchemaPath,
    current: ConfigNode,
    name: str,
    args: list[str],
    i: int,
    source_index: int,
) -> tuple[bool, ConfigNode, SchemaPath, int, bool]:
    """Classify one statement using schema.

    Returns (handled, current, path, i, done).
    """
    rule = schema.get_rule(path)

    if rule and name in rule.lists:
        list_rule = rule.lists[name]
        n_keys = max(1, len(list_rule.keys))
        if i >= len(args):
            current = _find_or_create(current, name, None, source_index)
            return True, current, join_schema_path(path, name), i, True
        n_keys = min(n_keys, len(args) - i)
        keys = [_strip_token(args[j]) for j in range(i, i + n_keys)]
        i += n_keys
        current = _find_or_create(current, name, keys, source_index)
        return True, current, join_schema_path(path, name), i, False

    child_path = join_schema_path(path, name)
    child_rule = schema.get_rule(child_path)

    # family inet { ... } — YANG container, CLI keyed form
    if name in CLI_KEYED_CONTAINERS and child_rule is not None and i < len(args):
        peek = _strip_token(args[i])
        peek_path = join_schema_path(child_path, peek)
        if (
            peek in child_rule.child_order
            and peek not in child_rule.lists
            and schema.get_rule(peek_path) is not None
        ):
            i += 1
            current = _find_or_create(current, name, [peek], source_index)
            return True, current, peek_path, i, False

    if child_rule is not None:
        current = _find_or_create(current, name, None, source_index)
        return True, current, child_path, i, False

    if rule and name in rule.child_order:
        if i < len(args):
            raw_tail = [_strip_token(t) for t in args[i:]]
            current = _find_or_create(current, name, raw_tail, source_index)
            return True, current, path, len(args), True
        current = _find_or_create(current, name, None, source_index)
        return True, current, path, i, True

    return False, current, path, i, False


def _classify_fallback(
    current: ConfigNode,
    path: SchemaPath,
    name: str,
    args: list[str],
    i: int,
    source_index: int,
    schema: SchemaIndex | None,
) -> tuple[ConfigNode, SchemaPath, int, bool]:
    """Hard-coded classification; advances schema path only when the child exists."""
    if name in LIST_KEYED_STATEMENTS and i < len(args):
        key = _strip_token(args[i])
        i += 1
        current = _find_or_create(current, name, [key], source_index)
        new_path = join_schema_path(path, name)
        if schema is None or schema.get_rule(new_path) is not None:
            path = new_path
        return current, path, i, False

    if name in VALUE_LEAVES and i < len(args):
        raw_tail = [_strip_token(t) for t in args[i:]]
        current = _find_or_create(current, name, raw_tail, source_index)
        return current, path, len(args), True

    current = _find_or_create(current, name, None, source_index)
    new_path = join_schema_path(path, name)
    if schema is None or schema.get_rule(new_path) is not None:
        path = new_path
    return current, path, i, False


def parse_set_line(
    line: str,
    source_index: int = 0,
    schema: SchemaIndex | None = None,
) -> ConfigNode | None:
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
    path: SchemaPath = ""
    i = 0
    while i < len(args):
        name = _strip_token(args[i])
        i += 1

        if schema is not None:
            handled, current, path, i, done = _classify_with_schema(
                schema, path, current, name, args, i, source_index
            )
            if handled:
                if done:
                    break
                continue

        current, path, i, done = _classify_fallback(
            current, path, name, args, i, source_index, schema
        )
        if done:
            break

    if cmd == "deactivate":
        current.flags.add("inactive")
    elif cmd == "activate":
        current.flags.discard("inactive")

    return root


def peek_set_version(text: str) -> str | None:
    """Return the first `set version <ver>` value in set-format text, if any."""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("/*"):
            continue
        tokens = _tokenize(stripped)
        if len(tokens) >= 3 and tokens[0].lower() == "set" and _strip_token(tokens[1]) == "version":
            return _strip_token(tokens[2])
    return None


def parse_set_config(text: str, schema: SchemaIndex | None = None) -> ConfigNode:
    """Parse a multi-line set-format configuration into a single ConfigNode tree."""
    root = ConfigNode(name="configuration")
    for idx, line in enumerate(text.splitlines()):
        node = parse_set_line(line, source_index=idx, schema=schema)
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
