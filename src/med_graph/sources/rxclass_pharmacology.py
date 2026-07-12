"""RxClass pharmacology: per-drug therapeutic class, mechanism, and neurotransmitter.

Read-only — does NOT touch Neo4j. Fetches a drug's classes from RxClass
`class/byRxcui` and derives, for the psychiatric-drug dataset:
  - drug_class      friendly therapeutic class from ATC (Antipsychotic, ...)
  - atc_codes       raw ATC codes (a drug can sit in several)
  - mechanisms      MoA class names (Serotonin Uptake Inhibitors, ...)
  - neurotransmitters  parsed from PE (Physiologic Effect) as (name, +/-)
  - may_treat       DISEASE classes it may treat (broad, incl. off-label)
"""

import httpx

from med_graph.sources.base import SourceFetchError
from med_graph.sources.http import HttpSource

BYRXCUI_URL = "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json"

# ATC prefix -> friendly class, most-specific prefix first so N05AN (lithium)
# is caught before the N05A (antipsychotic) it nests under.
ATC_CLASS_MAP: list[tuple[str, str]] = [
    ("N05AN", "Mood stabilizer"),  # lithium
    ("N05A", "Antipsychotic"),
    ("N05B", "Anxiolytic"),
    ("N05C", "Sedative-Hypnotic"),
    ("N06A", "Antidepressant"),
    ("N06B", "Stimulant"),
    ("N06D", "Anti-dementia"),
    ("N03A", "Mood stabilizer"),  # antiepileptic mood stabilizers
]

# When a drug matches several classes, this decides the single primary label.
CLASS_PRIORITY = [
    "Antipsychotic",
    "Antidepressant",
    "Mood stabilizer",
    "Stimulant",
    "Anxiolytic",
    "Sedative-Hypnotic",
    "Anti-dementia",
]

NEUROTRANSMITTERS = [
    "Serotonin",
    "Dopamine",
    "Norepinephrine",
    "GABA",
    "Histamine",
    "Acetylcholine",
    "Glutamate",
]


def atc_to_class(atc_codes: list[str]) -> str:
    """Map a drug's ATC codes to one friendly psychiatric drug class."""
    matched: set[str] = set()
    for code in atc_codes:
        for prefix, cls in ATC_CLASS_MAP:
            if code.startswith(prefix):
                matched.add(cls)
                break
    for cls in CLASS_PRIORITY:
        if cls in matched:
            return cls
    return "Other"


def parse_neurotransmitters(pe_names: list[str]) -> list[tuple[str, str]]:
    """Parse PE names like 'Increased ... Serotonin Activity' -> [('Serotonin','+')]."""
    direction_by_nt: dict[str, str] = {}
    for name in pe_names:
        lowered = name.lower()
        if "increas" in lowered:
            direction = "+"
        elif "decreas" in lowered:
            direction = "-"
        else:
            continue
        for nt in NEUROTRANSMITTERS:
            if nt.lower() in lowered:
                direction_by_nt[nt] = direction
    return [(nt, direction_by_nt[nt]) for nt in NEUROTRANSMITTERS if nt in direction_by_nt]


class RxClassPharmacologySource(HttpSource):
    def pharmacology(self, rxcui: str) -> dict:
        response = self._get_with_retry(
            BYRXCUI_URL, {"rxcui": rxcui}, "rxclass pharmacology"
        )
        if response is None:
            return _empty()
        try:
            info = (
                response.json()
                .get("rxclassDrugInfoList", {})
                .get("rxclassDrugInfo", [])
            )
        except ValueError as error:
            raise SourceFetchError(
                f"unexpected rxclass byRxcui response: {error}"
            ) from error

        atc_codes: list[str] = []
        mechanisms: set[str] = set()
        pe_names: list[str] = []
        may_treat: set[str] = set()
        for item in info:
            concept = item.get("rxclassMinConceptItem", {})
            class_type = concept.get("classType")
            name = concept.get("className")
            rela = item.get("rela")
            if class_type == "ATC1-4" and concept.get("classId"):
                atc_codes.append(concept["classId"])
            elif class_type == "MOA" and rela == "has_moa" and name:
                mechanisms.add(name)
            elif class_type == "PE" and rela == "has_pe" and name:
                pe_names.append(name)
            elif class_type == "DISEASE" and rela == "may_treat" and name:
                may_treat.add(name)

        atc_codes = sorted({c for c in atc_codes if c})
        return {
            "atc_codes": atc_codes,
            "drug_class": atc_to_class(atc_codes),
            "mechanisms": sorted(mechanisms),
            "neurotransmitters": parse_neurotransmitters(pe_names),
            "may_treat": sorted(may_treat),
        }


def _empty() -> dict:
    return {
        "atc_codes": [],
        "drug_class": "Other",
        "mechanisms": [],
        "neurotransmitters": [],
        "may_treat": [],
    }
