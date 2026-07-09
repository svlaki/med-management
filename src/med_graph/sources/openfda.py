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

OPENFDA_BASE_URL = "https://api.fda.gov/drug"
OPENFDA_MAX_LIMIT = 1000
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

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


def _escape_lucene_phrase(value: str) -> str:
    """Escape a value for use inside a double-quoted Lucene phrase.

    Within a phrase query only backslash and double-quote are special, so
    escaping those two is sufficient (and order matters: backslash first).
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
        if request_delay_seconds < 0 or retry_backoff_seconds < 0:
            raise ValueError("delay/backoff seconds must be non-negative")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        super().__init__(http_client)
        self._top_n = top_n
        self._request_delay_seconds = request_delay_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
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
                f'"{_escape_lucene_phrase(generic_name)}"'
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

        response = self._get_with_retry(f"{OPENFDA_BASE_URL}/event.json", params)
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

    def _get_with_retry(self, url: str, params: dict) -> httpx.Response | None:
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.get(url, params=params)
            except httpx.HTTPError as error:
                raise SourceFetchError(f"openfda request failed: {error}") from error
            if response.status_code == 404:
                return None
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep_before_retry(response, attempt)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise SourceFetchError(f"openfda request failed: {error}") from error
            return response
        # Unreachable: the final retryable attempt falls through to raise_for_status.
        raise SourceFetchError("openfda request failed after retries")

    def _sleep_before_retry(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            delay = float(retry_after)
        else:
            delay = self._retry_backoff_seconds * (2**attempt)
        if delay:
            time.sleep(delay)
