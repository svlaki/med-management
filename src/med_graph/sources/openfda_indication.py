"""openFDA label indications: which medications are FDA-approved for a condition.

RxClass's `may_treat` is broad (includes off-label use) and its granular disease
classes are unpopulated. The FDA label's `indications_and_usage` field, by
contrast, names the specific approved condition per drug. This adapter searches
that field for a condition's indication phrase(s) and returns the set of our
medications whose ingredient name appears among the matching labels — the
FDA-APPROVED (on-label) tier, layered on top of the RxClass edges.

Caveats: only on-label indications are captured (misses established off-label
use); free-text phrase matching can occasionally over-match. Match is by
ingredient name because a label's `openfda.rxcui` is usually a product/pack
rxcui, not the RxNorm ingredient rxcui we key medications on.
"""

import os
import re

import httpx

from med_graph.models import Medication
from med_graph.sources.base import SourceFetchError
from med_graph.sources.conditions import ConditionSpec
from med_graph.sources.http import HttpSource
from med_graph.sources.lucene import escape_phrase

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
# One request per indication term is plenty; openFDA caps limit at 1000.
INDICATION_LIMIT = "1000"


def name_matches(generic_name: str, label_names: set[str]) -> bool:
    """Whether an ingredient name appears as a whole word in any label name.

    e.g. "buspirone" matches "buspirone hydrochloride" but "lith" does not
    match "lithium carbonate".
    """
    needle = generic_name.lower().strip()
    if not needle:
        return False
    pattern = re.compile(r"\b" + re.escape(needle) + r"\b")
    return any(pattern.search(name) for name in label_names)


class OpenFdaIndicationSource(HttpSource):
    def __init__(
        self,
        http_client: httpx.Client | None = None,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        super().__init__(
            http_client,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self._api_key = os.environ.get("OPENFDA_API_KEY")

    def approved_rxcuis(
        self, spec: ConditionSpec, medications: tuple[Medication, ...]
    ) -> set[str]:
        """The rxcuis of medications whose FDA label names this condition."""
        label_names: set[str] = set()
        for term in spec.label_indication_terms:
            label_names |= self._label_names_for_indication(term)
        return {
            med.rxcui
            for med in medications
            if name_matches(med.generic_name, label_names)
        }

    def _label_names_for_indication(self, term: str) -> set[str]:
        params = {
            "search": f'indications_and_usage:"{escape_phrase(term)}"',
            "limit": INDICATION_LIMIT,
        }
        if self._api_key:
            params["api_key"] = self._api_key

        response = self._get_with_retry(
            OPENFDA_LABEL_URL, params, "openfda indications"
        )
        if response is None:
            return set()  # 404: no approved drug names this indication
        try:
            results = response.json().get("results") or []
        except ValueError as error:
            raise SourceFetchError(
                f"unexpected openfda indications response: {error}"
            ) from error

        names: set[str] = set()
        for result in results:
            openfda = result.get("openfda") or {}
            for field in ("generic_name", "substance_name"):
                for value in openfda.get(field, []):
                    names.add(value.lower())
        return names
