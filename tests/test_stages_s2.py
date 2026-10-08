"""S2 — `lookup/stages.list_editions`, offline, with the catalogues stubbed out.

The gates S2 calls are tested in `test_core_identity.py` and the row parsing in
`test_opac_rows.py`; what is tested here is the **wiring**, which is where this
step can go wrong without any gate being wrong:

* sending `ANY` with the listing query, which answers a different question (F2)
  and would list a third of the work;
* asking the OPAC for a work with no author, which answers with another book
  (`CLAUDE.md` rule 3);
* letting a language bucket shrink silently when a page fails or the facet caps;
* letting which language a parallel-text row keeps depend on thread timing;
* reporting "no work to list" as a source failure, which would put `partial` on
  a lookup where nothing went wrong.

Every catalogue call is monkeypatched. `conftest.py` blocks sockets for the
whole session, so a stub that forgets to intercept fails loudly rather than
quietly measuring live data.
"""

import pytest

from catalog import langs
from catalog.http import SourceError
from core.model import Work
from lookup import stages


def opac_row(bid, title, author="Orwell, George",
             imprint="London : Secker & Warburg, 1949",
             medium="Testo", language=None):
    return {"id": bid, "title": title, "author": author, "imprint": imprint,
            "infos": [imprint], "medium": medium, "level": "Monografia",
            "type": "text", "language": language}


def ol_row(key, title="Nineteen Eighty-Four", year="1949", language="eng",
           isbn=None):
    return {"source": "Open Library", "id": key, "title": title,
            "publisher": "Secker & Warburg", "year": year, "language": language,
            "isbn": isbn, "isbns_raw": [isbn] if isbn else [],
            "url": f"https://openlibrary.org/books/{key}", "series": None,
            "physical": None, "dewey": None, "dewey_all": [], "medium": None,
            "cover_url": None, "authors": ["George Orwell"], "translators": [],
            "evidence": [], "holdings": [], "publisher_names": ["Secker & Warburg"],
            "places": [], "translation_of": None, "works": ["/works/OL1W"]}


def identity(work=None, author="Orwell"):
    work = work if work is not None else Work(sbn_work="nineteen eighty-four",
                                              sbn_work_tier="strong",
                                              ol_keys=["OL1W"],
                                              authors=["George Orwell"])
    return stages.Identity(work=work, evidence={"question": {"author": author}})


@pytest.fixture
def catalogues(monkeypatch):
    """SBN answering one work and Open Library one set of editions."""
    state = {
        "facet": {"items": [{"value": "eng", "results": 2, "label": "INGLESE"},
                            {"value": "ita", "results": 1, "label": "ITALIANO"}],
                  "total": 3, "first": {}},
        "pages": {"eng": [opac_row("A1", "Nineteen eighty-four / George Orwell"),
                          opac_row("A2", "1984 / George Orwell")],
                  "ita": [opac_row("A3", "1984 / George Orwell",
                                   imprint="Milano : Mondadori, 1950")]},
        "whole": [],
        "ol": {"rows": [ol_row("OL9M")], "size": 1, "failed": []},
        "asked": [],
    }

    def work_languages(work, author):
        state["asked"].append(("facet", work, author))
        if not (work and author):
            raise ValueError("the OPAC work query always carries the author")
        return state["facet"]

    def work_records(work, author, language=None):
        state["asked"].append(("rows", work, author, language))
        if not (work and author):
            raise ValueError("the OPAC work query always carries the author")
        rows = state["pages"].get(language)
        if rows is None:
            raise SourceError(f"no stub for {language!r}")
        return {"rows": [{**r, "language": language} for r in rows],
                "total": len(rows), "pages": 1, "failed": [], "truncated": False}

    def all_rows(body, **kw):
        state["asked"].append(("whole", tuple(sorted(body))))
        return {"rows": state["whole"], "total": len(state["whole"]), "pages": 2,
                "failed": [], "truncated": False}

    def editions(key, **kw):
        state["asked"].append(("ol", key))
        return state["ol"]

    monkeypatch.setattr(stages.sbn_opac, "work_languages", work_languages)
    monkeypatch.setattr(stages.sbn_opac, "work_records", work_records)
    monkeypatch.setattr(stages.sbn_opac, "all_rows", all_rows)
    monkeypatch.setattr(stages.ol, "editions", editions)
    return state


