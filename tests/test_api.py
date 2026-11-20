import io
import json
import os
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from mira.api import (
    TOKEN_ENV, ApiError, AuthError, BrawlStarsClient, NotFoundError, encode_tag, load_token, normalize_tag,
)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def http_error(code: int, body: dict | None = None, headers: dict | None = None) -> urllib.error.HTTPError:
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("url", code, "err", msg, io.BytesIO(json.dumps(body or {}).encode()))


class ScriptedOpener:
    """Returns/raises the scripted outcomes in order and records requests."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return FakeResponse(json.dumps(out).encode())


def make_client(opener, **kw):
    sleeps = []
    client = BrawlStarsClient("tok", opener=opener, sleep=sleeps.append, min_interval=0, **kw)
    return client, sleeps


class TagTests(unittest.TestCase):
    def test_normalize_and_encode(self):
        self.assertEqual(normalize_tag(" #2pp "), "#2PP")
        self.assertEqual(normalize_tag("o8q"), "#08Q")
        self.assertEqual(encode_tag("#2PP"), "%232PP")
        self.assertEqual(encode_tag("2PP"), "%232PP")


class ClientTests(unittest.TestCase):
    def test_battlelog_url_and_auth_header(self):
        opener = ScriptedOpener({"items": [{"x": 1}]})
        client, _ = make_client(opener)
        self.assertEqual(client.battlelog("#ABC"), [{"x": 1}])
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://api.brawlstars.com/v1/players/%23ABC/battlelog")
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")

    def test_rankings_url(self):
        opener = ScriptedOpener({"items": []})
        client, _ = make_client(opener)
        client.player_rankings("US", limit=50)
        self.assertEqual(opener.requests[0].full_url, "https://api.brawlstars.com/v1/rankings/US/players?limit=50")

    def test_429_honours_retry_after(self):
        opener = ScriptedOpener(http_error(429, headers={"Retry-After": "7"}), {"items": []})
        client, sleeps = make_client(opener)
        client.brawlers()
        self.assertEqual(sleeps, [7.0])
        self.assertEqual(len(opener.requests), 2)

    def test_5xx_exponential_backoff(self):
        opener = ScriptedOpener(http_error(503), http_error(502), {"items": []})
        client, sleeps = make_client(opener, backoff_base=1.0)
        client.brawlers()
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_gives_up_after_max_retries(self):
        opener = ScriptedOpener(*[http_error(500) for _ in range(3)])
        client, sleeps = make_client(opener, max_retries=2)
        with self.assertRaises(ApiError) as cm:
            client.brawlers()
        self.assertEqual(cm.exception.status, 500)
        self.assertEqual(len(sleeps), 2)

    def test_network_error_retried(self):
        opener = ScriptedOpener(urllib.error.URLError("boom"), {"items": []})
        client, sleeps = make_client(opener)
        client.brawlers()
        self.assertEqual(len(sleeps), 1)

    def test_403_is_clear_auth_error(self):
        opener = ScriptedOpener(http_error(403, {"reason": "accessDenied.invalidIp", "message": "Invalid IP"}))
        client, sleeps = make_client(opener)
        with self.assertRaises(AuthError) as cm:
            client.brawlers()
        self.assertIn("IP whitelist", str(cm.exception))
        self.assertIn("accessDenied.invalidIp", str(cm.exception))
        self.assertEqual(sleeps, [])

    def test_404_not_retried(self):
        opener = ScriptedOpener(http_error(404))
        client, sleeps = make_client(opener)
        with self.assertRaises(NotFoundError):
            client.battlelog("#NOPE")
        self.assertEqual(sleeps, [])

    def test_throttle(self):
        t = [100.0]
        sleeps = []
        opener = ScriptedOpener({"items": []}, {"items": []})
        client = BrawlStarsClient("tok", opener=opener, sleep=sleeps.append, clock=lambda: t[0], min_interval=0.5)
        client.brawlers()
        t[0] += 0.2
        client.brawlers()
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.3)


class TokenTests(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {TOKEN_ENV: "fromenv"}):
            self.assertEqual(load_token("/nonexistent/.env"), "fromenv")

    def test_dotenv(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            p = Path(d) / ".env"
            p.write_text(f'# comment\nexport {TOKEN_ENV}="abc.def"\n')
            self.assertEqual(load_token(p), "abc.def")

    def test_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(AuthError):
                load_token("/nonexistent/.env")


if __name__ == "__main__":
    unittest.main()
