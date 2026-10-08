"""`core/fold.py` — records to editions, and the gate that pins it.

Step 5's gate: `fold.py` reproduces `results/stage-3/q2_printings.json` —
**483 ISBN-bearing records become 297 edition rows, and 295 records with no ISBN
stay one row each**. That measurement is what decision I rests on, so the fold is
checked against it rather than against a hand-built example, per book and pooled.

The input is `tests/data/results/stage-3/records.json`, which is committed: one entry
per SBN record of the eight Stage 3 books, carrying the normalised ISBN-13s the
benchmark read out of the full records. So this test measures the **grouping**,
which is what the gate names. The normalisation is checked separately below, on
literals.
"""

import json
from pathlib import Path

import pytest

from core import fold as F
from core.model import Provenance, Record

DATA = Path(__file__).resolve().parent / "data" / "results" / "stage-3"
P = Provenance(source="SBN", route="work listing", evidence="uniform title")


def record(rec_id, isbns=(), **kw) -> Record:
    return Record(source="SBN", id=rec_id, provenance=P, isbns_raw=list(isbns), **kw)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def load_stage3():
    """Per book: the fetched records, as `Record`s carrying their ISBNs."""
    recorded = json.loads((DATA / "records.json").read_text(encoding="utf-8"))
    out = {}
    for book, per_bid in recorded.items():
        rows = []
        for bid, r in per_bid.items():
            if not r["fetched"]:
                # The measurement counts fetched rows only: a row whose full
                # record never arrived has no ISBN *known*, which is a different
                # thing from having none.
                continue
            rows.append(record(bid, isbns=r["isbns"]))
        out[book] = rows
    return out


@pytest.fixture(scope="module")
def stage3():
    return load_stage3()


@pytest.fixture(scope="module")
def q2():
    return json.loads((DATA / "q2_printings.json").read_text(encoding="utf-8"))


def measure(rows):
    editions = F.fold(rows)
    with_isbn = [e for e in editions if e.isbn]
    without = [e for e in editions if not e.isbn]
    multi = [e for e in with_isbn if len(e.records) > 1]
    return {
        "sbn_rows": len(rows),
        "rows_with_isbn": sum(len(e.records) for e in with_isbn),
        "rows_without_isbn": len(without),
        "edition_rows_by_isbn": len(with_isbn),
        "editions_with_several_printings": len(multi),
        "records_in_those": sum(len(e.records) for e in multi),
        "largest": max((len(e.records) for e in editions), default=0),
    }


class TestReproducesQ2Printings:
    FIELDS = ("sbn_rows", "rows_with_isbn", "rows_without_isbn",
              "edition_rows_by_isbn", "editions_with_several_printings",
              "records_in_those")

    def test_the_pooled_numbers_the_gate_names(self, stage3, q2):
        got = {k: sum(measure(rows)[k] for rows in stage3.values()) for k in self.FIELDS}
        assert got["rows_with_isbn"] == 483
        assert got["edition_rows_by_isbn"] == 297
        assert got["rows_without_isbn"] == 295
        assert got == {k: q2["pooled"][k] for k in self.FIELDS}

    @pytest.mark.parametrize("book", ["N19", "E02", "N14", "N08", "N01", "E01", "N06", "N10"])
    def test_per_book(self, book, stage3, q2):
        got = measure(stage3[book])
        expected = q2["per_book"][book]
        assert got == {k: expected[k] for k in got}

    def test_the_largest_edition_is_f17s_thirty_one_printings(self, stage3):
        """One ISBN spans printings of many years (F17): Adelphi's
        `9788845906862` on 31 records of *L'insostenibile leggerezza
        dell'essere*, 1985-2026. A row that hid them would be wrong."""
        editions = F.fold(stage3["N01"])
        biggest = max(editions, key=lambda e: len(e.records))
        assert len(biggest.records) == 31
        assert biggest.isbn == "9788845906862"

    def test_no_record_is_lost_or_counted_twice(self, stage3):
        for book, rows in stage3.items():
            editions = F.fold(rows)
            ids = [r.id for e in editions for r in e.records]
            assert sorted(ids) == sorted(r.id for r in rows), book


