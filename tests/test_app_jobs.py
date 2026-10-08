"""The job transport, with the stages stubbed (Step 8).

What is tested here is the *shape* decision M chose, not a lookup: a job id
handed back before anything is fetched, a complete view per version, a poll at
the version already held costing nothing, eviction on a TTL, and — the clause
that is a real bug if it fails — **no thread outliving its job**.

The stages are stubbed on purpose. S1 and S2 have their own suites
(`test_stages_s1.py`, `test_stages_s2.py`) and their own live sweeps; wiring a
catalogue in here would test them a third time and this not at all. What the
stubs give instead is the thing no live run can: three versions in a row, a
stage that raises, and a TTL reached without waiting five minutes for it.
"""

import threading
import time

import pytest

from app import jobs
from core.model import Provenance, Record, Work


# ---------------------------------------------------------------------------
# A clock that only moves when a test moves it, and stages that only do what a
# test says. Neither reaches a catalogue.
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, seconds):
        self.t += seconds


def record(bid, title="Uno", language="ita"):
    return Record(source="SBN", id=bid, title=title, language=language,
                  year="1980", publisher="Einaudi",
                  provenance=Provenance("SBN", "work listing", "uniform title"))


def adds(bid, work=None):
    """A stage that writes one record, as every real producer does."""
    def run(job):
        job.work = work or job.work
        job.store.put(record(bid))
    return run


def stub(monkeypatch, *stages):
    monkeypatch.setattr(jobs, "STAGES", tuple(stages))


@pytest.fixture
def clock():
    return Clock()


