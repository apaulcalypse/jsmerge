"""Schema index models and loading."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

SchemaPath = tuple[str, ...]


@dataclass
class ListRule:
    ordered_by: Literal["user", "system"]
    keys: list[str]
    comparator: str = "default"


@dataclass
class NodeRule:
    child_order: list[str] = field(default_factory=list)
    lists: dict[str, ListRule] = field(default_factory=dict)


@dataclass
class SchemaIndex:
    version: str
    platform: Literal["evo", "classic"]
    nodes: dict[SchemaPath, NodeRule]

    def get_rule(self, path: SchemaPath) -> NodeRule | None:
        return self.nodes.get(path)

    @staticmethod
    def path_to_str(path: SchemaPath) -> str:
        return "/".join(path)

    @staticmethod
    def str_to_path(text: str) -> SchemaPath:
        return tuple(part for part in text.split("/") if part)


def _parse_list_rule(data: dict) -> ListRule:
    return ListRule(
        ordered_by=data["ordered_by"],
        keys=list(data["keys"]),
        comparator=data.get("comparator", "default"),
    )


def _parse_node_rule(data: dict) -> NodeRule:
    lists = {name: _parse_list_rule(rule) for name, rule in data.get("lists", {}).items()}
    return NodeRule(child_order=list(data.get("child_order", [])), lists=lists)


def load_schema_index(path: Path) -> SchemaIndex:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes: dict[SchemaPath, NodeRule] = {}
    for path_str, rule_data in payload["nodes"].items():
        nodes[SchemaIndex.str_to_path(path_str)] = _parse_node_rule(rule_data)
    return SchemaIndex(
        version=payload["version"],
        platform=payload["platform"],
        nodes=nodes,
    )


def schema_bundle_dir() -> Path:
    """Return the directory containing shipped schema bundles."""
    pkg = Path(__file__).resolve().parent
    bundled = pkg / "bundles"
    if bundled.is_dir():
        return bundled
    repo = Path(__file__).resolve().parents[3] / "schemas"
    return repo


def list_schema_bundles(directory: Path | None = None) -> list[Path]:
    root = directory or schema_bundle_dir()
    if not root.is_dir():
        return []
    return sorted(root.glob("*.json"), key=lambda p: p.stem, reverse=True)


_VERSION_RE = re.compile(
    r"^(\d+)\.(\d+)[A-Z]?\d*(?:[-.](\d+))?(?:R(\d+(?:\.\d+)?))?(?:[-_](\d+))?(?:-EVO)?",
    re.IGNORECASE,
)


def _normalize_version(version: str) -> str:
    return version.strip().rstrip(";")


def _version_sort_key(stem: str) -> tuple:
    """Sort key for schema bundle filenames (newest first)."""
    evo = 1 if stem.upper().endswith("-EVO") else 0
    match = _VERSION_RE.match(stem)
    if not match:
        return (evo, 0, 0, 0, 0, stem)
    major, minor, patch, release, build = match.groups()
    return (
        evo,
        int(major),
        int(minor),
        int(patch or 0),
        float(release or 0),
        int(float(build)) if build else 0,
        stem,
    )


def latest_schema_bundle(
    *,
    platform: Literal["evo", "classic"] | None = "evo",
    directory: Path | None = None,
) -> Path | None:
    bundles = list_schema_bundles(directory)
    if platform == "evo":
        evo = [b for b in bundles if b.stem.upper().endswith("-EVO")]
        if evo:
            return sorted(evo, key=lambda p: _version_sort_key(p.stem), reverse=True)[0]
    elif platform == "classic":
        classic = [b for b in bundles if not b.stem.upper().endswith("-EVO")]
        if classic:
            return sorted(classic, key=lambda p: _version_sort_key(p.stem), reverse=True)[0]
    if not bundles:
        return None
    return sorted(bundles, key=lambda p: _version_sort_key(p.stem), reverse=True)[0]


def find_schema_for_version(
    version: str,
    *,
    directory: Path | None = None,
) -> Path | None:
    version = _normalize_version(version)
    bundles = list_schema_bundles(directory)
    if not bundles:
        return None

    exact = [b for b in bundles if b.stem.lower() == version.lower()]
    if exact:
        return exact[0]

    is_evo = "evo" in version.lower()
    platform_suffix = "-EVO" if is_evo else ""
    base = version.replace("-EVO", "").replace("-evo", "")
    partial = [b for b in bundles if b.stem.lower().startswith(base.lower())]
    if is_evo:
        partial = [b for b in partial if b.stem.upper().endswith("-EVO")]
    else:
        partial = [b for b in partial if not b.stem.upper().endswith("-EVO")]
    if partial:
        return sorted(partial, key=lambda p: _version_sort_key(p.stem), reverse=True)[0]

    return latest_schema_bundle(platform="evo" if is_evo else "classic", directory=directory)


def extract_version_from_config(version_value: str | None) -> str | None:
    if version_value:
        return _normalize_version(version_value)
    return None


def resolve_schema_path(
    schema_arg: str,
    *,
    config_version: str | None = None,
    directory: Path | None = None,
) -> Path:
    root = directory or schema_bundle_dir()
    if schema_arg != "auto":
        candidate = Path(schema_arg)
        if candidate.is_file():
            return candidate
        bundled = root / f"{schema_arg}.json"
        if bundled.is_file():
            return bundled
        raise FileNotFoundError(f"Schema bundle not found: {schema_arg}")

    if config_version:
        found = find_schema_for_version(config_version, directory=root)
        if found:
            return found

    latest = latest_schema_bundle(platform="evo", directory=root)
    if latest:
        return latest
    raise FileNotFoundError("No schema bundles found; run jsmerge schema build or add schemas/*.json")