# ---------------------------------------------------------------------------
# What counts as the same ISBN
# ---------------------------------------------------------------------------

class TestIsbnNormalisation:
    def test_hyphens_and_spaces_between_digits_go(self):
        codes, invalid = F.isbns_in(["978-88-502-6890-0"])
        assert codes == {"9788850268900"} and invalid == []

    def test_an_isbn_10_becomes_its_isbn_13(self):
        """So SBN's pre-2007 printings join Open Library's modern ones."""
        assert F.to_isbn13("0099494096") == "9780099494096"
        codes, _ = F.isbns_in(["0099494096"])
        assert codes == {"9780099494096"}

    def test_a_bad_check_digit_is_reported_and_still_normalised(self):
        """Both catalogues copy what is printed on the book, so a shared typo is
        evidence they are the same book. Dropping it loses the join."""
        codes, invalid = F.isbns_in(["9788845906861"])
        assert codes == {"9788845906861"} and invalid == ["9788845906861"]

    def test_text_around_a_code_does_not_stop_it_being_read(self):
        codes, _ = F.isbns_in(["ISBN 9788845906862 (errato)"])
        assert codes == {"9788845906862"}

    def test_a_row_with_no_isbn_yields_nothing(self):
        assert F.isbn_keys(record("MIL0871878")) == set()

    def test_the_display_isbn_is_used_when_no_raw_list_was_parsed(self):
        r = Record(source="Open Library", id="OL1M", provenance=P, isbn="0-099-49409-6")
        assert F.isbn_keys(r) == {"9780099494096"}


class TestFoldRules:
    def test_two_records_sharing_an_isbn_are_one_edition(self):
        editions = F.fold([record("A", ["9788845906862"], year="1985"),
                           record("B", ["9788845906862"], year="2026")])
        assert len(editions) == 1
        assert editions[0].printings == ["1985", "2026"]
        assert editions[0].year == "1985"

    def test_a_record_with_no_isbn_is_its_own_edition(self):
        """295 of 778 full records carry none (F12). Guessing would merge a
        third of them wrongly (A4, precision 0.656)."""
        editions = F.fold([record("A", year="1976", publisher="Feltrinelli"),
                           record("B", year="1976", publisher="Feltrinelli")])
        assert len(editions) == 2
        assert [e.id for e in editions] == ["SBN:A", "SBN:B"]

    def test_records_are_joined_transitively(self):
        """A lists {x}, B lists {x, y}, C lists {y}: SBN said so twice."""
        editions = F.fold([record("A", ["9788845906862"]),
                           record("B", ["9788845906862", "9782070360024"]),
                           record("C", ["9782070360024"])])
        assert len(editions) == 1
        assert sorted(r.id for r in editions[0].records) == ["A", "B", "C"]

    def test_different_isbns_never_merge(self):
        """Faber 2021 `…884` and `…891` are two bindings of one year, and no
        listing field separates them — so nothing may join them either."""
        editions = F.fold([record("A", ["9780571355884"], year="2021", publisher="Faber"),
                           record("B", ["9780571355891"], year="2021", publisher="Faber")])
        assert len(editions) == 2

    def test_the_order_of_the_records_does_not_change_the_grouping(self):
        rows = [record("A", ["9788845906862"]), record("B", []),
                record("C", ["9782070360024"]), record("D", ["9788845906862"])]
        forward = {e.id: sorted(r.id for r in e.records) for e in F.fold(rows)}
        backward = {e.id: sorted(r.id for r in e.records) for e in F.fold(rows[::-1])}
        assert forward == backward


# ---------------------------------------------------------------------------
# The publisher, and the hint that is never a merge
# ---------------------------------------------------------------------------

