"""Builder tests (slow integration test uses cached YANG)."""

from pathlib import Path

import pytest

from jsmerge.schema.builder import build_schema_index
from jsmerge.schema.yang_fetch import yang_cache_dir


@pytest.mark.slow
def test_build_schema_from_cached_yang():
    cache = yang_cache_dir("25.4R1-EVO")
    modules = cache / "modules"
    if not modules.is_dir() or not any(modules.glob("junos-conf-root@*.yang")):
        pytest.skip("YANG cache not populated; run jsmerge schema build first")

    payload = build_schema_index(
        modules,
        version="25.4R1-EVO",
        platform="evo",
    )
    nodes = payload["nodes"]
    assert len(nodes) > 100
    assert "interfaces" in nodes
    assert "policy-options" in nodes
    assert "firewall" in nodes
    assert nodes["policy-options/policy-statement"]["lists"]["term"]["ordered_by"] == "user"
    assert nodes["interfaces"]["lists"]["interface"]["comparator"] == "interface"
    assert nodes["interfaces/interface"]["lists"]["unit"]["comparator"] == "numeric"
