"""MergeEngine and reverse_merge tests."""

from __future__ import annotations

from jsmerge.merge import MergeEngine, reverse_merge
from jsmerge.models import ConfigNode


def _leaf(name: str, *tail: str, flags: set[str] | None = None, comments: list[str] | None = None) -> ConfigNode:
    return ConfigNode(
        name=name,
        raw_tail=list(tail) if tail else None,
        flags=set(flags or ()),
        comments=list(comments or ()),
    )


def _container(name: str, *children: ConfigNode, flags: set[str] | None = None, comments: list[str] | None = None) -> ConfigNode:
    return ConfigNode(
        name=name,
        flags=set(flags or ()),
        comments=list(comments or ()),
        children=list(children),
    )


def test_overlay_leaf_value_wins():
    base = _container("configuration", _leaf("description", "old"))
    overlay = _container("configuration", _leaf("description", "new"))
    merged = MergeEngine().merge([base, overlay])
    desc = merged.children[0]
    assert desc.value == "new"


def test_replace_clears_previous_children():
    target = _container(
        "interfaces",
        _container("ge-0/0/0", _leaf("description", "keep-me"), _leaf("mtu", "1500")),
    )
    source = _container(
        "interfaces",
        _container(
            "ge-0/0/0",
            _leaf("description", "replaced"),
            flags={"replace"},
        ),
    )
    engine = MergeEngine()
    engine.deep_merge(target, source)
    iface = target.children[0]
    assert "replace" in iface.flags
    assert [c.name for c in iface.children] == ["description"]
    assert iface.children[0].value == "replaced"
    assert not any(c.name == "mtu" for c in iface.children)


def test_leaf_over_container_clears_children():
    target = _container("system", _container("host-name", _leaf("nested", "x")))
    # Make target.host-name look like a container with children; overlay a leaf
    host = target.children[0]
    assert not host.is_leaf()
    source = _container("system", _leaf("host-name", "router1"))
    MergeEngine().deep_merge(target, source)
    host = target.children[0]
    assert host.is_leaf()
    assert host.value == "router1"
    assert host.children == []


def test_reverse_merge_identical_inactive_trees_minimal_delta():
    base = _container(
        "configuration",
        _container("protocols", _container("bgp", flags={"inactive"})),
    )
    live = base.clone()
    delta = reverse_merge(base, live)
    assert delta.children == []
    assert delta.flags == set()
    assert delta.comments == []


def test_reverse_merge_value_change_emits_delta():
    base = _container("configuration", _leaf("description", "a"))
    live = _container("configuration", _leaf("description", "b"))
    delta = reverse_merge(base, live)
    assert len(delta.children) == 1
    assert delta.children[0].name == "description"
    assert delta.children[0].value == "b"


def test_reverse_merge_include_comments_false_strips_nested():
    base = _container("configuration", _container("system"))
    live = _container(
        "configuration",
        _container(
            "system",
            _leaf("host-name", "r1", comments=["# leaf comment"]),
            comments=["# system comment"],
        ),
        comments=["# root comment"],
    )
    delta = reverse_merge(base, live, include_comments=False)

    def _all_comments(n: ConfigNode) -> list[str]:
        found = list(n.comments)
        for c in n.children:
            found.extend(_all_comments(c))
        return found

    assert _all_comments(delta) == []
    # structural override still present
    assert delta.children[0].name == "system"
    assert delta.children[0].children[0].value == "r1"


def test_report_conflicts_smoke():
    base = _container("configuration", _leaf("description", "old"))
    overlay = _container("configuration", _leaf("description", "new"))
    engine = MergeEngine(report_conflicts=True)
    engine.merge([base, overlay])
    assert engine.conflicts
    assert any("description" in c for c in engine.conflicts)
