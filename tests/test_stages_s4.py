"""S4 — every admitted SBN row read in full, behind the page (Step 12).

Two halves. The first is the gate's own clause, **through the stage and not
beside it**: the eight Stage 3 books' records go into a store as brief rows —
no ISBN, which is what a listing row carries (F5) — and `stages.enrich` reads
their full records from the committed bundle (`tests/data/fixtures/`, no network).
Folding the result must give `results/stage-3/q2_printings.json` again: 297
rows from 483 ISBN-bearing records. `test_core_fold.py` checks the fold over the
ISBNs the benchmark read; this checks that the store, the gap-filling and the
parser deliver those ISBNs to it.

The second is the wiring, with the fetch stubbed: what is asked, what a failure
leaves, what the cap says, and that a refused row is never paid for.
"""

import json
from pathlib import Path

import pytest

from catalog import fixtures, langs
from core import notes
from core.fold import fold
from core.model import (AUTHOR_SWEEP, ENRICHED, REFUSED, TITLE_MATCH,
                        UNIFORM_TITLE, WORK_LISTING, Provenance, Record, Work)
from core.store import RecordStore
from lookup import stages

ROOT = Path(__file__).resolve().parent.parent
STAGE3 = ROOT / "tests" / "data" / "results" / "stage-3"
LISTED = Provenance("SBN", WORK_LISTING, UNIFORM_TITLE)


class _Identity:
    def __init__(self, work=None):
        self.work = work or Work(sbn_work="w", original_language="eng")


def brief(bid, provenance=LISTED, **kw) -> Record:
    return Record(source="SBN", id=bid, provenance=provenance, **kw)


# ---------------------------------------------------------------------------
# The gate, through the stage
# ---------------------------------------------------------------------------

@pytest.fixture
def bundle(monkeypatch):
    monkeypatch.setenv("BOOK_FIXTURES", str(ROOT / "tests" / "data" / "fixtures"))
    fixtures.reset()
    yield
    fixtures.reset()


def test_s4_reproduces_q2_printings_from_brief_rows(bundle):
    recorded = json.loads((STAGE3 / "records.json").read_text(encoding="utf-8"))
    q2 = json.loads((STAGE3 / "q2_printings.json").read_text(encoding="utf-8"))
    got = {"sbn_rows": 0, "rows_with_isbn": 0, "rows_without_isbn": 0,
           "edition_rows_by_isbn": 0, "editions_with_several_printings": 0,
           "records_in_those": 0}
    for book, per_bid in recorded.items():
        store = RecordStore()
        for bid, r in per_bid.items():
            if r["fetched"]:
                store.put(brief(bid))
        assert all(not r.isbn for r in store.records())
        found = stages.enrich(_Identity(), store).evidence
        assert found["failed"] == 0 and found["empty"] == 0, book
        assert found["read"] == len(store)

        editions = fold(store.records())
        with_isbn = [e for e in editions if e.isbn]
        multi = [e for e in with_isbn if len(e.records) > 1]
        got["sbn_rows"] += len(store)
        got["rows_with_isbn"] += sum(len(e.records) for e in with_isbn)
        got["rows_without_isbn"] += sum(1 for e in editions if not e.isbn)
        got["edition_rows_by_isbn"] += len(with_isbn)
        got["editions_with_several_printings"] += len(multi)
        got["records_in_those"] += sum(len(e.records) for e in multi)
    assert got == {k: q2["pooled"][k] for k in got}
    assert (got["rows_with_isbn"], got["edition_rows_by_isbn"]) == (483, 297)


# ---------------------------------------------------------------------------
# The wiring, with the fetch stubbed
# ---------------------------------------------------------------------------

def full(bid, **kw) -> dict:
    fields = {"source": "SBN", "id": bid, "title": "Nineteen eighty-four",
              "publisher": "Secker & Warburg", "year": "1949", "language": "eng",
              "isbn": None, "isbns_raw": [], "url": None, "series": None,
              "physical": "326 p.", "dewey": "823.912", "dewey_all": ["823.912"],
              "medium": "Testo a stampa", "cover_url": None, "authors": [],
              "translators": [], "evidence": [], "holdings": [],
              "publisher_names": ["Secker & Warburg"], "places": ["London"]}
    fields.update(kw)
    return fields


