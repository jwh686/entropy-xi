"""HTTP helper with retries and polite pacing."""
from __future__ import annotations

import time

import requests

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "EntropyXI/1.0 (football research; contact via site)"})


def get(url: str, *, timeout: float = 60, retries: int = 4, backoff: float = 3.0, ok_404: bool = False) -> requests.Response | None:
    """GET with exponential backoff on network errors and 5xx. Returns None on 404 when ok_404."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, timeout=timeout)
            if r.status_code == 404 and ok_404:
                return None
            if r.status_code >= 500 or r.status_code == 429:
                raise requests.HTTPError(f"HTTP {r.status_code} for {url}")
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_exc = exc
            if isinstance(exc, requests.HTTPError) and exc.response is not None and 400 <= exc.response.status_code < 500 \
                    and exc.response.status_code != 429:
                raise
            time.sleep(backoff * (2 ** attempt))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last_exc
