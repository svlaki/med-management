"""Map the free-text condition names in psych_drug_dataset.csv to canonical
Condition nodes.

The dataset's `approved_for` / `may_treat` cells use RxClass/MeSH disease labels,
several of which are synonyms or abbreviations of the same clinical entity
(``ADHD`` / ``Attention Deficit Disorder with Hyperactivity``; ``OCD`` /
``Obsessive-Compulsive Disorder``). Left as-is they would create duplicate graph
nodes. ``canonical_condition`` folds those into one node each, preserving the
``mdd`` / ``bipolar`` / ``gad`` slugs already in the graph, and slugifies any name
not in the curated table.
"""

from med_graph.models import Condition
from med_graph.models.slug import slugify

# Normalized (lowercased) raw name -> (slug, display name, ICD-10 or None).
# Entries that share a slug are merged into one node; ICD-10 codes are given for
# the well-known disorders and left None where a single code doesn't apply.
_ALIASES: dict[str, tuple[str, str, str | None]] = {
    # --- Mood ---
    "major depressive disorder": ("mdd", "Major Depressive Disorder", "F33"),
    "depressive disorder": ("depression", "Depressive Disorder", "F32"),
    "depressive disorder, treatment-resistant": (
        "depression-treatment-resistant",
        "Treatment-Resistant Depression",
        None,
    ),
    "dysthymic disorder": ("dysthymia", "Dysthymic Disorder", "F34.1"),
    "depression, postpartum": ("postpartum-depression", "Postpartum Depression", "F53.0"),
    "seasonal affective disorder": (
        "seasonal-affective-disorder",
        "Seasonal Affective Disorder",
        None,
    ),
    "bipolar disorder": ("bipolar", "Bipolar Disorder", "F31"),
    # --- Anxiety & related ---
    "anxiety disorders": ("anxiety", "Anxiety Disorders", "F41"),
    "generalized anxiety disorder": ("gad", "Generalized Anxiety Disorder", "F41.1"),
    "panic disorder": ("panic", "Panic Disorder", "F41.0"),
    "social anxiety disorder": ("social-anxiety", "Social Anxiety Disorder", "F40.1"),
    "agoraphobia": ("agoraphobia", "Agoraphobia", "F40.0"),
    "phobic disorders": ("phobic-disorders", "Phobic Disorders", "F40"),
    "ocd": ("ocd", "Obsessive-Compulsive Disorder", "F42"),
    "obsessive-compulsive disorder": ("ocd", "Obsessive-Compulsive Disorder", "F42"),
    "ptsd": ("ptsd", "Post-Traumatic Stress Disorder", "F43.1"),
    "stress disorders, post-traumatic": (
        "ptsd",
        "Post-Traumatic Stress Disorder",
        "F43.1",
    ),
    # --- Psychotic ---
    "schizophrenia": ("schizophrenia", "Schizophrenia", "F20"),
    "schizophrenia, paranoid": ("schizophrenia", "Schizophrenia", "F20"),
    "schizophrenia spectrum and other psychotic disorders": (
        "schizophrenia",
        "Schizophrenia",
        "F20",
    ),
    "psychotic disorders": ("psychotic-disorders", "Psychotic Disorders", "F29"),
    # --- Neurodevelopmental & childhood ---
    "adhd": ("adhd", "Attention-Deficit/Hyperactivity Disorder", "F90"),
    "attention deficit disorder with hyperactivity": (
        "adhd",
        "Attention-Deficit/Hyperactivity Disorder",
        "F90",
    ),
    "attention deficit and disruptive behavior disorders": (
        "adhd",
        "Attention-Deficit/Hyperactivity Disorder",
        "F90",
    ),
    "autistic disorder": ("autism", "Autistic Disorder", "F84.0"),
    "conduct disorder": ("conduct-disorder", "Conduct Disorder", "F91"),
    "child behavior disorders": (
        "child-behavior-disorders",
        "Child Behavior Disorders",
        None,
    ),
    "intellectual disability": ("intellectual-disability", "Intellectual Disability", "F79"),
    "tourette syndrome": ("tourette", "Tourette Syndrome", "F95.2"),
    "tic disorders": ("tic-disorders", "Tic Disorders", "F95"),
    "enuresis": ("enuresis", "Enuresis", "F98.0"),
    # --- Sleep ---
    "insomnia": ("insomnia", "Insomnia", "G47.0"),
    "sleep initiation and maintenance disorders": ("insomnia", "Insomnia", "G47.0"),
    "narcolepsy": ("narcolepsy", "Narcolepsy", "G47.4"),
    "restless legs syndrome": ("restless-legs-syndrome", "Restless Legs Syndrome", "G25.81"),
    "jet lag syndrome": ("jet-lag-syndrome", "Jet Lag Syndrome", None),
    # --- Substance use ---
    "alcoholism": ("alcohol-use-disorder", "Alcohol Use Disorder", "F10"),
    "binge drinking": ("alcohol-use-disorder", "Alcohol Use Disorder", "F10"),
    "alcohol withdrawal delirium": (
        "alcohol-withdrawal-delirium",
        "Alcohol Withdrawal Delirium",
        "F10.231",
    ),
    "tobacco use disorder": ("tobacco-use-disorder", "Tobacco Use Disorder", "F17"),
    "opioid-related disorders": (
        "opioid-use-disorder",
        "Opioid-Related Disorders",
        "F11",
    ),
    "cocaine-related disorders": (
        "cocaine-use-disorder",
        "Cocaine-Related Disorders",
        "F14",
    ),
    "substance-related disorders": (
        "substance-use-disorder",
        "Substance-Related Disorders",
        "F19",
    ),
    "substance withdrawal syndrome": (
        "substance-withdrawal-syndrome",
        "Substance Withdrawal Syndrome",
        None,
    ),
    # --- Neurocognitive & other ---
    "dementia": ("dementia", "Dementia", "F03"),
    "alzheimer disease": ("alzheimer-disease", "Alzheimer Disease", "G30"),
    "huntington disease": ("huntington-disease", "Huntington Disease", "G10"),
    "feeding and eating disorders": (
        "eating-disorders",
        "Feeding and Eating Disorders",
        "F50",
    ),
}


def canonical_condition(raw_name: str) -> Condition:
    """Resolve a dataset condition label to its canonical graph Condition.

    Known synonyms/abbreviations collapse to a shared slug; unknown names fall
    back to a slugified id with no ICD-10 code.
    """
    key = raw_name.strip().lower()
    entry = _ALIASES.get(key)
    if entry is not None:
        slug, display, icd10 = entry
        return Condition(id=slug, name=display, icd10=icd10)
    return Condition(id=slugify(raw_name), name=raw_name.strip(), icd10=None)