@pytest.fixture
def served(monkeypatch):
    """`bid -> full fields`, or None for a failed fetch. Records what was asked."""
    answers, asked = {}, []

    def fake(bid):
        asked.append(bid)
        value = answers.get(bid)
        return stages.full_fields(value) if value is not None else None

    monkeypatch.setattr(stages, "_enrich", fake)
    return answers, asked


class TestWhatIsRead:
    def test_printings_under_one_isbn_fold_into_one_row(self, served):
        answers, _ = served
        store = RecordStore()
        for bid, year in (("A1", "1985"), ("A2", "2026"), ("B1", "1990")):
            store.put(brief(bid, year=year))
        answers.update(A1=full("A1", year="1985", isbns_raw=["9788845906862"]),
                       A2=full("A2", year="2026", isbns_raw=["88-459-0686-6"]),
                       B1=full("B1", year="1990"))
        assert len(fold(store.records())) == 3
        ev = stages.enrich(_Identity(), store).evidence
        editions = fold(store.records())
        assert len(editions) == 2
        adelphi = next(e for e in editions if e.isbn)
        assert adelphi.printings == ["1985", "2026"] and adelphi.latest == "2026"
        assert ev["read"] == 3 and ev["gained_isbn"] == 2

    def test_a_second_isbn_on_the_full_record_joins_transitively(self, served):
        """`isbns_raw` is gap-filled, not just `isbn` — a paperback and hardback
        on one `numeri` field are what join two other printings."""
        answers, _ = served
        store = RecordStore()
        for bid in ("P", "Q", "R"):
            store.put(brief(bid))
        answers.update(P=full("P", isbns_raw=["9780141036144"]),
                       Q=full("Q", isbns_raw=["9780141036144", "9780141187761"]),
                       R=full("R", isbns_raw=["9780141187761"]))
        stages.enrich(_Identity(), store)
        assert len(fold(store.records())) == 1

    def test_a_recovered_row_gains_its_language(self, served):
        answers, _ = served
        store = RecordStore()
        store.put(brief("S3", Provenance("SBN", AUTHOR_SWEEP, TITLE_MATCH, 1.0)))
        answers["S3"] = full("S3", language="ita")
        ev = stages.enrich(_Identity(), store).evidence
        assert store.get("SBN", "S3").language == "ita"
        assert ev["gained_language"] == 1

    def test_the_full_record_s_language_is_judged_by_rule_4(self, served):
        """UBO4636099's shape: an English translation filed as the original's
        language. It stays unrecorded, and it is disclosed once."""
        answers, _ = served
        store = RecordStore()
        store.put(brief("UBO4636099"))
        store.put(brief("SEEN"))
        answers["UBO4636099"] = full("UBO4636099", language="jpn",
                                     translators=["Gabriel, Philip"])
        answers["SEEN"] = full("SEEN", language="jpn", translators=["Gabriel, Philip"])
        work = Work(sbn_work="w", original_language="jpn")
        ev = stages.enrich(_Identity(work), store, disbelieved=["SEEN"]).evidence
        assert store.get("SBN", "UBO4636099").language == langs.UNKNOWN
        assert [n["record"] for n in ev["language_disbelieved"]] == ["UBO4636099"]

    def test_refused_rows_and_other_sources_are_not_read(self, served):
        _, asked = served
        store = RecordStore()
        store.put(brief("IN"))
        store.put(brief("OUT", Provenance("SBN", AUTHOR_SWEEP, REFUSED, 0.0)))
        store.put(Record(source="Open Library", id="OL1M", provenance=LISTED))
        stages.enrich(_Identity(), store)
        assert asked == ["IN"]

    def test_a_row_already_read_is_not_read_again(self, served):
        answers, asked = served
        store = RecordStore()
        store.put(brief("X"))
        answers["X"] = full("X")
        stages.enrich(_Identity(), store)
        stages.enrich(_Identity(), store)
        assert asked == ["X"]
        assert [p.route for p in store.routes(store.get("SBN", "X"))] == \
            [WORK_LISTING, ENRICHED]
        # The evidence that admitted it is the listing's, still.
        assert store.get("SBN", "X").provenance.evidence == UNIFORM_TITLE


