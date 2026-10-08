"""`catalog/http.py` — the contact User-Agent and the request ledger (Step 4).

One ledger per lookup records every call under the HTTP layer. `Tally`, a
source's `partial (N failed)` and the slow-lookup note used to be separate
mechanisms that could disagree; they are now readings of it. This file pins the
three properties that make the readings trustworthy:

- **every call is on it** — through the network, the cache and the fixture
  bundle, from worker threads as well as the lookup's own, and a failure is
  counted whether or not the source that swallowed it said anything;
- **retries and Retry-After waits reach it**, though urllib3 hides both from
  the caller — exercised through urllib3's own `Retry` code, not a stand-in —
  and a wait over `RETRY_AFTER_CAP_S` is a failure at once, not a sleep;
- **the slow note names only what happened**: it appears on a slowed lookup, is
  absent on a fast one, and never names a cause the ledger did not record.

Offline, like the rest of `tests/`: `session()` is faked and time is a fake
clock. The Retry-After of 14 s is Wikimedia's own (F18).
"""

import gzip
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from email.utils import formatdate
from pathlib import Path

import pytest
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import ConnectTimeoutError, MaxRetryError
from urllib3.response import HTTPResponse
from urllib3.util import retry as urllib3_retry

from catalog import fixtures
from catalog import http as net
from core import notes

SBN = "https://opac.sbn.it/opacmobilegw/search.json"
OPEN_LIBRARY = "https://openlibrary.org/search.json"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status = body, status

    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(f"{self.status} error")

    def json(self):
        return self._body


class FakeSession:
    """Answers every request after `seconds` of fake time, or with `status`."""

    def __init__(self, clock, seconds=0.2, status=200, body=None):
        self.clock, self.seconds, self.status = clock, seconds, status
        self.body = {"ok": True} if body is None else body

    def get(self, url, params=None, timeout=None):
        self.clock.advance(self.seconds)
        return FakeResponse(self.body, self.status)

    post = get


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(net, "_now", c)
    return c


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(net, "CACHE_DIR", tmp_path)
    return tmp_path


def answering(monkeypatch, session):
    monkeypatch.setattr(net, "session", lambda: session)


# ------------------------------------------------------------- the agent -----

class TestUserAgent:
    def test_it_is_the_form_wikimedias_policy_asks_for(self):
        """`<client>/<version> (<contact>) <library>/<version>`. The contact is
        what lifts the throttle: 102 x 429 of 180 without it, 0 of 180 with."""
        assert re.fullmatch(r"[\w.-]+/[\d.]+ \(https://\S+\) python-requests/[\d.]+",
                            net.USER_AGENT), net.USER_AGENT

    def test_it_is_not_the_agent_that_was_throttled(self):
        assert "personal research tool" not in net.USER_AGENT

    def test_the_session_sends_it(self, monkeypatch):
        monkeypatch.setattr(net._local, "session", None, raising=False)
        assert net.session().headers["User-Agent"] == net.USER_AGENT


# ------------------------------------------------------ every call is on it -----

