"""Extract per-disorder diagnostic features from the WHO ICD-11 CDDR.

The CDDR (Clinical Descriptions and Diagnostic Requirements for ICD-11 Mental,
Behavioural and Neurodevelopmental Disorders, WHO 2024) is the clinician-authored
manual that says which features define each disorder. We use it to answer "which
symptoms belong to this disorder?" with a real citation instead of our judgment,
and -- via scripts/build_symptom_vocabulary.py -- to decide which candidate
symptoms are worth a node at all.

This script does the extraction only. It produces one row per (disorder, feature
bullet) with the printed page number, so every downstream claim can cite
"CDDR p. 162".

Two things worth knowing about the source PDF:
  * Running page headers ("Schizophrenia and other primary psychotic disorders")
    sit inside the text column and splice themselves into the middle of
    sentences. They are detected by frequency across pages and removed, rather
    than hardcoded.
  * The PDF page is the printed page + 18 (front matter). We record both and
    cite the printed one.

Licence: the CDDR is CC BY-NC-ND 3.0 IGO -- free to use and redistribute
NON-commercially, no adaptations. Rows derived from it are tagged
license_tier=1 downstream and must be removed before any commercial release.
See the commercial-release checklist in the plan.

Run: .venv/bin/python scripts/extract_cddr_symptoms.py
Output: data_clean/cddr_disorder_features.csv
"""

import re
import subprocess
from collections import Counter
from pathlib import Path

import httpx
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO / "data_exports" / "raw"
PDF = CACHE_DIR / "icd11_cddr_2024.pdf"
OUT = REPO / "data_clean" / "cddr_disorder_features.csv"

CDDR_URL = (
    "https://iris.who.int/server/api/core/bitstreams/"
    "dcf73611-9e0f-4d5c-85f6-85a58b0da6de/content"
)

# Front matter offset: PDF page N holds printed page N - 18.
PRINTED_PAGE_OFFSET = 18

# Section headings that delimit a disorder entry. We keep only the first.
SECTIONS = (
    "Essential (required) features",
    "Additional clinical features",
    "Boundary with normality (threshold)",
    "Course features",
    "Developmental presentations",
    "Culture-related features",
    "Sex- and/or gender-related features",
    "Boundaries with other disorders and conditions",
)
FEATURES_HEADING = SECTIONS[0]
# Bullets that sit directly under a code with no section heading of their own.
UNSECTIONED = "(unsectioned)"

# An ICD-11 code heading, e.g. "6A20   Schizophrenia".
CODE_HEADING = re.compile(
    r"^\s{0,12}([0-9][A-Z][0-9A-Z]{1,2}(?:\.[0-9A-Z]+)?)\s{2,}([A-Z][^\n]{2,80})$"
)
# A line that is only a page number.
PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
# Running headers carry the folio: "Schizophrenia and other ... disorders   163".
# The trailing number differs per page, so it must be stripped before the
# frequency test can recognise the header as repeated.
TRAILING_FOLIO = re.compile(r"\s+\d{1,4}\s*$")
# How many pages a line must appear on before it counts as a running header.
HEADER_PAGE_THRESHOLD = 5


