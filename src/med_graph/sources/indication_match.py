"""Controlled-vocabulary matching of disorders against FDA label indication text.

We don't parse disorders out of the free text — we take a known disorder
vocabulary (RxClass/MeSH names + label synonyms) and check which phrases the
label positively names, guarding against negated ("not indicated for X") and
"Limitations of Use" mentions.
"""

# Display name -> label search phrases (include spelling/phrasing synonyms).
DISORDER_VOCAB: dict[str, list[str]] = {
    "Major Depressive Disorder": ["major depressive disorder"],
    "Bipolar Disorder": [
        "bipolar disorder",
        "bipolar i disorder",
        "bipolar depression",
        "manic episode",
        "acute mania",
        "manic or mixed episodes",
    ],
    "Generalized Anxiety Disorder": ["generalized anxiety disorder"],
    "Social Anxiety Disorder": ["social anxiety disorder", "social phobia"],
    "Panic Disorder": ["panic disorder"],
    "OCD": ["obsessive-compulsive disorder", "obsessive compulsive disorder"],
    "PTSD": ["posttraumatic stress disorder", "post-traumatic stress disorder"],
    "Schizophrenia": ["schizophrenia"],
    "ADHD": [
        "attention deficit hyperactivity disorder",
        "attention-deficit hyperactivity disorder",
        "attention deficit disorder",
    ],
    "Insomnia": ["insomnia"],
}

# If any of these appears just before a matched phrase, treat it as a non-approval
# (negation or carve-out) rather than a positive indication.
NEGATION_MARKERS = (
    "not indicated",
    "limitations of use",
    "is not ",
    "are not ",
    "not been established",
    "not established",
    "not approved",
    "not recommended",
)
NEGATION_WINDOW = 45


def positively_mentions(text: str | None, phrase: str) -> bool:
    """Whether the phrase appears as a positive (non-negated) indication."""
    haystack = (text or "").lower()
    needle = phrase.lower()
    index = 0
    while True:
        position = haystack.find(needle, index)
        if position == -1:
            return False
        prefix = haystack[max(0, position - NEGATION_WINDOW) : position]
        if not any(marker in prefix for marker in NEGATION_MARKERS):
            return True
        index = position + len(needle)


def approved_disorders(indications_text: str | None) -> list[str]:
    """The vocabulary disorders the label positively indicates, in vocab order."""
    return [
        disorder
        for disorder, phrases in DISORDER_VOCAB.items()
        if any(positively_mentions(indications_text, p) for p in phrases)
    ]