class TestEveryCallIsRecorded:
    def test_network_cache_and_failure_each_leave_one_entry(self, clock, cache, monkeypatch):
        answering(monkeypatch, FakeSession(clock))
        with net.Ledger() as ledger:
            net.cached_get_json(OPEN_LIBRARY, {"q": "rumori"})      # network
            net.cached_get_json(OPEN_LIBRARY, {"q": "rumori"})      # cache
            answering(monkeypatch, FakeSession(clock, status=503))
            with pytest.raises(net.SourceError):
                net.cached_get_json(OPEN_LIBRARY, {"q": "noise"})
        assert [(c["source"], c["via"], bool(c["error"])) for c in ledger.calls] == [
            ("Open Library", "network", False),
            ("Open Library", "cache", False),
            ("Open Library", "network", True)]

    def test_a_failure_nobody_reports_is_still_counted(self, clock, cache, monkeypatch):
        """The shape of `CLAUDE.md` rule 5's worst bug: a source swallows the
        error and returns nothing. Under `Tally` it counted only if the source
        remembered to say so."""
        answering(monkeypatch, FakeSession(clock, body={"error": {"msg": "Solr"}}))
        with net.Ledger() as ledger:
            try:
                net.cached_get_json(SBN, {"title": "alpha / beta"},
                                    validate=lambda d: d.get("error") and "error payload")
            except net.SourceError:
                pass                                  # swallowed, and nothing said
        assert ledger.failed() == 1
        assert ledger.failed("SBN") == 1
        assert ledger.failed("Open Library") == 0

    def test_the_wikimedia_hosts_are_the_wikidata_source(self):
        assert net._source("en.wikipedia.org") == "Wikidata"
        assert net._source("www.wikidata.org") == "Wikidata"
        assert net._source("opac.sbn.it") == "SBN"
        assert net._source("openlibrary.org") == "Open Library"

    def test_a_fixture_answer_is_recorded_and_a_miss_is_not(self, tmp_path, monkeypatch):
        bodies = tmp_path / "bodies"
        bodies.mkdir()
        params = {"q": "rumori"}
        with gzip.open(bodies / f"{net._cache_key(OPEN_LIBRARY, params)}.json.gz", "wb") as fh:
            fh.write(json.dumps({"docs": []}).encode("utf-8"))
        (tmp_path / "manifest.json").write_text('{"fixtures": []}', encoding="utf-8")
        monkeypatch.setenv("BOOK_FIXTURES", str(tmp_path))
        fixtures.reset()
        try:
            with net.Ledger() as ledger:
                net.cached_get_json(OPEN_LIBRARY, params)
                with pytest.raises(fixtures.FixtureMiss):
                    net.cached_get_json(OPEN_LIBRARY, {"q": "not recorded"})
        finally:
            fixtures.reset()
        assert [c["via"] for c in ledger.calls] == ["fixture"]

    def test_outside_a_lookup_nothing_is_recorded_and_nothing_breaks(self, clock, cache,
                                                                     monkeypatch):
        """A call with no lookup around it — a sweep's probe, say."""
        answering(monkeypatch, FakeSession(clock))
        assert net.cached_get_json(OPEN_LIBRARY, {"q": "x"}) == {"ok": True}

    def test_two_lookups_do_not_share_a_ledger(self, clock, cache, monkeypatch):
        answering(monkeypatch, FakeSession(clock))
        with net.Ledger() as first:
            net.cached_get_json(OPEN_LIBRARY, {"q": "a"})
        with net.Ledger() as second:
            net.cached_get_json(OPEN_LIBRARY, {"q": "b"})
        assert len(first.calls) == len(second.calls) == 1


class TestPoolsCarryTheLedger:
    def test_a_pool_worker_records_into_the_lookup(self, clock, cache, monkeypatch):
        answering(monkeypatch, FakeSession(clock))
        with net.Ledger() as ledger:
            with net.Pool(max_workers=3) as pool:
                list(pool.map(lambda q: net.cached_get_json(OPEN_LIBRARY, {"q": q}),
                              ["a", "b", "c"]))
        assert len(ledger.calls) == 3

    def test_a_plain_pool_would_lose_every_call(self, clock, cache, monkeypatch):
        """Why `Pool` exists. If this starts passing with 3, Python began
        copying context into executor threads and `Pool` can go."""
        answering(monkeypatch, FakeSession(clock))
        with net.Ledger() as ledger:
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda q: net.cached_get_json(OPEN_LIBRARY, {"q": q}),
                              ["a", "b", "c"]))
        assert len(ledger.calls) == 0

    def test_every_pool_in_the_lookup_is_the_ledger_carrying_one(self):
        """All four packages, not just the one that happens to hold `Pool`.

        Step 5 split the tree, so `catalog/` and `core/` are scanned too: a
        plain executor added over there would lose its workers' calls exactly
        the way one in `lookup/` would. **Step 8 added `app/`**, and it is the
        worst place of the four to get wrong — the job's own pool is where the
        ledger is opened, so a plain executor there would lose every call the
        lookup makes rather than one stage's.

        The scan is a text match, so the class's name stays out of prose
        in these packages as well as out of their code; `catalog/http.py`
        is where it is written, and it is excluded because it is where
        `Pool` is.
        """
        home = Path(net.__file__)                    # catalog/http.py: `Pool` itself
        root = home.parent.parent
        roots = [home.parent, root / "core", root / "lookup", root / "app"]
        offenders = sorted(f"{p.parent.name}/{p.name}"
                           for root in roots for p in root.glob("*.py")
                           if p != home and "ThreadPoolExecutor" in p.read_text("utf-8"))
        assert offenders == []


