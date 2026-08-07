"""Render ConfigNode trees as Junos 'set' format."""

from __future__ import annotations

from jsmerge.models import ConfigNode


def _quote_if_needed(value: str) -> str:
    """Quote the value if it contains spaces or special characters.
    Strips existing surrounding quotes first (they come from the parser).
    """
    if not value:
        return '""'

    # Strip surrounding quotes that the parser may have left in raw_tail
    if (value.startswith('"') and value.endswith('"')) or \
       (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]

    if any(c in value for c in ' \t;{}'):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_set_lines(
    node: ConfigNode,
    current_path: list[str],
    lines: list[str],
) -> None:
    """Recursively build set/deactivate lines."""
    path = current_path + [node.name]

    is_list_key = bool(node.raw_tail) and bool(node.children)
    is_leaf_value = bool(node.raw_tail) and not node.children
    is_presence_only = (not node.raw_tail) and not node.children

    if is_list_key:
        # List key (e.g. unit 0, family inet, address 1.2.3.4/24) — extend the path
        key_value = " ".join(node.raw_tail)
        new_path = path + [key_value]
        if "inactive" in node.flags:
            lines.append(f"deactivate {' '.join(new_path)}")
        for child in node.children:
            _render_set_lines(child, new_path, lines)
        return

    if is_leaf_value:
        value = " ".join(node.raw_tail)
        value = _quote_if_needed(value)
        path_str = " ".join(path)
        # Always emit set so inactive leaves keep their value on round-trip
        lines.append(f"set {path_str} {value}")
        if "inactive" in node.flags:
            lines.append(f"deactivate {path_str}")
        return

    if is_presence_only:
        path_str = " ".join(path)
        lines.append(f"set {path_str}")
        if "inactive" in node.flags:
            lines.append(f"deactivate {path_str}")
        return

    # Normal containers
    if "inactive" in node.flags:
        lines.append(f"deactivate {' '.join(path)}")
    for child in node.children:
        _render_set_lines(child, path, lines)


def render_set(root: ConfigNode) -> str:
    """Render the configuration tree as 'set' format lines."""
    lines: list[str] = []

    # Start from the actual configuration children
    start_children = root.children if root.name == "configuration" else [root]

    for child in start_children:
        _render_set_lines(child, [], lines)

    return "\n".join(lines) + ("\n" if lines else "")
