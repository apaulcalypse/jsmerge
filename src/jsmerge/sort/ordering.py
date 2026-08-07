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

    # Group by name so duplicate top-level statements are preserved together
    groups: dict[str, list[ConfigNode]] = {}
    for child in root.children:
        groups.setdefault(child.name, []).append(child)

    ordered: list[ConfigNode] = []
    used: set[str] = set()
    for name in CLI_TOP_LEVEL_ORDER:
        nodes = groups.get(name)
        if nodes is not None:
            ordered.extend(nodes)
            used.add(name)

    # Preserve relative order of any unknown statements (by first source_index)
    remaining_names = [n for n in groups if n not in used]
    remaining_names.sort(key=lambda n: groups[n][0].source_index)
    for name in remaining_names:
        ordered.extend(groups[name])

    root.children = ordered