def fetch_cddr() -> Path:
    """Download the CDDR PDF once and cache it. Free, no registration."""
    if PDF.exists():
        return PDF
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading the CDDR (8 MB, one time)...")
    try:
        response = httpx.get(CDDR_URL, timeout=300, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise SystemExit(f"Could not download the CDDR: {error}") from error
    if not response.content.startswith(b"%PDF"):
        raise SystemExit("CDDR download was not a PDF; the WHO URL may have moved.")
    PDF.write_bytes(response.content)
    return PDF


def page_texts(pdf: Path) -> list[str]:
    """Layout-preserving text, one string per page."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf), "-"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as error:
        raise SystemExit(
            "pdftotext not found. Install poppler: brew install poppler"
        ) from error
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"pdftotext failed on {pdf}: {error.stderr[:300]}") from error
    return result.stdout.split("\f")


def running_headers(pages: list[str]) -> set[str]:
    """Lines repeated across many pages -- chapter headers, not content.

    Detected by frequency rather than hardcoded, so the parser survives a new
    CDDR edition with different section names.
    """
    counts = Counter(
        _header_key(line)
        for page in pages
        for line in page.split("\n")
        if len(line.strip()) > 12 and not _is_structural(line)
    )
    return {line for line, n in counts.items() if n >= HEADER_PAGE_THRESHOLD}


def _header_key(line: str) -> str:
    """A running header without its per-page folio, so repeats compare equal."""
    return TRAILING_FOLIO.sub("", line.strip()).strip()


def _is_structural(line: str) -> bool:
    """Section and code headings repeat on every page but are what we parse by.

    Without this guard "Essential (required) features" -- which appears ~140
    times -- is itself detected as a running header and stripped, leaving the
    parser nothing to find.
    """
    return any(section in line for section in SECTIONS) or bool(CODE_HEADING.match(line))


def split_bullets(lines: list[str]) -> list[str]:
    """Group wrapped lines into bullets. A bullet starts at a bullet glyph.

    Sub-items lettered a) b) c) stay attached to their parent bullet: the parent
    is usually "At least two of the following symptoms must be present", which is
    meaningless split from its list.
    """
    bullets: list[str] = []
    current: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("•", "•", "- ")):
            if current:
                bullets.append(" ".join(current.split()))
            current = stripped.lstrip("•• -").strip()
        elif current is not None and stripped:
            current += " " + stripped
    if current:
        bullets.append(" ".join(current.split()))
    return [b for b in bullets if len(b) > 20]


def document_lines(pages: list[str], headers: set[str]) -> list[tuple[str, int]]:
    """The whole book as (line, pdf_page) pairs, headers and page numbers removed.

    Parsing has to span pages: a disorder's lettered symptom list routinely runs
    across a page break, and treating pages independently truncates it mid-list.
    """
    return [
        (line, page_number)
        for page_number, page in enumerate(pages, start=1)
        for line in page.split("\n")
        if _is_structural(line)
        or (_header_key(line) not in headers and not PAGE_NUMBER.match(line))
    ]


def _named_entry_headings(lines: list[tuple[str, int]]) -> dict[int, str]:
    """Entries the CDDR titles in words instead of an ICD-11 code.

    The mood episode descriptions -- "Depressive episode", "Manic episode",
    "Hypomanic episode", "Mixed episode" -- carry the canonical symptom lists
    that the mood DISORDER entries then defer to ("see above essential
    features"). They have no code, so a code-anchored parser silently drops the
    most important symptom list in the book: without this, 6A70 Depressive
    disorder matches zero symptoms.

    Detected structurally rather than by name: a short title-case line, not
    itself a section heading, standing just above an "Essential (required)
    features" that has no ICD-11 code above it.
    """
    headings: dict[int, str] = {}
    for index, (text, _) in enumerate(lines):
        if FEATURES_HEADING not in text:
            continue
        if _nearest_code(lines, index) is not None:
            continue
        for offset in range(index - 1, max(index - 10, -1), -1):
            candidate = lines[offset][0].strip()
            if (
                candidate
                and len(candidate) < 60
                and candidate[0].isupper()
                and not any(section in candidate for section in SECTIONS)
            ):
                headings[offset] = candidate
                break
    return headings


def _nearest_code(lines: list[tuple[str, int]], index: int) -> str | None:
    """The ICD-11 code heading just above `index`, if there is one."""
    for offset in range(index - 1, max(index - 10, -1), -1):
        match = CODE_HEADING.match(lines[offset][0])
        if match:
            return match.group(1)
    return None


def parse_entries(lines: list[tuple[str, int]]) -> list[dict]:
    """One record per (code, section) block of bullets.

    Anchoring on "Essential (required) features" alone loses most of the book's
    symptom text: many entries -- notably the mood-episode specifiers 6A80.x,
    which are where "psychomotor retardation" and "elevated mood" actually live
    -- put their bullets directly under the code with no section heading at all.
    So we capture every bullet under each code and record which section it came
    from, letting the consumer decide how strict to be.
    """
    named = _named_entry_headings(lines)
    entries: list[dict] = []
    code = title = section = None
    page_number = 0
    body: list[str] = []

    def flush() -> None:
        if code and body:
            features = split_bullets(body)
            if features:
                entries.append({
                    "icd11_code": code,
                    "disorder_title": title,
                    "pdf_page": page_number,
                    "cddr_page": page_number - PRINTED_PAGE_OFFSET,
                    "section": section or UNSECTIONED,
                    "features": features,
                })

    for index, (text, page) in enumerate(lines):
        heading = CODE_HEADING.match(text)
        if heading:
            flush()
            code, title = heading.group(1), heading.group(2).strip()
            page_number, section, body = page, None, []
            continue
        if index in named:
            flush()
            code, title = named[index], named[index]
            page_number, section, body = page, None, []
            continue
        matched_section = next((s for s in SECTIONS if s in text), None)
        if matched_section:
            flush()
            section, body = matched_section, []
            continue
        body.append(text)
    flush()
    return entries


def main() -> None:
    pages = page_texts(fetch_cddr())
    headers = running_headers(pages)
    entries = parse_entries(document_lines(pages, headers))

    rows = [
        {
            "icd11_code": entry["icd11_code"],
            "disorder_title": entry["disorder_title"],
            "cddr_page": entry["cddr_page"],
            "section": entry["section"],
            "feature": feature,
        }
        for entry in entries
        for feature in entry["features"]
    ]
    frame = pd.DataFrame(
        rows, columns=["icd11_code", "disorder_title", "cddr_page", "section", "feature"]
    )
    frame.to_csv(OUT, index=False)

    print(f"Wrote {OUT.relative_to(REPO)}")
    codes = {e["icd11_code"] for e in entries}
    essential = int((frame.section == FEATURES_HEADING).sum())
    print(f"  {len(codes)} codes, {len(frame)} feature statements")
    print(f"    {essential} from '{FEATURES_HEADING}', {len(frame) - essential} from other sections")
    print(f"  {len(headers)} running headers stripped")



if __name__ == "__main__":
    main()