# ------------------------------------------------ retries, through urllib3 -----

def _in_flight():
    """A request in flight, as `_fetch` marks one, for urllib3's retry to find."""
    call = {"retries": []}
    token = net._call.set(call)
    return call, token


class TestRetriesReachTheLedger:
    def test_a_429_with_retry_after_is_one_retry_and_one_timed_wait(self, clock, monkeypatch):
        monkeypatch.setattr(urllib3_retry.time, "sleep", clock.advance)
        call, token = _in_flight()
        try:
            retry = net.RecordedRetry(total=2, status_forcelist=[429], allowed_methods={"GET"})
            response = HTTPResponse(body=b"", headers={"Retry-After": "14"}, status=429,
                                    preload_content=False)
            retry = retry.increment("GET", "/w/api.php", response=response)
            retry.sleep(response)
        finally:
            net._call.reset(token)
        assert call["retries"] == [{"cause": "HTTP 429", "waited": 14.0}]

    def test_a_connect_timeout_is_a_retry_with_no_wait(self, clock, monkeypatch):
        monkeypatch.setattr(urllib3_retry.time, "sleep", clock.advance)
        call, token = _in_flight()
        try:
            retry = net.RecordedRetry(total=2, connect=2, backoff_factor=0.3)
            retry = retry.increment("GET", "/opacmobilegw/full.json",
                                    error=ConnectTimeoutError("timed out"))
            retry.sleep()
        finally:
            net._call.reset(token)
        assert call["retries"] == [{"cause": "ConnectTimeoutError", "waited": 0.0}]

    def test_no_request_in_flight_means_nothing_recorded(self):
        retry = net.RecordedRetry(total=2, status_forcelist=[429], allowed_methods={"GET"})
        response = HTTPResponse(body=b"", status=429, preload_content=False)
        assert retry.increment("GET", "/", response=response).total == 1

    def test_a_retry_after_over_the_cap_is_refused_without_a_wait(self, clock, monkeypatch):
        monkeypatch.setattr(urllib3_retry.time, "sleep", clock.advance)
        call, token = _in_flight()
        try:
            retry = net.RecordedRetry(total=2, status_forcelist=[429], allowed_methods={"GET"})
            response = HTTPResponse(body=b"", headers={"Retry-After": "3600"}, status=429,
                                    preload_content=False)
            with pytest.raises(MaxRetryError, match="3600 s, over the 60 s cap"):
                retry.increment("GET", "/w/api.php", response=response)
        finally:
            net._call.reset(token)
        assert call["retries"] == []
        assert clock.t == 1000.0

    def test_a_retry_after_date_past_the_cap_is_refused_too(self):
        later = formatdate(time.time() + 3600, usegmt=True)
        retry = net.RecordedRetry(total=2, status_forcelist=[429], allowed_methods={"GET"})
        response = HTTPResponse(body=b"", headers={"Retry-After": later}, status=429,
                                preload_content=False)
        with pytest.raises(MaxRetryError, match="over the 60 s cap"):
            retry.increment("GET", "/w/api.php", response=response)

    def test_a_retry_after_at_the_cap_is_waited(self, clock, monkeypatch):
        monkeypatch.setattr(urllib3_retry.time, "sleep", clock.advance)
        call, token = _in_flight()
        try:
            retry = net.RecordedRetry(total=2, status_forcelist=[429], allowed_methods={"GET"})
            response = HTTPResponse(body=b"", status=429, preload_content=False,
                                    headers={"Retry-After": str(net.RETRY_AFTER_CAP_S)})
            retry.increment("GET", "/w/api.php", response=response).sleep(response)
        finally:
            net._call.reset(token)
        assert call["retries"] == [{"cause": "HTTP 429", "waited": 60.0}]

    def test_a_refused_wait_is_one_request_and_one_counted_failure(self, clock, cache,
                                                                   monkeypatch):
        """Through the real session and urllib3's pool, only the socket stubbed:
        the 429 is not asked again, and the lookup's ledger counts it."""
        sent = []

        def answer(self, conn, method, url, **kw):
            sent.append(url)
            return HTTPResponse(body=b"", headers={"Retry-After": "3600"}, status=429,
                                preload_content=False)

        monkeypatch.setattr(HTTPConnectionPool, "_make_request", answer)
        monkeypatch.setattr(net._local, "session", None, raising=False)
        monkeypatch.setattr(urllib3_retry.time, "sleep", clock.advance)
        with net.Ledger() as ledger:
            with pytest.raises(net.SourceError, match="over the 60 s cap"):
                net.cached_get_json("https://www.wikidata.org/w/api.php", {"q": "x"})
        assert len(sent) == 1
        assert ledger.failed("Wikidata") == 1
        assert clock.t == 1000.0

    def test_the_session_retries_with_it(self, monkeypatch):
        monkeypatch.setattr(net._local, "session", None, raising=False)
        adapter = net.session().get_adapter("https://en.wikipedia.org/")
        assert isinstance(adapter.max_retries, net.RecordedRetry)


