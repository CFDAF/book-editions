"""`core/view.py` — the snapshot, and the gate that it is the same every time.

Step 5's gate: **`view.py` produces an identical snapshot from an identical store
across 100 runs.** Tested rather than assumed, because a non-deterministic
derivation is a page that disagrees with its own store, and because the way it
goes wrong — a set iterated somewhere — is invisible until the day it is not.

100 runs in one process is the weaker half. `tests/snapshot_probe.py` runs the
same build in two subprocesses under different `PYTHONHASHSEED` values, which is
what actually catches a set: within one process, string hashing is stable.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import snapshot_probe
from catalog import langs
from core import view
from core.model import (DUPLICATE_WORK, REFUSED, TITLE_MATCH, UNIFORM_TITLE,
                        WORK_EDITIONS, WORK_KEY, WORK_LISTING, Provenance, Record,
                        Work)
from core.store import RecordStore

PROBE = Path(snapshot_probe.__file__)
LISTED = Provenance("SBN", WORK_LISTING, UNIFORM_TITLE)


def rec(rec_id, source="SBN", provenance=LISTED, **kw) -> Record:
    return Record(source=source, id=rec_id, provenance=provenance, **kw)


def store_of(*records) -> RecordStore:
    store = RecordStore()
    store.put_all(records)
    return store


def digest(snapshot) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False).encode()).hexdigest()


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_one_hundred_runs_of_the_same_store_give_the_same_snapshot(self):
        store, work = snapshot_probe.build()
        first = digest(view.snapshot(store, work, version=3))
        assert all(digest(view.snapshot(store, work, version=3)) == first
                   for _ in range(99))

    def test_two_identically_built_stores_give_the_same_snapshot(self):
        a, work_a = snapshot_probe.build()
        b, work_b = snapshot_probe.build()
        assert digest(view.snapshot(a, work_a, version=3)) \
            == digest(view.snapshot(b, work_b, version=3))

    @pytest.mark.parametrize("seeds", [("1", "2"), ("0", "12345")])
    def test_the_snapshot_does_not_move_with_the_hash_seed(self, seeds):
        """The half that actually catches an iterated set: string hashing is
        stable inside one process and randomised between them."""
        out = []
        for seed in seeds:
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run([sys.executable, str(PROBE)], env=env,
                                  capture_output=True, text=True, check=True)
            out.append(done.stdout.strip())
        assert out[0] == out[1] and len(out[0]) == 64


# ---------------------------------------------------------------------------
# Grouping and ordering
# ---------------------------------------------------------------------------

class TestGroupByLanguage:
    def test_an_edition_with_no_recorded_language_stays_in_the_answer(self):
        """Not folded into English, and not dropped: Open Library records a
        language for 80.8% of editions, so the other fifth has to go somewhere
        the reader can see."""
        grouped = view.group_by_language(
            _editions(rec("A", language="ita"), rec("B")))
        assert set(grouped) == {"ita", langs.UNKNOWN}

    def test_spans_are_earliest_first_so_the_original_leads(self):
        work = Work(original_language="spa", original_year="1967")
        grouped = view.group_by_language(_editions(
            rec("A", language="ita", year="1968"),
            rec("B", language="spa", year="1967"),
            rec("C", language="eng", year="1970")))
        assert [s["code"] for s in view.spans(work, grouped)] == ["spa", "ita", "eng"]

    def test_an_unrecorded_language_sorts_last_whatever_its_years(self):
        grouped = view.group_by_language(_editions(
            rec("A", year="1900"), rec("B", language="ita", year="2020")))
        assert [s["code"] for s in view.spans(None, grouped)] == ["ita", langs.UNKNOWN]

    def test_an_undated_language_sorts_after_the_dated_ones(self):
        grouped = view.group_by_language(_editions(
            rec("A", language="fre"), rec("B", language="ita", year="2020")))
        assert [s["code"] for s in view.spans(None, grouped)] == ["ita", "fre"]


class TestSpanIsOriginal:
    """The tag names a language but is read as naming the row, so the row has to
    be able to support it — a giapponese row reading 1972-2005 once carried it
    directly under 'first published 2002 in giapponese'."""

    def test_the_original_language_span_covering_the_original_year_is_marked(self):
        assert view.span_is_original(Work(original_language="spa",
                                          original_year="1967"), "spa", [1967, 2020])

    def test_a_span_that_cannot_contain_the_original_year_is_not(self):
        assert not view.span_is_original(Work(original_language="jpn",
                                              original_year="2002"), "jpn", [1972, 1980])

    def test_another_language_is_never_the_original(self):
        assert not view.span_is_original(Work(original_language="spa",
                                              original_year="1967"), "ita", [1967])

    def test_with_no_year_known_the_language_is_the_best_evidence_there_is(self):
        assert view.span_is_original(Work(original_language="spa"), "spa", [1990])

    def test_no_work_means_no_original_span(self):
        assert not view.span_is_original(None, "spa", [1967])


# ---------------------------------------------------------------------------
# The header
# ---------------------------------------------------------------------------

class TestOriginPhrase:
    def test_a_stated_year_and_language_are_stated_together(self):
        assert view.origin_phrase(1967, "spagnolo", 1985) \
            == "first published 1967 in spagnolo"

    def test_a_stated_year_alone(self):
        assert view.origin_phrase(2002, None, 1972) == "first published 2002"

    def test_a_known_language_is_never_paired_with_a_fallback_year(self):
        """'first published 1976 in inglese' would take the year from an Italian
        edition and the language from the English original, and is simply false."""
        assert view.origin_phrase(None, "inglese", 1976) \
            == "originally in inglese, earliest edition found 1976"

    def test_with_nothing_stated_only_what_was_found_is_said(self):
        assert view.origin_phrase(None, None, 1976) == "earliest edition found 1976"

    def test_with_nothing_at_all_it_says_nothing(self):
        assert view.origin_phrase(None, None, None) == ""


class TestStatedWhen:
    """The stated date as precise as Wikidata was: the P577s of
    decision AY's year probe."""

    @pytest.mark.parametrize("date,expected", [
        ((1866, 9), "1866"),                         # Crime and Punishment
        ((1838, 7), "in the 19th century"),          # Le livre des rois
        ((1304, 8), "in the 1300s"),                 # Convivio
        ((1316, 8), "in the 1310s"),                 # De Monarchia
        ((1500, 7), "in the 15th century"),          # Ovide du remede d'amours
        ((1901, 7), "in the 20th century"),
        ((1021, 7), "in the 11th century"),          # Kumogakure
        ((-600, 7), "in the 6th century BCE"),       # Batrachomyomachia
        ((-39, 9), "39 BCE"),                        # Eclogue 4
        ((1112, 7), "in the 12th century"),
        ((-1000, 6), None),                          # a millennium: not stated
    ])
    def test_as_precise_as_the_source(self, date, expected):
        assert view.stated_when(Work(original_date=date)) == expected

    def test_a_year_with_no_date_is_still_stated(self):
        assert view.stated_when(Work(original_year="1967")) == "1967"

    def test_nothing_stated(self):
        assert view.stated_when(Work()) is None
        assert view.stated_when(None) is None


