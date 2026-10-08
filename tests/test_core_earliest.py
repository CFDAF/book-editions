"""`core.view.earliest_edition` — a measurement, not an example.

Step 11's gate: the earliest-edition line reproduces
`results/stage-2/q4_earliest_found.json` — **22 right, 9 right with other
languages tying, 4 later than the first edition, 2 right-year-wrong-language,
and 0 older than the first edition** over the 37 scored corpus books. That count
is what decision D rests on, so the rule is checked against the measurement
rather than against a hand-built case, exactly as `test_core_fold.py` checks the
fold against `q2_printings.json`.

The input is the committed Stage 1 listings — SBN ∪ Open Library, the rows a
lookup of that book actually returned — and the original year is the one the
benchmark says the lookup would have had: P577 of the Wikidata item Step 4
accepts for most of that book's entries. **Both are inputs, not the rule.** The
rule under test is the shipped one, and it is the only thing this file calls:
the earliest dated edition, with editions dated before a known original year
left out.

One shape difference, and it is outcome-preserving: a catalogue row can carry
two languages (a parallel text), while an `Edition` carries one, so such a row
becomes one edition per language. The outcome is scored on the *set* of
languages at the earliest year, which that expansion leaves unchanged.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from core import view
from core.fold import fold
from core.model import Provenance, Record, Work

DATA = Path(__file__).resolve().parent / "data"
STAGE1 = DATA / "results" / "stage-1"

# The benchmark's own exclusions, repeated here because they are part of the
# measurement: E10 and E11 are generic titles and not works, N23 is scored for
# insights only.
NOT_A_WORK, INSIGHTS = {"E10", "E11"}, {"N23"}
ACCEPTED_YEARS = {"N04": {1866, 1867}}      # serial 1866, book 1867

P = Provenance(source="SBN", route="work listing", evidence="uniform title")


@pytest.fixture(scope="module")
def corpus():
    return json.loads((DATA / "corpus.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def q4():
    return json.loads((DATA / "results" / "stage-2" / "q4_earliest_found.json")
                      .read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def wikidata():
    return json.loads((STAGE1 / "a1_wd.json").read_text(encoding="utf-8"))["books"]


def editions_of(bid: str) -> list:
    """The book's Stage 1 listing rows as editions, one per stated language."""
    listing = json.loads((STAGE1 / "listings" / f"{bid}.json").read_text(encoding="utf-8"))
    rows = []
    for page in listing["sbn"]:
        for row in page.get("items", []):
            if row["year"]:
                rows.append((row["bid"], int(row["year"]), list(row["langs"]) or [None]))
    if listing["ol"]:
        for row in listing["ol"]["items"]:
            if row["year"]:
                rows.append((row["key"], int(row["year"]), list(row["languages"]) or [None]))
    records = []
    for rid, year, codes in rows:
        if not 1400 < year <= 2026:
            continue
        for code in codes:
            records.append(Record(source="SBN", id=f"{rid}/{code}", provenance=P,
                                  year=str(year),
                                  **({"language": code} if code else {})))
    return fold(records)


def original_year(bid: str, book: dict, wikidata: dict):
    """The year the lookup would have had: P577 of the item Step 4 accepts."""
    counted = Counter(wikidata[bid]["entries"][e["key"]]["step4"]["qid"]
                      for e in book["entries"]
                      if wikidata[bid]["entries"][e["key"]]["step4"]["qid"])
    if not counted:
        return None
    qid = counted.most_common(1)[0][0]
    cluster = next(wikidata[bid]["entries"][e["key"]]["today"] for e in book["entries"]
                   if wikidata[bid]["entries"][e["key"]]["today"]["qid"] == qid)
    year = cluster.get("original_year")
    return int(year) if year and str(year).isdigit() else None


def truth(book: dict) -> tuple:
    """The years and languages the first edition may have, hand-checked."""
    ground = book["ground_truth"]
    first = ground.get("first_edition_overall") or {}
    languages = {first.get("language") or ground["original_language"]}
    if book["id"] == "N02":
        languages.add(ground["original_language"])     # English and French at once
    year = first.get("year") or (ground.get("original_first_edition") or {}).get("year")
    years = ACCEPTED_YEARS.get(book["id"]) or (
        {int(year)} if year and str(year).isdigit() else set())
    return years, languages


def stated_languages(earliest) -> list:
    """The languages at the earliest year that a catalogue actually recorded.

    The shipped line names an unrecorded language as `unknown`, because a reader
    is owed it; the recorded measurement simply had no entry for such a row. So
    the scoring drops it, which is the measurement's own input shape and not a
    change to the rule.
    """
    return [code for code in earliest["languages"] if code != view.UNKNOWN]


