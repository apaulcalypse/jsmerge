"""Schema load tests (JSON + in-memory LRU; no disk pickle cache)."""

from __future__ import annotations

from pathlib import Path

from jsmerge.schema.loader import _load_schema_cached, load_schema_index

SCHEMAS = Path(__file__).parent.parent / "schemas"


def test_schema_json_load():
    json_path = SCHEMAS / "24.4R2-EVO.json"
    _load_schema_cached.cache_clear()
    index = load_schema_index(json_path)
    assert index.version
    assert index.platform in ("evo", "classic")
    assert index.nodes


def test_schema_memory_cache_reuses_same_mtime(tmp_path: Path):
    json_path = tmp_path / "test.json"
    json_path.write_text(
        '{"version":"1","platform":"evo","nodes":{"":{"child_order":[],"lists":{}}}}',
        encoding="utf-8",
    )

    _load_schema_cached.cache_clear()
    first = load_schema_index(json_path)
    second = load_schema_index(json_path)
    assert first is second
    assert first.version == "1"


def test_schema_reloads_when_json_mtime_changes(tmp_path: Path):
    json_path = tmp_path / "test.json"
    json_path.write_text(
        '{"version":"1","platform":"evo","nodes":{"":{"child_order":[],"lists":{}}}}',
        encoding="utf-8",
    )

    _load_schema_cached.cache_clear()
    first = load_schema_index(json_path)
    assert first.version == "1"

    import time

    time.sleep(0.01)
    json_path.write_text(
        '{"version":"2","platform":"evo","nodes":{"":{"child_order":[],"lists":{}}}}',
        encoding="utf-8",
    )

    second = load_schema_index(json_path)
    assert second.version == "2"
