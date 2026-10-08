"""Which year a row means (decision AY): the imprint parser, `core.dates`, the
labels `core.notes` words, and what the view does with a year it cannot settle.

Every imprint and every `dataf[]` value below is a live SBN record's, from
decision AY's year probe (2026-09-29); the record id is beside each one.
Do not replace one with a plausible invention: the traps are the catalogue's.
"""

import pytest

from catalog.sbn_mobile import date_statement, parse_publication
from core import dates, notes
from core.model import Provenance, Record, UNIFORM_TITLE, WORK_LISTING
from core.store import RecordStore
from core.view import snapshot


def sbn(date, indexed=None, failed=False, bid="TO01804900", year=None, language="per"):
    return Record(source="SBN", id=bid, year=year, date=date, date_indexed=indexed,
                  date_check_failed=failed, language=language,
                  provenance=Provenance("SBN", WORK_LISTING, UNIFORM_TITLE))


# ---------------------------------------------------------------------------
# The parser: three imprints the probe found it misreading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("imprint, publisher, year, statement", [
    # RMS2929941: the brackets went and `13711992` was left, so no year at all.
    ("Tihrān : Našr-i nay, 1371[1992]", "Našr-i nay", "1371", "1371[1992]"),
    # RMS1560500: `\b` refused a year with a calendar's letter on it.
    ("Tehran : Morvarid, 1373H", "Morvarid", "1373", "1373H"),
    # MOD1783518: the publisher's name opens with a number.
    ("Ankara : 1001 Çiçek kitaplar, 2015", "1001 Çiçek kitaplar", "2015", "2015"),
    # TO01804900: SBN's `\...!` brackets come back as `[...]`.
    ("[Teheran! : Hwarazmi, 1386 [2007!", "Hwarazmi", "1386", "1386 [2007]"),
    # IEI0689762: a statement that opens with a bracket keeps it.
    ("[Tihrān] : Anǧuman wa dūstdārān-i ketāb, [1331 A.H. 1952]",
     "Anǧuman wa dūstdārān-i ketāb", "1331", "[1331 A.H. 1952]"),
])
def test_imprint_readings(imprint, publisher, year, statement):
    assert parse_publication(imprint)[:2] == (publisher, year)
    assert date_statement(imprint) == statement


def test_a_plain_imprint_reads_as_before():
    assert parse_publication("Milano : Mazzotta, c1978, (stampa 1977)") == \
        ("Mazzotta", "1978", "Milano")
    assert date_statement("Milano : Mazzotta, c1978, (stampa 1977)") == "1978, (stampa 1977)"


def test_no_year_no_statement():
    # BVE0938818
    assert date_statement("Roma : Tipografia della r. Accademia de' Lincei") is None
    assert date_statement(None) is None


# ---------------------------------------------------------------------------
# core.dates.settle
# ---------------------------------------------------------------------------

def test_plain_year_is_taken_as_written():
    assert dates.settle(sbn("2015", bid="MOD1783518")) == ("2015", None, [])


def test_a_record_with_a_year_and_no_statement_keeps_it():
    assert dates.settle(sbn(None, year="1985")) == ("1985", None, [])


def test_no_year_at_all():
    assert dates.settle(sbn(None)) == (None, dates.NO_DATE, [])


def test_unchecked_calendar_year_is_unsure_and_shows_both():
    assert dates.settle(sbn("1386 [2007]")) == (None, dates.UNSURE, [1386, 2007])


def test_index_on_the_bracketed_year_infers_it():
    # TO01804756, dataf 2007
    assert dates.settle(sbn("1386 [2007]", ["2007"])) == ("2007", dates.INFERRED, [])


def test_index_on_the_first_year_keeps_it_without_a_label():
    # A Western printing statement: `2020, stampa 2019` is filed under 2020.
    assert dates.settle(sbn("2020, stampa 2019", ["2020"])) == ("2020", None, [])


def test_a_run_of_years_is_plain_from_its_first():
    # `1876-1884`, a multi-volume run
    assert dates.settle(sbn("1876-1884")) == ("1876", None, [])


def test_a_range_value_covers_its_first_year():
    # `[S.l. : s.n., tra 1905 e 1910]`, filed as the one value `1905-1910`
    assert dates.settle(sbn("[tra 1905 e 1910]", ["1905-1910"])) == ("1905", None, [])


