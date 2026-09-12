"""Controlled-vocabulary matching of disorders against FDA label indication text.

We don't parse disorders out of the free text — we take a known disorder
vocabulary (RxClass/MeSH names + label synonyms) and check which phrases the
label positively names.

Three guards keep precision high on real label text:

1. *Negation* — "not indicated for X", "Limitations of Use: ... X".
2. *Exclusion* — X named as a differential to rule out ("such as ... X").
3. *Indication context* — ambiguous legacy wording ("depression", "anxiety",
   "insomnia") counts only when it sits near indication language. Older
   tricyclic/MAOI/benzodiazepine labels predate the DSM names, so we must read
   them, but the same bare words also appear in symptom lists and trial
   descriptions where they are not indications.

A shorter phrase is also suppressed when a longer vocabulary phrase covers the
same span, so "social anxiety disorder" is not double-counted as bare "anxiety".
"""

# Display name -> label search phrases (include spelling/phrasing synonyms).
DISORDER_VOCAB: dict[str, list[str]] = {
    "Major Depressive Disorder": [
        "major depressive disorder",
        "mental depression",
        "depression",
        "depressed patients",
    ],
    "Bipolar Disorder": [
        "bipolar disorder",
        "bipolar i disorder",
        "bipolar depression",
        "manic episode",
        "acute mania",
        "manic or mixed episodes",
        "manic-depressive illness",
        "manic depressive illness",
    ],
    "Generalized Anxiety Disorder": [
        "generalized anxiety disorder",
        "anxiety disorders",
        "anxiety",
    ],
    "Social Anxiety Disorder": ["social anxiety disorder", "social phobia"],
    "Panic Disorder": ["panic disorder"],
    "OCD": ["obsessive-compulsive disorder", "obsessive compulsive disorder"],
    "PTSD": ["posttraumatic stress disorder", "post-traumatic stress disorder"],
    "Schizophrenia": ["schizophrenia", "schizophrenic"],
    "Schizoaffective Disorder": ["schizoaffective disorder"],
    "Psychotic Disorders": ["psychotic disorder"],
    "ADHD": [
        "attention deficit hyperactivity disorder",
        "attention-deficit hyperactivity disorder",
        "attention deficit disorder",
    ],
    "Premenstrual Dysphoric Disorder": [
        "premenstrual dysphoric disorder",
        "pmdd",
    ],
    "Postpartum Depression": ["postpartum depression"],
    "Seasonal Affective Disorder": ["seasonal affective disorder"],
    "Binge Eating Disorder": ["binge eating disorder", "binge-eating disorder"],
    "Bulimia Nervosa": ["bulimia nervosa", "bulimia"],
    "Tourette's Disorder": [
        "tourette's disorder",
        "tourette syndrome",
        "tic disorder",
    ],
    "Treatment-Resistant Depression": [
        "treatment-resistant depression",
        "treatment resistant depression",
    ],
    "Insomnia": ["insomnia", "difficulty falling asleep", "sleep onset"],
}

# Ambiguous phrases that also occur in symptom lists, trial narrative and
# comorbidity descriptions. These count only inside an indication context.
WEAK_PHRASES: frozenset[str] = frozenset(
    {
        "depression",
        "mental depression",
        "depressed patients",
        "anxiety",
        "anxiety disorders",
        "schizophrenic",
        "insomnia",
        "difficulty falling asleep",
        "sleep onset",
        "bulimia",
    }
)

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

# Wording that names a disorder only to rule it out as a differential diagnosis,
# or that frames it as something another condition merely resembles.
EXCLUSION_MARKERS = (
    "such as",
    "mimic",
    "other than",
    "not be due to",
    "rather than",
    "differential diagnosis",
    "secondary to",
)
EXCLUSION_WINDOW = 120

# Wording that marks the surrounding text as an indications statement.
INDICATION_MARKERS = (
    "indicated",
    "indication",
    "treatment of",
    "relief of",
    "management of",
    "symptomatic relief",
    "intended for use",
    "prevention of",
    "to control",
    "effective in",
    "useful in",
)
INDICATION_WINDOW = 80

# Longest first, so a span is tested against the most specific phrase available.
ALL_PHRASES: tuple[str, ...] = tuple(
    sorted(
        {phrase for phrases in DISORDER_VOCAB.values() for phrase in phrases},
        key=len,
        reverse=True,
    )
)


def _occurrences(haystack: str, needle: str) -> list[int]:
    """Every start index of needle in haystack."""
    positions = []
    index = haystack.find(needle)
    while index != -1:
        positions.append(index)
        index = haystack.find(needle, index + len(needle))
    return positions


def _preceded_by(haystack: str, position: int, markers, window: int) -> bool:
    prefix = haystack[max(0, position - window) : position]
    return any(marker in prefix for marker in markers)


def _in_indication_context(haystack: str, position: int, length: int) -> bool:
    """Whether indication language surrounds the span at this position."""
    start = max(0, position - INDICATION_WINDOW)
    end = min(len(haystack), position + length + INDICATION_WINDOW)
    window = haystack[start:end]
    return any(marker in window for marker in INDICATION_MARKERS)


def _covered_by_longer_phrase(haystack: str, position: int, needle: str) -> bool:
    """Whether a longer vocabulary phrase spans this same match."""
    end = position + len(needle)
    for phrase in ALL_PHRASES:
        if len(phrase) <= len(needle):
            break  # ALL_PHRASES is longest-first; nothing shorter can cover it.
        for start in _occurrences(haystack, phrase):
            if start <= position and start + len(phrase) >= end:
                return True
    return False


def positively_mentions(text: str | None, phrase: str) -> bool:
    """Whether the phrase appears as a positive (non-negated) indication."""
    haystack = (text or "").lower()
    needle = phrase.lower()
    return any(
        not _preceded_by(haystack, position, NEGATION_MARKERS, NEGATION_WINDOW)
        for position in _occurrences(haystack, needle)
    )


def _indicates(haystack: str, phrase: str) -> bool:
    """Whether the phrase names a disorder this label is indicated for."""
    needle = phrase.lower()
    is_weak = needle in WEAK_PHRASES
    for position in _occurrences(haystack, needle):
        if _preceded_by(haystack, position, NEGATION_MARKERS, NEGATION_WINDOW):
            continue
        if _preceded_by(haystack, position, EXCLUSION_MARKERS, EXCLUSION_WINDOW):
            continue
        if _covered_by_longer_phrase(haystack, position, needle):
            continue
        if is_weak and not _in_indication_context(haystack, position, len(needle)):
            continue
        return True
    return False


def approved_disorders(indications_text: str | None) -> list[str]:
    """The vocabulary disorders the label positively indicates, in vocab order."""
    haystack = (indications_text or "").lower()
    return [
        disorder
        for disorder, phrases in DISORDER_VOCAB.items()
        if any(_indicates(haystack, phrase) for phrase in phrases)
    ]