# ------------------------------------------------------- the slow note -----

def call(host, seconds=0.2, via="network", retries=(), error=None):
    return {"source": net._source(host), "host": host, "via": via, "seconds": seconds,
            "error": error, "retries": [dict(r) for r in retries]}


def ledger_of(*calls, wall=0.0):
    ledger = net.Ledger()
    ledger.calls = list(calls)
    ledger.wall = wall
    return ledger


class TestSlowCauses:
    def test_a_retry_after_wait_is_named_as_a_wait_and_not_again_as_slow(self):
        ledger = ledger_of(call("en.wikipedia.org", seconds=28.6, retries=[
            {"cause": "HTTP 429", "waited": 14.0}, {"cause": "HTTP 429", "waited": 14.0}]))
        causes = ledger.slow_causes()
        assert causes[0] == "en.wikipedia.org made it wait 28 s on Retry-After (HTTP 429 × 2)"
        assert not any("took" in c for c in causes)

    def test_retries_without_a_wait_are_counted_by_cause(self):
        ledger = ledger_of(
            call("opac.sbn.it", retries=[{"cause": "ConnectTimeoutError", "waited": 0.0}] * 2),
            call("opac.sbn.it", retries=[{"cause": "HTTP 503", "waited": 0.0}]))
        assert ledger.slow_causes()[0] == \
            "opac.sbn.it needed 3 retries (ConnectTimeoutError × 2, HTTP 503 × 1)"

    def test_a_slow_answer_is_named_with_its_time(self):
        ledger = ledger_of(call("openlibrary.org", seconds=14.9), call("openlibrary.org"))
        assert ledger.slow_causes()[0] == "openlibrary.org took 14.9 s to answer one request"

    def test_requests_sent_are_counted_per_source_and_cache_hits_are_not(self):
        ledger = ledger_of(call("opac.sbn.it", 0.3), call("opac.sbn.it", 0.3),
                           call("en.wikipedia.org", 0.1),
                           call("openlibrary.org", 5.0, via="cache"),
                           call("openlibrary.org", 5.0, via="fixture"))
        assert ledger.slow_causes() == ["requests sent: SBN 2 (0.6 s), Wikidata 1 (0.1 s)"]

    def test_a_clean_ledger_names_nothing_but_what_was_sent(self):
        """No retry, wait or slow answer happened, so none may be named."""
        causes = ledger_of(*[call("opac.sbn.it", 0.2)] * 150).slow_causes()
        assert causes == ["requests sent: SBN 150 (30.0 s)"]
        assert not re.search(r"wait|retr|took", " ".join(causes))

    def test_nothing_on_the_network_means_no_cause(self):
        assert ledger_of(call("opac.sbn.it", via="cache")).slow_causes() == []


