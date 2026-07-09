import httpx


class HttpSource:
    """Shared httpx client lifecycle for API-backed sources.

    Use as a context manager: a self-created client is closed on exit,
    an injected one stays owned by the caller.
    """

    def __init__(
        self, http_client: httpx.Client | None = None, timeout: float = 30
    ) -> None:
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    def __enter__(self) -> "HttpSource":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._http.close()
