"""The wire: what `POST /lookup` and `GET /lookup/<id>?v=N` actually return.

The handler is driven over a **fake connection** rather than a loopback socket,
so `conftest.py`'s ban on opening one stands untouched: this suite still cannot
reach a catalogue, and nothing here has to be trusted not to. What is exercised
is the real `BaseHTTPRequestHandler` machinery — request line, headers,
`Content-Length`, the gzip negotiation — against the real handler.

The stages are stubbed, for the reason `test_app_jobs.py` gives.
"""

import gzip
import io
import json
import threading
from http.client import HTTPResponse

import pytest

from app import jobs
from app.server import Handler
from core.model import Provenance, Record


class _Connection:
    """Enough of a socket for `StreamRequestHandler`: read the request from
    bytes, collect the response into a buffer."""

    def __init__(self, request: bytes):
        self._in, self.out = io.BytesIO(request), io.BytesIO()

    def makefile(self, mode="rb", *args, **kwargs):
        return self._in if "r" in mode else self.out

    def sendall(self, data):
        self.out.write(data)

    def close(self):
        pass


class _Response:
    def __init__(self, raw: bytes):
        parsed = HTTPResponse(_Connection(raw))
        parsed.begin()
        self.status = parsed.status
        self.headers = parsed.headers
        self.raw = parsed.read()

    @property
    def body(self):
        data = self.raw
        if self.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data.decode("utf-8"))


def call(method, path, body=None, accept_gzip=True) -> _Response:
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    lines = [f"{method} {path} HTTP/1.1", "Host: localhost"]
    if accept_gzip:
        lines.append("Accept-Encoding: gzip")
    if payload:
        lines += ["Content-Type: application/json",
                  f"Content-Length: {len(payload)}"]
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + payload
    connection = _Connection(raw)
    Handler(connection, ("127.0.0.1", 51234), object())
    return _Response(connection.out.getvalue())


def record(bid):
    return Record(source="SBN", id=bid, title="Uno", language="ita", year="1980",
                  publisher="Einaudi",
                  provenance=Provenance("SBN", "work listing", "uniform title"))


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    own = jobs.Registry()
    monkeypatch.setattr(Handler, "registry", own)
    yield own
    own.close()


@pytest.fixture
def one_row(monkeypatch):
    """One stage, one record, one version — the shape S2 publishes."""
    def run(job):
        job.store.put(record("IT001"))
    monkeypatch.setattr(jobs, "STAGES",
                        (jobs.Stage("listing the editions", run, publishes=True),))


def settled(registry, job_id):
    from tests.test_app_jobs import settled as wait
    return wait(registry.get(job_id))