# ---------------------------------------------------------------------------

class TestTheListingQuery:
    def test_it_asks_one_page_per_language_and_nothing_else(self, catalogues):
        stages.list_editions(identity())
        assert ("facet", "nineteen eighty-four", "Orwell") in catalogues["asked"]
        assert [a for a in catalogues["asked"] if a[0] == "rows"] == [
            ("rows", "nineteen eighty-four", "Orwell", "eng"),
            ("rows", "nineteen eighty-four", "Orwell", "ita")]

    def test_the_whole_work_is_not_paged_when_the_languages_add_up(self, catalogues):
        """Reading it as well would double the request cost of every lookup."""
        stages.list_editions(identity())
        assert not [a for a in catalogues["asked"] if a[0] == "whole"]

    def test_every_row_is_stored_with_the_language_of_its_page(self, catalogues):
        store = stages.list_editions(identity()).store
        assert {r.id: r.language for r in store.records()
                if r.source == "SBN"} == {"A1": "eng", "A2": "eng", "A3": "ita"}

    def test_an_sbn_row_is_admitted_by_the_catalogue_and_not_by_a_title_gate(
            self, catalogues):
        """`A2` is titled *1984* and the work is `nineteen eighty-four`: a title
        gate would score it 0.0 and refuse it. SBN said it is the work, and a
        statement outranks an inference — the gate is S3's."""
        store = stages.list_editions(identity()).store
        assert store.get("SBN", "A2").provenance.evidence == "uniform title"
        assert not store.refused()

    def test_nothing_is_listed_without_an_author(self, catalogues):
        """`CLAUDE.md` rule 3 — and it must not raise either: a lookup with no
        author for the OPAC still has Open Library to answer with."""
        listing = stages.list_editions(identity(author=""))
        assert listing.evidence["sbn"]["asked"] is False
        assert not [a for a in catalogues["asked"] if a[0] == "facet"]
        assert listing.evidence["open_library_rows"] == 1


class TestABucketNeverShrinksSilently:
    def test_a_failed_language_page_is_named_and_the_rest_stand(self, catalogues):
        catalogues["pages"].pop("ita")
        listing = stages.list_editions(identity())
        sbn = listing.evidence["sbn"]
        assert [f["language"] for f in sbn["failed"]] == ["ita"]
        assert listing.evidence["sbn_rows"] == 2          # the eng page survived

    def test_a_short_count_pages_the_whole_work_to_name_what_is_missing(
            self, catalogues):
        catalogues["facet"]["total"] = 4
        catalogues["whole"] = [opac_row("A4", "1984 / George Orwell")]
        listing = stages.list_editions(identity())
        assert listing.evidence["sbn"]["recovered"] == ["A4"]
        assert [a for a in catalogues["asked"] if a[0] == "whole"]

    def test_a_recovered_row_keeps_no_language_rather_than_a_guessed_one(
            self, catalogues):
        catalogues["facet"]["total"] = 4
        catalogues["whole"] = [opac_row("A4", "1984 / George Orwell")]
        store = stages.list_editions(identity()).store
        assert store.get("SBN", "A4").language == langs.UNKNOWN

    def test_a_capped_facet_is_reported(self, catalogues):
        """F11: the facet stops at 50 items, so 50 languages means 'at least'."""
        catalogues["facet"]["items"] = [{"value": f"x{i:02}", "results": 1}
                                        for i in range(50)]
        catalogues["pages"] = {f"x{i:02}": [] for i in range(50)}
        assert stages.list_editions(identity()).evidence["sbn"]["facet_truncated"]


