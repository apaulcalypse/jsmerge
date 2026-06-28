"""Renderer tests."""

from jsmerge.parser import parse_config
from jsmerge.render import render_config


def test_render_inactive_and_comments():
    text = """
    firewall {
        family inet {
            filter F {
                /* note */
                term t { then accept; }
            }
        }
    }
    """
    root = parse_config(text)
    out = render_config(root)
    assert "/* note */" in out
    assert "term t" in out
