"""`catalog/http.py` — the cache must refuse what its caller rejects (Step 3).

The bug this file pins: both SBN APIs answer a request they cannot run with
**HTTP 200 and a valid JSON body**, and a valid body is exactly what the disk
cache stores. Cached, the failure is replayed for the whole 24 h TTL — the
source stays `partial (1 request failed)` with no request having failed, and
"search again", which is the advice the page gives, cannot fill the gap.

The real body below is the one found in the working cache and in the Step 1C
regression cache, one per book for E04, N03 and N12, and reproduced live on
2026-09-18: a slash in an SBN free-text value opens a Solr regex literal that
is never closed. Nothing here is invented.

Offline by construction, like the rest of `tests/`: `session()` is faked, and
`conftest.py` would fail the run if anything opened a socket anyway.
"""

import gzip
import json

import pytest

from catalog import fixtures
from catalog import http as net
from catalog import sbn_opac as opac
from catalog.sbn_mobile import payload_error

# A body from the regression sweep's cache (U8), recorded
# 2026-09-18 for `title=Works (La tregua / Se questo è un uomo)&author=Levi`.
SOLR_ERROR = {"error": {"code": 0, "msg": "org.apache.solr.client.solrj."
                                          "SolrServerException: Error executing query"}}
# opacmobilegw/full.json?bid=ZZZ9999999, probed 2026-09-18 (F13). A real body,
# not an error: it must stay cacheable.
BOGUS_BID_SKELETON = {"numeri": [], "note": [], "nomi": [], "luogoNormalizzato": [],
                      "localizzazioni": [], "citazioni": [
                          {"standard": "mla", "valore": ","},
                          {"standard": "apa", "valore": "."}]}

URL = "https://opac.sbn.it/opacmobilegw/search.json"
PARAMS = {"title": "Die Verwandlung / la Metamorfosi", "author": "Kafka"}


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class FakeSession:
    """Answers with each body in turn, and counts the calls."""

    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.calls = 0

    def _next(self):
        self.calls += 1
        return FakeResponse(self.bodies[min(self.calls - 1, len(self.bodies) - 1)])

    def get(self, url, params=None, timeout=None):
        return self._next()

    def post(self, url, data=None, timeout=None):
        return self._next()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A cache directory of this test's own, never the project's."""
    monkeypatch.setattr(net, "CACHE_DIR", tmp_path)
    return tmp_path


def rejects_error(data):
    return payload_error(data)


class TestTheCacheRefusesWhatItsCallerRejects:
    def test_an_error_payload_is_never_written(self, cache, monkeypatch):
        monkeypatch.setattr(net, "session", lambda: FakeSession(SOLR_ERROR))
        with pytest.raises(net.SourceError):
            net.cached_get_json(URL, PARAMS, validate=rejects_error)
        assert list(cache.glob("*.json")) == []

    def test_a_good_payload_is_still_written(self, cache, monkeypatch):
        """The control: a hook that refused everything would pass the test above."""
        body = {"briefRecords": [{"codiceIdentificativo": "IT\\ICCU\\MIL\\0871878"}]}
        monkeypatch.setattr(net, "session", lambda: FakeSession(body))
        net.cached_get_json(URL, {"title": "Kafka sulla spiaggia"}, validate=rejects_error)
        written = list(cache.glob("*.json"))
        assert len(written) == 1
        assert json.loads(written[0].read_text(encoding="utf-8")) == body

    def test_a_replay_after_the_error_goes_back_to_the_network(self, cache, monkeypatch):
        """The whole point: the second lookup gets the answer, not the failure."""
        good = {"briefRecords": [], "facetRecords": []}
        session = FakeSession(SOLR_ERROR, good)
        monkeypatch.setattr(net, "session", lambda: session)

        with pytest.raises(net.SourceError):
            net.cached_get_json(URL, PARAMS, validate=rejects_error)
        assert net.cached_get_json(URL, PARAMS, validate=rejects_error) == good
        assert session.calls == 2

    def test_a_body_cached_before_this_hook_existed_is_dropped_on_sight(self, cache, monkeypatch):
        """There are three such files in the working cache and three more in
        the regression sweep's cache (U8). Re-reading one would keep reporting the failure
        for the rest of its TTL, which is the behaviour being ended."""
        poisoned = net._cache_path(URL, PARAMS)
        poisoned.write_text(json.dumps(SOLR_ERROR), encoding="utf-8")
        good = {"briefRecords": [], "facetRecords": []}
        monkeypatch.setattr(net, "session", lambda: FakeSession(good))

        assert net.cached_get_json(URL, PARAMS, validate=rejects_error) == good
        assert json.loads(poisoned.read_text(encoding="utf-8")) == good

    def test_a_post_payload_with_no_data_object_is_never_written(self, cache, monkeypatch):
        monkeypatch.setattr(net, "session", lambda: FakeSession({"status": "ko"}))
        with pytest.raises(net.SourceError):
            net.cached_post_json(opac.SEARCH, {"core": "sbn"}, validate=opac.no_data)
        assert list(cache.glob("*.json")) == []

    def test_no_validator_means_the_old_behaviour(self, cache, monkeypatch):
        """Wikidata, Wikipedia and Open Library pass none, and are unchanged."""
        monkeypatch.setattr(net, "session", lambda: FakeSession(SOLR_ERROR))
        assert net.cached_get_json(URL, PARAMS) == SOLR_ERROR
        assert len(list(cache.glob("*.json"))) == 1

    def test_an_error_payload_in_the_fixture_bundle_raises_too(self, tmp_path, monkeypatch):
        """Offline must fail where live fails, or the replay measures nothing.

        The committed bundle holds no error payload — 0 of its 2,707 bodies —
        so this is a property, not a description of it.
        """
        bodies = tmp_path / "bodies"
        bodies.mkdir()
        key = net._cache_key(URL, {"title": PARAMS["title"], "author": PARAMS["author"]})
        with gzip.open(bodies / f"{key}.json.gz", "wb") as fh:
            fh.write(json.dumps(SOLR_ERROR).encode("utf-8"))
        monkeypatch.setenv("BOOK_FIXTURES", str(tmp_path))
        fixtures.reset()
        try:
            with pytest.raises(net.SourceError):
                net.cached_get_json(URL, PARAMS, validate=rejects_error)
        finally:
            fixtures.reset()


class TestWhatCountsAsAnError:
    def test_the_recorded_solr_error_is_rejected(self):
        assert "SolrServerException" in payload_error(SOLR_ERROR)

    def test_a_bogus_bid_skeleton_is_not_an_error(self):
        """F13: `full.json` answers an unknown BID with a real, empty record.
        Rejecting it would refuse a body the catalogue actually means."""
        assert payload_error(BOGUS_BID_SKELETON) is None

    def test_an_ordinary_result_is_not_an_error(self):
        assert payload_error({"numFound": 0, "briefRecords": [],
                                   "facetRecords": []}) is None

    def test_an_empty_error_field_is_not_an_error(self):
        """`{"error": {}}` has never been seen; falsy is falsy, and inventing a
        rejection here would be the same mistake in the other direction."""
        assert payload_error({"error": {}}) is None

    def test_the_opac_needs_a_data_object(self):
        assert opac.no_data({"status": "ok", "data": {"total": 13}}) is None
        assert opac.no_data({"status": "ok"}) is not None
        assert opac.no_data({"status": "ok", "data": None}) is not None
        assert opac.no_data([]) is not None