class TestHeader:
    def test_it_states_the_original_and_the_earliest_found_side_by_side(self):
        """Decision D. It never compares them: the listing rule gave 8 false
        'first edition differs' flags and 1 miss over 36 books."""
        work = Work(original_title="Cien años de soledad", original_language="spa",
                    original_year="1967", stated_by="Wikidata")
        grouped = view.group_by_language(_editions(rec("A", language="ita", year="1985")))
        header = view.header(work, grouped, view.spans(work, grouped))
        assert header["original_year"] == 1967
        assert header["first_year_seen"] == 1985
        assert header["origin"] == "first published 1967 in spagnolo"
        assert not any("differs" in str(v) for v in header.values())

    def test_a_century_is_stated_as_one_and_filters_nothing(self):
        """Q95850477 *Le livre des rois*, P577 `+1838` at century precision.
        It read "first published 1838" and kept every printing before 1838 out
        of the earliest edition found; a century is neither."""
        work = Work(original_language="per", original_date=(1838, 7),
                    stated_by="Wikidata")
        grouped = view.group_by_language(_editions(rec("A", language="fre", year="1876")))
        header = view.header(work, grouped, view.spans(work, grouped))
        assert header["origin"] == "first published in the 19th century in persiano"
        assert header["original_year"] is None
        assert header["earliest"]["older_dropped"] == 0

    def test_with_no_stated_original_the_header_states_none(self):
        """Rule 8. The earliest edition found has a line of its own, so the
        origin phrase never borrows a year from an edition to stand in for one
        no source gave."""
        grouped = view.group_by_language(_editions(rec("A", language="ita", year="1985")))
        header = view.header(Work(), grouped, view.spans(Work(), grouped))
        assert header["original_year"] is None
        assert header["original_language"] is None
        assert header["original_stated"] is False
        assert header["origin"] == ""
        assert header["earliest"]["year"] == 1985

    def test_the_title_is_the_earliest_editions_when_no_original_is_known(self):
        """Counting occurrences picked the Italian title for 'The Invention of
        News': the two English records differ in article and casing and tie."""
        editions = _editions(
            rec("A", title="L'invenzione delle notizie", year="2015"),
            rec("B", title="The Invention of News", year="2014"),
            rec("C", title="the invention of news", year="2016"))
        assert view.display_title(editions, Work()) == "The Invention of News"

    def test_a_stated_original_title_wins_over_every_edition(self):
        editions = _editions(rec("A", title="Rumori", year="1978"))
        assert view.display_title(editions, Work(original_title="Bruits")) == "Bruits"


# ---------------------------------------------------------------------------
# Which book a row belongs to
# ---------------------------------------------------------------------------