class TestStart:

    def test_post_hands_back_an_id_and_a_poll_url(self, one_row, registry):
        answer = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"})
        assert answer.status == 202          # accepted: the work has not happened
        body = answer.body
        assert body["version"] == 0
        assert body["poll"] == f"/lookup/{body['id']}?v=0"
        settled(registry, body["id"])

    def test_it_returns_before_the_stages_do(self, monkeypatch, registry):
        """The whole point of the shape: the id comes back at once, not at the
        end of a lookup. Here the first stage is still blocked when it does."""
        entered, release = threading.Event(), threading.Event()

        def blocked(job):
            entered.set()
            release.wait(5)

        monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("a", blocked, publishes=True),))
        answer = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"})
        assert answer.status == 202
        assert entered.wait(5)
        assert registry.get(answer.body["id"]).version == 0
        release.set()

    def test_the_query_string_works_too(self, one_row, registry):
        answer = call("POST", "/lookup?title=Uno&author=Tizio")
        assert answer.status == 202
        settled(registry, answer.body["id"])

    def test_what_it_refuses_to_ask(self):
        answer = call("POST", "/lookup", {})
        assert answer.status == 400 and "give a title and an author" in answer.body["error"]

    def test_a_title_alone_is_asked_whose_book_it_is(self, one_row, registry, monkeypatch):
        """Decision AN. The job asks S0 first; the OPAC is never asked without
        an author (`CLAUDE.md` rule 3), which `test_app_jobs` holds."""
        asked = []
        monkeypatch.setattr(jobs.stages, "title_books", lambda title: asked.append(title) or {
            "books": [], "candidates": 0, "sources": {}})
        answer = call("POST", "/lookup", {"title": "Uno"})
        assert answer.status == 202
        settled(registry, answer.body["id"])
        assert asked == ["Uno"]

    def test_the_spelling_switches_are_passed_on(self, one_row, registry):
        answer = call("POST", "/lookup", {"title": "Uno", "author": "Tizio",
                                          "title_spellings": True})
        assert answer.status == 202
        job = registry.get(answer.body["id"])
        assert (job.title_spellings, job.author_spellings) == (True, False)
        settled(registry, answer.body["id"])

    def test_a_switch_that_is_not_a_boolean_is_a_400(self):
        answer = call("POST", "/lookup", {"title": "Uno", "author": "Tizio",
                                          "author_spellings": "yes"})
        assert answer.status == 400 and "author_spellings" in answer.body["error"]

    def test_a_body_that_is_not_json_is_a_400_not_a_500(self):
        raw = (b"POST /lookup HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\nnope!")
        connection = _Connection(raw)
        Handler(connection, ("127.0.0.1", 1), object())
        answer = _Response(connection.out.getvalue())
        assert answer.status == 400 and "not JSON" in answer.body["error"]


class TestPoll:

    def test_a_version_behind_gets_the_whole_view(self, one_row, registry):
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        settled(registry, job_id)
        answer = call("GET", f"/lookup/{job_id}?v=0")
        assert answer.status == 200
        body = answer.body
        assert body["version"] == 1
        assert [r["id"] for r in body["editions_by_language"]["ita"]] == ["SBN:IT001"]
        assert body["job"]["done"] is True and body["job"]["status"] == "done"

    def test_the_same_version_again_is_unchanged(self, one_row, registry):
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        settled(registry, job_id)
        answer = call("GET", f"/lookup/{job_id}?v=1")
        assert answer.status == 200
        assert answer.body["unchanged"] is True
        assert "editions_by_language" not in answer.body
        assert int(answer.headers["Content-Length"]) < 400

    def test_a_missing_or_unreadable_v_sends_what_there_is(self, one_row, registry):
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        settled(registry, job_id)
        for path in (f"/lookup/{job_id}", f"/lookup/{job_id}?v=later"):
            assert call("GET", path).body["version"] == 1

    def test_an_unknown_job_is_a_404_and_not_an_empty_result(self, registry):
        """It was evicted, or the server was restarted. A page that cannot
        tell that from `nothing found` shows a stale list as though live."""
        answer = call("GET", "/lookup/deadbeef?v=0")
        assert answer.status == 404 and answer.body["error"] == "no such job"

    def test_an_evicted_job_stops_being_served(self, one_row, registry):
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        settled(registry, job_id)
        registry.close()
        assert call("GET", f"/lookup/{job_id}?v=0").status == 404


class TestWire:

    def test_a_snapshot_is_gzipped_when_the_client_takes_it(self, monkeypatch, registry):
        """The worst case measured is *Odysseia* at 1,134.6 KB of JSON and
        96.3 KB gzipped, and every version replaces the last one."""
        def run(job):
            for n in range(400):
                job.store.put(record(f"IT{n:04d}"))
        monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("a", run, publishes=True),))
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        settled(registry, job_id)

        zipped = call("GET", f"/lookup/{job_id}?v=0", accept_gzip=True)
        plain = call("GET", f"/lookup/{job_id}?v=0", accept_gzip=False)
        assert zipped.headers["Content-Encoding"] == "gzip"
        assert plain.headers.get("Content-Encoding") is None
        assert zipped.body == plain.body
        assert len(zipped.raw) * 4 < len(plain.raw)

    def test_a_small_answer_is_not_gzipped(self, one_row, registry):
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        settled(registry, job_id)
        answer = call("GET", f"/lookup/{job_id}?v=1")
        assert answer.headers.get("Content-Encoding") is None

    def test_health_and_the_endpoints_that_do_not_exist(self, registry):
        assert call("GET", "/health").body == {"ok": True, "jobs": 0}
        assert call("GET", "/nope").status == 404
        assert call("POST", "/nope", {"title": "a", "author": "b"}).status == 404