def settled(job, timeout=5.0):
    """Wait for the runner, which is the one thing a test may not fake."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.state()["done"]:
            return job
        time.sleep(0.005)
    raise AssertionError(f"the job never finished: {job.state()}")


def threads_of(job):
    """The pool threads this job started, by the prefix it named them with.

    Its own, not every job's: the suite runs jobs in sequence and an earlier
    one's pool may still be winding down, which is not this one's business.
    """
    prefix = f"job-{job.id[:8]}"
    return [t for t in threading.enumerate() if t.name.startswith(prefix)]


# ---------------------------------------------------------------------------

class TestVersions:

    def test_the_first_snapshot_carries_the_whole_list(self, monkeypatch):
        """Step 8's gate: v1 is S2's complete list, not a header skeleton.

        S1 publishes nothing. It finishes ~1.5 s earlier with no editions in
        hand, and a header reading `0 editions` that then changes is churn the
        reader pays for (the user's call, 2026-09-22).
        """
        stub(monkeypatch,
             jobs.Stage("identifying the work", lambda job: None),
             jobs.Stage("listing the editions", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        assert job.version == 1
        assert [r["id"] for r in job.since(0)["editions_by_language"]["ita"]] == ["SBN:IT001"]

    def test_every_version_is_a_complete_view_not_a_delta(self, monkeypatch):
        """Rule 3: the view is recomputed from the store from scratch.

        v2 holds v1's row as well as its own — the client replaces what it has
        and never merges, which is what keeps the browser dumb.
        """
        stub(monkeypatch,
             jobs.Stage("a", adds("IT001"), publishes=True),
             jobs.Stage("b", adds("IT002"), publishes=True),
             jobs.Stage("c", adds("IT003"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        assert job.version == 3
        rows = [r["id"] for r in job.since(2)["editions_by_language"]["ita"]]
        assert rows == ["SBN:IT001", "SBN:IT002", "SBN:IT003"]

    def test_a_poll_at_the_held_version_returns_unchanged(self, monkeypatch):
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        answer = job.since(1)
        assert answer["unchanged"] is True and answer["version"] == 1
        assert "editions_by_language" not in answer
        # It still says what is happening: an unchanged poll is not an empty one.
        assert answer["job"]["done"] is True

    def test_a_poll_before_the_first_version_says_what_stage_it_is_on(self, monkeypatch):
        """What the page shows while it waits, and it is never invented."""
        started, release = threading.Event(), threading.Event()

        def slow(job):
            started.set()
            release.wait(5)

        stub(monkeypatch,
             jobs.Stage("identifying the work", slow),
             jobs.Stage("listing the editions", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        assert started.wait(5)
        answer = job.since(0)
        assert answer["unchanged"] is True and answer["version"] == 0
        assert answer["job"]["stage"] == "identifying the work"
        assert answer["job"]["done"] is False
        release.set()
        settled(job)


class TestFailure:

    def test_a_stage_that_raises_leaves_the_job_failed_and_says_so(self, monkeypatch):
        """A failure must never be indistinguishable from an empty result
        (`CLAUDE.md` rule 5) — including a failure of this layer's own."""
        def boom(job):
            raise RuntimeError("the catalogue fell over")

        stub(monkeypatch, jobs.Stage("a", boom, publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        state = job.state()
        assert state["status"] == jobs.FAILED
        assert state["error"] == "RuntimeError: the catalogue fell over"
        assert state["done"] is True
        assert job.version == 0

    def test_one_source_failing_does_not_make_the_others_healthy(self, monkeypatch):
        """`_merge_sources` keeps the first failure per source across stages."""
        def s1(job):
            job._merge_sources({"SBN": "ok", "Wikidata": "error: 500"})

        def s2(job):
            job._merge_sources({"SBN": "error: timeout", "Wikidata": "ok"})

        stub(monkeypatch, jobs.Stage("a", s1), jobs.Stage("b", s2, publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        assert job.state()["sources"] == {"SBN": "error: timeout",
                                          "Wikidata": "error: 500"}


class TestThreads:

    def test_a_finished_job_leaves_no_thread_running(self, monkeypatch):
        """The gate's clause, and the reason the pool is one per job.

        A reader closing the tab mid-lookup is exactly this: nothing polls
        again, the stages run out, and what must not remain is a thread.
        """
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        assert threads_of(job), "the stage did not run on the job's own pool"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and threads_of(job):
            time.sleep(0.005)
        assert threads_of(job) == []

    def test_the_pool_is_the_ledger_carrying_one(self):
        """Rule 5 again: a plain ThreadPoolExecutor runs its requests outside
        the lookup's ledger, so their failures reach no reading at all."""
        from catalog.http import Pool
        job = jobs.Job("Uno", "Tizio")
        try:
            assert isinstance(job.pool, Pool)
        finally:
            job.pool.shutdown(wait=False)


class TestRegistry:

    def test_a_job_is_evicted_once_nobody_asks_for_it(self, monkeypatch, clock):
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        registry = jobs.Registry(ttl=300.0, clock=clock)
        job = registry.start("Uno", "Tizio")
        settled(job)
        clock.tick(299)
        assert registry.sweep() == 0 and registry.get(job.id) is job
        clock.tick(299)                      # the get() above kept it alive
        assert registry.sweep() == 0
        clock.tick(301)
        assert registry.sweep() == 1
        assert registry.get(job.id) is None and len(registry) == 0

    def test_evicting_a_running_job_cancels_it(self, monkeypatch, clock):
        """Cancellation is at a stage boundary, and that is honest: a Python
        thread cannot be killed, and a half-written store is worse than a
        stage that finishes into a job nobody will read."""
        reached, release = threading.Event(), threading.Event()
        second = threading.Event()

        def first(job):
            reached.set()
            release.wait(5)

        stub(monkeypatch,
             jobs.Stage("a", first),
             jobs.Stage("b", lambda job: second.set(), publishes=True))
        registry = jobs.Registry(ttl=10.0, clock=clock)
        job = registry.start("Uno", "Tizio")
        assert reached.wait(5)
        clock.tick(11)
        assert registry.sweep() == 1
        assert job.cancelled is True
        release.set()
        settled(job)
        assert second.is_set() is False      # the next stage never ran
        assert job.version == 0
        assert job.state()["stage"] == "cancelled"

    def test_close_cancels_everything_held(self, monkeypatch, clock):
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        registry = jobs.Registry(clock=clock)
        one, two = registry.start("Uno", "Tizio"), registry.start("Due", "Caio")
        settled(one), settled(two)
        registry.close()
        assert len(registry) == 0
        assert one.cancelled and two.cancelled


class TestEnvelope:

    def test_the_envelope_carries_the_counts_and_one_wording_of_them(self, monkeypatch):
        """The counts are the ledger's; the three sentences read off them are
        `core.notes`', assembled here and worded nowhere else."""
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        state = job.state()
        assert state["requests"] == 0 and state["failed"] == 0
        assert state["incomplete"] is None and state["slow"] is None
        assert set(state) == {"id", "status", "stage", "done", "grouping", "choosing",
                              "elapsed_s",
                              "error", "sources", "requests", "failed",
                              "incomplete", "slow"}

    def test_the_snapshot_and_the_envelope_travel_as_one_object(self, monkeypatch):
        """The browser assigns one thing and re-renders (decision M)."""
        stub(monkeypatch,
             jobs.Stage("a", adds("IT001", work=Work(original_language="ita",
                                                     original_year="1980")),
                        publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        answer = job.since(0)
        assert answer["version"] == 1
        assert answer["header"]["original_language"] == "ita"
        assert answer["job"]["id"] == job.id


class TestTheRealStageList:
    """The one thing the stubs cannot check: what `STAGES` actually holds.

    Everything above replaces it, so a stage added without `publishes=True`
    would leave its records in the store and never in front of the reader, and
    every test here would still be green.
    """

    def test_s1_does_not_publish_and_every_stage_after_it_does(self):
        labels = [s.label for s in jobs.STAGES]
        assert labels == ["identifying the work",
                          "listing the editions",
                          "recovering what the listing cannot reach",
                          "grouping printings"]
        assert [s.publishes for s in jobs.STAGES] == [False, True, True, True]

    def test_every_stage_writes_into_the_job_s_own_store(self, monkeypatch):
        """S3 is a producer into S2's store, not a second list: it takes the
        job's store and hands back the same object."""
        seen = {}

        def identify(title, author, variants=(), **switches):
            seen["identify"] = (title, author)
            return type("I", (), {"work": Work(),
                                  "evidence": {"sources": {}}})()

        def list_editions(identity, store=None):
            seen["list"] = store
            return type("L", (), {"evidence": {"sources": {}}, "date_buckets": []})()

        def recover(identity, store=None):
            seen["recover"] = store
            return type("R", (), {"evidence": {"sources": {}}})()

        monkeypatch.setattr(jobs.stages, "identify", identify)
        monkeypatch.setattr(jobs.stages, "list_editions", list_editions)
        monkeypatch.setattr(jobs.stages, "recover", recover)
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        assert seen["identify"] == ("Uno", "Tizio")
        assert seen["list"] is job.store
        assert seen["recover"] is job.store


# ---------------------------------------------------------------------------
# What the envelope says about the network, and where the wording comes from
# (Step 11)
# ---------------------------------------------------------------------------

class FakeLedger:
    """A ledger's reading surface, with no HTTP under it.

    `Ledger` counts calls the network layer made; a stubbed stage makes none, so
    the only way to test what the envelope *says* about failures is to hand it
    the counts a real one would have.
    """

    def __init__(self, calls=0, failed=0, by_source=None, causes=()):
        self.calls = [None] * calls
        self._failed, self._by_source = failed, by_source or {}
        self._causes = list(causes)

    def failed(self, source=None):
        return self._by_source.get(source, 0) if source else self._failed

    def slow_causes(self):
        return list(self._causes)


class TestWhatTheEnvelopeSaysAboutTheNetwork:
    def test_a_source_that_lost_requests_is_partial(self, monkeypatch):
        """Rule 5, on the transport: the ledger counted it, so the source is
        not healthy — whether or not the source said anything went wrong."""
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        job.ledger = FakeLedger(calls=40, failed=3, by_source={"SBN": 3})
        job._sources = {"SBN": "ok", "Open Library": "ok"}
        state = job.state()
        assert state["sources"]["SBN"] == "partial (3 failed)"
        assert state["sources"]["Open Library"] == "ok"
        assert state["requests"] == 40 and state["failed"] == 3
        assert "3 requests failed" in state["incomplete"]

    def test_the_slow_note_waits_until_the_lookup_is_over(self, monkeypatch, clock):
        """A cold S1+S2 crosses the threshold while it is still running, and
        'this was slow' is a statement about a lookup that has finished."""
        stub(monkeypatch, jobs.Stage("a", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio", clock=clock)
        job.ledger = FakeLedger(calls=9, causes=["sbn.it needed 2 retries"])
        job._finished, job._status = None, jobs.RUNNING
        clock.tick(30)
        assert job.state()["slow"] is None          # still running
        job._status, job._finished = jobs.DONE, clock()
        note = job.state()["slow"]
        assert note.startswith("Slow lookup (30 s)") and "2 retries" in note

    def test_with_no_ledger_yet_it_says_nothing_rather_than_zero_prose(self):
        """A job polled before its runner opened the ledger."""
        job = jobs.Job("Uno", "Tizio")
        job.cancel()
        state = job.state()
        assert state["requests"] == 0 and state["failed"] == 0
        assert state["incomplete"] is None and state["slow"] is None


class TestTheEvidenceReachesTheLedgerBlock:
    def test_a_truncated_stage_is_on_the_snapshot(self, monkeypatch):
        """Rule 10's path: the stages record the cap, the job carries their
        evidence into `view.snapshot`, and the ledger phrases it once."""
        def run(job):
            job.store.put(record("IT001"))
            job.evidence["recovery"] = {"routes": {"author_sweep": {
                "truncated": True, "rows": 240, "total": 1366}}}
        stub(monkeypatch, jobs.Stage("a", run, publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        ledger = job.since(0)["ledger"]
        assert ledger["truncations"] == ["the author sweep read 240 of 1,366 "
                                         "records filed under this name"]
        assert ledger["records"] == 1

    def test_the_spelling_switches_reach_s1(self, monkeypatch):
        """Decision AV: off unless the reader ticked one, and passed as ticked."""
        seen = []

        def identify(title, author, variants=(), **switches):
            seen.append(switches)
            return type("I", (), {"work": Work(), "evidence": {"sources": {}}})()

        monkeypatch.setattr(jobs.stages, "identify", identify)
        stub(monkeypatch, jobs.Stage("a", jobs._identify))
        for job in (jobs.Job("Uno", "Tizio"),
                    jobs.Job("Uno", "Tizio", author_spellings=True)):
            job.start()
            settled(job)
        assert seen == [{"title_spellings": False, "author_spellings": False},
                        {"title_spellings": False, "author_spellings": True}]

    def test_s1s_own_evidence_is_kept_for_it(self, monkeypatch):
        """`_identify` stores it because the work facet's 50-item cap (F11) is
        a truncation like any other and S1 is the only stage that sees it."""
        seen = {}

        def identify(title, author, variants=(), **switches):
            seen["called"] = True
            return type("I", (), {"work": Work(), "evidence": {
                "sources": {}, "sbn_work": {"facet_truncated": True}}})()

        monkeypatch.setattr(jobs.stages, "identify", identify)
        stub(monkeypatch, jobs.Stage("a", jobs._identify),
             jobs.Stage("b", adds("IT001"), publishes=True))
        job = jobs.Job("Uno", "Tizio")
        job.start()
        settled(job)
        assert seen["called"]
        assert job.since(0)["ledger"]["truncations"] == [
            "SBN offered 50 uniform titles for this question and stops there, "
            "so the work was chosen from the first 50"]


def test_a_done_envelope_never_comes_with_a_stale_version(monkeypatch):
    """The race Step 14 hit in a browser: a poll that read the version before
    the last publish and the status after it said `unchanged` and `done`, and
    the page stopped one version short. Forced here by publishing and
    finishing inside the envelope read."""
    job = jobs.Job("Uno", "Tizio")
    job.publish()
    real = job.state

    def state_then_finish():
        got = real()
        if not got["done"]:
            job.publish()
            with job._lock:
                job._status = jobs.DONE
        return real()
    monkeypatch.setattr(job, "state", state_then_finish)
    answer = job.since(1)
    assert answer["job"]["done"] and answer.get("version") == 2 and not answer.get("unchanged")


class TestTitleOnly:
    """Decision AN: with no author, S0 asks whose book it is first."""

    BATESON = {"authors": ["Gregory Bateson"], "title": "Verso un'ecologia della mente",
               "first_year": 1972, "editions": 28,
               "sources": ["Open Library", "SBN", "Wikidata"]}
    NIHEI = {"authors": ["Tsutomu Nihei"], "title": "NOiSE", "first_year": 2003,
             "editions": 3, "sources": ["Open Library", "SBN"]}
    KAHNEMAN = {"authors": ["Daniel Kahneman"], "title": "Noise", "first_year": 2021,
                "editions": 23, "sources": ["Open Library", "SBN"]}

    def _found(self, monkeypatch, books):
        asked = []

        def title_books(title):
            asked.append(title)
            return {"books": books, "candidates": len(books),
                    "sources": {"Wikidata": "ok", "SBN": "ok", "Open Library": "ok"}}
        monkeypatch.setattr(jobs.stages, "title_books", title_books)
        return asked

    def test_one_agreed_book_runs_the_lookup_with_its_author(self, monkeypatch):
        self._found(monkeypatch, [self.BATESON])
        seen = {}

        def identity(job):
            seen["author"] = job.author
        stub(monkeypatch, jobs.Stage("s1", identity), jobs.Stage("s2", adds("A"), True))
        job = _started(jobs.Job("Verso un'ecologia della mente", ""))
        assert job.author == "Gregory Bateson"
        assert job._snapshot["header"]["author_adopted"]["note"] == \
            "author from Open Library, SBN and Wikidata — none was typed"

    def test_several_books_publish_a_chooser_and_stop(self, monkeypatch):
        self._found(monkeypatch, [self.KAHNEMAN, self.NIHEI])
        ran = []
        stub(monkeypatch, jobs.Stage("s1", lambda job: ran.append(1)))
        job = _started(jobs.Job("Noise", ""))
        assert ran == [] and job.state()["status"] == jobs.DONE
        assert job._snapshot["chooser"]["books"] == [self.KAHNEMAN, self.NIHEI]
        assert job.version == 1

    def test_nothing_found_goes_on_with_no_author(self, monkeypatch):
        self._found(monkeypatch, [])
        ran = []
        stub(monkeypatch, jobs.Stage("s1", lambda job: ran.append(job.author)))
        _started(jobs.Job("Umibe no Kafuka", ""))
        assert ran == [""]

    def test_an_author_typed_asks_nobody_whose_book_it_is(self, monkeypatch):
        asked = self._found(monkeypatch, [self.KAHNEMAN, self.NIHEI])
        stub(monkeypatch, jobs.Stage("s1", lambda job: None))
        _started(jobs.Job("Noise", "Kahneman"))
        assert asked == []


def _started(job):
    job.start()
    return settled(job)
