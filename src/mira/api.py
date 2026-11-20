"""Minimal Brawl Stars API client (standard library only)."""

from __future__ import annotations

import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

BASE_URL = "https://api.brawlstars.com/v1"
TOKEN_ENV = "BRAWLSTARS_API_TOKEN"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(Exception):
    """Any non-success response from the API."""

    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


class AuthError(ApiError):
    """403: bad key or the caller's IP is not on the key's whitelist."""


class NotFoundError(ApiError):
    """404: unknown player tag, country code, etc."""


def normalize_tag(tag: str) -> str:
    """Return a tag in canonical form: uppercase, '#' prefix, O -> 0."""
    tag = tag.strip().upper().lstrip("#").replace("O", "0")
    return "#" + tag


def encode_tag(tag: str) -> str:
    """URL-encode a player tag for use in a path segment ('#' -> '%23')."""
    return urllib.parse.quote(normalize_tag(tag), safe="")


def read_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Missing file -> empty dict."""
    values: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return values
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_token(dotenv_path: str | Path = ".env") -> str:
    token = os.environ.get(TOKEN_ENV) or read_dotenv(dotenv_path).get(TOKEN_ENV)
    if not token:
        raise AuthError(
            f"No API token found. Set {TOKEN_ENV} in your environment or in a .env file. "
            "Create a key at https://developer.brawlstars.com."
        )
    return token.strip()


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, dt.timestamp() - time.time())


class BrawlStarsClient:
    """Thin wrapper around the official API with throttling and retries.

    ``opener`` and ``sleep``/``clock`` are injectable so tests can run offline.
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = BASE_URL,
        min_interval: float = 0.1,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        backoff_cap: float = 60.0,
        timeout: float = 20.0,
        opener: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._lock = threading.Lock()  # the crawler calls get() from several threads
        self.request_count = 0

    # -- low level -----------------------------------------------------------

    def _throttle(self) -> None:
        # Reserve the next send slot under the lock, then sleep outside it, so threads
        # are spaced min_interval apart without blocking each other's sleeps.
        with self._lock:
            now = self._clock()
            wait = 0.0
            if self._last_request is not None and self.min_interval > 0:
                wait = max(0.0, self.min_interval - (now - self._last_request))
            self._last_request = now + wait
            self.request_count += 1
        if wait > 0:
            self._sleep(wait)

    def _backoff(self, attempt: int) -> float:
        return min(self.backoff_cap, self.backoff_base * (2 ** attempt))

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

        attempt = 0
        while True:
            self._throttle()
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with self._open(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                status = e.code
                body = _read_error_body(e)
                reason = body.get("reason")
                message = body.get("message") or e.reason
                if status == 403:
                    raise AuthError(
                        f"403 Forbidden ({reason or 'accessDenied'}): check your API key and that "
                        "its IP whitelist includes this machine's public IP "
                        "(https://developer.brawlstars.com/#/account).",
                        status=status,
                        reason=reason,
                    ) from None
                if status == 404:
                    raise NotFoundError(f"404 Not Found: {url}", status=status, reason=reason) from None
                if status in RETRY_STATUSES and attempt < self.max_retries:
                    delay = _retry_after_seconds(e.headers.get("Retry-After") if e.headers else None)
                    if delay is None:
                        delay = self._backoff(attempt)
                    self._sleep(delay)
                    attempt += 1
                    continue
                raise ApiError(f"HTTP {status} for {url}: {message}", status=status, reason=reason) from None
            # http.client.HTTPException covers a body cut off mid-read (IncompleteRead) on a flaky network.
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
                if attempt < self.max_retries:
                    self._sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                raise ApiError(f"Network error for {url}: {e}") from None

    # -- endpoints -----------------------------------------------------------

    def battlelog(self, tag: str) -> list[dict]:
        return self.get(f"players/{encode_tag(tag)}/battlelog").get("items", [])

    def player(self, tag: str) -> dict:
        return self.get(f"players/{encode_tag(tag)}")

    def player_rankings(self, country: str = "global", limit: int = 200) -> list[dict]:
        return self.get(f"rankings/{urllib.parse.quote(country, safe='')}/players", {"limit": limit}).get("items", [])

    def brawlers(self) -> list[dict]:
        return self.get("brawlers").get("items", [])


def _read_error_body(e: urllib.error.HTTPError) -> dict:
    try:
        data = json.loads(e.read().decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