class TestOpeningOneRow:
    """`GET /lookup/<id>/edition/<edition id>` — Step 10's expand.

    Job-scoped on purpose: the row belongs to a snapshot, the snapshot to a job
    whose store still holds the records behind it. So the server reads the row
    rather than having the page re-send it, and a row that has since become a
    different edition is a 404 rather than the wrong book.
    """

    @pytest.fixture
    def opened(self, monkeypatch):
        """No catalogue is stubbed: an SBN-only row fetches nothing, and
        `conftest.py`'s socket ban is what proves it."""
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        return job_id

    def test_a_row_comes_back_whole(self, one_row, registry, opened):
        settled(registry, opened)
        answer = call("GET", f"/lookup/{opened}/edition/SBN:IT001")
        assert answer.status == 200
        assert answer.body["id"] == "SBN:IT001"
        assert answer.body["buy_links"] == []            # no ISBN on the row
        assert answer.body["evidence"]["asked"] is False

    def test_the_network_reading_travels_with_it(self, one_row, registry, opened):
        """A request that failed must be distinguishable from an empty answer,
        so the counts come back even when nothing was asked (rule 5)."""
        settled(registry, opened)
        body = call("GET", f"/lookup/{opened}/edition/SBN:IT001").body
        assert body["requests"] == 0 and body["failed"] == 0

    def test_an_unknown_row_is_a_404_and_not_the_nearest_thing(self, one_row,
                                                               registry, opened):
        settled(registry, opened)
        answer = call("GET", f"/lookup/{opened}/edition/SBN:NOPE")
        assert answer.status == 404 and "no such edition" in answer.body["error"]

    def test_an_unknown_job_is_a_404(self, registry):
        assert call("GET", "/lookup/deadbeef/edition/SBN:IT001").status == 404

    def test_an_id_with_a_slash_in_it_survives_the_url(self, one_row, registry, opened):
        """A synthetic id is `source:record id` and Open Library's keys are
        clean, but the encoding has to hold whatever a catalogue puts in one."""
        settled(registry, opened)
        answer = call("GET", f"/lookup/{opened}/edition/SBN%3AIT001")
        assert answer.status == 200 and answer.body["id"] == "SBN:IT001"

    def test_a_path_under_lookup_that_is_not_an_edition_is_a_404(self, registry):
        assert call("GET", "/lookup/deadbeef/nonsense").status == 404


class TestThePage:
    """`app/web/` on the same origin as the JSON, because SBN sends no
    `Access-Control-Allow-Origin` header of any kind and a browser therefore
    cannot reach it from a static page."""

    def test_the_root_is_the_page(self, registry):
        answer = call("GET", "/")
        assert answer.status == 200
        assert answer.headers["Content-Type"].startswith("text/html")
        assert b"<title>Book editions</title>" in answer.raw

    def test_the_module_is_served_as_javascript(self, registry):
        answer = call("GET", "/filters.js")
        assert answer.status == 200
        assert "javascript" in answer.headers["Content-Type"]

    @pytest.mark.parametrize("path", [
        "/../app/server.py", "/%2e%2e/server.py", "/nope.js",
    ])
    def test_nothing_above_the_web_root_is_served(self, registry, path):
        assert call("GET", path).status == 404

    def test_the_api_is_not_shadowed_by_a_file(self, registry):
        assert call("GET", "/api/anything").status == 404
