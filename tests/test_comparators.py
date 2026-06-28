"""Comparator unit tests."""

from jsmerge.sort.comparators import compare_interface, compare_numeric


def test_compare_interface_type_then_slot():
    assert compare_interface("ge-0/0/0", "xe-0/0/0") < 0
    assert compare_interface("ge-0/0/2", "ge-0/0/10") < 0


def test_compare_numeric_units():
    assert compare_numeric("2", "10") < 0
