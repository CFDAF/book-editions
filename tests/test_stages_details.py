"""One row opened — `lookup/stages.details`, with Open Library stubbed out.

This is not a stage: it writes nothing to the store and no version follows it.
It is the answer to a gesture, so what is tested here is that the gesture costs
what it should and says what it found:

* **only Open Library is fetched.** The SBN full record is Step 12's, arriving
  in the background for every row, and paying for it here would put the 34.5 s
  back one row at a time;
* **a failed fetch is a failure, never an absence** (`CLAUDE.md` rule 5) — a row
  whose details could not be loaded must not look like a row with nothing to
  add;
* **buy links need no request at all** and are there either way, because for an
  out-of-print book the links are the whole answer;
* **a stale row id is refused**, not answered with the nearest thing: an id that
  no longer exists means the row gained an ISBN and became a different edition,
  and handing back the wrong book is worse than handing back nothing.

`conftest.py` blocks sockets for the whole session, so a stub that forgets to
intercept fails loudly rather than quietly measuring live data.
"""

import pytest

from catalog.http import SourceError
from core.model import Provenance, Record
from core.store import RecordStore
from lookup import stages

LISTED = Provenance("SBN", "work listing", "uniform title")
FROM_OL = Provenance("Open Library", "work editions", "work key")


def store_with(*records) -> RecordStore:
    store = RecordStore()
    store.put_all(records)
    return store


def sbn(bid="RMB0810956", isbn=None):
    return Record(source="SBN", id=bid, provenance=LISTED, title="1984",
                  publisher="Faber, London", year="2021", isbn=isbn,
                  url=f"https://opac.sbn.it/bid/{bid}")


def ol(key="OL57360519M", isbn=None):
    return Record(source="Open Library", id=key, provenance=FROM_OL, title="1984",
                  publisher="Faber & Faber", year="2021", isbn=isbn,
                  url=f"https://openlibrary.org/books/{key}")


# A real record, as `https://openlibrary.org/books/OL57360519M.json` returned it
# on 2026-09-23 — the Easton Press *Nineteen eighty-four*. Fields this module
# does not read are left out; nothing that is here was invented.
BODY = {"key": "/books/OL57360519M", "title": "Nineteen eighty-four",
        "publish_date": "1992", "edition_name": "Collector's ed.",
        "by_statement": "George Orwell ; Introduction by James Gunn ; "
                        "Artwork by Frank Kelly Freas",
        "notes": "Collector's notes laid in.", "contributions": ["Easton Press"],
        "publishers": ["Easton Press"], "publish_places": ["Norwalk, CT"],
        "pagination": "xiii, 314 p.", "number_of_pages": 314,
        "ocaid": "nineteeneightyfo0000geor_a4u8", "covers": [15257442],
        "languages": [{"key": "/languages/eng"}]}


@pytest.fixture
def fetched(monkeypatch):
    """Record which keys were asked for, and answer with one real body shape."""
    asked = []

    def book(key):
        asked.append(key)
        return dict(BODY)

    monkeypatch.setattr(stages.ol, "book", book)
    return asked


class TestWhatIsFetched:
    def test_an_open_library_row_is_fetched_and_parsed(self, fetched):
        found = stages.details(store_with(ol()), "Open Library:OL57360519M")
        assert fetched == ["OL57360519M"]
        assert found.edition["open_library"]["pages"] == 314
        assert found.edition["open_library"]["edition_name"] == "Collector's ed."
        assert found.evidence["asked"] is True

    def test_an_sbn_only_row_asks_nothing_and_says_why(self, fetched):
        found = stages.details(store_with(sbn()), "SBN:RMB0810956")
        assert fetched == []
        assert found.edition["open_library"] is None
        assert found.evidence["asked"] is False
        assert "no record" in found.evidence["why_not"]
        # The SBN half is read off the store; this row's full record was never
        # read, and the panel must be able to say so.
        assert found.edition["sbn"]["read"] == 0
        assert found.edition["sbn"]["holdings"] == []

    def test_a_folded_row_is_fetched_by_its_open_library_half(self, fetched):
        """Two sources on one ISBN are one row, and only one of them has
        details to fetch."""
        found = stages.details(
            store_with(sbn(isbn="9780571355884"), ol(isbn="9780571355884")),
            "9780571355884")
        assert fetched == ["OL57360519M"]
        assert found.edition["open_library"]["title"] == "Nineteen eighty-four"

    def test_only_one_fetch_even_with_several_open_library_records(self, monkeypatch):
        calls = []

        def book(key):
            calls.append(key)
            return dict(BODY)

        monkeypatch.setattr(stages.ol, "book", book)
        stages.details(store_with(ol("OL1M", isbn="9780571355884"),
                                  ol("OL2M", isbn="9780571355884")), "9780571355884")
        assert calls == ["OL1M"]


class TestWhenItFails:
    def test_a_failed_fetch_is_reported_as_a_failure(self, monkeypatch):
        def book(key):
            raise SourceError("openlibrary.org: 503")

        monkeypatch.setattr(stages.ol, "book", book)
        found = stages.details(store_with(ol()), "Open Library:OL57360519M")
        assert found.edition["open_library"] is None
        assert found.evidence["asked"] is True            # it was asked, and it failed
        assert found.evidence["failed"][0]["key"] == "OL57360519M"
        assert found.evidence["sources"]["Open Library"].startswith("error:")

    def test_a_failure_on_one_record_falls_through_to_the_next(self, monkeypatch):
        tried = []

        def book(key):
            tried.append(key)
            if key == "OL1M":
                raise SourceError("openlibrary.org: 503")
            return dict(BODY)

        monkeypatch.setattr(stages.ol, "book", book)
        found = stages.details(store_with(ol("OL1M", isbn="9780571355884"),
                                          ol("OL2M", isbn="9780571355884")),
                               "9780571355884")
        assert tried == ["OL1M", "OL2M"]
        assert found.edition["open_library"] is not None
        assert found.evidence["sources"]["Open Library"] == stages.OK
        assert found.evidence["failed"]              # and the failure is still on record

    def test_an_id_the_store_no_longer_folds_to_is_refused(self, fetched):
        with pytest.raises(KeyError):
            stages.details(store_with(ol()), "9780571355884")


class TestTheLinks:
    def test_buy_links_need_no_request(self, monkeypatch):
        """No stub at all: reaching a catalogue here would fail on the socket
        ban, so this passing is the proof that nothing was fetched."""
        found = stages.details(store_with(sbn(isbn="9788845906862")), "9788845906862")
        assert [link["store"] for link in found.edition["buy_links"]][0] == "IBS"

    def test_a_row_with_no_isbn_gets_no_links(self, fetched):
        found = stages.details(store_with(sbn()), "SBN:RMB0810956")
        assert found.edition["buy_links"] == []

    def test_the_internet_archive_link_comes_off_the_record(self, fetched):
        """For an out-of-print book a readable scan is the only answer to
        'where do I get a copy' that is not a shop's guess."""
        found = stages.details(store_with(ol()), "Open Library:OL57360519M")
        assert found.edition["open_library"]["archive_url"].endswith(
            "nineteeneightyfo0000geor_a4u8")

    def test_an_empty_cover_slot_is_not_a_cover(self, monkeypatch):
        """`covers` carries -1 where a slot is empty, and real records have it:
        `OL7353617M` is `[15152634, 8739161, -1]`."""
        monkeypatch.setattr(stages.ol, "book", lambda key: {**BODY, "covers": [-1]})
        found = stages.details(store_with(ol()), "Open Library:OL57360519M")
        assert found.edition["open_library"]["cover_url"] is None
