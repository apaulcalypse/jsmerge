"""MergeEngine and tree-diff primitives.

These form the core for both normal overlay/partition merge and the
first-class reverse-merge (drift extraction) feature.
"""

from __future__ import annotations

from typing import Optional

from jsmerge.filter import strip_comments
from jsmerge.models import ConfigNode
from jsmerge.schema.loader import SchemaIndex


def _is_list_child(parent_schema_path: str, child_name: str, schema_index: SchemaIndex | None) -> bool:
    """Return True if child_name is a keyed list under the given parent path according to schema."""
    if not schema_index:
        return False
    rule = schema_index.get_rule(parent_schema_path)
    return bool(rule and child_name in rule.lists)


def _find_child(
    children: list[ConfigNode],
    key_node: ConfigNode,
    parent_schema_path: str = "",
    schema_index: SchemaIndex | None = None,
) -> ConfigNode | None:
    is_list = _is_list_child(parent_schema_path, key_node.name, schema_index)
    for c in children:
        if is_list:
            if c.path_key() == key_node.path_key():
                return c
        else:
            # singleton (or unknown): match by name only
            if c.name == key_node.name:
                return c
    return None


def _is_user_ordered_like(node: ConfigNode) -> bool:
    # Heuristic: nodes with many children that look like terms/filters are user-ordered.
    # Real impl will consult schema; for now use simple signal (name hints + children).
    name = node.name.lower()
    return name in {"term", "route-filter", "prefix-list", "from", "then"} or len(node.children) > 0 and any(
        c.name in {"term", "route-filter"} for c in node.children
    )


def diff_trees(base: ConfigNode, live: ConfigNode) -> ConfigNode | None:
    """Return a ConfigNode subtree containing only the differences.

    Used by reverse_merge. Comments from 'live' are preserved by default.
    Deletions (present in base, absent in live) are currently omitted from
    the delta (absence = delete in overlay semantics); a future flag can emit
    explicit delete statements.
    """
    flags_differ = live.flags != base.flags
    comments_differ = live.comments != base.comments

    # Leaf vs leaf
    if live.is_leaf() and base.is_leaf():
        if live.value != base.value or flags_differ or comments_differ:
            return ConfigNode(
                name=live.name,
                raw_tail=list(live.raw_tail) if live.raw_tail else None,
                flags=set(live.flags),
                source_index=live.source_index,
                comments=list(live.comments),
            )
        return None

    # One is leaf, other is container -> whole live wins
    if live.is_leaf() != base.is_leaf():
        # copy whole live subtree
        return live.clone()

    # Both containers: recurse on children
    base_children = {c.path_key(): c for c in base.children}
    live_children = {c.path_key(): c for c in live.children}

    added_or_changed: list[ConfigNode] = []

    # additions and modifications from live
    for key, live_child in live_children.items():
        base_child = base_children.get(key)
        if base_child is None:
            # entirely new
            added_or_changed.append(live_child.clone())
            continue

        child_delta = diff_trees(base_child, live_child)
        if child_delta is not None:
            added_or_changed.append(child_delta)

    # deletions: present in base but missing in live -> for overlay we simply
    # omit them from delta (the merge will not see them). If we later want
    # explicit delete statements we can emit special delete nodes here.

    if not added_or_changed and not flags_differ and not comments_differ:
        # nothing changed at this level (identical flags/comments do not count)
        return None

    delta = ConfigNode(
        name=live.name,
        raw_tail=list(live.raw_tail) if live.raw_tail else None,
        flags=set(live.flags) if flags_differ else set(),
        source_index=live.source_index,
        comments=list(live.comments) if comments_differ else [],
    )
    delta.children = added_or_changed
    return delta


class MergeEngine:
    """Core merge logic. Reused by reverse-merge for delta extraction."""

    def __init__(
        self,
        strict: bool = False,
        report_conflicts: bool = False,
        schema_index: SchemaIndex | None = None,
    ) -> None:
        self.strict = strict
        self.report_conflicts = report_conflicts
        self.schema_index = schema_index
        self.conflicts: list[str] = []

    def merge(self, trees: list[ConfigNode], strategy: str = "overlay") -> ConfigNode:
        """Merge multiple trees into one."""
        if not trees:
            return ConfigNode(name="configuration")
        result = trees[0].clone()
        for t in trees[1:]:
            self.deep_merge(result, t, schema_path="")
        return result

    def deep_merge(
        self, target: ConfigNode, source: ConfigNode, path: str = "", schema_path: str = ""
    ) -> None:
        """Recursively merge source into target (in place). Overlay semantics."""
        current_path = f"{path}/{source.name}" if path else source.name
        # schema_path uses Juniper slash notation (root='', 'interfaces', 'interfaces/interface', ...)
        current_schema_path = schema_path

        # Merge flags (inactive etc.)
        if source.flags and source.flags != target.flags:
            if self.report_conflicts and target.flags:
                self.conflicts.append(f"{current_path}: flags {target.flags} -> {source.flags}")
            target.flags.update(source.flags)
        else:
            target.flags.update(source.flags)

        # Merge comments (preserve all, dedup later if needed)
        target.comments.extend(source.comments)

        # replace: replaces the target stanza entirely (children + raw_tail), still merging flags above
        if "replace" in source.flags:
            target.children = [c.clone() for c in source.children]
            target.raw_tail = list(source.raw_tail) if source.raw_tail else None
            return

        if source.is_leaf():
            if source.raw_tail and source.raw_tail != target.raw_tail:
                if self.report_conflicts and target.raw_tail:
                    old = " ".join(target.raw_tail)
                    new = " ".join(source.raw_tail)
                    self.conflicts.append(f"{current_path}: {old} -> {new}")
                target.raw_tail = list(source.raw_tail)
            elif source.raw_tail:
                target.raw_tail = list(source.raw_tail)
            # avoid hybrid leaf+container nodes with stale children
            target.children = []
            return

        # Container merge
        for src_child in source.children:
            existing = _find_child(
                target.children, src_child, parent_schema_path=current_schema_path, schema_index=self.schema_index
            )
            if existing is None:
                target.children.append(src_child.clone())
            else:
                # same key -> recurse; child name becomes next schema segment
                child_schema_path = (
                    f"{current_schema_path}/{src_child.name}" if current_schema_path else src_child.name
                )
                self.deep_merge(existing, src_child, current_path, child_schema_path)


def reverse_merge(
    base: ConfigNode,
    live: ConfigNode,
    include_comments: bool = True,
) -> ConfigNode:
    """High-level reverse-merge entry point (first-class feature).

    Produces a minimal delta tree that, when merged over base, reproduces
    the effective overrides present in live.
    """
    delta = diff_trees(base, live)
    if delta is None:
        return ConfigNode(name=base.name or "configuration")
    if not include_comments:
        delta = strip_comments(delta)
    return delta
