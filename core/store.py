"""The one place records are kept. Several producers write; the view is derived.

The shape the rebuild asks for is **producers -> store -> pure derivation ->
versioned snapshots**: each route writes records with provenance into here, and
the view is recomputed from scratch after every batch. There is no incremental
mutation of a display list anywhere (build rule 3), which is what
makes the page unable to disagree with its own store.

Two decisions this class makes and nothing else may:

- **A record arrives once.** `(source, id)` is its identity, so the same SBN row
  found by the work listing and again by the author sweep is one record with two
  routes on it — not two rows, and not a merge that has to be undone later.
- **Order is insertion order.** Every derivation downstream sorts explicitly, but
  where two values tie, the store's order breaks it, and it is the order the
  producers wrote in. That is what makes `view` deterministic rather than
  accidentally stable.

Nothing here decides whether a record belongs to the work. A refused record is
stored with `REFUSED` provenance and filtered by the view, because "what was
refused" is a disclosure (decision N) and a dropped record cannot be audited.
"""

import threading
from collections import Counter

from catalog import langs
from .model import Record


class RecordStore:
    """Records keyed on `(source, id)`, in the order they were written."""

    def __init__(self):
        self._records: dict = {}
        self._routes: dict = {}          # key -> [provenance, ...], in arrival order
        # A reader can read while a producer writes: Details during S3, and a
        # snapshot while the reader's own *Add* is being written. Iterating a
        # dict another thread inserts into raises, so both sides take this.
        self._lock = threading.RLock()

    # -- writing ------------------------------------------------------------

    def put(self, record: Record) -> Record:
        """Add a record, or note another route to one already held.

        Returns the stored record — the first one seen, not the newcomer. A
        second sighting does not overwrite: producers run concurrently and
        "last writer wins" would make the store depend on thread timing, which
        is the determinism the whole derivation rests on.

        What a second sighting *does* change: it appends its provenance, and it
        fills fields the first sighting left empty. A brief record has no
        language and no Dewey; its full record is the same row enriched, and
        arriving second must not lose what it carries.
        """
        key = record.key
        with self._lock:
            held = self._records.get(key)
            if held is None:
                self._records[key] = record
                self._routes[key] = [record.provenance]
                return record
            self._routes[key].append(record.provenance)
            _fill_gaps(held, record)
            # The strongest evidence seen for a row is the one it keeps. An
            # admitted sighting outranks a refusal: the record *is* the work's,
            # and one route having failed to prove it does not unprove it.
            if held.provenance.refused and not record.provenance.refused:
                held.provenance = record.provenance
            return held

    def put_all(self, records) -> list:
        return [self.put(r) for r in records]

    def note_date(self, key: tuple, indexed: list, failed: bool = False) -> None:
        """What SBN's index said about one held record's date (decision AY).

        A statement about the record, not a sighting of it: no route is added.
        Under the lock, because a snapshot may be reading the record.
        """
        with self._lock:
            held = self._records.get(key)
            if held is not None:
                held.date_indexed = list(indexed)
                held.date_check_failed = failed

    # -- reading ------------------------------------------------------------

    def records(self, include_refused: bool = False) -> list:
        """Every record, in arrival order. Refused ones only when asked for."""
        with self._lock:
            return [r for r in self._records.values()
                    if include_refused or not r.provenance.refused]

    def refused(self) -> list:
        with self._lock:
            return [r for r in self._records.values() if r.provenance.refused]

    def get(self, source: str, id: str) -> Record | None:
        return self._records.get((source, id))

    def routes(self, record: Record) -> list:
        """Every provenance written for this record, in arrival order."""
        with self._lock:
            return list(self._routes.get(record.key, []))

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, key) -> bool:
        return tuple(key) in self._records

    # -- what it adds up to -------------------------------------------------

    def coverage(self) -> dict:
        """Counts by source, route and evidence — the coverage ledger's numbers.

        A reading of the provenance field and nothing more: it counts **what was
        found**, never what exists. There is no census here and there cannot be
        one — VIAF was measured and is unusable for it (A6: 20 of 37 books), so
        "found N of ~M known" is not a thing this project says (decision C, which
        decision N only half reverses).
        """
        by_source, by_route, by_evidence = Counter(), Counter(), Counter()
        with self._lock:
            held = [(key, record, list(self._routes[key]))
                    for key, record in self._records.items()]
        for key, record, routes in held:
            by_source[record.source] += 1
            for p in routes:
                by_route[p.route] += 1
            by_evidence[record.provenance.evidence] += 1
        return {
            "records": len(held),
            "admitted": sum(1 for _, r, _ in held if not r.provenance.refused),
            "refused": sum(1 for _, r, _ in held if r.provenance.refused),
            "by_source": dict(sorted(by_source.items())),
            "by_route": dict(sorted(by_route.items())),
            "by_evidence": dict(sorted(by_evidence.items())),
        }


# `authors` is filled only when empty, like a scalar. A listing row's author is
# SBN's **main heading**, and `credited to X` (decision Z) is read off it; a full
# record's `nomi` lists everyone, the original author included — `[Autore]
# Orwell` on a Penguin Readers retelling, `[Autore citato] Homerus` on a set of
# summaries. Unioned, it silenced 10 correct labels over the corpus (Step 12).
_GAP_FIELDS = ("title", "publisher", "year", "date", "isbn", "url", "series",
               "physical", "dewey", "medium", "cover_url", "authors")
# `isbns_raw` is here because one `numeri` field often lists the paperback and
# the hardback, and `core.fold` joins on every one of them: filling only `isbn`
# would fold a two-ISBN full record by its first code alone.
_GAP_LISTS = ("isbns_raw", "dewey_all", "translators", "evidence", "holdings")


def _fill_gaps(held: Record, other: Record) -> None:
    """Fill what `held` does not have from `other`. Never overwrite.

    The brief-then-full case is the whole reason: `search.json` has no language,
    no Dewey and no holdings, and `full.json` for the same BID is that row
    again with them. Whichever arrives second, the row ends up with both.
    """
    for name in _GAP_FIELDS:
        if not getattr(held, name) and getattr(other, name):
            setattr(held, name, getattr(other, name))
    if held.language == langs.UNKNOWN and other.language != langs.UNKNOWN:
        held.language = other.language
    for name in _GAP_LISTS:
        current = getattr(held, name)
        seen = {repr(x) for x in current}
        current.extend(x for x in getattr(other, name) if repr(x) not in seen)