def outcome(earliest, years: set, languages: set) -> str:
    if earliest is None:
        return "no dated listing"
    found, at = earliest["year"], set(stated_languages(earliest))
    if not years:
        return "no ground-truth year"
    if found < min(years):
        return "earlier"
    if found > max(years):
        return "later"
    if at & languages:
        return "right, tie" if at - languages else "right"
    return "right year, not its language"


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

class TestTheMeasurement:
    def test_it_reproduces_q4_over_the_scored_corpus(self, corpus, q4, wikidata):
        """Book for book, not just in total: a count can agree by two errors
        cancelling, and the per-book verdict is what decision D was taken on."""
        counts, disagreed = Counter(), []
        for book in corpus["books"]:
            bid = book["id"]
            if bid in NOT_A_WORK:
                continue
            year = original_year(bid, book, wikidata)
            work = Work(original_year=str(year) if year else None)
            earliest = view.earliest_edition(work, editions_of(bid))
            verdict = outcome(earliest, *truth(book))
            if bid not in INSIGHTS:
                counts[verdict] += 1
            recorded = q4["books"][bid]
            if verdict != recorded["outcome"]:
                disagreed.append(f"{bid}: {verdict} != {recorded['outcome']}")
            if earliest is not None:
                assert earliest["year"] == recorded["earliest_found"], bid
                assert stated_languages(earliest) == recorded["languages_at_earliest"], bid
        assert not disagreed
        assert dict(counts) == {"right": 22, "right, tie": 9, "later": 4,
                                "right year, not its language": 2}
        assert counts["earlier"] == 0        # never older than the first edition

    def test_the_rule_is_what_keeps_the_older_rows_out(self, corpus, wikidata):
        """Without the original-year floor the corpus *does* go older than the
        first edition — that is the bad-catalogue-date failure A5 measured, so
        the clause above passes because of the rule and not by luck."""
        older = 0
        for book in corpus["books"]:
            bid = book["id"]
            if bid in NOT_A_WORK or bid in INSIGHTS:
                continue
            editions = editions_of(bid)
            unfloored = view.earliest_edition(Work(), editions)
            if outcome(unfloored, *truth(book)) == "earlier":
                older += 1
        assert older > 0


class TestTheRuleItself:
    def test_an_edition_older_than_a_stated_original_is_left_out(self):
        """An audiobook catalogued 2001 under a work first published 2002."""
        editions = fold([
            Record(source="OL", id="a", provenance=P, year="2001", language="eng"),
            Record(source="OL", id="b", provenance=P, year="2002", language="jpn"),
        ])
        earliest = view.earliest_edition(Work(original_year="2002"), editions)
        assert earliest["year"] == 2002 and earliest["older_dropped"] == 1

    def test_with_no_stated_original_year_nothing_is_left_out(self):
        editions = fold([Record(source="OL", id="a", provenance=P, year="1866")])
        earliest = view.earliest_edition(Work(), editions)
        assert earliest["year"] == 1866 and earliest["older_dropped"] == 0

    def test_a_tie_names_every_language_at_that_year(self):
        """9 books of 37 tie. The line says so rather than picking one."""
        editions = fold([
            Record(source="SBN", id="a", provenance=P, year="1967", language="spa",
                   publisher="Sudamericana"),
            Record(source="OL", id="b", provenance=P, year="1967", language="eng"),
        ])
        earliest = view.earliest_edition(Work(original_language="spa"), editions)
        assert earliest["languages"] == ["eng", "spa"]
        assert earliest["language"] == "spa"           # the original's row leads
        assert earliest["publisher"] == "Sudamericana"
        assert earliest["editions"] == 2

    def test_the_lead_row_is_the_stores_first_when_no_original_language_matches(self):
        editions = fold([
            Record(source="SBN", id="a", provenance=P, year="1967", language="fre",
                   publisher="Seuil"),
            Record(source="OL", id="b", provenance=P, year="1967", language="eng"),
        ])
        earliest = view.earliest_edition(Work(original_language="spa"), editions)
        assert earliest["language"] == "fre" and earliest["publisher"] == "Seuil"

    def test_nothing_dated_means_no_line_at_all(self):
        """Rather than a line with a blank year in it (rule 8)."""
        editions = fold([Record(source="OL", id="a", provenance=P)])
        assert view.earliest_edition(Work(), editions) is None

    def test_every_edition_older_than_the_original_means_no_line(self):
        editions = fold([Record(source="OL", id="a", provenance=P, year="1912")])
        assert view.earliest_edition(Work(original_year="1925"), editions) is None
