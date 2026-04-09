"""
Item text normalization, parsing, categorization, and ambiguity flagging.

Design intent:
- Split multi-item messages
- Normalize name variants (2% milk -> milk 2%, etc.)
- Categorize by keyword
- Flag ambiguous items; never silently guess
"""

import re
from typing import Optional
from .models import ParsedItem

# ---------------------------------------------------------------------------
# Canonical name mappings (common variants -> canonical form)
# ---------------------------------------------------------------------------
CANONICAL_MAP: dict[str, str] = {
    "2% milk": "milk 2%",
    "whole milk": "milk whole",
    "skim milk": "milk skim",
    "oat milk": "milk oat",
    "almond milk": "milk almond",
    "soy milk": "milk soy",
    "ground beef": "beef ground",
    "ground turkey": "turkey ground",
    "ground chicken": "chicken ground",
    "chicken breast": "chicken breast",
    "paper towel": "paper towels",
    "paper towels": "paper towels",
    "dish soap": "dish soap",
    "dish detergent": "dish soap",
    "laundry detergent": "laundry detergent",
    "tp": "toilet paper",
    "toilet paper": "toilet paper",
    "toilet tissue": "toilet paper",
    "eggs": "eggs",
    "egg": "eggs",
    "bananas": "bananas",
    "banana": "bananas",
    "apples": "apples",
    "apple": "apples",
    "bread": "bread",
    "white bread": "bread white",
    "sourdough": "bread sourdough",
    "sourdough bread": "bread sourdough",
    "wheat bread": "bread wheat",
    "whole wheat bread": "bread whole wheat",
    "orange juice": "orange juice",
    "oj": "orange juice",
}

# ---------------------------------------------------------------------------
# Category keyword rules (first match wins)
# ---------------------------------------------------------------------------
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("produce",    ["banana", "apple", "orange", "grape", "strawberr", "blueberr",
                    "lettuce", "spinach", "tomato", "carrot", "celery", "onion",
                    "garlic", "pepper", "cucumber", "broccoli", "avocado", "lemon",
                    "lime", "berry", "kale", "zucchini", "squash", "mushroom"]),
    ("protein",    ["chicken", "beef", "turkey", "pork", "salmon", "tuna", "shrimp",
                    "fish", "steak", "ground", "sausage", "bacon", "ham", "lamb",
                    "tofu", "tempeh", "eggs", "egg"]),
    ("dairy",      ["milk", "cheese", "yogurt", "butter", "cream", "sour cream",
                    "cream cheese", "cottage cheese", "half and half", "kefir"]),
    ("frozen",     ["frozen", "ice cream", "pizza", "waffles", "edamame",
                    "peas", "corn", "veggie burger"]),
    ("pantry",     ["bread", "pasta", "rice", "flour", "sugar", "salt", "oil",
                    "vinegar", "sauce", "soup", "can", "bean", "lentil", "cereal",
                    "oat", "coffee", "tea", "juice", "cracker", "chip", "nut",
                    "peanut butter", "jam", "honey", "syrup", "spice", "seasoning",
                    "tortilla", "wrap", "noodle", "broth", "stock"]),
    ("household",  ["paper towel", "toilet paper", "dish soap", "laundry",
                    "trash bag", "garbage bag", "sponge", "cleaner", "bleach",
                    "detergent", "dryer sheet", "foil", "plastic wrap",
                    "zip lock", "ziploc", "bag"]),
]

