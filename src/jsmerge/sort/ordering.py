"""Top-level ordering strategies for Junos configuration."""

from __future__ import annotations

from jsmerge.models import ConfigNode

# Stable top-level order observed across real Junos "show configuration" output
# from many routers. This produces output that closely matches what the router
# emits, which is the recommended default for round-tripping and generation.
CLI_TOP_LEVEL_ORDER: list[str] = [
    "version",
    "groups",
    "apply-groups",
    "system",
    "chassis",
    "services",
    "security",
    "interfaces",
    "snmp",
    "forwarding-options",
    "policy-options",
    "class-of-service",
    "firewall",
    "routing-instances",
    "routing-options",
    "protocols",
]


def apply_top_level_order(root: ConfigNode, mode: str) -> None:
    """Reorder direct children of the configuration root according to `mode`.

    mode:
        "cli"   - Use the stable observed CLI order (recommended)
        "yang"  - Leave ordering as produced by SortEngine (YANG child_order)
        "source"- Leave ordering as produced by SortEngine (source order)
    """
    if mode != "cli":
        return

    name_to_node = {child.name: child for child in root.children}
    ordered: list[ConfigNode] = []
    for name in CLI_TOP_LEVEL_ORDER:
        node = name_to_node.pop(name, None)
        if node is not None:
            ordered.append(node)

    # Preserve relative order of any unknown statements
    remaining = sorted(name_to_node.values(), key=lambda n: n.source_index)
    root.children = ordered + remaining