class TestAssignGroups:
    def test_one_man_spelled_two_ways_is_one_book(self):
        rows = _editions(rec("A", authors=["García Márquez, Gabriel"]),
                         rec("B", authors=["Gabriel Garcia Marquez"]))
        keys = view.assign_groups(rows, [])
        assert keys[0] == keys[1]

    def test_two_unrelated_books_sharing_a_title_stay_apart(self):
        """'La matrice sociale della psichiatria' is Ruesch and Bateson in 1976
        and Michael Shepherd in 1990."""
        rows = _editions(rec("A", authors=["Ruesch, Jurgen", "Bateson, Gregory"]),
                         rec("B", authors=["Shepherd, Michael"]))
        keys = view.assign_groups(rows, [])
        assert keys[0] != keys[1]

    def test_a_row_with_no_author_inherits_the_works(self):
        rows = _editions(rec("A", authors=["Attali, Jacques"]), rec("B"))
        keys = view.assign_groups(rows, ["Attali, Jacques"])
        assert keys[0] == keys[1]

    def test_it_returns_a_key_per_row_and_mutates_nothing(self):
        rows = _editions(rec("A", authors=["Attali, Jacques"]))
        before = rows[0].records[0].authors[:]
        keys = view.assign_groups(rows, ["Someone Else"])
        assert len(keys) == len(rows)
        assert rows[0].records[0].authors == before


class TestChoices:
    def test_one_book_is_not_a_choice(self):
        rows = _editions(rec("A", authors=["Attali, Jacques"], year="1977"))
        assert view.choices(rows, view.assign_groups(rows, [])) == []

    def test_two_books_are_listed_newest_first(self):
        rows = _editions(
            rec("A", title="La matrice sociale della psichiatria",
                authors=["Ruesch, Jurgen"], year="1976"),
            rec("B", title="La matrice sociale della psichiatria",
                authors=["Shepherd, Michael"], year="1990"))
        out = view.choices(rows, view.assign_groups(rows, []))
        assert [c["last_year"] for c in out] == [1990, 1976]

    def test_one_man_is_not_offered_as_a_collaboration(self):
        """Compared on stripped tokens 'Gabriel García Márquez' and 'Gabriel
        Garcia Marquez' are one person; the accented spelling is shown."""
        rows = _editions(
            rec("A", authors=["Gabriel García Márquez"], year="1985"),
            rec("B", authors=["Gabriel Garcia Marquez"], year="1990"),
            rec("C", authors=["Shepherd, Michael"], year="1991"))
        out = view.choices(rows, view.assign_groups(rows, []))
        marquez = next(c for c in out if "arc" in c["authors"][0])
        assert marquez["authors"] == ["Gabriel García Márquez"]


# ---------------------------------------------------------------------------
# The snapshot's shape
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_the_band_is_separate_from_the_editions_and_the_counts(self):
        """Decision N: refused records are shown, collapsed, and counted nowhere
        near the header's totals."""
        store = store_of(rec("A", language="ita", year="1985"),
                         rec("B", language="ita", year="1984",
                             provenance=Provenance("SBN", "author sweep", REFUSED, 0.5)))
        snapshot = view.snapshot(store, Work())
        assert snapshot["header"]["total_editions"] == 1
        band = snapshot["loose_matches"]
        assert band["total"] == 1
        assert [r["id"] for g in band["groups"] for r in g["rows"]] == ["B"]
        assert snapshot["header"]["first_year_seen"] == 1985

    def test_a_band_row_carries_the_score_it_was_refused_at(self):
        store = store_of(rec("B", title="Postille a Il nome della rosa",
                             provenance=Provenance("SBN", "author sweep", REFUSED, 0.5)))
        row = view.snapshot(store, Work())["loose_matches"]["groups"][0]["rows"][0]
        assert row["route"] == "author sweep"
        assert row["score"] == 0.5

    def test_every_route_that_reached_a_row_is_on_it(self):
        store = RecordStore()
        store.put(rec("A", language="ita", year="1985"))
        store.put(rec("A", provenance=Provenance("SBN", "author sweep", TITLE_MATCH, 1.0)))
        row = view.snapshot(store, Work())["editions_by_language"]["ita"][0]
        assert [p["route"] for p in row["provenance"]] == [WORK_LISTING, "author sweep"]

    def test_the_coverage_ledger_is_in_the_snapshot(self):
        store = store_of(rec("A", language="ita"))
        assert view.snapshot(store, Work())["coverage"]["records"] == 1

    def test_the_language_order_matches_the_spans(self):
        store = store_of(rec("A", language="ita", year="1985"),
                         rec("B", language="spa", year="1967"))
        snapshot = view.snapshot(store, Work(original_language="spa"))
        assert snapshot["language_order"] == [s["code"] for s in snapshot["header"]["spans"]]
        assert set(snapshot["language_order"]) == set(snapshot["editions_by_language"])

    def test_an_empty_store_is_a_snapshot_and_not_an_error(self):
        snapshot = view.snapshot(RecordStore(), Work())
        assert snapshot["header"]["found"] is False
        assert snapshot["editions_by_language"] == {}
        assert snapshot["header"]["origin"] == ""


