"""Interface and default key comparators for system-ordered lists."""

from __future__ import annotations

import ipaddress
import re
from functools import cmp_to_key

from jsmerge.models import ConfigNode

_INTERFACE_RE = re.compile(
    r"^(?P<type>[a-z]+(?:-[a-z]+)*)"
    r"(?:-(?P<fpc>\d+)/(?P<pic>\d+)/(?P<port>\d+)(?:[.:](?P<subport>\d+))?)?"
    r"$",
    re.IGNORECASE,
)


def _parse_interface(name: str) -> tuple:
    if name is None:
        return ("", 0, 0, 0, 0, "")
    match = _INTERFACE_RE.match(name)
    if not match:
        return (name.lower(), 0, 0, 0, 0, name.lower())
    groups = match.groupdict()
    return (
        groups["type"].lower(),
        int(groups["fpc"] or 0),
        int(groups["pic"] or 0),
        int(groups["port"] or 0),
        int(groups["subport"] or 0),
        name.lower(),
    )


def compare_interface(a: str | None, b: str | None) -> int:
    left, right = _parse_interface(a or ""), _parse_interface(b or "")
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def compare_numeric(a: str | None, b: str | None) -> int:
    try:
        left, right = int(a or 0), int(b or 0)
    except ValueError:
        return compare_lexicographic(a, b)
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def compare_lexicographic(a: str | None, b: str | None) -> int:
    left = (a or "").lower()
    right = (b or "").lower()
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def compare_prefix(a: str | None, b: str | None) -> int:
    """Compare IP prefixes numerically (network address first, then prefix length)."""
    def key(p: str | None):
        if not p:
            return (0, 0, "")
        try:
            net = ipaddress.ip_network(p, strict=False)
            return (int(net.network_address), net.prefixlen, p)
        except ValueError:
            return (0, 0, p.lower())

    left, right = key(a), key(b)
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def _primary_value(node: ConfigNode) -> str:
    if node.value is not None:
        return node.value
    if node.raw_tail:
        return node.raw_tail[0]
    return ""

def extract_list_key(node: ConfigNode, keys: list[str]) -> tuple[str, ...]:
    if len(keys) == 1 and keys[0] == "name":
        return (_primary_value(node),)
    values: list[str] = []
    for key in keys:
        if key == "name":
            values.append(_primary_value(node))
            continue
        child = next((c for c in node.children if c.name == key and c.value is not None), None)
        values.append(child.value if child else "")
    return tuple(values)


def compare_nodes(a: ConfigNode, b: ConfigNode, keys: list[str], comparator: str) -> int:
    if comparator == "interface":
        return compare_interface(_primary_value(a), _primary_value(b))
    if comparator == "numeric":
        return compare_numeric(_primary_value(a), _primary_value(b))
    if comparator == "prefix" or a.name == "prefix-list-item":
        return compare_prefix(_primary_value(a), _primary_value(b))
    if len(keys) == 1:
        return compare_lexicographic(_primary_value(a), _primary_value(b))
    left = extract_list_key(a, keys)
    right = extract_list_key(b, keys)
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def sort_key_for_nodes(keys: list[str], comparator: str):
    return cmp_to_key(lambda a, b: compare_nodes(a, b, keys, comparator))
