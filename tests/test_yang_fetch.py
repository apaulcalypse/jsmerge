"""Tests for Juniper YANG GitHub fetch helpers."""

import pytest

from jsmerge.schema.yang_fetch import github_url_for_version, parse_junos_version


@pytest.mark.parametrize(
    ("version", "platform", "github_conf_root"),
    [
        ("25.4R1-EVO", "evo", "25.4/25.4R1-EVO/native/conf-and-rpcs"),
        ("25.4R1", "classic", "25.4/25.4R1/native/conf-and-rpcs"),
        ("24.4R2-EVO", "evo", "24.4/24.4R2-EVO/native/conf-and-rpcs"),
    ],
)
def test_parse_junos_version(version, platform, github_conf_root):
    release = parse_junos_version(version)
    assert release.version == version
    assert release.platform == platform
    assert release.github_conf_root == github_conf_root


def test_github_url_for_version():
    url = github_url_for_version("25.4R1-EVO")
    assert url == "https://github.com/Juniper/yang/tree/master/25.4"


def test_parse_invalid_version():
    with pytest.raises(ValueError):
        parse_junos_version("not-a-version")
