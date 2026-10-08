"""Author mode over the transport, with the stages stubbed (Step 14, UC4).

What is tested is the job's shape, not a lookup: an author job offers its
people as v1 and **waits**; one person on every form goes straight on (decision
AJ); the reader's pick is refused for an id the job never offered or at a
moment it is not waiting; both runs land on one ledger; and a stage that raises
fails the job rather than the server.
"""

import pytest

from app import jobs
from core.authors import Candidate
from lookup import stages
from tests.test_app_jobs import settled
from tests.test_app_server import call, registry  # noqa: F401 — the fixture


def resolution(skip):
    people = [Candidate("CFIV034892", "Bateson , Gregory", agrees=True, records=134),
              Candidate("RT1V031559", "Finke , Peter  <1942->")]
    return stages.AuthorResolution(
        candidates=people, resolved="CFIV034892", skip=skip, person=None,
        evidence={"typed": "Gregory Bateson", "forms": ["Gregory Bateson"],
                  "sources": {"SBN": "ok", "Wikidata": "ok"}})


WORKS = stages.WorkList(
    works=[{"key": "Q1970551", "title": "Steps to an Ecology of Mind"}],
    contributed=[], band=[],
    evidence={"sbn": [{"name": "Gregory Bateson", "total": 134, "covered": 100,
                       "split": True}],
              "sources": {"SBN": "ok", "Wikidata": "ok", "Open Library": "ok"}})


@pytest.fixture
def stubbed(monkeypatch):
    listed = []

    def list_works(res, ids, year):
        listed.append(list(ids))
        return WORKS
    monkeypatch.setattr(stages, "list_works", list_works)
    return listed


def waiting(job, timeout=5.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.state()["choosing"] or job.state()["done"]:
            return job
        time.sleep(0.005)
    raise AssertionError(job.state())


class TestTheJob:

    def test_one_person_goes_straight_to_the_works(self, monkeypatch, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(True))
        job = jobs.AuthorJob("Byung-Chul Han")
        job.start()
        settled(job)
        view = job.since(0)
        assert stubbed == [["CFIV034892"]] and view["version"] == 2
        assert view["mode"] == "author" and view["works"][0]["title"].startswith("Steps")
        assert view["truncations"][0].startswith("SBN lists at most 50 works")
        assert view["job"]["status"] == "done"

    def test_several_people_wait_for_the_reader(self, monkeypatch, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(False))
        job = jobs.AuthorJob("Gregory Bateson")
        job.start()
        waiting(job)
        view = job.since(0)
        assert view["job"]["choosing"] and not view["job"]["done"]
        assert [p["id"] for p in view["people"]] == ["CFIV034892", "RT1V031559"]
        assert view["works"] is None and stubbed == []
        job.choose(["CFIV034892"])
        settled(job)
        assert stubbed == [["CFIV034892"]] and job.since(1)["chosen"] == ["CFIV034892"]

    def test_a_pick_it_never_offered_is_refused(self, monkeypatch, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(False))
        job = waiting(_started("Gregory Bateson"))
        with pytest.raises(KeyError):
            job.choose(["ZZQX999999"])
        with pytest.raises(KeyError):
            job.choose([])
        job.choose(["CFIV034892"])
        with pytest.raises(RuntimeError):
            job.choose(["CFIV034892"])
        settled(job)

    def test_a_stage_that_raises_fails_the_job(self, monkeypatch):
        def boom(typed):
            raise RuntimeError("catalogue on fire")
        monkeypatch.setattr(stages, "resolve_author", boom)
        job = _started("x")
        settled(job)
        assert job.state()["status"] == "failed" and "on fire" in job.state()["error"]

    def test_a_cancelled_job_lists_nothing(self, monkeypatch, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(False))
        job = waiting(_started("Gregory Bateson"))
        job.cancel()
        job.choose(["CFIV034892"])
        import time
        time.sleep(0.05)
        assert stubbed == []


def _started(name):
    job = jobs.AuthorJob(name)
    job.start()
    return job


class TestTheWire:

    def test_an_author_alone_starts_an_author_job(self, monkeypatch, registry, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(False))
        answer = call("POST", "/lookup", {"author": "Gregory Bateson"})
        assert answer.status == 202
        job = waiting(registry.get(answer.body["id"]))
        assert call("POST", f"/lookup/{job.id}/choose", {"ids": ["ZZQX"]}).status == 400
        assert call("POST", f"/lookup/{job.id}/choose", {"ids": "CFIV034892"}).status == 400
        chose = call("POST", f"/lookup/{job.id}/choose", {"ids": ["CFIV034892"]})
        assert chose.status == 202 and chose.body["id"] == job.id
        settled(job)
        assert call("POST", f"/lookup/{job.id}/choose", {"ids": ["CFIV034892"]}).status == 409
        assert call("GET", f"/lookup/{job.id}?v=0").body["works"]

    def test_a_title_lookup_is_not_waiting_for_a_choice(self, monkeypatch, registry):
        monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("a", lambda job: None),))
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        assert call("POST", f"/lookup/{job_id}/choose", {"ids": ["X"]}).status == 409

    def test_an_unknown_job_and_an_unreadable_body(self, registry):
        assert call("POST", "/lookup/nope/choose", {"ids": ["X"]}).status == 404


