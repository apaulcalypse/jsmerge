"""High-level sort API."""

from __future__ import annotations

from pathlib import Path

from jsmerge.normalize import denormalize_tree, normalize_tree
from jsmerge.parser import parse_config
from jsmerge.render import render_config
from jsmerge.schema.loader import load_schema_index, resolve_schema_path
from jsmerge.sort import SortEngine
from jsmerge.sort.ordering import apply_top_level_order


def sort_config(
    text: str,
    *,
    schema: str = "auto",
    schema_dir: Path | None = None,
    strict: bool = False,
    order: str = "cli",
) -> str:
    """Parse, normalize, sort, and render a Junos configuration."""
    root = normalize_tree(parse_config(text))
    config_version = next(
        (child.raw_tail[0] for child in root.children if child.name == "version" and child.raw_tail),
        None,
    )
    schema_path = resolve_schema_path(schema, config_version=config_version, directory=schema_dir)
    index = load_schema_index(schema_path)
    sorted_root = denormalize_tree(SortEngine(index, strict=strict).sort(root))
    apply_top_level_order(sorted_root, order)
    return render_config(sorted_root)
