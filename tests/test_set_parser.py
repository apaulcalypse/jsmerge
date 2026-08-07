"""Tests for Junos set-format parsing and rendering."""

from jsmerge.normalize import normalize_tree
from jsmerge.parser.set_parser import parse_set_config
from jsmerge.render.set_renderer import render_set


def test_sibling_protocols_bgp_and_ospf():
    text = """
set protocols bgp
set protocols ospf area 0
"""
    root = parse_set_config(text)
    protocols = root.children[0]
    assert protocols.name == "protocols"
    names = {c.name for c in protocols.children}
    assert names == {"bgp", "ospf"}

    bgp = next(c for c in protocols.children if c.name == "bgp")
    assert bgp.raw_tail is None
    assert bgp.children == []

    ospf = next(c for c in protocols.children if c.name == "ospf")
    area = ospf.children[0]
    assert area.name == "area"
    assert area.raw_tail == ["0"]


def test_unit_0_and_unit_1_are_distinct():
    text = """
set interfaces ge-0/0/0 unit 0 family inet
set interfaces ge-0/0/0 unit 1 family inet
"""
    root = parse_set_config(text)
    iface = root.children[0].children[0]
    assert iface.name == "ge-0/0/0"
    units = iface.children
    assert len(units) == 2
    assert units[0].name == "unit" and units[0].raw_tail == ["0"]
    assert units[1].name == "unit" and units[1].raw_tail == ["1"]


def test_disable_is_presence_child():
    text = "set interfaces ge-0/0/0 disable\n"
    root = parse_set_config(text)
    iface = root.children[0].children[0]
    assert iface.name == "ge-0/0/0"
    assert iface.raw_tail is None
    disable = iface.children[0]
    assert disable.name == "disable"
    assert disable.raw_tail is None
    assert disable.children == []


def test_host_name_value_leaf():
    text = "set system host-name router1\n"
    root = parse_set_config(text)
    host = root.children[0].children[0]
    assert host.name == "host-name"
    assert host.raw_tail == ["router1"]
    assert host.children == []


def test_inactive_leaf_value_round_trip():
    text = """
set system host-name router1
deactivate system host-name
"""
    root = parse_set_config(text)
    host = root.children[0].children[0]
    assert host.name == "host-name"
    assert host.raw_tail == ["router1"]
    assert "inactive" in host.flags

    rendered = render_set(root)
    assert "set system host-name router1" in rendered
    assert "deactivate system host-name" in rendered


def test_normalize_applies_to_set_interfaces():
    text = """
set interfaces ge-0/0/0 unit 0 family inet
set interfaces ge-0/0/0 disable
"""
    root = normalize_tree(parse_set_config(text))
    iface = root.children[0].children[0]
    assert iface.name == "interface"
    assert iface.raw_tail == ["ge-0/0/0"]
    names = {c.name for c in iface.children}
    assert "unit" in names
    assert "disable" in names
