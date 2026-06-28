"""Schema-driven configuration sort engine."""

from __future__ import annotations

import logging
from collections import defaultdict

from jsmerge.models import ConfigNode
from jsmerge.schema.loader import NodeRule, SchemaIndex, SchemaPath
from jsmerge.sort.comparators import sort_key_for_nodes

logger = logging.getLogger(__name__)


class SortEngine:
    def __init__(self, schema: SchemaIndex, *, strict: bool = False) -> None:
        self.schema = schema
        self.strict = strict

    def sort(self, root: ConfigNode) -> ConfigNode:
        sorted_root = root.clone()
        if sorted_root.name == "configuration":
            sorted_root.children = self._sort_children(sorted_root.children, ())
        else:
            sorted_root.children = self._sort_children(sorted_root.children, (sorted_root.name,))
        return sorted_root

    def _children_schema_path(self, path: SchemaPath, node: ConfigNode) -> SchemaPath:
        if node.value is not None:
            valued = path + (node.name, node.value)
            if self.schema.get_rule(valued) is not None:
                return valued
        return path + (node.name,)

    def _sort_children(self, children: list[ConfigNode], path: SchemaPath) -> list[ConfigNode]:
        rule = self.schema.get_rule(path)
        if rule is None:
            if self.strict:
                path_str = "/".join(path) or "<root>"
                raise ValueError(f"No schema rule for path: {path_str}")
            rule = NodeRule()

        grouped: dict[str, list[ConfigNode]] = defaultdict(list)
        for child in children:
            grouped[child.name].append(child)

        ordered_names = self._ordered_child_names(grouped.keys(), rule)
        result: list[ConfigNode] = []

        for name in ordered_names:
            nodes = grouped.pop(name, [])
            list_rule = rule.lists.get(name)
            if list_rule and all(node.value is not None for node in nodes):
                nodes = self._sort_list(nodes, list_rule)
            for node in nodes:
                node.children = self._sort_children(
                    node.children,
                    self._children_schema_path(path, node),
                )
                result.append(node)

        for name in sorted(grouped.keys()):
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
        remaining = sorted(names_set - set(ordered))
        return ordered + remaining

    def _sort_list(self, nodes: list[ConfigNode], list_rule) -> list[ConfigNode]:
        if list_rule.ordered_by == "user":
            return sorted(nodes, key=lambda n: n.source_index)
        return sorted(
            nodes,
            key=sort_key_for_nodes(list_rule.keys, list_rule.comparator),
        )
