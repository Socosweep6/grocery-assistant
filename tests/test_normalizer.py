"""Tests for normalizer: parsing, canonical mapping, categorization, ambiguity."""

import pytest
from grocery_assistant.normalizer import parse_message, normalize_item_name


# ---------------------------------------------------------------------------
# Single item parsing
# ---------------------------------------------------------------------------

def test_single_item_basic():
    items = parse_message("bananas")
    assert len(items) == 1
    assert items[0].canonical == "bananas"


def test_single_item_with_quantity():
    items = parse_message("ground turkey 2 lb")
    assert len(items) == 1
    assert items[0].canonical == "turkey ground"
    assert items[0].quantity == "2"
    assert items[0].unit == "lb"


def test_leading_quantity():
    items = parse_message("2 lb ground beef")
    assert len(items) == 1
    assert items[0].quantity == "2"
    assert items[0].unit == "lb"
    assert items[0].canonical == "beef ground"


def test_strip_dont_forget_prefix():
    items = parse_message("don't forget dish soap")
    assert len(items) == 1
    assert items[0].canonical == "dish soap"


def test_strip_we_need_prefix():
    items = parse_message("we need eggs")
    assert len(items) == 1
    assert items[0].canonical == "eggs"


def test_strip_out_of_prefix():
    items = parse_message("we're out of paper towels")
    assert len(items) == 1
    assert items[0].canonical == "paper towels"


# ---------------------------------------------------------------------------
# Multi-item parsing
# ---------------------------------------------------------------------------

def test_comma_separated():
    items = parse_message("bananas, eggs, oat milk")
    canonicals = [i.canonical for i in items]
    assert "bananas" in canonicals
    assert "eggs" in canonicals
    assert "milk oat" in canonicals


def test_and_separated_list():
    items = parse_message("bread and eggs and bananas")
    canonicals = [i.canonical for i in items]
    assert "bananas" in canonicals
    assert "eggs" in canonicals


def test_compound_not_split():
    # "mac and cheese" should stay together
    items = parse_message("mac and cheese")
    assert len(items) == 1


def test_newline_separated():
    items = parse_message("eggs\nmilk 2%\nbananas")
    assert len(items) == 3


def test_mixed_separators():
    items = parse_message("eggs, bread\noat milk")
    assert len(items) == 3


# ---------------------------------------------------------------------------
# Canonical mapping
# ---------------------------------------------------------------------------

def test_canonical_2pct_milk():
    items = parse_message("2% milk")
    assert items[0].canonical == "milk 2%"


def test_canonical_oat_milk():
    assert normalize_item_name("oat milk") == "milk oat"


def test_canonical_tp():
    assert normalize_item_name("tp") == "toilet paper"


def test_canonical_oj():
    assert normalize_item_name("OJ") == "orange juice"


def test_canonical_egg_singular():
    items = parse_message("egg")
    assert items[0].canonical == "eggs"


def test_canonical_banana_singular():
    items = parse_message("banana")
    assert items[0].canonical == "bananas"


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

def test_category_produce():
    items = parse_message("bananas")
    assert items[0].category == "produce"


def test_category_protein():
    items = parse_message("ground turkey 2 lb")
    assert items[0].category == "protein"


def test_category_dairy():
    items = parse_message("2% milk")
    assert items[0].category == "dairy"


def test_category_household():
    items = parse_message("dish soap")
    assert items[0].category == "household"


def test_category_household_paper_towels():
    items = parse_message("paper towels")
    assert items[0].category == "household"


def test_category_pantry():
    items = parse_message("pasta")
    assert items[0].category == "pantry"


# ---------------------------------------------------------------------------
# Ambiguity flagging
# ---------------------------------------------------------------------------

def test_ambiguous_bare_milk():
    items = parse_message("milk")
    assert items[0].ambiguous is True
    assert "type" in items[0].ambiguity_reason.lower()


def test_ambiguous_bare_bread():
    items = parse_message("bread")
    assert items[0].ambiguous is True


def test_not_ambiguous_oat_milk():
    items = parse_message("oat milk")
    assert items[0].ambiguous is False


def test_ambiguous_chips():
    items = parse_message("chips")
    assert items[0].ambiguous is True


def test_not_ambiguous_eggs():
    items = parse_message("eggs")
    assert items[0].ambiguous is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string():
    assert parse_message("") == []


def test_whitespace_only():
    assert parse_message("   ") == []


def test_notes_extraction():
    items = parse_message("chicken breast (boneless)")
    assert len(items) == 1
    assert items[0].notes == "boneless"