def test_a_printing_year_is_not_a_second_reading():
    # `1996, stampa 1997` is one plain year: nothing asks SBN about it...
    assert dates.settle(sbn("1996, stampa 1997")) == ("1996", None, [])
    assert dates.is_plain("1978, (stampa 1977)")


def test_a_plain_year_the_index_contradicts_shows_both():
    # A printing the imprint does not state is no explanation.
    assert dates.settle(sbn("1996, stampa 1997", ["1995"])) == \
        (None, dates.UNSURE, [1995, 1996])
    # ...and where SBN files it under that printing, nothing is unsure: the row is
    # 1996's and says it was printed in 1997 (`Delitto e castigo`, ita).
    assert dates.settle(sbn("1996, stampa 1997", ["1997"])) == \
        ("1996", dates.PRINTED, [1997])
    assert dates.printing_years("1957, stampa 1958") == [1958]
    # URB0413776, `Paris : Stock, 1930`, filed under 1925
    assert dates.settle(sbn("1930", ["1925"])) == (None, dates.UNSURE, [1925, 1930])
    assert dates.settle(sbn("1930", [])) == (None, dates.UNSURE, [1930])
    assert dates.settle(sbn("1930", ["1930"])) == ("1930", None, [])
    assert dates.settle(sbn("1930", [], failed=True)) == ("1930", None, [])


def facet(**counts):
    return [{"value": v.lstrip("y"), "results": n} for v, n in counts.items()]


def test_values_to_ask_are_the_years_whose_counts_disagree():
    records = [sbn("1930", bid="A"), sbn("1930", bid="B"), sbn("2015", bid="C"),
               sbn("1386 [2007]", ["2007"], bid="D"), sbn(None, bid="E")]
    # SBN: one 1930 and one 1925 (a 1930 row is filed elsewhere), 2015 agrees,
    # 2007 is the checked Persian row, 1999 the undated one.
    ask, absent = dates.values_to_ask(facet(y1930=1, y1925=1, y2015=1, y2007=1, y1999=1),
                                      records, capped=False)
    assert ask == ["1925", "1930", "1999"] and absent == set()


def test_a_year_sbn_never_lists_is_absent_unless_the_facet_was_cut():
    records = [sbn("1930", bid="A")]
    assert dates.values_to_ask(facet(y1925=1), records, capped=False) == (["1925"], {"1930"})
    assert dates.values_to_ask(facet(y1925=1), records, capped=True) == (["1925", "1930"], set())


def test_contradicted_needs_the_year_asked_or_absent():
    row = sbn("1930", bid="URB0413776")
    assert dates.contradicted(row, {"1930": set(), "1925": {"URB0413776"}}, set()) == ["1925"]
    assert dates.contradicted(row, {"1925": {"URB0413776"}}, {"1930"}) == ["1925"]
    assert dates.contradicted(row, {"1930": set()}, set()) == []
    assert dates.contradicted(row, {"1930": {"URB0413776"}}, set()) is None
    assert dates.contradicted(row, {"1925": {"URB0413776"}}, set()) is None   # 1930 agreed
    assert dates.contradicted(row, {"1920-1935": {"URB0413776"}}, {"1930"}) is None
    assert dates.contradicted(sbn("1386 [2007]"), {}, set()) is None


@pytest.mark.parametrize("statement, indexed, year", [
    ("1918 [1925/1926]", ["1925-1926"], "1925"),     # NAP0958386, Ethiopian
    ("1383 [2004 o 2005]", ["2004-2005"], "2004"),   # RMS3018513, Persian
])
def test_a_year_straddling_two_gregorian_ones_is_inferred_from_the_first(
        statement, indexed, year):
    assert dates.settle(sbn(statement, indexed)) == (year, dates.INFERRED, [])


def test_two_years_that_are_not_consecutive_stay_two():
    assert dates.candidates("1968, = 1975/76") == [1968, 1975]      # NAP0957789


def test_a_decade_is_unsure_and_shows_what_was_written():
    ol = Record(source="Open Library", id="OL1M", date="199u",
                provenance=Provenance("Open Library", "work editions", "work key"))
    assert dates.settle(ol) == (None, dates.UNSURE, ["199u"])


