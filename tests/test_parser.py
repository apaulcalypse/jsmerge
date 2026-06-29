"""Parser tests."""

from jsmerge.parser import parse_config


def test_parse_interfaces_and_comments():
    text = """
    interfaces {
        ge-0/0/0 {
            /* JIRA-99 */
            description "test";
        }
    }
    """
    root = parse_config(text)
    iface = root.children[0]
    assert iface.name == "interfaces"
    ge = iface.children[0]
    assert ge.name == "ge-0/0/0"
    assert ge.children[0].comments == ["JIRA-99"]
    assert ge.children[0].name == "description"
    assert ge.children[0].value == '"test"'


def test_parse_inactive():
    text = """
    policy-options {
        inactive: policy-statement FOO {
            then accept;
        }
    }
    """
    root = parse_config(text)
    stmt = root.children[0].children[0]
    assert "inactive" in stmt.flags
    assert stmt.name == "policy-statement"
    assert stmt.value == "FOO"


def test_parse_route_filter_multi_token_value():
    text = """
    policy-options {
        policy-statement FOO {
            term BAR {
                from {
                    route-filter 100.1.4.0/24 exact;
                }
            }
        }
    }
    """
    root = parse_config(text)
    rf = (
        root.children[0]
        .children[0]
        .children[0]
        .children[0]
        .children[0]
    )
    assert rf.name == "route-filter"
    assert rf.value == "100.1.4.0/24 exact"


def test_parse_route_filter_upto_prefix_length():
    text = """
    policy-options {
        policy-statement FOO {
            term BAR {
                from {
                    route-filter 100.3.0.0/16 upto /24;
                }
            }
        }
    }
    """
    root = parse_config(text)
    rf = (
        root.children[0]
        .children[0]
        .children[0]
        .children[0]
        .children[0]
    )
    assert rf.name == "route-filter"
    assert rf.value == "100.3.0.0/16 upto /24"


def test_parse_ether_options_802_3ad():
    text = """
    interfaces {
        et-0/0/0 {
            ether-options {
                802.3ad ae10;
            }
        }
    }
    """
    root = parse_config(text)
    stmt = root.children[0].children[0].children[0].children[0]
    assert stmt.name == "802.3ad"
    assert stmt.value == "ae10"


def test_parse_version():
    root = parse_config("version 24.4R2-EVO;")
    assert root.children[0].name == "version"
    assert root.children[0].value == "24.4R2-EVO"