CUT = {"read": [{"id": "CFIV034892", "total": 2575, "read": 500, "truncated": True,
                  "failed": 0}], "rows": 1, "records": 1}


class TestReadTheRest:
    """Decision BA: the records past the cap under the name, on demand, on the
    job's ledger, refused unless the works are listed and the cap cut something."""

    @pytest.fixture
    def cut(self, monkeypatch):
        import dataclasses
        works = dataclasses.replace(WORKS, unlinked=[{"title": "Naven"}],
                                    evidence={**WORKS.evidence, "unlinked": CUT})
        monkeypatch.setattr(stages, "list_works", lambda res, ids, year: works)
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(True))
        read = []

        def read_rest(w, year):
            read.append(w)
            return dataclasses.replace(
                w, unlinked=[{"title": "Naven"}, {"title": "Mind and nature"}],
                evidence={**w.evidence, "unlinked": {**CUT, "read": [
                    {**CUT["read"][0], "read": 2575, "truncated": False}]}})
        monkeypatch.setattr(stages, "read_rest", read_rest)
        return read

    def test_the_group_is_drawn_again_as_a_new_version(self, cut):
        job = settled(_started("Gregory Bateson"))
        before = job.since(0)
        assert before["unread"] == {"records": 2075, "pages": 104}
        assert before["truncations"][-1].startswith("read 500 of 2,575 records")
        job.read_rest()
        settled(job)
        after = job.since(before["version"])
        assert after["version"] == before["version"] + 1 and len(cut) == 1
        assert [u["title"] for u in after["unlinked"]] == ["Naven", "Mind and nature"]
        assert after["unread"] is None and after["works"] == before["works"]
        assert not any(t.startswith("read 500") for t in after["truncations"])
        assert after["job"]["status"] == jobs.DONE

    def test_refused_while_running_and_once_read(self, cut):
        job = waiting(_started("Gregory Bateson"))
        settled(job)
        job.read_rest()
        with pytest.raises(RuntimeError):
            job.read_rest()
        settled(job)
        with pytest.raises(RuntimeError, match="every record"):
            job.read_rest()
        assert len(cut) == 1

    def test_nothing_cut_is_refused(self, monkeypatch, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(True))
        job = settled(_started("Byung-Chul Han"))
        assert job.since(0)["unread"] is None
        with pytest.raises(RuntimeError):
            job.read_rest()

    def test_no_thread_outlives_the_read(self, cut):
        import time
        from tests.test_app_jobs import threads_of
        job = settled(_started("Gregory Bateson"))
        job.read_rest()
        settled(job)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and threads_of(job):
            time.sleep(0.01)
        assert not threads_of(job)

    def test_on_the_wire(self, cut, registry):
        job_id = call("POST", "/lookup", {"author": "Gregory Bateson"}).body["id"]
        job = settled(registry.get(job_id))
        answer = call("POST", f"/lookup/{job_id}/more", {})
        assert answer.status == 202 and answer.body["id"] == job_id
        settled(job)
        assert call("POST", f"/lookup/{job_id}/more", {}).status == 409
        assert call("POST", "/lookup/nope/more", {}).status == 404

    def test_the_body_is_read_off_a_kept_alive_connection(self, cut, registry):
        """The page sends `{}`. Left unread, it opened the next request on the
        same connection — `{}GET /lookup/…`, a 501 — and the page stopped polling."""
        from app.server import Handler
        from tests.test_app_server import _Connection, _Response
        job_id = call("POST", "/lookup", {"author": "Gregory Bateson"}).body["id"]
        job = settled(registry.get(job_id))
        poll = f"GET /lookup/{job_id}?v=0 HTTP/1.1\r\nHost: localhost\r\n\r\n"
        raw = (f"POST /lookup/{job_id}/more HTTP/1.1\r\nHost: localhost\r\n"
               "Content-Type: application/json\r\nContent-Length: 2\r\n\r\n{}" + poll)
        connection = _Connection(raw.encode("utf-8"))
        Handler(connection, ("127.0.0.1", 51234), object())
        settled(job)
        out = connection.out.getvalue()
        first = _Response(out)
        assert first.status == 202
        second = _Response(out[out.index(b"HTTP/1.1", 1):])
        assert second.status == 200 and second.body["job"]["id"] == job_id

    def test_a_title_lookup_reads_under_no_name(self, monkeypatch, registry):
        monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("a", lambda job: None),))
        job_id = call("POST", "/lookup", {"title": "Uno", "author": "Tizio"}).body["id"]
        assert call("POST", f"/lookup/{job_id}/more", {}).status == 409