class TestWhatTheRowSaysAboutANonEdition:
    """Step 7, on the user's decision: **label the row, never filter it.**

    SBN links study guides, graded readers, omnibus volumes and adaptations to a
    work and neither `tiporec[]` nor `level[]` separates them (F16). Hiding them
    would be a claim the list is clean, which it is not; the row says what the
    catalogue says instead.
    """

    def test_a_row_credited_to_somebody_else_says_so_and_stays_in_the_list(self):
        store = store_of(rec("TO10037839", language="eng", year="2020",
                             title="Nineteen eighty-four",
                             authors=["MacKenzie, Fiona"]))
        rows = view.snapshot(store, Work(authors=["George Orwell"]))["editions_by_language"]
        assert rows["eng"][0]["credited_to"] == "Fiona MacKenzie"
        assert len(rows["eng"]) == 1

    def test_the_work_s_own_author_gets_no_label(self):
        store = store_of(rec("A", language="eng", authors=["Orwell, George"]))
        row = view.snapshot(store, Work(authors=["George Orwell"]))["editions_by_language"]["eng"][0]
        assert row["credited_to"] is None

    def test_an_authority_heading_counts_as_the_author(self):
        """`Work.author_headings` is SBN's own spelling, and without it ten
        Mahfouz rows read as somebody else's book."""
        store = store_of(rec("A", language="ita", authors=["Maḥfūẓ, Naǧīb"]))
        work = Work(authors=["Naguib Mahfouz"], author_headings=["Mahfouz , Naguib"])
        row = view.snapshot(store, work)["editions_by_language"]["ita"][0]
        assert row["credited_to"] is None

    def test_the_medium_is_on_the_row(self):
        store = store_of(rec("A", language="ita",
                             medium="registrazione sonora non musicale"))
        row = view.snapshot(store, Work())["editions_by_language"]["ita"][0]
        assert row["medium"] == "registrazione sonora non musicale"

    def test_with_no_work_at_all_nothing_is_labelled(self):
        """A book with no identity is a normal answer (A1), and a label needs an
        author to compare against."""
        store = store_of(rec("A", language="ita", authors=["Manara, Milo"]))
        row = view.snapshot(store, None)["editions_by_language"]["ita"][0]
        assert row["credited_to"] is None
        assert view.author_forms(None) == []


def _editions(*records):
    """The records folded, so the view is tested on what it actually receives."""
    from core.fold import fold
    return fold(records)


class TestDisplayTitleFallbacks:
    def test_the_original_languages_title_is_used_when_no_original_title_is_stated(self):
        """Wikidata states P407 more often than P1476, so the language's own label
        is the next best thing a catalogue actually said."""
        work = Work(original_language="spa",
                    titles_by_lang={"spa": "Cien años de soledad",
                                    "ita": "Cent'anni di solitudine"})
        editions = _editions(rec("A", title="Cent'anni di solitudine", year="1985"))
        assert view.display_title(editions, work) == "Cien años de soledad"

    def test_with_nothing_dated_the_commonest_spelling_is_used(self):
        editions = _editions(rec("A", title="Rumori"), rec("B", title="Rumori"),
                             rec("C", title="Bruits"))
        assert view.display_title(editions, Work()) == "Rumori"

    def test_with_no_editions_at_all_there_is_no_title(self):
        assert view.display_title([], Work()) == ""


# ---------------------------------------------------------------------------
# Step 10 — what the browser's three filters read
# ---------------------------------------------------------------------------

class TestTheOrderRowsAreDrawnIn:
    """Newest first, undated last, inside each language group.

    Stated here rather than in the page, so the CLI, the tests and the browser
    cannot disagree about it — and so a filter, which only ever removes rows,
    can never change the order of the ones it keeps.
    """

    def test_newest_first_inside_a_language(self):
        store = store_of(rec("A", language="ita", year="1985"),
                         rec("B", language="ita", year="2020"),
                         rec("C", language="ita", year="1999"))
        rows = view.snapshot(store, Work())["editions_by_language"]["ita"]
        assert [r["year"] for r in rows] == ["2020", "1999", "1985"]

    def test_an_undated_row_goes_last_and_is_not_dropped(self):
        store = store_of(rec("A", language="ita"),
                         rec("B", language="ita", year="1985"))
        rows = view.snapshot(store, Work())["editions_by_language"]["ita"]
        assert [r["id"] for r in rows] == ["SBN:B", "SBN:A"]

    def test_a_year_buried_in_free_text_still_sorts(self):
        """Open Library dates are free text — 'December 31, 1985' — and slicing
        the first four characters dropped every month-name date."""
        store = store_of(rec("A", language="eng", year="June 1985"),
                         rec("B", language="eng", year="2001"))
        rows = view.snapshot(store, Work())["editions_by_language"]["eng"]
        assert [r["year_num"] for r in rows] == [2001, 1985]

    def test_rows_of_the_same_year_keep_the_stores_order(self):
        store = store_of(rec("A", language="ita", year="1985"),
                         rec("B", language="ita", year="1985"))
        rows = view.snapshot(store, Work())["editions_by_language"]["ita"]
        assert [r["id"] for r in rows] == ["SBN:A", "SBN:B"]


