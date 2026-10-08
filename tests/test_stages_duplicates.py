"""Open Library's other records for the work — the stage, the Add, the wire (Step 13).

Open Library is stubbed: the list's rule is `core.identity.duplicate_works`'s
and is tested in `test_core_identity.py`, and what is tested here is the wiring
around it — what is searched with, that a search that fails says so rather than
listing nothing, that nothing is looked for without a main work, that an Add
opens the record **by key** and only a record on the list, and that a record
which failed to open is marked failed and never shown as one with no editions.

The docs and titles are E16's, as Step 13's live run
recorded them on 2026-09-25.
"""

import pytest

from app import jobs
from catalog.http import SourceError
from core.model import DUPLICATE_WORK, Provenance, Record, Work
from core.store import RecordStore
from lookup import stages
from tests.test_app_jobs import settled
from tests.test_app_server import call, registry  # noqa: F401 — the fixture

TITLES = {"rus": "Доктор Живаго", "eng": "Doctor Zhivago"}


class _Identity:
    def __init__(self, work=None, typed="Doktor Zhivago"):
        self.work = work or Work(ol_keys=["OL258301W"], original_title="Доктор Живаго",
                                 original_language="rus", titles_by_lang=dict(TITLES))
        self.evidence = {"question": {"typed_title": typed, "typed_author": "Pasternak"},
                         "ol_author_keys": {"keys": []}}


def doc(key, title, count, author="Boris Pasternak"):
    return {"key": f"/works/{key}", "title": title, "author_name": [author],
            "edition_count": count, "language": ["eng"], "first_publish_year": 1958}


ANSWERS = {
    "Доктор Живаго Pasternak": [doc("OL258301W", "Доктор Живаго", 176)],
    "Doctor Zhivago Pasternak": [doc("OL31357567W", "Doctor Zhivago", 13),
                                 doc("OL31702700W", "The Poems Of Doctor Zhivago", 5),
                                 doc("OL19743505W", "Lara", 6)],
    "Doktor Zhivago Pasternak": [doc("OL31431616W", "Doktor Zhivago", 2)],
}


@pytest.fixture
def searched(monkeypatch):
    asked = []

    def search_counted(q, limit):
        asked.append(q)
        if q not in ANSWERS:
            raise SourceError(f"{q}: 503")
        docs = ANSWERS[q]
        return {"docs": docs, "total": len(docs) + (100 if "Doctor" in q else 0)}
    monkeypatch.setattr(stages.ol, "search_counted", search_counted)
    return asked


def edition(key, title, language="eng", year="1958"):
    return {"key": f"/books/{key}", "title": title, "publish_date": year,
            "languages": [{"key": f"/languages/{language}"}], "publishers": ["Pantheon"]}


@pytest.fixture
def opened(monkeypatch):
    asked = []
    books = {"OL31357567W": [edition("OL1M", "Doctor Zhivago"),
                             edition("OL2M", "Doctor Zhivago", year="1959")],
             "OL31702700W": [edition("OL3M", "The Poems of Doctor Zhivago", year="1967")]}

    def editions(key):
        asked.append(key)
        if key == "OL31431616W":
            raise SourceError("503")
        if key == "OL31702700W" and asked.count(key) == 1:
            return {"rows": [], "size": 1, "failed": ["page 2: timed out"]}
        from catalog.openlibrary import parse_edition
        return {"rows": [parse_edition(e) for e in books.get(key, [])],
                "size": len(books.get(key, [])), "failed": []}
    monkeypatch.setattr(stages.ol, "editions", editions)
    return asked


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------

