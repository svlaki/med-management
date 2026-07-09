"""
Two utility functions: slugify() lowercases a string and replaces non-alphanumeric runs with hyphens (e.g., "Weight Gain" -> "weight-gain").
validate_slug() does the same but rejects empty results.
"""

import re


def slugify(value: str) -> str:
    """Canonicalize a display string into a stable node key, e.g. 'Weight Gain' -> 'weight-gain'."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def validate_slug(value: str) -> str:
    """Slugify and reject values that carry no alphanumeric content."""
    slug = slugify(value)
    if not slug:
        raise ValueError("id must contain at least one alphanumeric character")
    return slug
