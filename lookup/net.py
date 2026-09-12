"""HTTP plumbing shared by every source.

Two things live here because every source needs both and neither is worth its
own module:

1. A pooled ``requests.Session`` per thread. The pipeline fans out with a
   ThreadPoolExecutor and ``Session`` is not documented as thread-safe, so each
   worker gets its own rather than sharing one and hoping.

2. A disk cache keyed on the fully-resolved request URL. This is not an
   optimisation detail: one lookup issues 15+ SBN ``full.json`` calls plus
   Wikipedia and Wikidata hops, and the web UI re-runs the same lookup every
   time you touch a filter. Without the cache the tool is unusable to iterate
   on and impolite to the upstream catalogues.
"""

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

USER_AGENT = "book-editions-lookup/3.0 (personal research tool)"
# Split connect and read. All four APIs normally answer well under a second, so
# a stalled *connection* should fail fast and be retried rather than consume a
# long read budget — an occasional 20s+ connect stall to one Wikipedia host was
# single-handedly setting the cold-lookup time.
TIMEOUT = (4, 15)
CACHE_DIR = Path(os.environ.get("BOOK_CACHE_DIR", Path(__file__).parent.parent / ".cache"))
CACHE_TTL = int(os.environ.get("BOOK_CACHE_TTL", 24 * 3600))

_local = threading.local()


def session() -> requests.Session:
    """One pooled, retrying Session per thread."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        retries = Retry(
            total=2,
            backoff_factor=0.3,
            connect=2,
            status_forcelist=[429, 500, 502, 503, 504],
            # The OPAC's search is a POST, but a search has no side effect, so
            # retrying one is as safe as retrying a GET.
            allowed_methods={"GET", "POST"},
        )
        adapter = HTTPAdapter(max_retries=retries, pool_maxsize=8)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.session = s
    return s


def _cache_path(url: str, params: dict | None) -> Path:
    key = url + "?" + urlencode(sorted((params or {}).items()), doseq=True)
    return CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"


class SourceError(Exception):
    """A source failed in a way the caller should report, not crash on."""


class Tally:
    """Counts requests that failed but were swallowed to keep a lookup going.

    A lookup fans out over dozens of requests and every helper treats a failed
    one as "no results", which is right — one bad request should not sink the
    whole answer. What was wrong is that the answer then looked complete: a
    dropped Open Library query removed the English editions, a dropped SBN probe
    removed the Italian ones, and the source was still reported as 'ok'. A
    partial answer that cannot be told apart from a complete one is worse than
    an error, so they are counted and reported.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.failures = []

    def note(self, where: str, exc) -> None:
        with self._lock:
            self.failures.append(f"{where}: {exc}")

    def count(self, prefix: str = "") -> int:
        with self._lock:
            return sum(1 for f in self.failures if f.startswith(prefix))

    def __len__(self):
        with self._lock:
            return len(self.failures)

    # Without this an empty Tally is falsy, because __len__ returns 0 — which
    # silently disabled every `if tally:` guard exactly when it mattered.
    def __bool__(self):
        return True


def cached_post_json(url: str, body: dict, ttl: int = CACHE_TTL, timeout=TIMEOUT):
    """POST a form and cache the JSON, keyed on the url and the body.

    Only the OPAC needs this: its search is a POST. A search is a read, so
    caching it is as sound as caching a GET, and the cache matters more here
    than anywhere — the web UI re-runs the whole lookup on every filter change.
    """
    path = _cache_path(url + "#post", body)
    if path.is_file() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    try:
        r = session().post(url, data=body, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise SourceError(f"{url}: {exc}") from exc
    except ValueError as exc:
        raise SourceError(f"{url}: response was not JSON ({exc})") from exc

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return data


def cached_get_json(url: str, params: dict | None = None, ttl: int = CACHE_TTL,
                    timeout=TIMEOUT):
    """GET JSON through the disk cache. Raises SourceError on failure.

    Cache hits are returned regardless of whether the network is reachable, so
    a flaky connection degrades to stale-but-useful rather than to nothing.
    """
    path = _cache_path(url, params)
    if path.is_file() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # corrupt entry, fall through and refetch

    try:
        r = session().get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise SourceError(f"{url}: {exc}") from exc
    except ValueError as exc:
        raise SourceError(f"{url}: response was not JSON ({exc})") from exc

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # a read-only cache dir must not break a lookup
    return data