class TestAParallelTextRow:
    def test_it_is_stored_once_and_both_languages_are_reported(self, catalogues):
        """51 of 2,603 rows come back on two language pages — a Russian/Italian
        parallel text, a Latin/Italian edition."""
        catalogues["pages"]["ita"].append(
            opac_row("A1", "Nineteen eighty-four / George Orwell"))
        listing = stages.list_editions(identity())
        assert listing.evidence["sbn_rows"] == 3
        assert listing.evidence["sbn"]["multi_language"] == {"A1": ["eng", "ita"]}

    def test_it_keeps_the_language_of_the_larger_bucket_not_of_the_faster_thread(
            self, catalogues):
        """Facet order is by count, so the answer is the same on every run. The
        store's arrival order is what breaks every tie downstream of it."""
        catalogues["pages"]["ita"].append(
            opac_row("A1", "Nineteen eighty-four / George Orwell"))
        store = stages.list_editions(identity()).store
        assert store.get("SBN", "A1").language == "eng"


class TestTheLanguageAROWClaimsIsNotAlwaysBelieved:
    def test_a_record_naming_a_translator_in_the_work_s_own_language(self, catalogues):
        """`UBO4636099` — 'translated from the Japanese', filed GIAPPONESE."""
        catalogues["facet"] = {"items": [{"value": "jpn", "results": 1}],
                               "total": 1, "first": {}}
        catalogues["pages"] = {"jpn": [opac_row(
            "UBO4636099",
            "Kafka on the shore / Haruki Murakami ; translated from the Japanese "
            "by Philip Gabriel", author="Murakami, Haruki")]}
        work = Work(sbn_work="umibe no kafuka", ol_keys=[], original_language="jpn")
        listing = stages.list_editions(identity(work=work, author="Murakami"))
        assert listing.store.get("SBN", "UBO4636099").language == langs.UNKNOWN
        assert [d["record"] for d in listing.evidence["language_disbelieved"]] \
            == ["UBO4636099"]

    def test_a_cyrillic_title_filed_as_english(self, catalogues):
        catalogues["facet"] = {"items": [{"value": "eng", "results": 1}],
                               "total": 1, "first": {}}
        catalogues["pages"] = {"eng": [opac_row(
            "RAV1", "Преступлéние и наказáние. 1/2", author="Dostoevskij, Fedor")]}
        work = Work(sbn_work="prestuplenie i nakazanie", ol_keys=[])
        listing = stages.list_editions(identity(work=work, author="Dostoevskij"))
        assert listing.store.get("SBN", "RAV1").language == langs.UNKNOWN
        assert "script" in listing.evidence["language_disbelieved"][0]["why"]

    def test_the_row_is_kept_rather_than_dropped(self, catalogues):
        """A disbelieved language is not a disbelieved record. The old pipeline
        dropped it and `docs/limits.md` case 13 has looked for it ever since."""
        catalogues["facet"] = {"items": [{"value": "eng", "results": 1}],
                               "total": 1, "first": {}}
        catalogues["pages"] = {"eng": [opac_row("RAV1", "Преступлéние и наказáние")]}
        listing = stages.list_editions(identity(work=Work(sbn_work="w", ol_keys=[])))
        assert listing.store.get("SBN", "RAV1") is not None


class TestOpenLibrary:
    def test_editions_come_by_work_key(self, catalogues):
        stages.list_editions(identity())
        assert ("ol", "OL1W") in catalogues["asked"]

    def test_a_work_with_no_key_is_not_asked_and_is_not_a_failure(self, catalogues):
        work = Work(sbn_work="nineteen eighty-four", ol_keys=[])
        listing = stages.list_editions(identity(work=work))
        assert listing.evidence["open_library"]["asked"] is False
        assert listing.evidence["sources"]["Open Library"] == stages.OK

    def test_the_editions_fields_open_library_carries_for_itself_are_dropped(
            self, catalogues):
        """`translation_of` and `works` are recorded and relied on nowhere —
        `Record` has no field for either, so passing them through would raise
        rather than being ignored. This test is that `TypeError` not happening."""
        record = stages.list_editions(identity()).store.get("Open Library", "OL9M")
        assert record.title == "Nineteen Eighty-Four"
        assert not hasattr(record, "translation_of")


