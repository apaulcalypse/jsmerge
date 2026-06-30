"""Render ConfigNode trees as Junos curly-brace configuration text."""

from __future__ import annotations

from jsmerge.models import ConfigNode

INDENT = "    "



def render_config(
    root: ConfigNode,
    *,
    include_root: bool = False,
    blank_between_top_level: bool = False,
) -> str:
    lines: list[str] = []
    if include_root or root.name != "configuration":
        _render_node(root, 0, lines, blank_between_top_level=blank_between_top_level)
    else:
        children = root.children
        for idx, child in enumerate(children):
            if blank_between_top_level and idx > 0:
                lines.append("")
            _render_node(child, 0, lines, blank_between_top_level=False)
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def _render_node(
    node: ConfigNode,
    depth: int,
    lines: list[str],
    *,
    blank_between_top_level: bool,
) -> None:
    indent = INDENT * depth
    prefix = ""
    if "replace" in node.flags:
        prefix = "replace: "
    elif "inactive" in node.flags:
        prefix = "inactive: "

    for comment in node.comments:
        lines.append(f"{indent}/* {comment} */")

    tail = " " + " ".join(node.raw_tail) if node.raw_tail else ""

    if node.children:
        lines.append(f"{indent}{prefix}{node.name}{tail} {{")
        for child in node.children:
            _render_node(child, depth + 1, lines, blank_between_top_level=False)
        lines.append(f"{indent}}}")
    else:
        secret = " ## SECRET-DATA" if "secret-data" in node.flags else ""
        lines.append(f"{indent}{prefix}{node.name}{tail};{secret}")