# ---------------------------------------------------------------------------
# Items that are inherently ambiguous without more detail
# ---------------------------------------------------------------------------
AMBIGUITY_RULES: list[tuple[str, str]] = [
    (r"^milk$",          "missing type (whole, 2%, oat, etc.)"),
    (r"^bread$",         "missing type (white, wheat, sourdough, etc.)"),
    (r"^chips$",         "missing brand or flavor"),
    (r"^soda$",          "missing type or brand"),
    (r"^juice$",         "missing type"),
    (r"^cheese$",        "missing type (cheddar, mozzarella, etc.)"),
    (r"^yogurt$",        "missing type or brand"),
    (r"^cookies$",       "missing type or brand"),
    (r"^crackers$",      "missing type or brand"),
    (r"^cereal$",        "missing type or brand"),
    (r"^pasta$",         "missing shape or brand"),
    (r"^sauce$",         "missing type (pasta, hot, etc.)"),
    (r"^nuts$",          "missing type"),
    (r"^dressing$",      "missing type or brand"),
    (r"^meat$",          "missing type"),
    (r"^fish$",          "missing type"),
]

# Phrases that should be stripped from raw text before parsing items
STRIP_PHRASES = [
    r"^don['\u2019]?t forget\s+",
    r"^please\s+get\s+",
    r"^can you get\s+",
    r"^we need\s+",
    r"^we['\u2019]?re out of\s+",
    r"^out of\s+",
    r"^need\s+",
    r"^get\s+",
    r"^also\s+",
    r"^and\s+",
    r"^\s*-\s*",
]


def _strip_prefix(text: str) -> str:
    for pattern in STRIP_PHRASES:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
    return text


def _split_items(raw_text: str) -> list[str]:
    """Split a message into individual item strings."""
    # Normalize whitespace
    text = raw_text.strip()

    # Split on commas, semicolons, or newlines
    parts = re.split(r"[,;\n]+", text)

    # Secondary split: "X and Y" but not "mac and cheese" or "salt and pepper"
    expanded: list[str] = []
    compound_pairs = {
        ("mac", "cheese"), ("salt", "pepper"), ("bread", "butter"),
        ("peanut", "butter"), ("oil", "vinegar"),
    }
    for part in parts:
        # Check for " and " that looks like a list separator (not compound)
        and_parts = re.split(r"\s+and\s+", part, flags=re.IGNORECASE)
        if len(and_parts) > 1:
            # Simple heuristic: if any adjacent pair is a known compound, keep together
            is_compound = False
            if len(and_parts) == 2:
                left = and_parts[0].strip().lower().split()[-1] if and_parts[0].strip() else ""
                right = and_parts[1].strip().lower().split()[0] if and_parts[1].strip() else ""
                if (left, right) in compound_pairs:
                    is_compound = True
            if not is_compound:
                expanded.extend(and_parts)
            else:
                expanded.append(part)
        else:
            expanded.append(part)

    cleaned = []
    for p in expanded:
        p = _strip_prefix(p.strip())
        if p:
            cleaned.append(p)
    return cleaned


def _extract_quantity(text: str) -> tuple[Optional[str], Optional[str], str]:
    """
    Extract quantity and unit from text, checking leading then trailing positions.
    Returns (quantity, unit, remainder).

    Examples:
      "2 lb ground turkey"   -> ("2", "lb", "ground turkey")
      "ground turkey 2 lb"   -> ("2", "lb", "ground turkey")
      "2 eggs"               -> ("2", None, "eggs")
      "2% milk"              -> (None, None, "2% milk")   [% not a unit]
    """
    unit_words = r"(lb|lbs|pound|pounds|oz|ounce|ounces|kg|g|grams|pack|packs|bag|bags|box|boxes|jar|jars|can|cans|bottle|bottles|gallon|gallons|qt|quart|quarts|dozen|count|ct|piece|pieces|slice|slices)s?"

    # Leading: "2 lb ground turkey"
    leading_with_unit = rf"^(\d+(?:\.\d+)?(?:/\d+)?)\s*{unit_words}\s+"
    m = re.match(leading_with_unit, text, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).lower().rstrip("s"), text[m.end():].strip()

    # Trailing: "ground turkey 2 lb"
    trailing_with_unit = rf"\s+(\d+(?:\.\d+)?(?:/\d+)?)\s*{unit_words}$"
    m = re.search(trailing_with_unit, text, re.IGNORECASE)
    if m:
        remainder = text[:m.start()].strip()
        if remainder:
            return m.group(1), m.group(2).lower().rstrip("s"), remainder

    # Leading number only, NOT followed by % (e.g. "2 eggs" but not "2% milk")
    leading_num = r"^(\d+(?:\.\d+)?(?:/\d+)?)(?!%)\s+"
    m = re.match(leading_num, text)
    if m:
        remainder = text[m.end():].strip()
        if remainder:
            return m.group(1), None, remainder

    return None, None, text