class TestARowWithSeveralPrintings:
    """One ISBN, printed in 1985 and 2026 (Adelphi's `9788845906862`, F17).
    Decision AG: it sorts by its latest printing, and the year filter and the
    language span read every printing."""

    def store(self):
        return store_of(rec("P1", language="ita", year="1985", isbn="9788845906862"),
                        rec("P2", language="ita", year="2026", isbn="9788845906862"),
                        rec("M", language="ita", year="2000"))

    def test_it_sorts_by_its_latest_printing(self):
        rows = view.snapshot(self.store(), Work())["editions_by_language"]["ita"]
        assert [r["id"] for r in rows] == ["9788845906862", "SBN:M"]
        assert rows[0]["latest"] == "2026" and rows[0]["year"] == "1985"

    def test_it_carries_every_printing_year_for_the_filter(self):
        row = view.snapshot(self.store(), Work())["editions_by_language"]["ita"][0]
        assert row["years_num"] == [1985, 2026]
        assert row["year_num"] == 1985

    def test_the_language_span_runs_to_the_latest_printing(self):
        span = view.snapshot(self.store(), Work())["header"]["spans"][0]
        assert (span["first_year"], span["last_year"]) == (1985, 2026)

    def test_the_earliest_edition_is_still_the_first_printing(self):
        assert view.snapshot(self.store(), Work())["header"]["earliest"]["year"] == 1985

    def test_holdings_are_not_carried_in_the_snapshot(self):
        """One full record lists up to 851 libraries; they are read on expand."""
        row = view.snapshot(self.store(), Work())["editions_by_language"]["ita"][0]
        assert "holdings" not in row


class TestTheYearTheFilterCompares:
    def test_it_is_the_same_reading_the_header_uses(self):
        """A year filter and 'earliest edition found' must parse a catalogue's
        free-text date the same way, or a filtered list can disagree with the
        header above it. Both are `year_of`."""
        store = store_of(rec("A", language="eng", year="December 31, 1985"))
        snapshot = view.snapshot(store, Work())
        assert snapshot["header"]["first_year_seen"] == 1985
        assert snapshot["editions_by_language"]["eng"][0]["year_num"] == 1985

    def test_an_unparsable_date_is_null_rather_than_a_guess(self):
        store = store_of(rec("A", language="eng", year="n.d."))
        assert view.snapshot(store, Work())["editions_by_language"]["eng"][0]["year_num"] is None


class TestThePublisherFacet:
    def test_one_house_spelled_two_ways_is_one_chip(self):
        """'Mondadori, Milano' and 'A. Mondadori, Milano' are the same house, and
        the rule that says so is `core.fold.publisher_key` — the one that was
        measured, not a second one written for the page."""
        store = store_of(
            rec("A", language="ita", publisher="Mondadori, Milano", places=["Milano"]),
            rec("B", language="ita", publisher="A. Mondadori, Milano", places=["Milano"]))
        facets = view.snapshot(store, Work())["publishers"]
        assert len(facets) == 1
        assert facets[0]["editions"] == 2
        assert facets[0]["label"] == "Mondadori"

    def test_a_row_naming_two_publishers_is_offered_under_both(self):
        store = store_of(rec("A", language="eng", publisher="Penguin ; Secker",
                             publisher_names=["Penguin", "Secker"]))
        row = view.snapshot(store, Work())["editions_by_language"]["eng"][0]
        assert len(row["publisher_ids"]) == 2
        assert {f["label"] for f in view.snapshot(store, Work())["publishers"]} == \
            {"Penguin", "Secker"}

    def test_the_facets_are_most_editions_first(self):
        store = store_of(rec("A", language="ita", publisher="Einaudi"),
                         rec("B", language="ita", publisher="Adelphi"),
                         rec("C", language="ita", publisher="Adelphi"))
        assert [f["label"] for f in view.snapshot(store, Work())["publishers"]] == \
            ["Adelphi", "Einaudi"]

    def test_a_row_with_no_readable_publisher_names_none(self):
        """It is not filed under an empty chip: it is simply not in the facet,
        and a publisher filter hides it, which the hidden count then says."""
        store = store_of(rec("A", language="ita"))
        snapshot = view.snapshot(store, Work())
        assert snapshot["publishers"] == []
        assert snapshot["editions_by_language"]["ita"][0]["publisher_ids"] == []

    def test_a_generic_word_alone_is_not_a_publisher(self):
        """'Edizioni' and 'Press' name a kind of company, not which one."""
        store = store_of(rec("A", language="ita", publisher="Edizioni"))
        assert view.snapshot(store, Work())["publishers"] == []

    def test_the_facet_counts_editions_and_not_records(self):
        """Two printings folded onto one ISBN are one edition, and the chip that
        says '1' has to agree with the one row the reader then sees."""
        store = store_of(
            rec("A", language="ita", publisher="Adelphi", isbn="9788845906862"),
            rec("B", language="ita", publisher="Adelphi", isbn="9788845906862"))
        snapshot = view.snapshot(store, Work())
        assert len(snapshot["editions_by_language"]["ita"]) == 1
        assert snapshot["publishers"][0]["editions"] == 1