def test_bracket_and_index_disagreeing_is_unsure():
    # RMS2735237: the bracket is right, SBN's index is not — so neither wins.
    record = sbn("1958 ʻĀ.Me. [1966]", ["1958"], language="amh")
    assert dates.settle(record) == (None, dates.UNSURE, [1958, 1966])


def test_the_second_year_without_brackets_is_inferred_from_the_index():
    # NAP0955999: Ethiopian 1975, SBN files it under 1982.
    assert dates.settle(sbn("1975, 1982/83", ["1982"], language="amh")) == \
        ("1982", dates.INFERRED, [])


def test_a_failed_check_is_unchecked():
    assert dates.settle(sbn("1386 [2007]", [], failed=True)) == \
        (None, dates.UNCHECKED, [1386, 2007])


def test_no_gregorian_year_is_another_calendar():
    # RMS0184828 and RMS1129284 (a lunar year in a Persian book)
    assert dates.settle(sbn("1316 s", [])) == (None, dates.OTHER_CALENDAR, [1316])
    assert dates.settle(sbn("1304 h", ["1887"])) == \
        (None, dates.OTHER_CALENDAR, [1304, 1887])


def test_a_marked_year_that_looks_gregorian_is_another_calendar():
    assert dates.settle(sbn("1958 ʻĀ.Me.", [])) == (None, dates.OTHER_CALENDAR, [1958])


def test_the_index_disagreeing_with_every_year_is_unsure():
    # VEA1339728, filed under 2017
    assert dates.settle(sbn("1397, 2018-2019", ["2017"])) == \
        (None, dates.UNSURE, [1397, 2017, 2018])


def test_a_year_after_next_year_is_not_plain():
    # UTO1506643's Bikram Sambat year, had it come without its bracket
    assert dates.is_plain("2044")
    assert not dates.is_plain("2044", this_year=2026)
    assert dates.settle(sbn("2044", []), this_year=2026) == \
        (None, dates.OTHER_CALENDAR, [2044])


def test_between_two_years_is_not_plain():
    assert not dates.is_plain("[tra il 1970 e il 1990]")
    assert dates.is_plain("1930")


def test_indexed_years_reads_ranges_and_skips_the_rest():
    assert dates.indexed_years(["2007", "1977-1991", "19.."]) == {2007, 1977, 1991}
    assert dates.indexed_years(None) == set()


def test_only_sbn_records_with_an_unsettled_statement_need_a_check():
    assert dates.needs_check(sbn("1386 [2007]"))
    assert not dates.needs_check(sbn("2015"))
    assert not dates.needs_check(sbn(None))
    ol = Record(source="Open Library", id="OL1M", date="1386 [2007]",
                provenance=Provenance("Open Library", "work editions", "work key"))
    assert not dates.needs_check(ol)


def test_settled_copy_leaves_the_stored_record_alone():
    stored = sbn("1386 [2007]", ["2007"], year="1386")
    copy = dates.settled(stored)
    assert (copy.year, copy.year_note) == ("2007", dates.INFERRED)
    assert (stored.year, stored.year_note) == ("1386", None)


def test_row_note_takes_the_least_certain_and_drops_no_date_beside_a_year():
    unsure = dates.settled(sbn("1386 [2007]"))
    inferred = dates.settled(sbn("1386 [2007]", ["2007"], bid="TO01804756"))
    blank = dates.settled(sbn(None, bid="RMB0739154"))
    assert dates.row_note([inferred, unsure]) == ("unsure", ["1386", "2007"], ["1386 [2007]"])
    assert dates.row_note([inferred, blank])[0] == "inferred"
    assert dates.row_note([blank])[0] == "no date"
    assert dates.row_note([dates.settled(sbn("2015"))]) == (None, [], [])


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------

def test_labels_are_short():
    assert [notes.year_label(n) for n in dates.SEVERITY if n != dates.PRINTED] == \
        ["year unchecked", "year unsure", "other calendar", "year inferred", "no year"]
    assert notes.year_label(dates.PRINTED, ["1997"]) == "printed 1997"