class TestSpellingsOnTheWire:

    def test_the_spellings_reach_the_identify_stage(self, monkeypatch, registry):
        seen = {}

        def identify(job):
            seen["variants"] = job.variants
        monkeypatch.setattr(jobs, "STAGES", (jobs.Stage("identifying the work", identify),))
        answer = call("POST", "/lookup", {"title": "bain el-qasrain", "author": "Naguib Mahfouz",
                                          "variants": ["bayn al-qasrayn", "Palace Walk"]})
        assert answer.status == 202
        settled(registry.get(answer.body["id"]))
        assert seen["variants"] == ["bayn al-qasrayn", "Palace Walk"]

    @pytest.mark.parametrize("variants", ["bayn", [1], [""], ["x"] * 13])
    def test_malformed_spellings_are_refused(self, variants, registry):
        answer = call("POST", "/lookup", {"title": "t", "author": "a", "variants": variants})
        assert answer.status == 400 and "spellings" in answer.body["error"]


class TestRunToEnd:
    """`jobs.run_to_end` — the CLI's and the sweeps' lookup, with no page to
    wait for a choice: it goes on with the person the page would have ticked."""

    def test_a_waiting_author_job_goes_on_with_the_ticked_person(self, monkeypatch,
                                                                 stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(False))
        job = jobs.run_to_end(None, "Gregory Bateson")
        assert stubbed == [["CFIV034892"]]
        assert job.state()["status"] == jobs.DONE
        assert job.since(0)["works"] == WORKS.works

    def test_one_person_is_listed_once(self, monkeypatch, stubbed):
        monkeypatch.setattr(stages, "resolve_author", lambda typed: resolution(True))
        jobs.run_to_end(None, "Byung-Chul Han")
        assert stubbed == [["CFIV034892"]]

    def test_a_title_runs_every_stage_in_this_thread(self, monkeypatch):
        from tests.test_app_jobs import adds, stub
        stub(monkeypatch, jobs.Stage("listing", adds("B1"), publishes=True))
        job = jobs.run_to_end("Rumori", "Attali")
        assert job.state()["done"] and job.version == 1
        assert job.since(0)["header"]["total_editions"] == 1