# ---------------------------------------------------------------------------
# The coverage ledger (Step 11)
# ---------------------------------------------------------------------------

class TestTheCoverageLedger:
    def test_every_admitted_record_lands_on_exactly_one_line(self):
        """The gate's reconciliation clause: found = linked + other routes +
        duplicates listed, and records = admitted + refused."""
        store = store_of(
            rec("A", language="ita"),
            rec("B", provenance=Provenance("SBN", "title probe", TITLE_MATCH, 0.9)),
            rec("C", source="Open Library",
                provenance=Provenance("Open Library", "work editions", "work key")),
            rec("D", provenance=Provenance("SBN", "author sweep", REFUSED, 0.0)))
        ledger = view.snapshot(store, Work())["ledger"]
        assert ledger["records"] == 4
        assert ledger["admitted"] == 3 and ledger["refused"] == 1
        assert sum(line["count"] for line in ledger["lines"]) == ledger["admitted"]
        assert [line["text"] for line in ledger["lines"]] == [
            "linked to this work in SBN",
            "found by other routes — SBN holds them but has not linked them",
            "in Open Library's record for this work"]

    def test_evidence_no_line_claims_is_counted_rather_than_lost(self):
        """A new kind of evidence must break the reconciliation loudly, not
        vanish from a ledger that still adds up."""
        store = store_of(rec("A", provenance=Provenance("SBN", "title probe",
                                                        "something new", 1.0)))
        ledger = view.snapshot(store, Work())["ledger"]
        assert ledger["lines"] == [{"count": 1, "text": "admitted on other evidence"}]
        assert sum(line["count"] for line in ledger["lines"]) == ledger["admitted"]

    def test_it_counts_editions_beside_records_because_they_differ(self):
        """The header says editions and the ledger says records; two printings
        on one ISBN are one of the first and two of the second."""
        store = store_of(rec("A", language="ita", isbn="9788845906862", year="1985"),
                         rec("B", language="ita", isbn="9788845906862", year="2026"))
        ledger = view.snapshot(store, Work())["ledger"]
        assert (ledger["records"], ledger["editions"]) == (2, 1)

    def test_a_truncated_query_reaches_the_ledger(self):
        """Rule 10: every truncation is on the page, and this is the path it
        takes to get there."""
        evidence = {"recovery": {"routes": {"author_sweep": {
            "truncated": True, "rows": 240, "total": 1366}}}}
        ledger = view.snapshot(store_of(rec("A")), Work(), evidence=evidence)["ledger"]
        assert ledger["truncations"] == ["the author sweep read 240 of 1,366 "
                                         "records filed under this name"]

    def test_a_disbelieved_language_is_disclosed(self):
        """Rule 4 is this tool acting on a catalogue's statement, so it says so."""
        evidence = {"listing": {"language_disbelieved": [{"record": "IT1"}]},
                    "recovery": {"gate": {"language_disbelieved": [{"record": "IT2"}]}}}
        ledger = view.snapshot(store_of(rec("A")), Work(), evidence=evidence)["ledger"]
        assert ledger["disbelieved"] == 2

    def test_with_no_evidence_at_all_it_still_reconciles(self):
        ledger = view.snapshot(store_of(rec("A")), Work())["ledger"]
        assert ledger["truncations"] == [] and ledger["not_asked"] == []
        assert ledger["disbelieved"] == 0 and ledger["multi_language"] == 0


# ---------------------------------------------------------------------------
# The loose-match band (Step 11, decision N)
# ---------------------------------------------------------------------------

