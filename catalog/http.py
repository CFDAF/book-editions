"""HTTP plumbing shared by every source. One session, one cache, one ledger.

Was `lookup/net.py` through Steps 1A-4; moved here in Step 5 and still reachable
under the old name, which is an alias rather than a copy (`lookup/net.py` says
why). There is exactly one of it, so both trees share one cache and one ledger
while they run side by side.

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

   **The cache refuses what its caller rejects.** Both SBN APIs answer a
   request they dislike with HTTP 200 and a valid JSON body saying so, and a
   valid body is exactly what this cache stores. Cached, that failure is
   replayed for the whole TTL: the source stays ``partial`` for 24 h and
   "search again", which is the advice the page gives, cannot fill the gap.
   So a caller passes ``validate=`` — the judgement only it can make — and a
   payload it rejects is never written, and an already-written one is dropped
   on sight.

3. The ledger: every call one lookup makes, and what happened to it. See
   ``Ledger``.
"""

import contextvars
import hashlib
import json
import os
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InvalidHeader, MaxRetryError, ResponseError
from urllib3.util import Retry

from . import fixtures

# The form Wikimedia's User-Agent policy asks for: `<client>/<version>
# (<contact>) <library>/<version>`. It throttles an agent with no contact — the
# old "(personal research tool)" was answered 10 times a minute and then got
# `429, retry-after: 14`: 102 of 180 requests, against 0 of 180 with a contact
# URL (A8, F18). That throttling, not the network, was Wikimedia's
# 35% of request time.
USER_AGENT = ("book-editions-lookup/3.0 (https://github.com/CFDAF/book-editions) "
              f"python-requests/{requests.__version__}")
# Split connect and read. All four APIs normally answer well under a second, so
# a stalled *connection* should fail fast and be retried rather than consume a
# long read budget.
#
# This comment used to blame the cold-lookup time on "an occasional 20s+ connect
# stall to one Wikipedia host". That was wrong, and the correction is measured:
# Wikimedia's 35% of request time was *throttling* an agent with no contact URL,
# not the network (`docs/DECISIONS.md` pitfall 10, F18). Step 4 saw it directly — two
# Retry-After waits of 36 s in one throttled run, and none at all with the
# contact agent. The split timeout is still right; the story behind it was not.
TIMEOUT = (4, 15)
# The longest Retry-After any host has asked for is Wikimedia's 36 s (Step 4),
# and urllib3 would otherwise sleep up to 6 h on one. A server asking for more
# than this will not answer inside the lookup, so the request fails at once and
# the ledger shows it, rather than sleeping and asking again too soon.
RETRY_AFTER_CAP_S = 60
CACHE_DIR = Path(os.environ.get("BOOK_CACHE_DIR", Path(__file__).parent.parent / ".cache"))
CACHE_TTL = int(os.environ.get("BOOK_CACHE_TTL", 24 * 3600))

# Above this a lookup says what made it slow. The identity path's p90 is 5.7 s
# (decision K), so a lookup past 10 s has something to explain.
SLOW_LOOKUP_S = 10
# A request that took longer than this to answer is named as a cause.
SLOW_REQUEST_S = 10

_local = threading.local()
_now = time.monotonic
_ledger = contextvars.ContextVar("ledger", default=None)   # the lookup being recorded
_call = contextvars.ContextVar("call", default=None)       # the request in flight


