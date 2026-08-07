"""Filter path matching and comment-stripping tests."""

from __future__ import annotations

from jsmerge.filter import filter_config, strip_comments
from jsmerge.models import ConfigNode
from jsmerge.normalize import normalize_tree
from jsmerge.parser import parse_config


def test_filter_interface_by_key_after_normalize():
    text = """
interfaces {
    ge-0/0/0 {
        description "Access";
    }
    xe-0/0/1 {
        description "Uplink";
    }
}
"""
    root = normalize_tree(parse_config(text))
    result = filter_config(root, ["interfaces ge-0/0/0"])

    assert len(result.children) == 1
    interfaces = result.children[0]
    assert interfaces.name == "interfaces"
    assert len(interfaces.children) == 1
    iface = interfaces.children[0]
    assert iface.name == "interface"
    assert iface.raw_tail == ["ge-0/0/0"]
    assert iface.children[0].name == "description"


def test_multi_filter_coalesces_shared_parent():
    text = """
protocols {
    bgp {
        group INTERNAL {
            type internal;
        }
    }
    ospf {
        area 0.0.0.0 {
            interface ge-0/0/0.0;
        }
    }
    isis {
        interface all;
    }
}
"""
    root = normalize_tree(parse_config(text))
    result = filter_config(root, ["protocols bgp", "protocols ospf"])

    assert len(result.children) == 1
    protocols = result.children[0]
    assert protocols.name == "protocols"
    names = [c.name for c in protocols.children]
    assert names == ["bgp", "ospf"]


def test_strip_comments_removes_nested():
    root = ConfigNode(
        name="configuration",
        comments=["top"],
        children=[
            ConfigNode(
                name="firewall",
                comments=["mid"],
                children=[
                    ConfigNode(
                        name="filter",
                        raw_tail=["PROTECT"],
                        comments=["leaf"],
                    )
                ],
            )
        ],
    )
    stripped = strip_comments(root)
    assert stripped.comments == []
    assert stripped.children[0].comments == []
    assert stripped.children[0].children[0].comments == []
    # Original unchanged
    assert root.comments == ["top"]