class TestTheLabelSurvives:
    def test_a_full_record_does_not_add_the_original_author_to_the_heading(self, served):
        """`TO10037839`, Penguin Readers: SBN heads it MacKenzie, and its full
        record's `nomi` lists `[Autore] Orwell, George` beside her. Unioned, the
        row stopped being labelled; decision Z's label is read off the heading."""
        answers, _ = served
        store = RecordStore()
        store.put(brief("TO10037839", authors=["MacKenzie, Fiona"]))
        answers["TO10037839"] = full("TO10037839",
                                     authors=["MacKenzie, Fiona", "Orwell, George"])
        stages.enrich(_Identity(), store)
        assert store.get("SBN", "TO10037839").authors == ["MacKenzie, Fiona"]

    def test_a_row_with_no_heading_takes_the_full_record_s_authors(self, served):
        answers, _ = served
        store = RecordStore()
        store.put(brief("X"))
        answers["X"] = full("X", authors=["Orwell, George"])
        stages.enrich(_Identity(), store)
        assert store.get("SBN", "X").authors == ["Orwell, George"]


class TestWhatIsNotRead:
    def test_a_failed_fetch_keeps_the_brief_row_and_is_counted(self, served):
        answers, _ = served
        store = RecordStore()
        store.put(brief("GONE", year="2001"))
        ev = stages.enrich(_Identity(), store).evidence
        assert ev["failed"] == 1 and ev["read"] == 0
        assert store.get("SBN", "GONE").year == "2001"

    def test_a_skeleton_body_is_not_this_row(self, served):
        """F13: a bogus BID answers with a record carrying no id. `put` would
        add it as a new row, so it is counted and dropped."""
        answers, _ = served
        store = RecordStore()
        store.put(brief("BOGUS"))
        answers["BOGUS"] = full(None)
        ev = stages.enrich(_Identity(), store).evidence
        assert ev["empty"] == 1 and len(store) == 1

    def test_the_cap_is_a_line_on_the_page(self, served, monkeypatch):
        answers, asked = served
        monkeypatch.setattr(stages, "ENRICH_CAP", 2)
        store = RecordStore()
        for bid in ("a", "b", "c"):
            store.put(brief(bid))
            answers[bid] = full(bid)
        ev = stages.enrich(_Identity(), store).evidence
        assert asked == ["a", "b"]
        assert ev["truncated"] and (ev["asked"], ev["rows"]) == (2, 3)
        assert notes.truncations({"enrich": ev}) == [
            "full records were read for 2 of 3 SBN rows; the rest are listed as "
            "the listing has them, so their printings are not grouped"]

    def test_no_cap_no_line(self):
        assert notes.truncations({"enrich": {"truncated": False, "asked": 5,
                                             "rows": 5}}) == []


class TestDetailsAfterS4:
    def test_holdings_come_off_the_store_with_no_request(self, served, monkeypatch):
        monkeypatch.setattr(stages.ol, "book", lambda key: pytest.fail("fetched"))
        answers, _ = served
        store = RecordStore()
        store.put(brief("H"))
        answers["H"] = full("H", holdings=[{"library": "Biblioteca nazionale centrale",
                                            "city": "Firenze", "isil": "IT-FI0098"}],
                            translators=["Barbato, Antonio"])
        stages.enrich(_Identity(), store)
        found = stages.details(store, "SBN:H").edition["sbn"]
        assert found["read"] == 1
        assert found["holdings"][0]["city"] == "Firenze"
        assert found["translators"] == ["Barbato, Antonio"]
