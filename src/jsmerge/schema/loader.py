"""Schema index models and loading."""

from __future__ import annotations

import json
import logging
import pickle
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

SchemaPath = str
CACHE_SUFFIX = ".cache"


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
        if isinstance(path, tuple):
            path = "/".join(path)
        return self.nodes.get(path)

    @staticmethod
    def path_to_str(path: SchemaPath) -> str:
        if isinstance(path, tuple):
            return "/".join(path)
        return path

    @staticmethod
    def str_to_path(text: str) -> SchemaPath:
        return text


def join_schema_path(parent: SchemaPath, *segments: str) -> SchemaPath:
    """Join schema path segments using Juniper's slash notation."""
    if isinstance(parent, tuple):
        parent = "/".join(parent)
    parts = [parent, *segments] if parent else list(segments)
    return "/".join(part for part in parts if part)


def _parse_list_rule(data: dict) -> ListRule:
    return ListRule(
        ordered_by=data["ordered_by"],
        keys=list(data["keys"]),
        comparator=data.get("comparator", "default"),
    )


def _parse_node_rule(data: dict) -> NodeRule:
    lists = {name: _parse_list_rule(rule) for name, rule in data.get("lists", {}).items()}
    return NodeRule(child_order=list(data.get("child_order", [])), lists=lists)


def _load_json(path: Path) -> dict:
    raw = path.read_bytes()
    try:
        import orjson

        return orjson.loads(raw)
    except ImportError:
        return json.loads(raw.decode("utf-8"))


def _parse_schema_payload(payload: dict) -> SchemaIndex:
    nodes = {path_str: _parse_node_rule(rule_data) for path_str, rule_data in payload["nodes"].items()}
    return SchemaIndex(
        version=payload["version"],
        platform=payload["platform"],
        nodes=nodes,
    )


def _parse_schema_json(path: Path) -> SchemaIndex:
    return _parse_schema_payload(_load_json(path))


def schema_cache_path(json_path: Path) -> Path:
    return json_path.with_name(json_path.name + CACHE_SUFFIX)


def write_schema_cache(index: SchemaIndex, json_path: Path) -> Path:
    """Write a pickle cache for faster subsequent loads."""
    cache_path = schema_cache_path(json_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as handle:
        pickle.dump(index, handle, protocol=pickle.HIGHEST_PROTOCOL)
    return cache_path


@lru_cache(maxsize=8)
def _load_schema_cached(resolved: str, mtime_ns: int) -> SchemaIndex:
    path = Path(resolved)
    cache_path = schema_cache_path(path)

    if cache_path.is_file() and cache_path.stat().st_mtime_ns >= mtime_ns:
        try:
            with cache_path.open("rb") as handle:
                index = pickle.load(handle)
            logger.debug("Loaded schema cache %s", cache_path)
            return index
        except (OSError, pickle.UnpicklingError) as exc:
            logger.debug("Schema cache unreadable (%s); rebuilding from JSON", exc)

    index = _parse_schema_json(path)
    try:
        write_schema_cache(index, path)
        logger.debug("Wrote schema cache %s", cache_path)
    except OSError as exc:
        logger.debug("Could not write schema cache: %s", exc)
    return index

def load_schema_index(path: Path) -> SchemaIndex:
    resolved = path.resolve()
    mtime_ns = resolved.stat().st_mtime_ns
    return _load_schema_cached(str(resolved), mtime_ns)


def release_schema_memory_cache() -> None:
    """Drop in-memory schema indexes to avoid slow process teardown."""
    _load_schema_cached.cache_clear()


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