def _extract_notes(text: str) -> tuple[str, Optional[str]]:
    """Extract parenthetical or dash-separated notes from item text."""
    m = re.search(r"\s*[\(\[](.*?)[\)\]]\s*$", text)
    if m:
        note = m.group(1).strip()
        remainder = text[:m.start()].strip()
        return remainder, note

    m = re.search(r"\s+-\s+(.+)$", text)
    if m:
        note = m.group(1).strip()
        remainder = text[:m.start()].strip()
        return remainder, note

    return text, None


def _categorize(canonical: str) -> str:
    lower = canonical.lower()
    for category, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw in lower:
                return category
    return "other"


def _check_ambiguity(canonical: str) -> tuple[bool, Optional[str]]:
    for pattern, reason in AMBIGUITY_RULES:
        if re.match(pattern, canonical.lower()):
            return True, reason
    return False, None


def _to_canonical(name: str) -> str:
    lower = name.lower().strip()
    if lower in CANONICAL_MAP:
        return CANONICAL_MAP[lower]
    # Collapse multiple spaces
    return re.sub(r"\s+", " ", lower)


def parse_message(raw_text: str) -> list[ParsedItem]:
    """
    Parse a raw intake message into a list of ParsedItems.
    Never raises. Returns empty list on blank input.
    """
    if not raw_text or not raw_text.strip():
        return []

    item_strings = _split_items(raw_text)
    results: list[ParsedItem] = []

    for item_str in item_strings:
        if not item_str:
            continue

        quantity, unit, remainder = _extract_quantity(item_str)
        remainder, notes = _extract_notes(remainder)

        if not remainder:
            continue

        canonical = _to_canonical(remainder)
        category = _categorize(canonical)
        ambiguous, ambiguity_reason = _check_ambiguity(canonical)

        results.append(ParsedItem(
            raw=item_str,
            canonical=canonical,
            quantity=quantity,
            unit=unit,
            notes=notes,
            category=category,
            ambiguous=ambiguous,
            ambiguity_reason=ambiguity_reason,
        ))

    return results


def normalize_item_name(raw: str) -> str:
    """Convenience: normalize a single item name to canonical form."""
    _, _, remainder = _extract_quantity(raw.strip())
    remainder, _ = _extract_notes(remainder)
    return _to_canonical(remainder or raw)


def normalize_item(raw: str) -> "ParsedItem":
    """
    Parse and normalize a single item string into a ParsedItem.

    Unlike parse_message, this treats the entire input as one item
    and does not split on commas or 'and'.
    """
    text = _strip_prefix(raw.strip())
    if not text:
        from .models import ParsedItem
        return ParsedItem(raw=raw, canonical="", quantity=None, unit=None,
                          notes=None, category="other", ambiguous=True,
                          ambiguity_reason="empty input")

    quantity, unit, remainder = _extract_quantity(text)
    remainder, notes = _extract_notes(remainder)

    if not remainder:
        from .models import ParsedItem
        return ParsedItem(raw=raw, canonical="", quantity=None, unit=None,
                          notes=None, category="other", ambiguous=True,
                          ambiguity_reason="empty after parsing")

    canonical = _to_canonical(remainder)
    category = _categorize(canonical)
    ambiguous, ambiguity_reason = _check_ambiguity(canonical)

    from .models import ParsedItem
    return ParsedItem(
        raw=text,
        canonical=canonical,
        quantity=quantity,
        unit=unit,
        notes=notes,
        category=category,
        ambiguous=ambiguous,
        ambiguity_reason=ambiguity_reason,
    )