class TestAFailingSourceIsNotAnEmptyAnswer:
    def test_a_healthy_lookup_says_so_for_both_sources(self, catalogues):
        listing = stages.list_editions(identity())
        assert listing.evidence["sources"] == {"SBN": stages.OK,
                                               "Open Library": stages.OK}

    def test_a_failing_sbn_leaves_open_library_s_records_standing(
            self, catalogues, monkeypatch):
        def boom(*a, **k):
            raise SourceError("SBN down")
        monkeypatch.setattr(stages.sbn_opac, "work_languages", boom)
        listing = stages.list_editions(identity())
        assert listing.evidence["sources"]["SBN"].startswith("error:")
        assert listing.evidence["open_library_rows"] == 1

    def test_a_failing_open_library_leaves_sbn_s_records_standing(
            self, catalogues, monkeypatch):
        def boom(*a, **k):
            raise SourceError("Open Library down")
        monkeypatch.setattr(stages.ol, "editions", boom)
        listing = stages.list_editions(identity())
        assert listing.evidence["sources"]["Open Library"].startswith("error:")
        assert listing.evidence["sbn_rows"] == 3

    def test_not_asked_is_never_reported_as_a_failure(self, catalogues):
        """Rule 5 runs one way: a failure must not look like an empty result. An
        empty result must not look like a failure either, or every book with no
        SBN work reports `partial`."""
        listing = stages.list_editions(identity(work=Work()))
        assert set(listing.evidence["sources"].values()) == {stages.OK}
        assert listing.evidence["records"] == 0


class TestTheStoreIsShared:
    def test_a_caller_s_store_is_written_into_rather_than_replaced(self, catalogues):
        """S3, S4 and the duplicate works all add to the same store, and the
        view is derived from it once."""
        first = stages.list_editions(identity())
        again = stages.list_editions(identity(), store=first.store)
        assert again.store is first.store
        assert len(first.store) == 4         # the same rows, seen twice


class TestOtherUniformTitles:
    """A work SBN files under two romanisations (Step 14) lists under both."""

    @pytest.fixture
    def two(self, catalogues, monkeypatch):
        first = stages.sbn_opac.work_languages
        rows = stages.sbn_opac.work_records

        def work_languages(work, author):
            if work == "1984":
                catalogues["asked"].append(("facet", work, author))
                return {"items": [{"value": "ita", "results": 2}], "total": 2, "first": {}}
            return first(work, author)

        def work_records(work, author, language=None):
            if work == "1984":
                catalogues["asked"].append(("rows", work, author, language))
                return {"rows": [{**opac_row("A3", "1984"), "language": "ita"},
                                 {**opac_row("B9", "1984"), "language": "ita"}],
                        "total": 2, "pages": 1, "failed": [], "truncated": False}
            return rows(work, author, language)
        monkeypatch.setattr(stages.sbn_opac, "work_languages", work_languages)
        monkeypatch.setattr(stages.sbn_opac, "work_records", work_records)
        return catalogues

    def test_both_are_listed_once_per_record(self, two):
        work = Work(sbn_work="nineteen eighty-four", sbn_work_tier="strong",
                    sbn_other_works=["1984"], authors=["George Orwell"])
        listing = stages.list_editions(identity(work))
        ids = sorted(r.id for r in listing.store.records() if r.source == "SBN")
        assert ids == ["A1", "A2", "A3", "B9"]
        sbn = listing.evidence["sbn"]
        assert sbn["total"] == 5 and sbn["by_language"] == {"eng": 2, "ita": 3}
        assert sbn["others"] == [{"W": "1984", "state": "ok", "total": 2, "requests": 2}]

    def test_a_failing_other_title_marks_the_source_and_keeps_w(self, two, monkeypatch):
        def work_languages(work, author):
            if work == "1984":
                raise SourceError("503")
            return two["facet"]
        monkeypatch.setattr(stages.sbn_opac, "work_languages", work_languages)
        work = Work(sbn_work="nineteen eighty-four", sbn_work_tier="strong",
                    sbn_other_works=["1984"])
        listing = stages.list_editions(identity(work))
        assert listing.evidence["sbn"]["state"].startswith("error:")
        assert len([r for r in listing.store.records() if r.source == "SBN"]) == 3
