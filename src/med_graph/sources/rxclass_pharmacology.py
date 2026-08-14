"""RxClass pharmacology: per-drug therapeutic class, mechanism, and neurotransmitter.

Read-only — does NOT touch Neo4j. Fetches a drug's classes from RxClass
`class/byRxcui` and derives, for the psychiatric-drug dataset:
  - drug_class      friendly therapeutic class from ATC (Antipsychotic, ...)
  - atc_codes       raw ATC codes (a drug can sit in several)
  - mechanisms      MoA class names (Serotonin Uptake Inhibitors, ...)
  - neurotransmitters  parsed from PE (Physiologic Effect) AND MoA as (name, dir)
                    where dir is + (increase), - (decrease), or ~ (affects/unclear)
  - may_treat       DISEASE classes it may treat (broad, incl. off-label)
"""

import re

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
    "Epinephrine",
    "GABA",
    "Histamine",
    "Acetylcholine",
    "Glutamate",
    "Melatonin",
    "Orexin",
    "Opioid",
]

# RxClass names a transmitter *system* by its receptor/pharmacology adjective far
# more often than by the transmitter's own name ("Adrenergic alpha-Agonists", not
# "Norepinephrine"). Map those adjectives to the canonical transmitter; the alias
# is only a matching key and is never surfaced in the output.
NT_ALIASES: dict[str, str] = {
    "adrenergic": "Norepinephrine",
    "noradrenergic": "Norepinephrine",
    "cholinergic": "Acetylcholine",
    "muscarinic": "Acetylcholine",
    "nicotinic": "Acetylcholine",
    "dopaminergic": "Dopamine",
    "serotonergic": "Serotonin",
    "gabaergic": "GABA",
    "gamma-aminobutyric acid": "GABA",
    "histaminergic": "Histamine",
    "glutamatergic": "Glutamate",
    "nmda": "Glutamate",
    "melatonergic": "Melatonin",
}


def _mentions(term: str, lowered: str) -> bool:
    """Word-boundary match so 'epinephrine' does not fire inside 'norepinephrine'."""
    return re.search(rf"\b{re.escape(term)}\b", lowered) is not None


def _match_neurotransmitters(lowered: str) -> list[str]:
    """Canonical transmitters named (directly or via an alias) in a lowered term."""
    found: list[str] = []
    for nt in NEUROTRANSMITTERS:
        if _mentions(nt.lower(), lowered):
            found.append(nt)
    for alias, nt in NT_ALIASES.items():
        if nt not in found and _mentions(alias, lowered):
            found.append(nt)
    return found


def _ordered(direction_by_nt: dict[str, str]) -> list[tuple[str, str]]:
    return [(nt, direction_by_nt[nt]) for nt in NEUROTRANSMITTERS if nt in direction_by_nt]


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
    """Parse PE names like 'Increased ... Serotonin Activity' -> [('Serotonin','+')].

    Direction is + (increased), - (decreased), or ~ (named an 'Activity
    Alteration' without a direction).
    """
    direction_by_nt: dict[str, str] = {}
    for name in pe_names:
        lowered = name.lower()
        if "increas" in lowered:
            direction = "+"
        elif "decreas" in lowered:
            direction = "-"
        elif "alteration" in lowered:
            direction = "~"
        else:
            continue
        for nt in _match_neurotransmitters(lowered):
            direction_by_nt.setdefault(nt, direction)
    return _ordered(direction_by_nt)


def _moa_direction(lowered: str) -> str | None:
    """Net direction a mechanism-of-action class has on its transmitter.

    Order matters: 'antagonist' must be tested before 'agonist' (it ends in it),
    and 'uptake inhibitor' before a bare 'inhibitor'.
    """
    if "antagonist" in lowered or "blocker" in lowered:
        return "-"
    if "agonist" in lowered:  # includes 'partial agonist'
        return "+"
    if "uptake inhibitor" in lowered or "reuptake inhibitor" in lowered:
        return "+"  # blocks reuptake -> more transmitter in the synapse
    if "releasing" in lowered or "releaser" in lowered or "potentiator" in lowered:
        return "+"
    if "modulator" in lowered:
        if "negative" in lowered:
            return "-"
        if "positive" in lowered:
            return "+"
        return "~"
    return None


def neurotransmitters_from_moa(moa_names: list[str]) -> list[tuple[str, str]]:
    """Derive transmitter effects from MoA class names (fills what PE misses)."""
    direction_by_nt: dict[str, str] = {}
    for name in moa_names:
        lowered = name.lower()
        # Well-established net effects that a keyword heuristic would get wrong.
        if "monoamine oxidase inhibitor" in lowered:
            for nt in ("Serotonin", "Norepinephrine", "Dopamine"):
                direction_by_nt.setdefault(nt, "+")
            continue
        if "cholinesterase inhibitor" in lowered:  # incl. acetylcholinesterase
            direction_by_nt.setdefault("Acetylcholine", "+")
            continue
        direction = _moa_direction(lowered)
        if direction is None:
            continue
        # alpha-2 autoreceptor agonists (clonidine, guanfacine) REDUCE NE release.
        alpha2 = bool(re.search(r"alpha[\s-]?2", lowered))
        for nt in _match_neurotransmitters(lowered):
            resolved = "-" if (nt == "Norepinephrine" and alpha2 and direction == "+") else direction
            direction_by_nt.setdefault(nt, resolved)
    return _ordered(direction_by_nt)


def neurotransmitter_effects(
    pe_names: list[str], moa_names: list[str]
) -> list[tuple[str, str]]:
    """Merge PE- and MoA-derived transmitter effects; PE wins on conflict."""
    combined: dict[str, str] = {}
    for nt, direction in neurotransmitters_from_moa(moa_names):
        combined[nt] = direction
    for nt, direction in parse_neurotransmitters(pe_names):
        combined[nt] = direction  # PE overrides the MoA guess
    return _ordered(combined)


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
            "neurotransmitters": neurotransmitter_effects(pe_names, sorted(mechanisms)),
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
