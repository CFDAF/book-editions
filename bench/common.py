"""Shared plumbing for the benchmark scripts.

`setup(cache)` must run before anything imports `lookup`: `lookup.net` reads
BOOK_CACHE_DIR at import time. It then swaps `net.session` for a factory whose
sessions log every network request (cache hits never reach a session, so the
log counts real requests only) and enforce the politeness rules in
docs/Task.md: one request at a time per host, up to 4 on the SBN OPAC API,
Open Library at most 1 request per second.

`lookup` code is not modified; only the session it asks for is wrapped.
"""

import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
RESULTS = BENCH / "results" / "stage-1"
RAW = BENCH / "raw" / "stage-1"

LOG: list = []
_log_lock = threading.Lock()
_raw_log = None

# key -> (concurrency, minimum seconds between request starts)
POLICY = {
    "opac.sbn.it/o": (4, 0.0),
    "opac.sbn.it/opacmobilegw": (1, 0.0),
    "openlibrary.org": (1, 1.0),
    "viaf.org": (1, 0.5),
}
_gates: dict = {}
_gates_lock = threading.Lock()


def host_key(url: str) -> str:
    parts = urlsplit(url)
    if parts.netloc == "opac.sbn.it":
        first = parts.path.strip("/").split("/", 1)[0]
        return f"opac.sbn.it/{first}"
    return parts.netloc


class _Gate:
    def __init__(self, concurrency, interval):
        self.sem = threading.Semaphore(concurrency)
        self.interval = interval
        self.lock = threading.Lock()
        self.last = 0.0

    def __enter__(self):
        self.sem.acquire()
        if self.interval:
            with self.lock:
                wait = self.last + self.interval - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()

    def __exit__(self, *exc):
        self.sem.release()


def gate(key: str) -> _Gate:
    with _gates_lock:
        if key not in _gates:
            _gates[key] = _Gate(*POLICY.get(key, (1, 0.0)))
        return _gates[key]


def record(entry: dict) -> None:
    with _log_lock:
        LOG.append(entry)
        if _raw_log is not None:
            _raw_log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _raw_log.flush()


UA_CONTACT = "book-editions-lookup/3.0 (https://github.com/CFDAF/book-editions)"


def setup(cache_name: str, fresh: bool = False, log_name: str | None = None,
          user_agent: str | None = None):
    """Point the lookup cache at bench/cache/<cache_name> and instrument it.

    `user_agent` replaces net.USER_AGENT for this process only. The Wikimedia
    parts pass UA_CONTACT: A8 measured today's agent being throttled after 10
    requests a minute, which would turn identity results into 429 failures.
    """
    global _raw_log
    cache = BENCH / "cache" / cache_name
    if fresh and cache.exists():
        # Only ever a directory under bench/cache/, never the project's .cache/.
        assert BENCH / "cache" in cache.parents
        for p in cache.glob("*.json"):
            p.unlink()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["BOOK_CACHE_DIR"] = str(cache)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import requests
    from lookup import net

    if user_agent:
        net.USER_AGENT = user_agent

    class LoggedSession(requests.Session):
        def request(self, method, url, **kwargs):
            key = host_key(url)
            entry = {"host": key, "method": method, "url": url[:300]}
            if kwargs.get("params"):
                entry["params"] = {k: str(v)[:120] for k, v in dict(kwargs["params"]).items()}
            if kwargs.get("data"):
                entry["data"] = {k: str(v)[:120] for k, v in dict(kwargs["data"]).items()}
            with gate(key):
                t0 = time.time()
                entry["t"] = round(t0, 3)
                try:
                    r = super().request(method, url, **kwargs)
                except Exception as exc:  # counted, then re-raised to the caller
                    entry.update(elapsed=round(time.time() - t0, 3), status=None,
                                 error=f"{type(exc).__name__}: {str(exc)[:200]}")
                    record(entry)
                    raise
            entry.update(elapsed=round(time.time() - t0, 3), status=r.status_code,
                         bytes=len(r.content))
            if r.status_code >= 400:
                entry["error"] = f"HTTP {r.status_code}"
            record(entry)
            return r

    def session():
        s = getattr(net._local, "session", None)
        if s is None or not isinstance(s, LoggedSession):
            s = LoggedSession()
            s.headers["User-Agent"] = net.USER_AGENT
            from requests.adapters import HTTPAdapter
            from urllib3.util import Retry
            retries = Retry(total=2, backoff_factor=0.3, connect=2,
                            status_forcelist=[429, 500, 502, 503, 504],
                            allowed_methods={"GET", "POST"})
            adapter = HTTPAdapter(max_retries=retries, pool_maxsize=8)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            net._local.session = s
        return s

    net.session = session
    if log_name:
        RAW.mkdir(parents=True, exist_ok=True)
        _raw_log = open(RAW / f"{log_name}.requests.jsonl", "a", encoding="utf-8")
    return net


def cached_get(url: str, params: dict, headers: dict, cache_name: str):
    """GET JSON with extra headers (VIAF needs Accept), cached under bench/cache.

    Goes through `net.session()`, so it is logged and gated like everything
    else. Failures raise `net.SourceError` and are never cached.
    """
    import hashlib
    from urllib.parse import urlencode
    from lookup import net

    key = url + "?" + urlencode(sorted(params.items())) + "#" + json.dumps(headers, sort_keys=True)
    path = BENCH / "cache" / cache_name / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    import requests
    for attempt in range(4):
        try:
            r = net.session().get(url, params=params, headers=headers, timeout=(10, 60))
            r.raise_for_status()
            data = r.json()
            break
        except requests.ConnectionError as exc:
            # Intermittent local DNS failures for viaf.org; every attempt is logged.
            if attempt == 3:
                raise net.SourceError(f"{url}: {type(exc).__name__}: {str(exc)[:200]}") from exc
            time.sleep(10 * (attempt + 1))
        except Exception as exc:
            raise net.SourceError(f"{url}: {type(exc).__name__}: {str(exc)[:200]}") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def mark() -> int:
    """Index into LOG, to summarise the requests made after this point."""
    with _log_lock:
        return len(LOG)


def summarise(start: int = 0, end: int | None = None) -> dict:
    """Requests, failures and time per host for LOG[start:end]."""
    with _log_lock:
        entries = LOG[start:end]
    out = {}
    for e in entries:
        h = out.setdefault(e["host"], {"requests": 0, "failed": 0, "elapsed": []})
        h["requests"] += 1
        if e.get("error"):
            h["failed"] += 1
        h["elapsed"].append(e["elapsed"])
    for h in out.values():
        el = sorted(h.pop("elapsed"))
        h["total_s"] = round(sum(el), 2)
        h["p50_s"] = round(statistics.median(el), 3) if el else None
        h["max_s"] = round(el[-1], 3) if el else None
    return out


def failures(start: int = 0, end: int | None = None) -> list:
    with _log_lock:
        return [e for e in LOG[start:end] if e.get("error")]


def load_corpus() -> dict:
    return json.loads((BENCH / "corpus.json").read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