def session() -> requests.Session:
    """One pooled, retrying Session per thread.

    Under ``BOOK_FIXTURES`` the two cached_* helpers below answer from the
    bundle and never get here, so reaching this point means some other code
    path is about to open a socket. That is the thing an offline run must not
    do quietly, so it raises rather than returns.
    """
    if fixtures.active():
        raise fixtures.FixtureMiss(
            "a request was about to bypass the fixture bundle and open a "
            "network connection. Route it through cached_get_json / "
            "cached_post_json, or record it into the bundle.")
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = USER_AGENT
        retries = RecordedRetry(
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


def _cache_key(url: str, params: dict | None) -> str:
    """The identity of a request. The disk cache and the fixture bundle are
    both keyed on it, so an offline run finds exactly what a live one cached."""
    key = url + "?" + urlencode(sorted((params or {}).items()), doseq=True)
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _cache_path(url: str, params: dict | None) -> Path:
    return CACHE_DIR / f"{_cache_key(url, params)}.json"


class SourceError(Exception):
    """A source failed in a way the caller should report, not crash on."""


def _checked(url: str, data, validate):
    """Raise before a payload the caller cannot use reaches the disk.

    ``validate`` returns a reason to reject, or None. It runs on every route
    into a body — network, cache and fixture bundle alike — so an error payload
    cannot be smuggled in by having been cached earlier.
    """
    problem = validate(data) if validate else None
    if problem:
        raise SourceError(f"{url}: {problem}")
    return data


def _from_cache(path: Path, ttl: int):
    """The cached body, or None when there is nothing worth having."""
    if path.is_file() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # corrupt entry, fall through and refetch
    return None


def _store(path: Path, data) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # a read-only cache dir must not break a lookup


def _cached(path: Path, ttl: int, url: str, validate):
    """A usable cached body, or None. A rejected one is deleted, not returned.

    Deleting matters: without it a body cached before this hook existed would
    be re-read, re-rejected and re-reported for the rest of its TTL, which is
    the behaviour the hook exists to end.
    """
    data = _from_cache(path, ttl)
    if data is None:
        return None
    try:
        return _checked(url, data, validate)
    except SourceError:
        path.unlink(missing_ok=True)
        return None


class RecordedRetry(Retry):
    """urllib3's retry, telling the request in flight what each retry cost.

    Retries happen inside the adapter: the session sees one slow request, and
    a 429 that was slept through never reaches the caller at all. This is the
    only place one shows, so it is where the ledger learns of it.
    """

    def increment(self, method=None, url=None, response=None, error=None,
                  _pool=None, _stacktrace=None):
        if response is not None:
            try:
                wait = self.get_retry_after(response)
            except InvalidHeader:
                wait = None
            if wait is not None and wait > RETRY_AFTER_CAP_S:
                raise MaxRetryError(_pool, url, ResponseError(
                    f"HTTP {response.status} asked to retry after {wait:.0f} s, "
                    f"over the {RETRY_AFTER_CAP_S} s cap"))
        retry = super().increment(method, url, response, error, _pool, _stacktrace)
        call = _call.get()
        if call is not None:
            # urllib3 sleeps on the object this returns, so the wait is
            # written onto the same entry by sleep_for_retry below.
            retry._entry = {"cause": f"HTTP {response.status}" if response is not None
                                     else type(error).__name__,
                            "waited": 0.0}
            call["retries"].append(retry._entry)
        return retry

    def sleep_for_retry(self, response) -> bool:
        started = _now()
        slept = super().sleep_for_retry(response)
        entry = getattr(self, "_entry", None)
        if slept and entry is not None:
            entry["waited"] = _now() - started
        return slept


def _source(host: str) -> str:
    """The catalogue a host belongs to, named the way `Report.sources` names it.

    Wikipedia is how the Wikidata source finds its items, so the report has
    always counted the two as one source.
    """
    if host.endswith(".sbn.it"):
        return "SBN"
    if host.endswith("openlibrary.org"):
        return "Open Library"
    if host.endswith((".wikipedia.org", ".wikidata.org")):
        return "Wikidata"
    return host


class Ledger:
    """Every call one lookup made through this module, and what happened to it.

    Three things used to answer "what happened on the network", and they could
    disagree: `Tally`, which counted only the failures a source remembered to
    report; a source's `partial (N failed)`, which read `Tally`; and nothing at
    all for why a lookup was slow. They are now readings of this one record,
    written under the HTTP layer where every source has to pass, so a failure
    no source mentions is still counted.

    Per call: the source and host, whether it was answered by the network, the
    cache or the fixture bundle, how long it took, its error if it failed, and
    each urllib3 retry with its cause and any Retry-After wait.

    Open one per lookup with ``with Ledger() as ledger:``. It binds itself to
    the current context, and `Pool` carries that context into worker threads.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.calls = []
        self.started = _now()
        self.wall = 0.0

    def __enter__(self):
        self._token = _ledger.set(self)
        return self

    def __exit__(self, *exc):
        _ledger.reset(self._token)
        self.wall = _now() - self.started

    def record(self, call: dict) -> None:
        with self._lock:
            self.calls.append(call)

    def failed(self, source: str | None = None) -> int:
        """Calls that failed, for one source or all of them."""
        with self._lock:
            return sum(1 for c in self.calls
                       if c["error"] and source in (None, c["source"]))

    def slow_causes(self) -> list:
        """What this lookup spent time on, one clause per kind — all measured.

        A clause names a host only for something the ledger saw that host do in
        this lookup. Nothing is inferred: a lookup that was slow for a reason
        the network layer cannot see gets no cause at all.
        """
        waited = defaultdict(float)             # host -> seconds slept on Retry-After
        waits = defaultdict(Counter)            # host -> cause -> retries that waited
        retried = defaultdict(Counter)          # host -> cause -> the other retries
        slow = defaultdict(list)                # host -> seconds, slow answers
        sent = defaultdict(lambda: [0, 0.0])    # source -> [requests, seconds]
        with self._lock:
            calls = [c for c in self.calls if c["via"] == "network"]
        for c in calls:
            answering = c["seconds"]
            for r in c["retries"]:
                if r["waited"]:
                    waited[c["host"]] += r["waited"]
                    waits[c["host"]][r["cause"]] += 1
                    answering -= r["waited"]
                else:
                    retried[c["host"]][r["cause"]] += 1
            # A wait is named once, as a wait, not again as a slow answer.
            if answering > SLOW_REQUEST_S:
                slow[c["host"]].append(answering)
            sent[c["source"]][0] += 1
            sent[c["source"]][1] += c["seconds"]

        causes = [f"{host} made it wait {secs:.0f} s on Retry-After ({_counts(waits[host])})"
                  for host, secs in waited.items()]
        causes += [f"{host} needed {sum(n.values())} "
                   f"{'retry' if sum(n.values()) == 1 else 'retries'} ({_counts(n)})"
                   for host, n in retried.items()]
        causes += [f"{host} took {times[0]:.1f} s to answer one request" if len(times) == 1
                   else f"{host} took over {SLOW_REQUEST_S} s to answer {len(times)} requests "
                        f"(longest {max(times):.1f} s)"
                   for host, times in slow.items()]
        if sent:
            causes.append("requests sent: " + ", ".join(
                f"{source} {n} ({secs:.1f} s)" for source, (n, secs)
                in sorted(sent.items(), key=lambda kv: -kv[1][1])))
        return causes


def _counts(counter: Counter) -> str:
    return ", ".join(f"{cause} \u00d7 {n}" for cause, n in counter.most_common())


class Pool(ThreadPoolExecutor):
    """A thread pool whose workers record into the lookup that started them.

    A new thread starts with an empty context, so a plain ThreadPoolExecutor
    runs its requests outside the lookup's ledger: their failures reach no
    reading, which is `CLAUDE.md` rule 5's failure exactly. Every pool in
    `lookup/` is this one; `tests/test_net_ledger.py` checks.
    """

    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)


def cached_post_json(url: str, body: dict, ttl: int = CACHE_TTL, timeout=TIMEOUT,
                     validate=None):
    """POST a form and cache the JSON, keyed on the url and the body.

    Only the OPAC needs this: its search is a POST. A search is a read, so
    caching it is as sound as caching a GET, and the cache matters more here
    than anywhere — the web UI re-runs the whole lookup on every filter change.
    """
    return _recorded("POST", url, body, ttl, timeout, validate)


def cached_get_json(url: str, params: dict | None = None, ttl: int = CACHE_TTL,
                    timeout=TIMEOUT, validate=None):
    """GET JSON through the disk cache. Raises SourceError on failure.

    Cache hits are returned regardless of whether the network is reachable, so
    a flaky connection degrades to stale-but-useful rather than to nothing.
    """
    return _recorded("GET", url, params, ttl, timeout, validate)


def _recorded(method: str, url: str, fields, ttl: int, timeout, validate):
    """`_fetch`, with the call written to the ledger of the lookup making it."""
    host = urlsplit(url).hostname or ""
    call = {"source": _source(host), "host": host, "via": None, "seconds": 0.0,
            "error": None, "retries": []}
    started = _now()
    try:
        return _fetch(call, method, url, fields, ttl, timeout, validate)
    except SourceError as exc:
        call["error"] = str(exc)
        raise
    finally:
        call["seconds"] = _now() - started
        ledger = _ledger.get()
        if ledger is not None and call["via"]:
            ledger.record(call)


def _fetch(call: dict, method: str, url: str, fields, ttl: int, timeout, validate):
    """The body from the fixture bundle, the disk cache or the network, in that
    order, noting in ``call`` which one answered."""
    key_url = f"{url}#post" if method == "POST" else url
    if fixtures.active():
        data = fixtures.load(_cache_key(key_url, fields), f"{method} {url}")
        call["via"] = "fixture"          # after the load: a miss stops the run, unrecorded
        return _checked(url, data, validate)

    path = _cache_path(key_url, fields)
    cached = _cached(path, ttl, url, validate)
    if cached is not None:
        call["via"] = "cache"
        return cached

    call["via"] = "network"
    token = _call.set(call)          # so RecordedRetry can write its retries here
    try:
        if method == "POST":
            r = session().post(url, data=fields, timeout=timeout)
        else:
            r = session().get(url, params=fields, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        raise SourceError(f"{url}: {exc}") from exc
    except ValueError as exc:
        raise SourceError(f"{url}: response was not JSON ({exc})") from exc
    finally:
        _call.reset(token)

    _checked(url, data, validate)   # raises before the write, never after
    _store(path, data)
    return data
