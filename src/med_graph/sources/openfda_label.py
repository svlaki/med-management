"""openFDA drug-label adapter: cross-references FAERS side effects against the
FDA label's adverse-reactions section.

For each medication it fetches the label's free-text adverse-reactions section
and marks each existing FAERS CAUSES edge as label_confirmed:
  True  - the reaction term appears (word-boundary) in the label text
  False - the label was fetched but does not mention the term
  None  - no label available, so it can be neither confirmed nor denied

Matching is a conservative lexical check: True is high-precision, but False can
be a false negative from spelling/phrasing variants (e.g. MedDRA "Diarrhoea"
vs. a US label's "diarrhea").
"""

import os
import re
import time

import httpx

from med_graph.models import Medication, SideEffect
from med_graph.sources.base import SourceBatch, SourceFetchError
from med_graph.sources.http import HttpSource
from med_graph.sources.lucene import escape_phrase

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"


def label_mentions(effect: SideEffect, label_text: str) -> bool:
    """Whether a side effect's term appears as a whole word in the label text."""
    if not label_text:
        return False
    haystack = label_text.lower()
    candidates = (effect.meddra_term, effect.name)
    for candidate in candidates:
        if candidate and re.search(
            r"\b" + re.escape(candidate.lower()) + r"\b", haystack
        ):
            return True
    return False


class OpenFdaLabelSource(HttpSource):
    def __init__(
        self,
        http_client: httpx.Client | None = None,
        request_delay_seconds: float = 0.3,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds must be non-negative")
        super().__init__(
            http_client,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self._request_delay_seconds = request_delay_seconds
        self._api_key = os.environ.get("OPENFDA_API_KEY")

    def confirm(
        self, medications: tuple[Medication, ...], batch: SourceBatch
    ) -> SourceBatch:
        """Return a copy of `batch` with label_confirmed set on each CAUSES edge."""
        generic_by_rxcui = {med.rxcui: med.generic_name for med in medications}
        effect_by_id = {effect.id: effect for effect in batch.side_effects}
        label_texts = self._fetch_label_texts(sorted(set(generic_by_rxcui.values())))

        confirmed_causes = []
        for edge in batch.causes:
            generic_name = generic_by_rxcui.get(edge.medication_rxcui)
            text = label_texts.get(generic_name) if generic_name else None
            effect = effect_by_id.get(edge.side_effect_id)
            if text is None or effect is None:
                confirmed: bool | None = None
            else:
                confirmed = label_mentions(effect, text)
            confirmed_causes.append(edge.model_copy(update={"label_confirmed": confirmed}))

        return SourceBatch(
            side_effects=batch.side_effects, causes=tuple(confirmed_causes)
        )

    def _fetch_label_texts(self, generic_names: list[str]) -> dict[str, str | None]:
        texts: dict[str, str | None] = {}
        for index, generic_name in enumerate(generic_names):
            if index and self._request_delay_seconds:
                time.sleep(self._request_delay_seconds)
            texts[generic_name] = self._adverse_reactions_text(generic_name)
        return texts

    def _adverse_reactions_text(self, generic_name: str) -> str | None:
        params = {
            "search": f'openfda.generic_name:"{escape_phrase(generic_name)}"',
            "limit": "1",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        response = self._get_with_retry(OPENFDA_LABEL_URL, params, "openfda label")
        if response is None:
            return None  # 404: no label indexed for this drug
        try:
            results = response.json().get("results") or []
        except ValueError as error:
            raise SourceFetchError(
                f"unexpected openfda label response: {error}"
            ) from error
        if not results:
            return None
        sections = results[0].get("adverse_reactions") or []
        # An empty/absent adverse-reactions section is "nothing to check"
        # (None), not "checked and denied" (which the caller reads as False).
        return " ".join(sections) or None