class TestTheLooseMatchBand:
    def test_it_holds_the_refused_records_and_nothing_else(self):
        """The gate's clause. 8,833 refusals over 79 entries **M**, and a floor
        anywhere here would make the clause uncheckable."""
        store = store_of(
            rec("A", language="ita"),
            rec("B", provenance=Provenance("SBN", "title probe", REFUSED, 0.4)),
            rec("C", provenance=Provenance("SBN", "author sweep", REFUSED, 0.0)))
        band = view.snapshot(store, Work())["loose_matches"]
        assert band["total"] == 2
        assert {r["id"] for g in band["groups"] for r in g["rows"]} == {"B", "C"}

    def test_the_two_groups_are_the_route_and_not_the_score(self):
        """A title probe offered the record as this work's title; the sweep only
        ever said the same person is on it. Calling 6,799 of the latter
        'matched loosely' would be false."""
        store = store_of(
            rec("B", provenance=Provenance("SBN", "title probe", REFUSED, 0.0)),
            rec("C", provenance=Provenance("SBN", "author sweep", REFUSED, 0.3)))
        groups = view.snapshot(store, Work())["loose_matches"]["groups"]
        assert [g["group"] for g in groups] == ["matched", "swept"]
        assert [r["id"] for r in groups[0]["rows"]] == ["B"]
        assert [r["id"] for r in groups[1]["rows"]] == ["C"]

    def test_an_isbn_probe_counts_as_a_match_that_was_refused(self):
        store = store_of(rec("B", provenance=Provenance("SBN", "isbn probe",
                                                        REFUSED, 0.0)))
        groups = view.snapshot(store, Work())["loose_matches"]["groups"]
        assert [g["group"] for g in groups] == ["matched"]

    def test_an_empty_group_is_not_drawn(self):
        store = store_of(rec("C", provenance=Provenance("SBN", "author sweep",
                                                        REFUSED, 0.0)))
        band = view.snapshot(store, Work())["loose_matches"]
        assert [g["group"] for g in band["groups"]] == ["swept"]

    def test_rows_are_best_first_then_newest_then_stable(self):
        store = store_of(
            rec("B", provenance=Provenance("SBN", "title probe", REFUSED, 0.2),
                year="2001"),
            rec("C", provenance=Provenance("SBN", "title probe", REFUSED, 0.5),
                year="1975"),
            rec("D", provenance=Provenance("SBN", "title probe", REFUSED, 0.2),
                year="2010"),
            rec("E", provenance=Provenance("SBN", "title probe", REFUSED, 0.2)))
        rows = view.snapshot(store, Work())["loose_matches"]["groups"][0]["rows"]
        assert [r["id"] for r in rows] == ["C", "D", "B", "E"]

    def test_a_band_row_is_lean_and_says_how_near_it_came(self):
        """Nine fields: what a reader needs to judge a refusal. A refused record
        is in no language group, no filter, no count and no duplicate hint, so
        it carries none of the fields those need — which is what makes showing
        every one of them affordable."""
        store = store_of(rec("B", title="Postille a Il nome della rosa",
                             year="1983", publisher="Bompiani",
                             url="https://opac.sbn.it/bid/CFI0012345",
                             provenance=Provenance("SBN", "title probe", REFUSED, 0.667)))
        row = view.snapshot(store, Work())["loose_matches"]["groups"][0]["rows"][0]
        assert row == {"id": "B", "source": "SBN",
                       "title": "Postille a Il nome della rosa", "year": "1983",
                       "publisher": "Bompiani",
                       "url": "https://opac.sbn.it/bid/CFI0012345",
                       "route": "title probe", "score": 0.667, "group": "matched"}

    def test_the_band_carries_the_threshold_it_was_refused_by(self):
        band = view.snapshot(store_of(rec("A")), Work())["loose_matches"]
        assert band["threshold"] == 0.6


# ---------------------------------------------------------------------------
# A row SBN returned under two languages (Step 7's open question)
# ---------------------------------------------------------------------------

class TestARowFiledUnderTwoLanguages:
    def test_the_other_language_is_a_label_on_the_row(self):
        """326 rows over the corpus **M**. The row is counted once, in one
        group — and the code it is not grouped under is still the catalogue's
        own statement, so it is shown and it filters nothing."""
        evidence = {"listing": {"sbn": {"multi_language": {"A": ["rus", "ita"]}}}}
        store = store_of(rec("A", language="ita"))
        row = view.snapshot(store, Work(), evidence=evidence)["editions_by_language"]["ita"][0]
        assert row["also_in"] == [{"code": "rus", "name": "russo"}]

    def test_the_language_it_is_grouped_under_is_not_repeated(self):
        evidence = {"listing": {"sbn": {"multi_language": {"A": ["ita"]}}}}
        store = store_of(rec("A", language="ita"))
        row = view.snapshot(store, Work(), evidence=evidence)["editions_by_language"]["ita"][0]
        assert row["also_in"] == []

    def test_a_row_no_page_doubled_says_nothing(self):
        store = store_of(rec("A", language="ita"))
        row = view.snapshot(store, Work())["editions_by_language"]["ita"][0]
        assert row["also_in"] == []


# ---------------------------------------------------------------------------
# Open Library's other records, added by the reader (Step 13, decision AI)
# ---------------------------------------------------------------------------

def added(rec_id, via="OL31357567W", **kw) -> Record:
    return rec(rec_id, source="Open Library", provenance=Provenance(
        "Open Library", DUPLICATE_WORK, DUPLICATE_WORK, via=via), **kw)


MAIN = Provenance("Open Library", WORK_EDITIONS, WORK_KEY)


