"""`core/store.py` — one record per `(source, id)`, in the order it arrived.

Two properties the derivation rests on, so both are asserted rather than
assumed: a record arrives once however many routes found it, and the order it
comes back in is the producers' order and not a hash's. The store is also the
only thing that remembers *every* route, which is what the coverage ledger and
the recovered badge read.
"""

from catalog import langs
from core.model import (AUTHOR_SWEEP, REFUSED, TITLE_MATCH, UNIFORM_TITLE,
                        WORK_LISTING, Holding, Provenance, Record)
from core.store import RecordStore

LISTED = Provenance("SBN", WORK_LISTING, UNIFORM_TITLE)
SWEPT = Provenance("SBN", AUTHOR_SWEEP, TITLE_MATCH, 1.0)
BAND = Provenance("SBN", AUTHOR_SWEEP, REFUSED, 0.5)


def rec(rec_id, source="SBN", provenance=LISTED, **kw) -> Record:
    return Record(source=source, id=rec_id, provenance=provenance, **kw)


class TestOneRecordPerKey:
    def test_the_same_row_found_twice_is_one_record(self):
        store = RecordStore()
        store.put(rec("MIL0871878"))
        store.put(rec("MIL0871878", provenance=SWEPT))
        assert len(store) == 1

    def test_both_routes_are_remembered_in_arrival_order(self):
        store = RecordStore()
        held = store.put(rec("MIL0871878"))
        store.put(rec("MIL0871878", provenance=SWEPT))
        assert [p.route for p in store.routes(held)] == [WORK_LISTING, AUTHOR_SWEEP]

    def test_the_second_sighting_does_not_overwrite_the_first(self):
        """Producers run concurrently, so "last writer wins" would make the store
        depend on thread timing — and the derivation on nothing at all."""
        store = RecordStore()
        store.put(rec("A", title="Cent'anni di solitudine"))
        store.put(rec("A", title="CENT ANNI DI SOLITUDINE"))
        assert store.get("SBN", "A").title == "Cent'anni di solitudine"

    def test_a_full_record_arriving_second_fills_what_the_brief_one_lacked(self):
        """`search.json` has no language, no Dewey and no holdings; `full.json`
        for the same BID is that row with them."""
        store = RecordStore()
        store.put(rec("A", title="Rumori"))
        store.put(rec("A", language="ita", dewey="780.07",
                     holdings=[Holding("Nazionale", "Roma", "IT-RM0267")]))
        held = store.get("SBN", "A")
        assert held.language == "ita" and held.dewey == "780.07"
        assert [h.city for h in held.holdings] == ["Roma"]

    def test_a_brief_record_arriving_second_does_not_blank_the_language(self):
        store = RecordStore()
        store.put(rec("A", language="ita"))
        store.put(rec("A", language=langs.UNKNOWN))
        assert store.get("SBN", "A").language == "ita"

    def test_an_admitted_sighting_outranks_an_earlier_refusal(self):
        """The record *is* the work's; one route having failed to prove it does
        not unprove it."""
        store = RecordStore()
        store.put(rec("A", provenance=BAND))
        store.put(rec("A", provenance=LISTED))
        assert not store.get("SBN", "A").provenance.refused

    def test_a_refusal_arriving_after_an_acceptance_does_not_demote_it(self):
        store = RecordStore()
        store.put(rec("A", provenance=LISTED))
        store.put(rec("A", provenance=BAND))
        assert store.get("SBN", "A").provenance.evidence == UNIFORM_TITLE


class TestOrder:
    def test_records_come_back_in_the_order_they_were_written(self):
        store = RecordStore()
        ids = ["MIL0871878", "TO01234567", "UBO4636099", "CFI1172094"]
        store.put_all([rec(i) for i in ids])
        assert [r.id for r in store.records()] == ids

    def test_a_second_sighting_does_not_move_a_record_in_the_order(self):
        store = RecordStore()
        store.put_all([rec("A"), rec("B"), rec("C")])
        store.put(rec("A", provenance=SWEPT))
        assert [r.id for r in store.records()] == ["A", "B", "C"]


class TestRefusedRecordsAreKept:
    def test_a_refused_record_is_out_of_the_default_view_and_still_in_the_store(self):
        """Decision N: what was refused is a disclosure, and a dropped record
        cannot be audited."""
        store = RecordStore()
        store.put_all([rec("A"), rec("B", provenance=BAND)])
        assert [r.id for r in store.records()] == ["A"]
        assert [r.id for r in store.refused()] == ["B"]
        assert [r.id for r in store.records(include_refused=True)] == ["A", "B"]


class TestCoverage:
    def test_it_counts_what_was_found_by_source_route_and_evidence(self):
        store = RecordStore()
        store.put_all([
            rec("A"), rec("B"),
            rec("A", provenance=SWEPT),
            rec("C", source="Open Library",
                provenance=Provenance("Open Library", "work editions", "work key")),
            rec("D", provenance=BAND),
        ])
        coverage = store.coverage()
        assert coverage["records"] == 4
        assert coverage["admitted"] == 3 and coverage["refused"] == 1
        assert coverage["by_source"] == {"Open Library": 1, "SBN": 3}
        assert coverage["by_route"] == {AUTHOR_SWEEP: 2, "work editions": 1,
                                       WORK_LISTING: 2}
        assert coverage["by_evidence"] == {REFUSED: 1, UNIFORM_TITLE: 2,
                                           "work key": 1}

    def test_it_counts_routes_not_records_so_a_row_found_twice_shows_twice(self):
        """It is a reading of the provenance field: "how many did this route
        find" is a different question from "how many rows are there"."""
        store = RecordStore()
        store.put(rec("A"))
        store.put(rec("A", provenance=SWEPT))
        coverage = store.coverage()
        assert coverage["records"] == 1
        assert sum(coverage["by_route"].values()) == 2

    def test_there_is_no_census_in_it(self):
        """Decision C: VIAF cannot say how many editions exist (A6, 20 of 37
        books unusable), so "found N of ~M known" is not a thing this project
        says. Nothing here counts anything but what was found."""
        assert set(RecordStore().coverage()) == {
            "records", "admitted", "refused", "by_source", "by_route", "by_evidence"}


class TestMembership:
    def test_a_key_can_be_asked_for_without_being_fetched(self):
        store = RecordStore()
        store.put(rec("MIL0871878"))
        assert ("SBN", "MIL0871878") in store
        assert ("SBN", "ZZQ9999999") not in store
        assert ("Open Library", "MIL0871878") not in store


def test_a_reader_never_sees_the_store_change_size_under_it():
    """Details can be opened while S3 writes, and a snapshot derived while the
    reader's own *Add* does (Step 12's noticed row, closed in Step 13). Without
    the lock, iterating the dict another thread inserts into raises."""
    import threading

    from core.model import Provenance, Record
    store = RecordStore()
    errors, done = [], threading.Event()

    def write():
        for i in range(20000):
            store.put(Record(source="SBN", id=f"IT{i}",
                             provenance=Provenance("SBN", "title probe", "title match")))
        done.set()

    def read():
        while not done.is_set():
            try:
                store.records(), store.coverage(), store.refused()
            except RuntimeError as exc:
                errors.append(exc)
                return

    threads = [threading.Thread(target=write), threading.Thread(target=read)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(store) == 20000