class TestPublisherKeys:
    def test_a_generic_word_says_nothing_about_which_publisher(self):
        assert F.publisher_key("Einaudi") == F.publisher_key("Giulio Einaudi editore") - {"giulio"}
        assert F.publisher_key("Press") == frozenset()

    def test_containment_is_what_matches_an_imprint_to_its_house(self):
        assert F.publisher_agrees({F.publisher_key("Mondadori")},
                                  {F.publisher_key("Oscar Mondadori")})

    def test_two_different_houses_do_not_agree(self):
        assert not F.publisher_agrees({F.publisher_key("Feltrinelli")},
                                      {F.publisher_key("Adelphi")})

    def test_a_place_set_off_by_punctuation_is_removed(self):
        assert F.strip_places("Milano, Mondadori", {"milano"}) == "Mondadori"
        assert F.strip_places("London : Penguin", {"london"}) == "Penguin"

    def test_a_publisher_named_after_a_town_keeps_its_name(self):
        """'Cambridge University Press' is not a place followed by a publisher."""
        assert F.strip_places("Cambridge University Press", {"cambridge"}) \
            == "Cambridge University Press"


class TestCollisions:
    """Decision H: a collision is a hint, and only where it cannot be settled."""

    def sbn(self, rec_id, **kw):
        return Record(source="SBN", id=rec_id, provenance=P, **kw)

    def ol(self, rec_id, **kw):
        return Record(source="Open Library", id=rec_id,
                      provenance=Provenance("Open Library", "work editions", "work key"), **kw)

    def test_a_pair_where_both_sides_have_an_isbn_is_never_hinted(self):
        """They either share one — and `fold` merged them — or they differ, and
        that settles it. A bracket there would contradict the page's own data."""
        rows = [self.sbn("A", isbn="9788845906862", year="1985", language="ita",
                         publisher_names=["Adelphi"]),
                self.ol("B", isbn="9788845906863", year="1985", language="ita",
                        publisher_names=["Adelphi"])]
        assert F.collisions(F.fold(rows)) == []

    def test_a_pair_with_one_side_missing_its_isbn_is_hinted(self):
        rows = [self.sbn("A", year="1985", language="ita", publisher_names=["Adelphi"]),
                self.ol("B", isbn="9788845906862", year="1985", language="ita",
                        publisher_names=["Adelphi edizioni"])]
        hints = F.collisions(F.fold(rows))
        assert len(hints) == 1
        assert {hints[0]["a"], hints[0]["b"]} == {"SBN:A", "9788845906862"}

    def test_two_rows_from_the_same_source_are_not_duplicates_of_each_other(self):
        rows = [self.sbn("A", year="1985", language="ita", publisher_names=["Adelphi"]),
                self.sbn("B", year="1985", language="ita", publisher_names=["Adelphi"])]
        assert F.collisions(F.fold(rows)) == []

    def test_an_unrecorded_language_never_collides(self):
        """Open Library records a language for 80.8% of editions; a blank one may
        not be made to agree with anything."""
        rows = [self.sbn("A", year="1985", language="ita", publisher_names=["Adelphi"]),
                self.ol("B", year="1985", publisher_names=["Adelphi"])]
        assert F.collisions(F.fold(rows)) == []

    def test_different_years_never_collide(self):
        rows = [self.sbn("A", year="1985", language="ita", publisher_names=["Adelphi"]),
                self.ol("B", year="1986", language="ita", publisher_names=["Adelphi"])]
        assert F.collisions(F.fold(rows)) == []

    def test_a_hint_is_not_a_merge(self):
        rows = [self.sbn("A", year="1985", language="ita", publisher_names=["Adelphi"]),
                self.ol("B", year="1985", language="ita", publisher_names=["Adelphi"])]
        editions = F.fold(rows)
        assert len(editions) == 2 and len(F.collisions(editions)) == 1


class TestPublisherFallbacks:
    def test_an_unsplit_publisher_statement_is_still_read(self):
        """Open Library's search docs carry one string and no split list, so the
        display field is the fallback rather than nothing."""
        r = Record(source="Open Library", id="OL1W", provenance=P,
                   publisher="Oscar Mondadori")
        assert F.publisher_keys(r, set()) == {frozenset({"oscar", "mondadori"})}

    def test_a_record_naming_no_publisher_has_no_key(self):
        assert F.publisher_keys(record("A"), set()) == set()

    def test_places_are_collected_from_the_records_that_name_them(self):
        rows = [record("A", places=["Milano"]), record("B", places=["New York", ""])]
        assert F.places_in(rows) == {"milano", "new york"}