def read(ledger, **sources) -> tuple:
    """The three readings, the way `app.jobs.Job.state` takes them: the source
    states, and the notes `core.notes` words — incomplete, then slow."""
    states = notes.source_states({"Wikidata": "ok", "Open Library": "ok", "SBN": "ok",
                                  **sources}, ledger.failed)
    said = [notes.incomplete(ledger.failed()),
            notes.slow(ledger.wall, ledger.slow_causes(), net.SLOW_LOOKUP_S)]
    return states, [n for n in said if n]


class TestReadings:
    def test_a_fast_lookup_says_nothing(self):
        states, said = read(ledger_of(call("opac.sbn.it"), wall=3.5))
        assert said == []
        assert set(states.values()) == {"ok"}

    def test_a_slow_lookup_names_its_measured_causes(self):
        _, said = read(ledger_of(call("openlibrary.org", seconds=14.9), wall=17.2))
        assert said[0].startswith("Slow lookup (17 s). Measured in it: openlibrary.org "
                                  "took 14.9 s to answer one request; requests sent: "
                                  "Open Library 1 (14.9 s).")

    def test_a_slow_lookup_with_nothing_sent_names_no_cause(self):
        _, said = read(ledger_of(call("opac.sbn.it", via="cache"), wall=11.0))
        assert said == ["Slow lookup (11 s), though no request in it went to the network."]

    def test_failures_degrade_only_the_source_that_lost_them(self):
        states, said = read(ledger_of(call("opac.sbn.it", error="x"),
                                      call("opac.sbn.it", error="y"),
                                      call("openlibrary.org"), wall=4.0))
        assert states == {"Wikidata": "ok", "Open Library": "ok",
                          "SBN": "partial (2 failed)"}
        assert said == [notes.incomplete(2)]

    def test_a_source_that_errored_outright_stays_errored(self):
        states, _ = read(ledger_of(call("www.wikidata.org", error="boom"), wall=2.0),
                         Wikidata="error: boom")
        assert states["Wikidata"] == "error: boom"


class TestEndToEnd:
    """Through the real HTTP helpers, with only the session and the clock faked."""

    def run(self, clock, cache, monkeypatch, seconds):
        answering(monkeypatch, FakeSession(clock, seconds=seconds))
        with net.Ledger() as ledger:
            # One worker: two sharing the fake clock would time each other.
            with net.Pool(max_workers=1) as pool:
                list(pool.map(lambda q: net.cached_get_json(OPEN_LIBRARY, {"q": q}),
                              ["noise", "rumori"]))
        return read(ledger)[1]

    def test_a_deliberately_slowed_run_gets_the_note(self, clock, cache, monkeypatch):
        said = self.run(clock, cache, monkeypatch, seconds=12.0)
        assert len(said) == 1
        assert "openlibrary.org took over 10 s to answer 2 requests (longest 12.0 s)" \
            in said[0]
        assert not re.search(r"wait|retr", said[0])

    def test_a_fast_run_does_not(self, clock, cache, monkeypatch):
        assert self.run(clock, cache, monkeypatch, seconds=0.3) == []
