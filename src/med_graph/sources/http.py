import time

import httpx

from med_graph.sources.base import SourceFetchError

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpSource:
    """Shared httpx client lifecycle and retry policy for API-backed sources.

    Use as a context manager: a self-created client is closed on exit,
    an injected one stays owned by the caller.
    """

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        timeout: float = 30,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds

    def __enter__(self) -> "HttpSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def _get_with_retry(
        self, url: str, params: dict, error_label: str
    ) -> httpx.Response | None:
        """GET with bounded retry on transient status codes.

        Returns None on 404 (the caller treats "no data" as empty), retries
        RETRYABLE_STATUS up to max_retries, and raises SourceFetchError on
        transport failure or a non-retryable/exhausted error status.
        """
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.get(url, params=params)
            except httpx.HTTPError as error:
                raise SourceFetchError(
                    f"{error_label} request failed: {error}"
                ) from error
            if response.status_code == 404:
                return None
            if response.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                self._sleep_before_retry(response, attempt)
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise SourceFetchError(
                    f"{error_label} request failed: {error}"
                ) from error
            return response
        # Unreachable: the final retryable attempt falls through to raise_for_status.
        raise SourceFetchError(f"{error_label} request failed after retries")

    def _sleep_before_retry(self, response: httpx.Response, attempt: int) -> None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            delay = float(retry_after)
        else:
            delay = self._retry_backoff_seconds * (2**attempt)
        if delay:
            time.sleep(delay)
