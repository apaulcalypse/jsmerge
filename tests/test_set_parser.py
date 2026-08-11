"""Tests for Junos set-format parsing and rendering."""

from pathlib import Path

import jsmerge.parser.set_parser as set_parser
from jsmerge.normalize import normalize_tree
from jsmerge.parser.set_parser import parse_set_config, peek_set_version
from jsmerge.render.renderer import render_config
from jsmerge.render.set_renderer import render_set
from jsmerge.schema.loader import load_schema_index

SCHEMAS = Path(__file__).parent.parent / "schemas"


def _shipped_schema():
    path = SCHEMAS / "25.4R1-EVO.json"
    if not path.is_file():
        bundles = sorted(SCHEMAS.glob("*.json"))
        assert bundles, "No schema bundles in schemas/"
        path = bundles[0]
    return load_schema_index(path)


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


def test_peek_set_version():
    text = """
set system host-name x
set version 25.4R1-EVO;
set protocols isis
"""
    assert peek_set_version(text) == "25.4R1-EVO"


def test_schema_isis_level_and_auth_leaves_without_allowlists(monkeypatch):
    """Schema must classify level/auth — not the fallback frozensets."""
    monkeypatch.setattr(
        set_parser,
        "LIST_KEYED_STATEMENTS",
        frozenset(x for x in set_parser.LIST_KEYED_STATEMENTS if x != "level"),
    )
    monkeypatch.setattr(
        set_parser,
        "VALUE_LEAVES",
        frozenset(
            x
            for x in set_parser.VALUE_LEAVES
            if x
            not in {
                "metric",
                "hello-authentication-key",
                "hello-authentication-type",
            }
        ),
    )

    schema = _shipped_schema()
    text = """
set protocols isis interface ae26.0 level 2 metric 1
set protocols isis interface ae26.0 level 2 hello-authentication-key TODOADDVAULTPATH
set protocols isis interface ae26.0 level 2 hello-authentication-type md5
set protocols isis interface ae26.0 point-to-point
"""
    root = parse_set_config(text, schema=schema)
    iface = root.children[0].children[0].children[0]
    assert iface.name == "interface" and iface.raw_tail == ["ae26.0"]

    level = next(c for c in iface.children if c.name == "level")
    assert level.raw_tail == ["2"]
    assert not any(c.name == "2" for c in level.children)

    by_name = {c.name: c for c in level.children}
    assert by_name["metric"].raw_tail == ["1"]
    assert by_name["hello-authentication-key"].raw_tail == ["TODOADDVAULTPATH"]
    assert by_name["hello-authentication-type"].raw_tail == ["md5"]

    rendered = render_config(root)
    assert "level 2 {" in rendered
    assert "level {" not in rendered
    assert "hello-authentication-key TODOADDVAULTPATH;" in rendered
    assert "hello-authentication-type md5;" in rendered
    assert "point-to-point;" in rendered


def test_schema_isis_unit_nesting_still_list_keys_level(monkeypatch):
    """Off-schema 'unit' under isis must not break schema list-key for level."""
    monkeypatch.setattr(
        set_parser,
        "LIST_KEYED_STATEMENTS",
        frozenset(x for x in set_parser.LIST_KEYED_STATEMENTS if x != "level"),
    )
    monkeypatch.setattr(
        set_parser,
        "VALUE_LEAVES",
        frozenset(x for x in set_parser.VALUE_LEAVES if x != "metric"),
    )

    schema = _shipped_schema()
    text = """
set protocols isis interface ae26 unit 0 level 2 metric 1
set protocols isis interface ae26 unit 0 level 2 hello-authentication-key TODOADDVAULTPATH
set protocols isis interface ae26 unit 0 point-to-point
"""
    root = parse_set_config(text, schema=schema)
    rendered = render_config(root)
    assert "level 2 {" in rendered
    assert "level {" not in rendered
    assert "hello-authentication-key TODOADDVAULTPATH;" in rendered
    assert "metric 1;" in rendered


def test_schema_family_inet_cli_keyed(monkeypatch):
    """family inet must use CLI_KEYED_CONTAINERS + schema, not LIST_KEYED fallback."""
    monkeypatch.setattr(
        set_parser,
        "LIST_KEYED_STATEMENTS",
        frozenset(x for x in set_parser.LIST_KEYED_STATEMENTS if x != "family"),
    )
    schema = _shipped_schema()
    # Explicit list keyword so schema path stays on interfaces/interface/unit
    text = "set interfaces interface ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n"
    root = parse_set_config(text, schema=schema)
    iface = root.children[0].children[0]
    assert iface.name == "interface" and iface.raw_tail == ["ge-0/0/0"]
    unit = next(c for c in iface.children if c.name == "unit")
    family = next(c for c in unit.children if c.name == "family")
    assert family.raw_tail == ["inet"]
    assert not any(c.name == "inet" for c in family.children)
    assert family.children[0].name == "address"
    assert family.children[0].raw_tail == ["10.0.0.1/24"]
    assert "family inet {" in render_config(root)