class TestCollisionsRefusedOnThePublisher:
    def test_two_houses_in_one_year_and_language_do_not_collide(self):
        """The rule is language *and* year *and* publisher. Feltrinelli's 1985
        and Adelphi's 1985 are two different books' editions."""
        a = Record(source="SBN", id="A", provenance=P, year="1985", language="ita",
                   publisher_names=["Feltrinelli"])
        b = Record(source="Open Library", id="B",
                   provenance=Provenance("Open Library", "work editions", "work key"),
                   year="1985", language="ita", publisher_names=["Adelphi"])
        assert F.collisions(F.fold([a, b])) == []


class TestCollisionsRefusedOnPages:
    """Decision AX: two page counts far apart are two editions, so no hint.

    Every `physical` below is verbatim from a pair Step 13 judged by hand
    (`tests/data/results/step13/u5_sample.json`, `u5_hints.U5_HINTS`)."""

    OL = Provenance("Open Library", "work editions", "work key")

    def pair(self, sbn_physical, ol_physical, year="1983", language="ita"):
        a = Record(source="SBN", id="A", provenance=P, year=year, language=language,
                   publisher_names=["Bompiani"], physical=sbn_physical)
        b = Record(source="Open Library", id="B", provenance=self.OL, year=year,
                   language=language, publisher_names=["Bompiani"], physical=ol_physical)
        return F.collisions(F.fold([a, b]))

    def test_503_against_442_pages_is_not_hinted(self):
        """Bompiani's two *Il nome della rosa* of 1983, judged different."""
        assert self.pair("503 p. ; 21 cm.", "442 p.") == []

    def test_the_same_count_is_still_hinted(self):
        assert len(self.pair("351 p. ; 20 cm.", "351 p.")) == 1

    def test_a_count_within_ten_percent_is_still_hinted(self):
        """Harcourt's 1949 *Nineteen Eighty-Four*, 313 against 314, judged the same."""
        assert len(self.pair("313 p. ; 21 cm.", "314 p.")) == 1

    def test_small_counts_need_ten_pages_between_them(self):
        """60 against 66 is 9% of 66 but only 6 pages: left to the reader."""
        assert len(self.pair("60 p. : ill. ; 30 cm", "66 p.")) == 1

    def test_one_side_stating_no_count_is_still_hinted(self):
        assert len(self.pair("351 p. ; 20 cm", None)) == 1

    def test_the_largest_run_is_the_count_and_a_height_is_not_one(self):
        e = F.fold([record("A", physical="XIV, 637 p., [10] c. di tav. ; 23 cm.")])[0]
        assert F.page_counts(e) == [637]
        assert F.page_counts(F.fold([record("B", physical="1 volume : ill. ; 26 cm")])[0]) == []

    def test_the_known_cost_an_open_library_height_read_as_pages(self):
        """Open Library's `number_of_pages` 23 for the Twickenham Pope, which is
        its 23 cm: judged the same, and withheld. The one wrong call in 100."""
        assert self.pair("XVII, 460 p., \\11! c. di tav. ; 23 cm.", "23 p.") == []


def test_the_rule_reproduces_the_probe_over_step_13s_judged_hints():
    """The U5 tightening probe's 10% row (decision AX), through `core.fold` itself."""
    from u5_hints import U5_HINTS
    sample = json.loads((DATA.parent / "step13" / "u5_sample.json").read_text())["sample"]

    def edition(side):
        return F.Edition(id=side["id"], isbn=side["isbn"], records=[
            Record(source=r["source"], id=r["id"], provenance=P, physical=r["physical"])
            for r in side["records"]])

    withheld = {}
    for pair in sample:
        verdict = U5_HINTS[f"{pair['a']['id']}~{pair['b']['id']}"][0]
        if F.pages_disagree(edition(pair["a"]), edition(pair["b"])):
            withheld[verdict] = withheld.get(verdict, 0) + 1
    assert withheld == {"different": 9, "same": 1}
