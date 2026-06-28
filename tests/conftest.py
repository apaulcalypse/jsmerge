"""Test fixtures and helpers."""

from __future__ import annotations

import random
from pathlib import Path

from jsmerge.models import ConfigNode
from jsmerge.normalize import denormalize_tree, normalize_tree
from jsmerge.parser import parse_config
from jsmerge.render import render_config
from jsmerge.schema.loader import SchemaPath, join_schema_path, load_schema_index
from jsmerge.sort import SortEngine

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMAS = Path(__file__).parent.parent / "schemas"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def sort_text(text: str, schema_name: str = "24.4R2-EVO") -> str:
    root = normalize_tree(parse_config(text))
    schema = load_schema_index(SCHEMAS / f"{schema_name}.json")
    sorted_root = SortEngine(schema).sort(root)
    return render_config(denormalize_tree(sorted_root))


def _children_schema_path(path: SchemaPath, node: ConfigNode, schema) -> SchemaPath:
    if node.value is not None:
        valued = join_schema_path(path, node.name, node.value)
        if schema.get_rule(valued) is not None:
            return valued
    return join_schema_path(path, node.name)


def shuffle_reorderable(
    node: ConfigNode,
    path: SchemaPath,
    schema,
    rng: random.Random,
) -> None:
    """Shuffle only system-ordered siblings; preserve user-ordered list sequence."""
    rule = schema.get_rule(path)
    user_lists = {name for name, lr in rule.lists.items() if lr.ordered_by == "user"} if rule else set()

    reorderable_idx = [i for i, child in enumerate(node.children) if child.name not in user_lists]
    reorderable = [node.children[i] for i in reorderable_idx]
    rng.shuffle(reorderable)
    for idx, child in zip(reorderable_idx, reorderable, strict=True):
        node.children[idx] = child

    for child in node.children:
        child_path = _children_schema_path(path, child, schema)
        shuffle_reorderable(child, child_path, schema, rng)