class TestFinding:
    def test_it_searches_every_title_of_the_work_then_the_typed_one(self, searched):
        found = stages.find_duplicates(_Identity()).evidence
        assert searched == ["Доктор Живаго Pasternak", "Doctor Zhivago Pasternak",
                            "Doktor Zhivago Pasternak"]
        assert [q["by"] for q in found["queries"]] == ["work title", "work title",
                                                       "typed title"]

    def test_a_typed_title_the_work_already_has_is_not_asked_twice(self, searched):
        stages.find_duplicates(_Identity(typed="doctor zhivago"))
        assert searched == ["Доктор Живаго Pasternak", "Doctor Zhivago Pasternak"]

    def test_it_lists_what_the_tests_pass_and_never_the_main_work(self, searched):
        rows = stages.find_duplicates(_Identity()).evidence["rows"]
        assert [r["key"] for r in rows] == ["OL31357567W", "OL31702700W", "OL31431616W"]

    def test_it_records_how_much_of_each_answer_it_read(self, searched):
        queries = stages.find_duplicates(_Identity()).evidence["queries"]
        assert [(q["docs"], q["total"]) for q in queries] == [(1, 1), (3, 103), (1, 1)]

    def test_a_search_that_failed_is_not_a_search_that_found_nothing(self, searched,
                                                                     monkeypatch):
        """Rule 5: the source is in error and the query says which."""
        monkeypatch.delitem(ANSWERS, "Doktor Zhivago Pasternak")
        found = stages.find_duplicates(_Identity()).evidence
        assert found["sources"]["Open Library"].startswith("error:")
        assert "503" in found["queries"][-1]["error"]
        assert [r["key"] for r in found["rows"]] == ["OL31357567W", "OL31702700W"]

    def test_with_no_main_work_nothing_is_looked_for_and_it_says_why(self, searched):
        found = stages.find_duplicates(_Identity(work=Work(titles_by_lang=TITLES))).evidence
        assert searched == [] and found["asked"] is False and found["rows"] == []
        assert "no Open Library work" in found["why_not"]


class TestAdding:
    def listed(self, searched):
        return stages.find_duplicates(_Identity()).evidence

    def test_it_opens_the_record_by_key_and_labels_what_it_puts_in(self, searched, opened):
        store = RecordStore()
        out = stages.add_duplicates(_Identity(), store, self.listed(searched), ["OL31357567W"])
        assert opened == ["OL31357567W"] and out["added"] == ["OL31357567W"]
        assert out["rows"] == 2
        assert {r.provenance for r in store.records()} == {
            Provenance("Open Library", DUPLICATE_WORK, DUPLICATE_WORK, via="OL31357567W")}

    def test_a_key_that_is_not_on_the_list_is_refused_not_opened(self, searched, opened):
        """The list is what the title and author tests passed; opening any key
        at all would be a route around them."""
        with pytest.raises(KeyError):
            stages.add_duplicates(_Identity(), RecordStore(), self.listed(searched),
                                  ["OL19743505W"])
        assert opened == []

    def test_a_record_that_failed_to_open_is_failed_whole(self, searched, opened):
        """A page that failed part way leaves the record *not added*, not half
        in the list with nothing saying which half."""
        store = RecordStore()
        out = stages.add_duplicates(_Identity(), store, self.listed(searched),
                                    ["OL31431616W", "OL31702700W"])
        assert out["added"] == [] and len(store) == 0
        assert set(out["failed"]) == {"OL31431616W", "OL31702700W"}

    def test_one_already_added_is_not_fetched_again(self, searched, opened):
        listed = {**self.listed(searched), "added": ["OL31357567W"]}
        out = stages.add_duplicates(_Identity(), RecordStore(), listed,
                                    ["OL31357567W", "OL31357567W"])
        assert opened == [] and out["asked"] == []

    def test_a_language_the_record_contradicts_is_disbelieved_here_too(self, searched,
                                                                       monkeypatch):
        """Rule 4, on the same terms as S2's Open Library rows."""
        from catalog.openlibrary import parse_edition
        row = parse_edition({**edition("OL9M", "Doctor Zhivago", language="rus"),
                             "by_statement": "translated by Max Hayward"})
        row["translators"] = ["Hayward, Max"]
        monkeypatch.setattr(stages.ol, "editions",
                            lambda key: {"rows": [row], "size": 1, "failed": []})
        store = RecordStore()
        out = stages.add_duplicates(_Identity(), store, self.listed(searched), ["OL31357567W"])
        assert [n["record"] for n in out["language_disbelieved"]] == ["OL9M"]
        assert store.records()[0].language == "unknown"


