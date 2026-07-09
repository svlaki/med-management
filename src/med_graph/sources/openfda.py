"""openFDA FAERS adapter: real-world adverse-event reports per medication.

For each medication, fetches the most-reported MedDRA reaction terms and
yields SideEffect nodes plus CAUSES edges tagged with faers provenance and
the raw report count. FAERS counts are report volumes, not incidence rates.
"""

import os
import time

import httpx
from pydantic import ValidationError

from med_graph.models import CausesEdge, EdgeSource, Medication, SideEffect
from med_graph.sources.base import SourceBatch, SourceFetchError
from med_graph.sources.http import HttpSource
from med_graph.sources.lucene import escape_phrase

OPENFDA_BASE_URL = "https://api.fda.gov/drug"
OPENFDA_MAX_LIMIT = 1000

# MedDRA terms that describe medication-use problems, not adverse effects
ADMINISTRATIVE_TERMS = frozenset(
    {
        "DRUG INEFFECTIVE",
        "DRUG INEFFECTIVE FOR UNAPPROVED INDICATION",
        "OFF LABEL USE",
        "PRODUCT USE IN UNAPPROVED INDICATION",
        "PRODUCT USE ISSUE",
        "PRODUCT DOSE OMISSION",
        "PRODUCT DOSE OMISSION ISSUE",
        "THERAPY NON-RESPONDER",
    }
)


class OpenFdaFaersSource(HttpSource):
    def __init__(
        self,
        http_client: httpx.Client | None = None,
        top_n: int = 20,
        request_delay_seconds: float = 0.3,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if not 1 <= top_n <= OPENFDA_MAX_LIMIT:
            raise ValueError(f"top_n must be between 1 and {OPENFDA_MAX_LIMIT}")
        if request_delay_seconds < 0:
            raise ValueError("request_delay_seconds must be non-negative")
        super().__init__(
            http_client,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        self._top_n = top_n
        self._request_delay_seconds = request_delay_seconds
        self._api_key = os.environ.get("OPENFDA_API_KEY")

    def enrich(self, medications: tuple[Medication, ...]) -> SourceBatch:
        effects_by_id: dict[str, SideEffect] = {}
        causes: list[CausesEdge] = []
        for index, medication in enumerate(medications):
            if index and self._request_delay_seconds:
                time.sleep(self._request_delay_seconds)
            for term, count in self._reaction_counts(medication.generic_name):
                record = self._build_records(medication, term, count)
                if record is None:
                    continue
                effect, edge = record
                effects_by_id[effect.id] = effect
                causes.append(edge)
        return SourceBatch(
            side_effects=tuple(effects_by_id.values()), causes=tuple(causes)
        )

    def _build_records(
        self, medication: Medication, term: str, count: int
    ) -> tuple[SideEffect, CausesEdge] | None:
        """Build a node/edge pair, or None if this single row fails validation.

        Skipping a bad row keeps one odd FAERS term from aborting the whole run.
        """
        try:
            effect = SideEffect(id=term, name=term.capitalize(), meddra_term=term)
            edge = CausesEdge(
                medication_rxcui=medication.rxcui,
                side_effect_id=effect.id,
                source=EdgeSource.FAERS,
                report_count=count,
            )
        except ValidationError:
            return None
        return effect, edge

    def _reaction_counts(self, generic_name: str) -> list[tuple[str, int]]:
        params = {
            "search": (
                "patient.drug.openfda.generic_name:"
                f'"{escape_phrase(generic_name)}"'
            ),
            "count": "patient.reaction.reactionmeddrapt.exact",
            # Over-fetch so administrative terms filtered below can't shrink the
            # result under top_n: at most len(ADMINISTRATIVE_TERMS) can be dropped.
            "limit": str(
                min(self._top_n + len(ADMINISTRATIVE_TERMS), OPENFDA_MAX_LIMIT)
            ),
        }
        if self._api_key:
            params["api_key"] = self._api_key

        response = self._get_with_retry(
            f"{OPENFDA_BASE_URL}/event.json", params, "openfda"
        )
        if response is None:
            # openFDA returns 404 when a drug has no FAERS reports
            return []
        try:
            rows = [(row["term"], row["count"]) for row in response.json()["results"]]
        except (KeyError, TypeError) as error:
            raise SourceFetchError(
                f"unexpected openfda response shape: {error}"
            ) from error
        filtered = [(term, count) for term, count in rows if term not in ADMINISTRATIVE_TERMS]
        return filtered[: self._top_n]
