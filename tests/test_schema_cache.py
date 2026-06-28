"""Schema load caching tests."""

from __future__ import annotations

import pickle
from pathlib import Path

from jsmerge.schema.loader import _load_schema_cached, load_schema_index, schema_cache_path

SCHEMAS = Path(__file__).parent.parent / "schemas"


def test_schema_disk_cache_roundtrip():
    json_path = SCHEMAS / "24.4R2-EVO.json"
    cache_path = schema_cache_path(json_path)
    if cache_path.exists():
        cache_path.unlink()

    _load_schema_cached.cache_clear()
    index = load_schema_index(json_path)
    assert cache_path.is_file()

    _load_schema_cached.cache_clear()
    cached = load_schema_index(json_path)
    assert cached.version == index.version
    assert cached.nodes == index.nodes


def test_schema_cache_invalidated_when_json_newer(tmp_path: Path):
    json_path = tmp_path / "test.json"
    json_path.write_text(
        '{"version":"1","platform":"evo","nodes":{"":{"child_order":[],"lists":{}}}}',
        encoding="utf-8",
    )
    cache_path = schema_cache_path(json_path)
    stale = pickle.dumps("stale")
    cache_path.write_bytes(stale)

    # Make JSON newer than cache
    import time

    time.sleep(0.01)
    json_path.write_text(
        '{"version":"2","platform":"evo","nodes":{"":{"child_order":[],"lists":{}}}}',
        encoding="utf-8",
    )

    _load_schema_cached.cache_clear()
    index = load_schema_index(json_path)
    assert index.version == "2"