def test_details_say_what_each_reading_said():
    assert notes.year_detail("inferred", ["1386 [2007]"], ["2007"]) == \
        "Catalogue: 1386 [2007]. SBN index: 2007. The year both agree on is shown."
    assert notes.year_detail("unsure", ["1958 ʻĀ.Me. [1966]"], ["1958"]).endswith(
        "They do not agree on one year.")
    assert notes.year_detail("unsure", ["1386 [2007]"], []).endswith(
        "Nothing to check it against.")
    assert notes.year_detail("unsure", ["1386 [2007]"], [], asked=True).endswith(
        "SBN's index gives none of these years.")
    assert notes.year_detail("unchecked", ["1386 [2007]"], []).endswith(
        "SBN could not be asked.")
    assert notes.year_detail("other calendar", ["1316 s"], []).endswith(
        "Another calendar; not converted.")
    assert notes.year_detail("no date", [], []) == "The catalogue gives no year."
    assert notes.year_detail("printed", ["1996, stampa 1997"], ["1997"]) == (
        "Catalogue: 1996, stampa 1997. SBN index: 1997. SBN files it under the "
        "printing; the year shown is the publication's.")


def test_the_date_cap_is_a_truncation_line():
    assert notes.truncations({"dates": {"truncated": True, "checked": 300, "rows": 412}}) == \
        ["dates were checked with SBN for 300 of 412 rows whose year is not plain; "
         "the rest are labelled year unsure"]
    assert notes.truncations({"dates": {"truncated": False}}) == []
    assert notes.truncations({"dates": {"reconcile_truncated": True,
                                        "reconcile_requests": 60, "reconcile_wanted": 330}}) == \
        ["SBN's index was asked about 60 of 330 years whose counts disagree with the "
         "listing; rows under the rest keep the year they state"]


# ---------------------------------------------------------------------------
# The store and the view
# ---------------------------------------------------------------------------

def test_note_date_writes_the_answer_and_adds_no_route():
    store = RecordStore()
    held = store.put(sbn("1386 [2007]"))
    store.note_date(held.key, ["2007"])
    store.note_date(("SBN", "nobody"), ["2007"])          # not held: nothing happens
    assert (held.date_indexed, held.date_check_failed) == (["2007"], False)
    assert len(store.routes(held)) == 1 and len(store) == 1


def persian_and_italian():
    store = RecordStore()
    store.put(sbn("1386 [2007]", year="1386"))
    store.put(Record(source="SBN", id="RAV0000001", year="1990", date="1990",
                     language="ita",
                     provenance=Provenance("SBN", WORK_LISTING, UNIFORM_TITLE)))
    return store


def test_an_unsure_year_leads_nothing_and_says_so():
    """With no original year stated, 1386 used to be the earliest edition found
    and put the Persian group first (BACKLOG, Step 15)."""
    view = snapshot(persian_and_italian())
    assert view["header"]["earliest"]["year"] == 1990
    assert view["header"]["first_year_seen"] == 1990
    assert view["language_order"] == ["ita", "per"]
    row = view["editions_by_language"]["per"][0]
    assert (row["year"], row["year_num"]) == (None, None)
    assert row["year_note"] == {
        "note": "unsure", "label": "year unsure", "shown": "1386 / 2007",
        "detail": "Catalogue: 1386 [2007]. Nothing to check it against."}
    assert view["editions_by_language"]["ita"][0]["year_note"] is None


def test_a_checked_year_takes_its_place_in_the_history():
    store = persian_and_italian()
    store.note_date(("SBN", "TO01804900"), ["2007"])
    view = snapshot(store)
    assert view["language_order"] == ["ita", "per"]
    per = next(s for s in view["header"]["spans"] if s["code"] == "per")
    assert (per["first_year"], per["last_year"]) == (2007, 2007)
    row = view["editions_by_language"]["per"][0]
    assert (row["year"], row["year_note"]["label"], row["year_note"]["shown"]) == \
        ("2007", "year inferred", None)


def test_a_printed_row_keeps_its_year_and_names_the_printing():
    store = RecordStore()
    store.put(sbn("1996, stampa 1997", ["1997"], language="ita", bid="RAV0000002"))
    row = snapshot(store)["editions_by_language"]["ita"][0]
    assert (row["year"], row["year_note"]["label"], row["year_note"]["shown"]) == \
        ("1996", "printed 1997", None)


def test_a_refused_row_shows_its_unsettled_years():
    store = RecordStore()
    store.put(Record(source="SBN", id="TO01804900", date="1386 [2007]", year="1386",
                     provenance=Provenance("SBN", "title probe", "refused", 0.2)))
    rows = snapshot(store)["loose_matches"]["groups"][0]["rows"]
    assert rows[0]["year"] == "1386 / 2007"
