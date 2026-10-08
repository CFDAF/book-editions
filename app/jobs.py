"""One lookup as a job: stages run behind it, snapshots come out in front.

Decision M settles U4 — the page is handed a **job id** at once and then polls
for versions, rather than holding a request open for the length of a lookup.
This module is that job, with no HTTP in it, so the whole of it can be driven
from a test without binding a port.

**Each snapshot is a complete view.** A stage that changes the store is followed
by a new `core.view.snapshot` derived from the store *from scratch*
(build rule 3), and the client replaces what it holds. There is no
delta, no patch and no running total anywhere between here and the browser,
which is where complexity is most expensive and hardest to see.

**Only S2 publishes today**, and that is the step's gate: the first snapshot
carries the complete S2 list. S1 finishes ~1.5 s earlier with no editions in
hand, and a header reading `0 editions` that then changes is exactly the
churn rule 8 is about. What the reader gets before v1 is the stage's own label
and nothing invented.

Three things that look like plumbing and are not:

- **The ledger is opened here, in the job's own thread**, so every request any
  stage makes lands on one record and a failure no source mentions is still
  counted (`CLAUDE.md` rule 5). `Pool` carries that context into the stages'
  own pools; a plain executor would not.
- **A job's pool never outlives it.** One `Pool(1)` per job, shut down in a
  `finally`, so a reader who closes the tab mid-lookup leaves nothing running.
- **Eviction is swept, not timed.** A reaper thread would itself be a thread
  outliving every job, which is the thing being guarded against, so the sweep
  runs on the server's own requests.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field

from catalog.http import SLOW_LOOKUP_S, Ledger, Pool
from core import notes
from core.store import RecordStore
from core import identity as gate
from core.view import disbelieved_notes, snapshot, title_chooser
from lookup import stages

# How long a job survives its last poll. Cold S1+S2 is ~4 s (max 15.4 s
# measured over 77 entries) and S4 up to ~45 s on N23, so this is generous by an
# order of magnitude on purpose: it evicts what a closed tab left behind, not
# a lookup that is merely slow.
IDLE_TTL_S = 300.0

RUNNING, DONE, FAILED = "running", "done", "failed"
# An author job that has offered its people and waits for the reader (UC4).
CHOOSING = "choosing"
READING_REST = "reading the remaining records under this name"


@dataclass
class Stage:
    """One step of a lookup, and whether a version follows it.

    `label` is a phrase, not a code. Anything that is *phrasing* rather than
    data belongs on this side of the wire (`docs/limits.md`, *Do not
    regress*): the alternative is the page and the CLI wording the same
    sentence separately and drifting.
    """
    label: str
    run: object
    publishes: bool = False


def _identify(job) -> None:
    job.identity = stages.identify(job.title, job.author, job.variants,
                                   title_spellings=job.title_spellings,
                                   author_spellings=job.author_spellings)
    job.work = job.identity.work
    job.evidence["identity"] = job.identity.evidence
    job._merge_sources(job.identity.evidence["sources"])


def _list_editions(job) -> None:
    listing = stages.list_editions(job.identity, job.store)
    job.evidence["listing"] = listing.evidence
    job.date_buckets = listing.date_buckets
    job._merge_sources(listing.evidence["sources"])


def _recover(job) -> None:
    recovery = stages.recover(job.identity, job.store)
    job.evidence["recovery"] = recovery.evidence
    job._merge_sources(recovery.evidence["sources"])


def _enrich(job) -> None:
    """S4 and the date check (decision AY), with Step 13's search beside them.

    They ask different hosts and neither reads what the other writes — the
    search writes no record at all, only the list it offers — so the list costs
    the reader no wait and arrives in S4's one version (decision AI).
    """
    already = [n["record"] for n in disbelieved_notes(job.evidence)]
    with Pool(1) as pool:
        found = pool.submit(stages.find_duplicates, job.identity)
        enrichment = stages.enrich(job.identity, job.store, already)
        # After S4, so a recovered row has the language its check is asked in,
        # and before S4's one publish, so no reader sees a year settle.
        checked = stages.check_dates(job.identity, job.store, job.this_year,
                                     job.date_buckets)
        duplicates = found.result()
    job.evidence["enrich"] = enrichment.evidence
    job.evidence["dates"] = checked.evidence
    job.evidence["duplicates"] = duplicates.evidence
    job._merge_sources(enrichment.evidence["sources"])
    job._merge_sources(checked.evidence["sources"])
    job._merge_sources(duplicates.evidence["sources"])


WHOSE_BOOK = "finding whose book this is"

# S4 publishes **once, when it ends** (decision AG): the list does not move under
# the reader while printings fold, and the envelope's `grouping` says the counts
# are provisional until it has.
GROUPING = "grouping printings"

STAGES = (
    Stage("identifying the work", _identify),
    Stage("listing the editions", _list_editions, publishes=True),
    Stage("recovering what the listing cannot reach", _recover, publishes=True),
    Stage(GROUPING, _enrich, publishes=True),
)


class Job:
    """One lookup: its store, its versions, and how far it has got.

    Every mutable field crossing threads is read and written under `_lock`. The
    runner is the only writer; the HTTP handler only ever reads, through
    `state()`.
    """

    def __init__(self, title: str, author: str, clock=time.monotonic, variants=(),
                 title_spellings: bool = False, author_spellings: bool = False,
                 this_year: int | None = None):
        self.id = uuid.uuid4().hex
        # What `core.dates` holds a year after this one against (decision AY),
        # and author mode's ceiling. Read here because `core/` reads no clock.
        self.this_year = this_year or time.localtime().tm_year
        self.title, self.author = title, author
        # Other spellings of the title, from an author-mode row (Step 14).
        self.variants = list(variants or [])
        # The reader's two switches (decision AV): off unless ticked.
        self.title_spellings, self.author_spellings = title_spellings, author_spellings
        self._clock = clock
        self._lock = threading.Lock()

        self.store = RecordStore()
        self.date_buckets: list = []         # S2's `dataf[]` facets (decision AY)
        self.identity = None
        self.work = None
        self.evidence: dict = {}
        self.ledger = None

        self._version = 0
        self._snapshot = None
        self._status = RUNNING
        self._stage = STAGES[0].label
        self._error = None
        self._sources: dict = {}
        self._cancelled = False
        self._adding = threading.Lock()

        self.created = self.touched = clock()
        self._finished = None
        self.pool = Pool(1, thread_name_prefix=f"job-{self.id[:8]}")

    # -- what the runner writes ---------------------------------------------

    def _merge_sources(self, states: dict) -> None:
        """One state per source across the stages: the first failure, or ok.

        A source that answered S1 and then failed in S2 is not healthy because
        one of its two calls worked — the same rule `stages._worst` applies
        within a stage, applied across them.
        """
        with self._lock:
            for name, state in states.items():
                if self._sources.get(name, stages.OK) == stages.OK:
                    self._sources[name] = state

    def publish(self) -> int:
        """Derive the whole view from the store again and hand it out as v+1."""
        with self._lock:
            version = self._version + 1
        view = snapshot(self.store, self.work, version=version,
                        evidence=dict(self.evidence), this_year=self.this_year)
        with self._lock:
            self._version, self._snapshot = version, view
        return version

    def add(self, keys: list) -> dict:
        """The reader's *Add*: open these Open Library records and publish.

        **Only once the lookup has finished.** The list arrives with S4's last
        version, so a page cannot offer it earlier, and refusing it here keeps
        a reader's write from racing a stage's. One add at a time per job: two
        clicks on the same row open it once.

        The caller opens the ledger, as it does for Details — the job's own
        closed when its stages did — so a work that failed to open reaches the
        page as *failed*, per row, and never as a record with no editions.
        """
        with self._lock:
            if self._status == RUNNING:
                raise RuntimeError("the lookup is still running")
        with self._adding:
            listed = self.evidence.get("duplicates") or {}
            result = stages.add_duplicates(self.identity, self.store, listed, keys)
            listed["added"] = listed["added"] + result["added"]
            failed = {k: v for k, v in listed["failed"].items() if k not in result["added"]}
            listed["failed"] = {**failed, **result["failed"]}
            listed["language_disbelieved"] = (listed["language_disbelieved"]
                                              + result["language_disbelieved"])
            version = self.publish()
        return {**result, "version": version}

    def cancel(self) -> None:
        """Stop at the next stage boundary.

        A stage already in flight runs to its end: a Python thread cannot be
        killed, and pretending otherwise would leave the store half written by
        a producer that believes it is still going.
        """
        with self._lock:
            self._cancelled = True

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    # -- what the handler reads ---------------------------------------------

    def state(self) -> dict:
        """The job envelope: what the page says while it waits, and the raw
        network reading underneath it.

        `requests` and `failed` are counts off the ledger, not prose — and the
        three readings of them that *are* prose (`partial (N failed)`, the
        *Incomplete* note and the slow-lookup note) are worded by `core.notes`
        and only assembled here. Phrasing them in this module was refused in
        Step 8 for the reason that still holds: two places wording the same
        number are two places that can disagree.

        They sit on the envelope rather than in the snapshot because they are
        readings of a ledger that is still being written — a poll that gains no
        version still reports a request that failed since the last one.
        """
        with self._lock:
            done = self._status in (DONE, FAILED)
            # `_finished` is written in the runner's `finally`, one lock
            # acquisition after a failure sets the status, so a poll landing
            # between the two must not read `None` as a timestamp.
            end = self._finished if self._finished is not None else self._clock()
            elapsed = end - self.created
            ledger, sources = self.ledger, dict(self._sources)
            status, stage, error = self._status, self._stage, self._error
        # The ledger's own counts are taken outside this job's lock: they take
        # the ledger's, and the runner is writing to it while the poll reads.
        failed = ledger.failed() if ledger else 0
        return {
            "id": self.id,
            "status": status,
            "stage": stage,
            "done": done,
            "grouping": status == RUNNING and stage == GROUPING,
            "choosing": status == CHOOSING,
            "elapsed_s": round(elapsed, 3),
            "error": error,
            "sources": notes.source_states(sources, ledger.failed) if ledger
                       else sources,
            "requests": len(ledger.calls) if ledger else 0,
            "failed": failed,
            "incomplete": notes.incomplete(failed),
            # Only once the lookup is over: a cold S1+S2 crosses the threshold
            # while it is still running, and a note saying it was slow is a
            # statement about a lookup that has finished.
            "slow": (notes.slow(elapsed, ledger.slow_causes(), SLOW_LOOKUP_S)
                     if done and ledger else None),
        }

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def since(self, version: int) -> dict:
        """The snapshot if the caller is behind, else `{"unchanged": true}`.

        Both carry the job envelope, so a poll that gains no version still
        tells the page what is happening and costs ~200 bytes.
        """
        # The envelope first, the snapshot second. A job publishes before it
        # says it is done, so a snapshot read *after* an envelope reading
        # `done` is the last one. The other order let a poll land between the
        # two — `unchanged` from before the final publish, `done` from after
        # it — and the page stopped polling one version short (Step 14).
        state = self.state()
        with self._lock:
            held, view = self._version, self._snapshot
        if view is None or version >= held:
            return {"unchanged": True, "version": held, "job": state}
        return {**view, "job": state}

    # -- the runner ---------------------------------------------------------

    def start(self):
        return self.pool.submit(self._run)

    def _whose_book(self) -> bool:
        """A title with no author: whose book is it? False when the reader must say.

        One book the sources agree on is adopted and the lookup goes on with
        its author, the byline saying none was typed; several are published as
        a chooser and the lookup ends there (decision AN). None at all goes on
        with no author, as before — the OPAC is then not asked (rule 3).
        """
        with self._lock:
            self._stage = WHOSE_BOOK
        found = stages.title_books(self.title)
        self.evidence["title_books"] = found
        self._merge_sources({k: v for k, v in found["sources"].items()
                             if not v.startswith("not asked")})
        adopted = gate.adopted_book(found["books"])
        if adopted:
            self.author = adopted["authors"][0]
            self.evidence["author_adopted"] = {
                "name": self.author, "authors": adopted["authors"],
                "sources": adopted["sources"],
                "note": notes.author_adopted(adopted["sources"])}
            return True
        if len(found["books"]) < 2:
            return True
        with self._lock:
            version = self._version + 1
            self._version = version
            self._snapshot = title_chooser(self.title, found["books"], version)
        return False

    def _run(self) -> None:
        try:
            with Ledger() as ledger:
                with self._lock:
                    self.ledger = ledger
                if not self.author and not self._whose_book():
                    return
                for stage in STAGES:
                    if self.cancelled:
                        break
                    with self._lock:
                        self._stage = stage.label
                    stage.run(self)
                    if stage.publishes:
                        self.publish()
        except Exception as exc:                  # a stage is not allowed to
            with self._lock:                      # take the server down with it
                self._status, self._error = FAILED, f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                if self._status == RUNNING:
                    self._status = DONE
                    self._stage = "cancelled" if self._cancelled else "finished"
                self._finished = self._clock()
            self.pool.shutdown(wait=False)


class AuthorJob(Job):
    """UC4: an author with no title. The person first, then their works.

    Two runs, one ledger. The first resolves the name (`stages.resolve_author`)
    and publishes the people it may mean; when one person answers every form
    asked it goes straight on (decision AJ), and otherwise the job **waits**,
    `choosing`, until the reader picks. The second lists the works of the ids
    picked. Both enter the same `Ledger`, so the envelope's counts are the
    whole lookup's, and both run on the job's own pool, so nothing outlives it.
    """

    def __init__(self, author: str, clock=time.monotonic, this_year: int | None = None):
        super().__init__("", author, clock=clock, this_year=this_year)
        self._stage = "finding the person"
        self.resolution = None
        self.works = None
        self.chosen: list = []
        self.ledger = Ledger()

    def publish(self) -> int:
        with self._lock:
            version = self._version + 1
        view = author_snapshot(self.resolution, self.chosen, self.works, version)
        with self._lock:
            self._version, self._snapshot = version, view
        return version

    def start(self):
        return self.pool.submit(self._guarded, self._resolve)

    def choose(self, ids: list):
        """The reader's pick. Refused unless the job is waiting for one, and
        for any id it did not offer — an id from elsewhere is not a person this
        lookup resolved."""
        offered = {c.id for c in self.resolution.candidates} if self.resolution else set()
        with self._lock:
            if self._status != CHOOSING:
                raise RuntimeError("this lookup is not waiting for a choice")
            unknown = [i for i in ids if i not in offered]
            if not ids or unknown:
                raise KeyError(f"not offered: {unknown}" if unknown else "choose someone")
            self._status, self._stage = RUNNING, "listing the works"
        return self.pool.submit(self._guarded, self._list, list(ids))

    def read_rest(self):
        """The reader's *read the rest* (decision BA): every record under the
        chosen names past `stages.UNLINKED_MAX_PAGES`, on a pool of its own —
        the job's closed when the works were listed — and the same ledger, so
        the envelope's counts stay the whole lookup's. Refused unless the
        works are listed and the cap cut something."""
        with self._lock:
            if self._status != DONE or self.works is None:
                raise RuntimeError("the works are not listed yet")
            if stages.unread_under_name(self.works.evidence) is None:
                raise RuntimeError("every record under this name was read")
            self._status, self._stage, self._finished = RUNNING, READING_REST, None
            self.pool.shutdown(wait=False)
            self.pool = pool = Pool(1, thread_name_prefix=f"job-{self.id[:8]}")
        return pool.submit(self._guarded, self._read_rest)

    def _read_rest(self) -> None:
        if not self.cancelled:
            self.works = stages.read_rest(self.works, self.this_year)
            self._merge_sources(self.works.evidence["sources"])
            self.evidence["works"] = self.works.evidence
            self.publish()
        with self._lock:
            self._status, self._stage = DONE, "finished"

    def _resolve(self) -> None:
        self.resolution = stages.resolve_author(self.author)
        self._merge_sources(self.resolution.evidence["sources"])
        self.evidence["resolution"] = self.resolution.evidence
        if self.resolution.skip:
            self.publish()
            with self._lock:
                self._stage = "listing the works"
            self._list([self.resolution.resolved])
            return
        with self._lock:
            self._status, self._stage = CHOOSING, "choose the person"
        self.publish()

    def _list(self, ids: list) -> None:
        if self.cancelled:
            return
        self.chosen = ids
        self.works = stages.list_works(self.resolution, ids, self.this_year)
        self._merge_sources(self.works.evidence["sources"])
        self.evidence["works"] = self.works.evidence
        self.publish()
        with self._lock:
            self._status, self._stage = DONE, "finished"

    def _guarded(self, run, *args) -> None:
        try:
            with self.ledger:
                run(*args)
        except Exception as exc:                  # never take the server down
            with self._lock:
                self._status, self._error = FAILED, f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                # The pool this run is on, taken under the lock: `read_rest`
                # may already have put a new one in its place.
                closing = self.pool if self._status in (DONE, FAILED) else None
                if closing:
                    self._finished = self._clock()
            if closing:
                closing.shutdown(wait=False)


def author_snapshot(resolution, chosen: list, works, version: int) -> dict:
    """One complete author view — the people offered, then the works once
    listed. Derived whole every time, like `core.view.snapshot`."""
    people = [{"id": c.id, "name": c.display, "heading": c.heading,
               "agrees": c.agrees, "records": c.records, "languages": c.languages,
               "forms": c.forms} for c in (resolution.candidates if resolution else [])]
    out = {"mode": "author", "version": version,
           "asked": resolution.evidence["typed"] if resolution else "",
           "forms": resolution.evidence["forms"] if resolution else [],
           "people": people, "resolved": resolution.resolved if resolution else None,
           "chosen": list(chosen), "works": None, "contributed": None, "band": None,
           "unlinked": None, "unread": None,
           "truncations": [], "not_asked": []}
    if works is not None:
        out.update(works=works.works, contributed=works.contributed, band=works.band,
                   unlinked=works.unlinked, unread=stages.unread_under_name(works.evidence),
                   truncations=notes.author_truncations(works.evidence))
    return out


def run_to_end(title: str | None, author: str | None, *, title_spellings: bool = False,
               author_spellings: bool = False) -> Job:
    """One lookup, run in this thread to its end: the CLI's and the sweeps'.

    An author with no title is UC4, and where the page would wait for the
    reader to pick a person this goes on with the one the page ticks,
    `resolution.resolved` (decision AJ). The job's pool is shut down before
    this returns, so nothing outlives the call.
    """
    if title:
        job = Job(title, author or "", title_spellings=title_spellings,
                  author_spellings=author_spellings)
        try:
            job._run()
        finally:
            job.pool.shutdown(wait=False)
        return job
    job = AuthorJob(author)
    try:
        with job.ledger:
            job._resolve()
            if job.state()["choosing"] and job.resolution.resolved:
                job._list([job.resolution.resolved])
    finally:
        job.pool.shutdown(wait=False)
    return job


class Registry:
    """Job id -> job, behind one lock, swept on every request.

    `clock` is injected so the TTL can be tested without sleeping for it.
    """

    def __init__(self, ttl: float = IDLE_TTL_S, clock=time.monotonic):
        self.ttl, self._clock = ttl, clock
        self._lock = threading.Lock()
        self._jobs: dict = {}

    def start(self, title: str, author: str, variants=(), title_spellings: bool = False,
              author_spellings: bool = False) -> Job:
        job = Job(title, author, clock=self._clock, variants=variants,
                  title_spellings=title_spellings, author_spellings=author_spellings) \
            if title else AuthorJob(author, clock=self._clock)
        with self._lock:
            self._jobs[job.id] = job
        job.start()
        return job

    def get(self, job_id: str) -> Job | None:
        """Fetch a job and keep it alive: a polled job is one somebody wants."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.touched = self._clock()
            return job

    def sweep(self) -> int:
        """Drop every job nobody has asked about for `ttl`, and stop it.

        A running job that is evicted is cancelled first, so its pool closes at
        the next stage boundary rather than running on for a page that is gone.
        """
        cutoff = self._clock() - self.ttl
        with self._lock:
            stale = [j for j in self._jobs.values() if j.touched < cutoff]
            for job in stale:
                del self._jobs[job.id]
        for job in stale:
            job.cancel()
        return len(stale)

    def close(self) -> None:
        """Cancel everything held. For shutdown and for tests."""
        with self._lock:
            jobs, self._jobs = list(self._jobs.values()), {}
        for job in jobs:
            job.cancel()

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)
