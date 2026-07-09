"""Shared helpers for building openFDA/Lucene query strings safely."""


def escape_phrase(value: str) -> str:
    """Escape a value for use inside a double-quoted Lucene phrase.

    Within a phrase query only backslash and double-quote are special, so
    escaping those two is sufficient (and order matters: backslash first).
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')
