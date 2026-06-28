"""Sort engine tests."""

from __future__ import annotations

import random
from pathlib import Path

from conftest import load_fixture, shuffle_reorderable, sort_text
from jsmerge.normalize import denormalize_tree, normalize_tree
from jsmerge.parser import parse_config
from jsmerge.render import render_config
from jsmerge.schema.loader import load_schema_index, resolve_schema_path

SCHEMAS = Path(__file__).parent.parent / "schemas"


def test_interface_ordering():
    text = """
    interfaces {
        xe-0/0/1 { description a; }
        ge-0/0/10 { disable; }
        ge-0/0/0 { description b; }
    }
    """
    out = sort_text(text)
    assert out.index("ge-0/0/0") < out.index("ge-0/0/10")
    assert out.index("ge-0/0/10") < out.index("xe-0/0/1")


def test_policy_term_order_preserved():
    text = """
    policy-options {
        policy-statement TEST {
            term second {
                then accept;
            }
            term first {
                then reject;
            }
        }
    }
    """
    out = sort_text(text)
    assert out.index("term second") < out.index("term first")


def test_policy_statement_alpha_order():
    text = """
    policy-options {
        policy-statement ZEBRA { then accept; }
        policy-statement ALPHA { then accept; }
    }
    """
    out = sort_text(text)
    assert out.index("policy-statement ALPHA") < out.index("policy-statement ZEBRA")


def test_child_statement_order_within_interface():
    text = """
    interfaces {
        ge-0/0/0 {
            unit 0 { family inet { address 1.1.1.1/32; } }
            description "x";
            mtu 9000;
        }
    }
    """
    out = sort_text(text)
    assert out.index("description") < out.index("mtu")
    assert out.index("mtu") < out.index("unit 0")


def test_comments_preserved_through_sort():
    text = load_fixture("sample.conf")
    out = sort_text(text)
    assert "/* JIRA-1234: temporary RE protection */" in out


def test_golden_sample_stable_under_sort():
    text = load_fixture("sample.conf")
    once = sort_text(text)
    twice = sort_text(once)
    assert once == twice


def test_permutation_roundtrip():
    text = load_fixture("sample.conf")
    golden = sort_text(text)
    schema = load_schema_index(SCHEMAS / "24.4R2-EVO.json")
    root = normalize_tree(parse_config(text))
    rng = random.Random(42)
    shuffle_reorderable(root, (), schema, rng)
    shuffled = render_config(denormalize_tree(root))
    assert sort_text(shuffled) == golden


def test_schema_auto_latest_evo():
    resolved = resolve_schema_path("auto", config_version=None, directory=SCHEMAS)
    assert resolved.name.endswith("-EVO.json")
    # Should be the newest EVO bundle present
    evo_bundles = sorted(SCHEMAS.glob("*-EVO.json"), reverse=True)
    assert evo_bundles
    assert resolved == evo_bundles[0]


def test_schema_auto_from_version():
    resolved = resolve_schema_path("auto", config_version="24.4R2-EVO", directory=SCHEMAS)
    assert resolved.name == "24.4R2-EVO.json"


def test_then_terminating_actions_last():
    text = """
    policy-options {
        policy-statement FOO {
            term BAR {
                then {
                    accept;
                    metric 1200;
                    local-preference 150;
                }
            }
        }
    }
    """
    out = sort_text(text)
    assert out.index("metric 1200") < out.index("local-preference 150")
    assert out.index("local-preference 150") < out.index("accept;")


def test_then_block_from_simple_conf_order():
    text = """
    policy-options {
        policy-statement FOO-IN {
            term BLAH {
                from {
                    community BLAH;
                    route-filter 100.1.4.0/24 exact;
                    route-filter 100.3.0.0/16 upto /24;
                }
                then {
                    accept;
                    metric 1200;
                    local-preference 150;
                }
            }
            then reject;
        }
    }
    """
    out = sort_text(text)
    assert out.index("metric 1200") < out.index("local-preference 150")
    assert out.index("local-preference 150") < out.index("accept;")
    assert out.index("term BLAH") < out.index("then reject")


def test_unit_numeric_ordering():
    text = """
    interfaces {
        ge-0/0/0 {
            unit 10 { description "ten"; }
            unit 2 { description "two"; }
        }
    }
    """
    out = sort_text(text)
    assert out.index("unit 2") < out.index("unit 10")
    text = """
    interfaces {
        ge-0/0/0 {
            unit 10 { description "ten"; }
            unit 2 { description "two"; }
        }
    }
    """
    out = sort_text(text)
    assert out.index("unit 2") < out.index("unit 10")