# ---------------------------------------------------------------------------
# The job and the wire
# ---------------------------------------------------------------------------

def _listed(job):
    job.identity = _Identity()
    job.work = job.identity.work
    job.store.put(Record(source="Open Library", id="OL0M", title="Доктор Живаго",
                         language="rus", year="1957",
                         provenance=Provenance("Open Library", "work editions", "work key")))
    job.evidence["duplicates"] = stages.find_duplicates(job.identity).evidence


@pytest.fixture
def one_lookup(monkeypatch, searched, opened):
    monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("grouping", _listed, publishes=True),))


class TestTheJob:
    def test_an_add_publishes_a_new_version_holding_the_rows(self, one_lookup):
        job = settled(_started())
        out = job.add(["OL31357567W"])
        assert out["version"] == 2 and job.version == 2
        snap = job.since(1)
        assert snap["header"]["total_editions"] == 1 and snap["header"]["added"] == 2
        assert [r["added"] for r in snap["duplicate_works"]["rows"]] == [True, False, False]

    def test_a_failure_is_marked_and_a_retry_clears_it(self, one_lookup):
        job = settled(_started())
        job.add(["OL31702700W"])
        row = job.since(0)["duplicate_works"]["rows"][1]
        assert row["key"] == "OL31702700W" and row["failed"] and not row["added"]
        job.add(["OL31702700W"])
        row = job.since(0)["duplicate_works"]["rows"][1]
        assert row["added"] and row["failed"] is None

    def test_no_add_while_the_lookup_is_running(self):
        job = jobs.Job("Doktor Zhivago", "Pasternak")
        with pytest.raises(RuntimeError):
            job.add(["OL31357567W"])


def _started():
    job = jobs.Job("Doktor Zhivago", "Pasternak")
    job.start()
    return job


class TestTheWire:
    def start(self, registry):
        job_id = call("POST", "/lookup", {"title": "Doktor Zhivago",
                                          "author": "Pasternak"}).body["id"]
        settled(registry.get(job_id))
        return job_id

    def test_add_answers_with_the_version_and_the_network_reading(self, one_lookup,
                                                                 registry):
        job_id = self.start(registry)
        answer = call("POST", f"/lookup/{job_id}/add", {"keys": ["OL31357567W"]})
        assert answer.status == 200
        assert answer.body["added"] == ["OL31357567W"] and answer.body["version"] == 2
        assert answer.body["failed_requests"] == 0
        assert call("GET", f"/lookup/{job_id}?v=1").body["header"]["added"] == 2

    @pytest.mark.parametrize("body", [{}, {"keys": []}, {"keys": "OL1W"}, {"keys": [3]}])
    def test_what_it_refuses_to_add(self, one_lookup, registry, body):
        assert call("POST", f"/lookup/{self.start(registry)}/add", body).status == 400

    def test_a_key_off_the_list_is_a_400(self, one_lookup, registry):
        answer = call("POST", f"/lookup/{self.start(registry)}/add",
                      {"keys": ["OL19743505W"]})
        assert answer.status == 400 and "not on this lookup's list" in answer.body["error"]

    def test_an_unknown_job_is_a_404(self, registry):
        assert call("POST", "/lookup/deadbeef/add", {"keys": ["OL1W"]}).status == 404

    def test_a_running_job_is_a_409(self, monkeypatch, registry, searched):
        import threading
        gate = threading.Event()
        monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("wait", lambda job: gate.wait(5)),))
        job_id = call("POST", "/lookup", {"title": "x", "author": "y"}).body["id"]
        try:
            assert call("POST", f"/lookup/{job_id}/add", {"keys": ["OL1W"]}).status == 409
        finally:
            gate.set()