class TestWhatTheReaderAdded:
    def store(self):
        return store_of(
            rec("A", language="rus", year="1957", title="Doktor Živago"),
            rec("B", source="Open Library", provenance=MAIN, language="eng",
                year="1958", title="Doctor Zhivago"),
            added("X", language="eng", year="1949", title="Doctor Zhivago"),
            added("Y", language="fin", year="1960", title="Tohtori Živago"))

    def test_the_header_states_only_what_the_catalogues_tie_to_the_work(self):
        """An added record dated 1949 must not become the earliest edition found."""
        h = view.snapshot(self.store(), Work())["header"]
        assert h["earliest"]["year"] == 1957
        assert h["total_editions"] == 2 and h["added"] == 2

    def test_the_groups_and_their_counts_hold_everything(self):
        snap = view.snapshot(self.store(), Work())
        assert [r["id"] for r in snap["editions_by_language"]["eng"]] == [
            "Open Library:B", "Open Library:X"]
        spans = {s["code"]: s for s in snap["header"]["spans"]}
        assert (spans["eng"]["editions"], spans["eng"]["added"]) == (1, 1)
        assert spans["eng"]["first_year"] == 1958

    def test_a_language_only_an_addition_reaches_still_has_a_group(self):
        snap = view.snapshot(self.store(), Work())
        spans = {s["code"]: s for s in snap["header"]["spans"]}
        assert (spans["fin"]["editions"], spans["fin"]["added"]) == (0, 1)
        assert spans["fin"]["first_year"] is None
        assert "fin" in snap["language_order"]

    def test_a_row_says_which_record_it_was_added_from(self):
        rows = view.snapshot(self.store(), Work())["editions_by_language"]["eng"]
        assert [r["added_from"] for r in rows] == [[], ["OL31357567W"]]
        assert rows[1]["provenance"][0]["via"] == "OL31357567W"
        assert "via" not in rows[0]["provenance"][0]

    def test_one_record_the_catalogues_tie_to_the_work_keeps_the_row_in_the_header(self):
        """Sharing an ISBN with an SBN printing makes the row the catalogues'."""
        store = store_of(rec("A", language="ita", year="1957", isbn="9788807900000"),
                         added("X", language="ita", year="1957", isbn="9788807900000"))
        assert view.snapshot(store, Work())["header"]["added"] == 0

    def test_the_ledger_counts_them_on_their_own_line(self):
        lines = view.snapshot(self.store(), Work())["ledger"]["lines"]
        assert lines[-1] == {"count": 2,
                             "text": "in Open Library's other records for the same work"}

    def test_nothing_looked_for_is_an_empty_list_not_a_missing_key(self):
        assert view.snapshot(self.store(), Work())["duplicate_works"] == {
            "asked": False, "rows": [], "editions": 0, "why_not": None}

    def test_the_list_marks_what_was_added_and_what_failed(self):
        evidence = {"duplicates": {"asked": True, "rows": [
            {"key": "OL31357567W", "title": "Doctor Zhivago", "editions": 13},
            {"key": "OL38068744W", "title": "Doctor Zhivago", "editions": 11},
            {"key": "OL31702700W", "title": "The Poems Of Doctor Zhivago", "editions": 5}],
            "added": ["OL31357567W"], "failed": {"OL38068744W": "timed out"}}}
        listed = view.snapshot(self.store(), Work(), evidence=evidence)["duplicate_works"]
        assert listed["editions"] == 29 and listed["added"] == 1
        assert [(r["added"], r["failed"]) for r in listed["rows"]] == [
            (True, None), (False, "timed out"), (False, None)]


class TestEveryDisbelievedLanguageIsCounted:
    def test_the_reverse_path_and_the_additions_are_read_too(self):
        """Step 12 found the ledger's count missed decision Q's reverse path."""
        evidence = {"recovery": {"reverse": {"language_disbelieved": [{"record": "IT3"}]}},
                    "duplicates": {"language_disbelieved": [{"record": "OL1M"}]}}
        assert view.snapshot(store_of(rec("A")), Work(),
                             evidence=evidence)["ledger"]["disbelieved"] == 2

    def test_evidence_that_is_not_a_stage_is_passed_over(self):
        assert view.disbelieved_notes({"version": 3, "listing": {
            "language_disbelieved": [{"record": "IT1"}]}}) == [{"record": "IT1"}]


class TestTitleOnly:
    """Decision AN: a bare title that names several books gets a chooser and
    nothing else; with an author there is nothing to choose between."""

    def test_the_chooser_carries_the_books_and_its_heading_and_no_list(self):
        books = [{"authors": ["Daniel Kahneman"], "title": "Noise", "first_year": 2021,
                  "editions": 23, "sources": ["Open Library", "SBN"]}]
        out = view.title_chooser("Noise", books * 2, version=1)
        assert out["chooser"]["books"] == books * 2
        assert out["chooser"]["heading"] == "2 books are called “Noise” — pick one"
        assert "editions_by_language" not in out and "header" not in out

    def test_an_author_asked_means_no_choices(self):
        store = store_of(
            rec("A", title="La matrice sociale della psichiatria",
                authors=["Ruesch, Jurgen"], year="1976"),
            rec("B", title="La matrice sociale della psichiatria",
                authors=["Shepherd, Michael"], year="1990"))
        asked = {"identity": {"question": {"author": "Ruesch"}}}
        assert view.snapshot(store, Work(), evidence=asked)["choices"] == []
        assert len(view.snapshot(store, Work())["choices"]) == 2

    def test_an_adopted_author_reaches_the_header(self):
        adopted = {"name": "Gregory Bateson", "sources": ["Open Library", "Wikidata"],
                   "note": "author from Open Library and Wikidata — none was typed"}
        out = view.snapshot(store_of(rec("A", year="1976")), Work(),
                            evidence={"author_adopted": adopted})
        assert out["header"]["author_adopted"] == adopted
