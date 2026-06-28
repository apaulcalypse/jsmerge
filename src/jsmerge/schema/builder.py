"""Build SchemaIndex JSON from Juniper YANG modules using pyang."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from jsmerge.schema._pyang import load_pyang

# When focus_only is True, these top-level stanzas (plus root) are guaranteed in output
# but the full tree is still built from the resolved schema.
FOCUS_STANZAS = frozenset({"interfaces", "policy-options", "firewall"})


def _keyword(stmt) -> str:
    keyword = stmt.keyword
    if isinstance(keyword, tuple):
        return keyword[1]
    return keyword


def _is_ordered_by_user(stmt) -> bool:
    for sub in stmt.substmts:
        if sub.keyword == "ordered-by" and sub.arg == "user":
            return True
    return False


def _list_keys(stmt) -> list[str]:
    for sub in stmt.substmts:
        if sub.keyword == "key":
            return sub.arg.split()
    return ["name"]


def _list_comparator(name: str) -> str:
    if name == "interface":
        return "interface"
    if name == "unit":
        return "numeric"
    return "default"


def _find_configuration_container(ctx):
    for module in ctx.modules.values():
        if module.arg != "junos-conf-root":
            continue
        for sub in module.substmts:
            if _keyword(sub) == "container" and sub.arg == "configuration":
                return sub
    raise RuntimeError(
        "junos-conf-root configuration container not found. "
        "Ensure junos-conf-root@*.yang is present in the YANG directory."
    )


def build_schema_index(
    yang_dir: Path,
    *,
    version: str,
    platform: Literal["evo", "classic"],
    focus_only: bool = True,
    progress=None,
) -> dict:
    context, yang_repository = load_pyang()

    yang_dir = Path(yang_dir)
    module_paths = sorted(yang_dir.glob("*.yang"))
    if not module_paths:
        raise FileNotFoundError(f"No .yang files found in {yang_dir}")

    total_modules = len(module_paths)
    if progress is not None:
        progress.step(f"Loading {total_modules} YANG modules")

    repo = yang_repository.FileRepository(str(yang_dir))
    ctx = context.Context(repo)

    for index, path in enumerate(module_paths, start=1):
        ctx.add_module(path.as_posix(), path.read_text(encoding="utf-8"))
        if progress is not None and (index == 1 or index == total_modules or index % 25 == 0):
            progress.update(f"Loading YANG modules ({index}/{total_modules})")

    if progress is not None:
        progress.finish(f"Loaded {total_modules} YANG modules")
        progress.step("Validating YANG modules")

    ctx.validate()

    if progress is not None:
        progress.finish("Validated YANG modules")
        progress.step("Building schema index from YANG tree")

    configuration = _find_configuration_container(ctx)
    nodes: dict[str, dict] = {}

    def add_node(path: list[str], child_order: list[str], lists: dict[str, dict]) -> None:
        key = "/".join(path)
        existing = nodes.get(key, {"child_order": [], "lists": {}})
        merged_order = list(existing["child_order"])
        for child in child_order:
            if child not in merged_order:
                merged_order.append(child)
        existing_lists = dict(existing["lists"])
        existing_lists.update(lists)
        nodes[key] = {"child_order": merged_order, "lists": existing_lists}

    def walk_children(children, path: list[str]) -> None:
        child_order: list[str] = []
        lists: dict[str, dict] = {}

        def emit(stmt) -> None:
            keyword = _keyword(stmt)

            if keyword == "container":
                child_order.append(stmt.arg)
                walk_children(getattr(stmt, "i_children", []), path + [stmt.arg])
            elif keyword == "list":
                child_order.append(stmt.arg)
                lists[stmt.arg] = {
                    "ordered_by": "user" if _is_ordered_by_user(stmt) else "system",
                    "keys": _list_keys(stmt),
                    "comparator": _list_comparator(stmt.arg),
                }
                walk_children(getattr(stmt, "i_children", []), path + [stmt.arg])
            elif keyword in ("leaf", "leaf-list"):
                child_order.append(stmt.arg)
            elif keyword == "choice":
                # Inline choice cases at this position (accept/reject belong near end of then)
                for case in getattr(stmt, "i_children", []):
                    for case_child in getattr(case, "i_children", []):
                        emit(case_child)

        for stmt in children:
            emit(stmt)

        if child_order or lists:
            add_node(path, child_order, lists)

    walk_children(configuration.i_children, [])

    if focus_only:
        nodes = _filter_focus_nodes(nodes)

    if progress is not None:
        progress.finish(f"Built schema index ({len(nodes):,} paths)")

    return {
        "version": version,
        "platform": platform,
        "nodes": nodes,
    }


def _filter_focus_nodes(nodes: dict[str, dict]) -> dict[str, dict]:
    """Keep root ordering and focus stanza subtrees."""
    keep: dict[str, dict] = {}

    # Always keep root
    if "" in nodes:
        root = nodes[""]
        keep[""] = {
            "child_order": list(root["child_order"]),
            "lists": dict(root["lists"]),
        }

    for path_str, rule in nodes.items():
        if not path_str:
            continue
        top = path_str.split("/")[0]
        if top in FOCUS_STANZAS:
            keep[path_str] = rule
            # Ensure ancestor paths exist for prefix walking
            parts = path_str.split("/")
            for i in range(1, len(parts)):
                ancestor = "/".join(parts[:i])
                if ancestor in nodes and ancestor not in keep:
                    keep[ancestor] = nodes[ancestor]

    return keep


def write_schema_index(
    yang_dir: Path,
    output: Path,
    *,
    version: str,
    platform: Literal["evo", "classic"],
    focus_only: bool = True,
    progress=None,
) -> None:
    from jsmerge.schema.loader import _parse_schema_payload, write_schema_cache

    payload = build_schema_index(
        yang_dir,
        version=version,
        platform=platform,
        focus_only=focus_only,
        progress=progress,
    )
    if progress is not None:
        progress.step(f"Writing schema bundle to {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if progress is not None:
        progress.finish(f"Wrote schema bundle to {output}")
        progress.step("Writing schema cache")

    write_schema_cache(_parse_schema_payload(payload), output)

    if progress is not None:
        progress.finish("Wrote schema cache")
