"""Schema-driven configuration sort engine."""

from __future__ import annotations

import logging
from collections import defaultdict

from jsmerge.models import ConfigNode
from jsmerge.schema.loader import NodeRule, SchemaIndex, SchemaPath, join_schema_path
from jsmerge.sort.comparators import sort_key_for_nodes

logger = logging.getLogger(__name__)


class SortEngine:
    def __init__(self, schema: SchemaIndex, *, strict: bool = False) -> None:
        self.schema = schema
        self.strict = strict
        self._path_cache: dict[tuple[str, str, str | None], SchemaPath] = {}

    def sort(self, root: ConfigNode) -> ConfigNode:
        if root.name == "configuration":
            root.children = self._sort_children(root.children, "")
        else:
            root.children = self._sort_children(root.children, root.name)
        return root

    def _children_schema_path(self, path: SchemaPath, node: ConfigNode) -> SchemaPath:
        val = node.raw_tail[0] if node.raw_tail else None
        cache_key = (path, node.name, val)
        cached = self._path_cache.get(cache_key)
        if cached is not None:
            return cached

        if val is not None:
            valued = join_schema_path(path, node.name, val)
            if self.schema.get_rule(valued) is not None:
                self._path_cache[cache_key] = valued
                return valued
        result = join_schema_path(path, node.name)
        self._path_cache[cache_key] = result
        return result

    def _sort_children(self, children: list[ConfigNode], path: SchemaPath) -> list[ConfigNode]:
        rule = self.schema.get_rule(path)
        if rule is None:
            if self.strict:
                path_str = path or "<root>"
                raise ValueError(f"No schema rule for path: {path_str}")
            rule = NodeRule()

        grouped: dict[str, list[ConfigNode]] = defaultdict(list)
        for child in children:
            grouped[child.name].append(child)

        ordered_names = self._ordered_child_names(grouped.keys(), rule)
        ordered_set = set(ordered_names)
        result: list[ConfigNode] = []

        for name in ordered_names:
            nodes = grouped.pop(name, [])
            list_rule = rule.lists.get(name)
            if list_rule and all(node.raw_tail is not None for node in nodes):
                nodes = self._sort_list(nodes, list_rule)
            for node in nodes:
                node.children = self._sort_children(
                    node.children,
                    self._children_schema_path(path, node),
                )
                result.append(node)

        # Unknown names: preserve original source order (first appearance)
        unknown_names = sorted(
            grouped.keys(),
            key=lambda n: min(c.source_index for c in grouped[n])
        )
        for name in unknown_names:
            if name in ordered_set:
                continue
            for node in grouped[name]:
                node.children = self._sort_children(
                    node.children,
                    self._children_schema_path(path, node),
                )
                result.append(node)

        return result

    def _ordered_child_names(self, names, rule: NodeRule) -> list[str]:
        names_set = set(names)
        ordered: list[str] = [name for name in rule.child_order if name in names_set]
        ordered_set = set(ordered)
        # For names not explicitly ordered by schema, we will handle order preservation
        # in _sort_children by sorting unknown names by source_index.
        remaining = [n for n in names if n not in ordered_set]
        return ordered + remaining

    def _sort_list(self, nodes: list[ConfigNode], list_rule) -> list[ConfigNode]:
        # Default to preserving source order (user order) unless the schema
        # explicitly wants a key-based sort. This makes jsmerge sort idempotent
        # on already-canonical "show configuration" output.
        if list_rule.ordered_by == "user" or not list_rule.keys:
            return sorted(nodes, key=lambda n: n.source_index)
        return sorted(
            nodes,
            key=sort_key_for_nodes(list_rule.keys, list_rule.comparator),
        )
