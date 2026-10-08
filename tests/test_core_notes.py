"""`core/notes.py` — the one wording of what a lookup could not do.

Every sentence the page says about the network or about a cap is written here,
so these tests are where that wording is pinned. Two properties matter more than
the exact words:

- **A failure is never an empty result** (`CLAUDE.md` rule 5): a source the
  ledger counted failures for is `partial`, whether or not the source said so.
- **A truncation states what was read**, never what exists (decision C). There
  is no census in this project and a line here must not read like one.
"""

from core import notes


class TestSourceStates:
    def test_a_source_that_lost_requests_is_partial_even_when_it_says_ok(self):
        """The ledger counts a failure the source swallowed. This is the whole
        reason the ledger exists — it was the worst bug in the project."""
        failed = {"SBN": 3}.get
        states = notes.source_states({"SBN": "ok", "Open Library": "ok"}, failed)
        assert states == {"SBN": "partial (3 failed)", "Open Library": "ok"}

    def test_an_error_outranks_partial(self):
        """`error:` is the worse state and the worse state is the true one."""
        states = notes.source_states({"SBN": "error: timed out"}, {"SBN": 2}.get)
        assert states == {"SBN": "error: timed out"}

    def test_a_name_the_ledger_does_not_count_is_left_alone(self):
        """`SBN authority`'s requests are counted under SBN, so charging it the
        same failures would report one failure twice."""
        states = notes.source_states({"SBN authority": "ok"}, {"SBN": 4}.get)
        assert states == {"SBN authority": "ok"}

    def test_no_failures_changes_nothing(self):
        assert notes.source_states({"SBN": "ok"}, lambda name: 0) == {"SBN": "ok"}


class TestIncomplete:
    def test_nothing_failed_means_no_note(self):
        assert notes.incomplete(0) is None

    def test_one_failure_is_singular(self):
        assert notes.incomplete(1).startswith("Incomplete: 1 request failed")

    def test_it_says_what_a_missing_request_costs(self):
        """Not "an error occurred": the answer arrived and may be short, and a
        whole language can drop out without looking any different."""
        note = notes.incomplete(4)
        assert "4 requests failed" in note
        assert "a whole language can drop out this way" in note


class TestSlow:
    def test_a_quick_lookup_says_nothing(self):
        assert notes.slow(3.0, ["SBN made it wait"], 10) is None

    def test_a_slow_lookup_names_only_what_was_measured(self):
        note = notes.slow(61.9, ["wikidata.org made it wait 36 s on Retry-After"], 10)
        assert "Slow lookup (62 s)" in note
        assert "wikidata.org made it wait 36 s" in note

    def test_it_labels_the_parallel_sum_rather_than_hiding_it(self):
        """'Wikidata 8 (75.0 s)' inside a 62 s lookup is accurate and reads as
        nonsense unless the summing is said out loud."""
        note = notes.slow(62.0, ["requests sent: Wikidata 8 (75.0 s)"], 10)
        assert "summed across requests that ran in parallel" in note

    def test_slow_with_nothing_measured_says_that_too(self):
        assert notes.slow(14.0, [], 10) == (
            "Slow lookup (14 s), though no request in it went to the network.")


class TestTruncations:
    def test_nothing_truncated_is_an_empty_list(self):
        assert notes.truncations({}) == []

    def test_the_author_sweep_says_how_much_of_the_name_it_read(self):
        """Rule 10. The sweep truncated on 26 of 79 fitting entries **M**, and
        saying nothing would make 240 rows look like the whole of SBN."""
        lines = notes.truncations({"recovery": {"routes": {"author_sweep": {
            "truncated": True, "rows": 240, "total": 1366}}}})
        assert lines == ["the author sweep read 240 of 1,366 records filed "
                         "under this name"]

    def test_a_title_probe_names_the_title_it_truncated_on(self):
        lines = notes.truncations({"recovery": {"routes": {"title_probes": [
            {"title": "Il nome della rosa", "truncated": True, "rows": 239,
             "total": 298},
            {"title": "The Name of the Rose", "truncated": False, "rows": 12,
             "total": 12}]}}})
        assert lines == ["the title probe for 'Il nome della rosa' read 239 of "
                         "298 records"]

    def test_a_listing_short_of_its_own_total_is_a_truncation(self):
        """The language pages are the whole work on every book measured, but
        the facet caps at 50 (F11) and a failed page loses its rows."""
        lines = notes.truncations({"listing": {"sbn_rows": 143, "sbn": {"total": 190}}})
        assert lines == ["the SBN listing read 143 of 190 records filed under "
                         "this work"]

    def test_a_complete_listing_is_not_reported_as_one(self):
        assert notes.truncations({"listing": {"sbn_rows": 143,
                                              "sbn": {"total": 143}}}) == []

    def test_the_facet_caps_are_named_where_they_bind(self):
        lines = notes.truncations({
            "identity": {"sbn_work": {"facet_truncated": True}},
            "listing": {"sbn_rows": 5, "sbn": {"total": 5, "facet_truncated": True}}})
        assert len(lines) == 2
        assert "50 uniform titles" in lines[0]
        assert "at most 50 languages" in lines[1]

    def test_a_count_with_no_total_still_says_what_was_read(self):
        lines = notes.truncations({"recovery": {"routes": {"author_sweep": {
            "truncated": True, "rows": 240, "total": 0}}}})
        assert lines == ["the author sweep read 240 records filed under this name"]

    def test_another_name_record_s_sweep_says_how_much_it_read(self):
        lines = notes.truncations({"recovery": {"routes": {"other_author_sweeps": [
            {"authority": "CFIV093786", "truncated": True, "rows": 240, "total": 531},
            {"authority": "LO1V444420", "truncated": False, "rows": 2, "total": 2}]}}})
        assert lines == ["the sweep of SBN's name record CFIV093786 read 240 of 531 "
                         "records filed under that spelling"]

    def test_the_title_switch_s_cap_is_named_where_it_binds(self):
        lines = notes.truncations({"identity": {"title_spellings": {
            "offered": 9, "asked": ["a", "b", "c", "d", "e", "f"]}}})
        assert lines == ["of the 9 other spellings of the title Wikidata gives, "
                         "the first 6 were asked of SBN"]
        assert notes.truncations({"identity": {"title_spellings": {
            "offered": 2, "asked": ["a", "b"]}}}) == []


class TestSpellings:
    """Decision AV: what a ticked switch asked, said even when it found nothing
    — an empty answer and a question never sent must not read the same."""

    def test_nothing_ticked_says_nothing(self):
        assert notes.spellings({}, {}) == []
        assert notes.spellings({"title_spellings": None, "author_spellings": None}, {}) == []

    def test_the_title_switch(self):
        asked = {"title_spellings": {"item": "Q3149381", "asked": ["Palace Walk",
                                                                   "Tra i due palazzi"]},
                 "spellings": [{"spelling": "Palace Walk", "W": "bain el-qasrain."},
                               {"spelling": "Tra i due palazzi", "W": None}]}
        assert notes.spellings(asked, {}) == [
            "other spellings of the title asked of SBN: 'Palace Walk', 'Tra i due "
            "palazzi'; SBN files them under 'bain el-qasrain.'"]
        asked["spellings"] = []
        assert notes.spellings(asked, {})[0].endswith("SBN files none of them under a work")
        assert "Wikidata gives none" in notes.spellings(
            {"title_spellings": {"item": "Q1", "asked": []}}, {})[0]
        assert "no item for this work" in notes.spellings(
            {"title_spellings": {"item": None, "asked": []}}, {})[0]

    def test_the_author_switch(self):
        ident = {"authority": {"id": "BMCV001724"},
                 "author_spellings": {"asked": True, "forms": ["Naguib Mahfouz", "Nagib Mahfuz"],
                                      "ids": ["BMCV001724", "CFIV093786"]}}
        swept = {"routes": {"other_author_sweeps": [{"authority": "CFIV093786", "rows": 240},
                                                    {"authority": "LO1V444420", "rows": 1}]}}
        assert notes.spellings(ident, swept) == [
            "other spellings of the author: 2 asked of SBN, which files the same person "
            "under 2 more name records, swept: CFIV093786 (240 records), LO1V444420 (1 record)"]
        swept["routes"]["other_author_sweeps"].pop()
        assert "under 1 more name record, swept" in notes.spellings(ident, swept)[0]
        assert "not swept" in notes.spellings(ident, {})[0]
        ident["author_spellings"]["ids"] = ["BMCV001724"]
        assert notes.spellings(ident, {})[0].endswith("under no other name record")
        assert notes.spellings({"author_spellings": {"asked": False, "why_not": "no author"}},
                               {}) == ["other spellings of the author: none asked — no author"]
        assert notes.spellings({"author_spellings": {"asked": False}}, {})[0].endswith(
            "Wikidata did not answer")


class TestNotAsked:
    def test_a_query_that_was_never_sent_is_not_a_failure(self):
        """A request that could only come back looking like an answer is not
        made. That is a disclosure, and the difference from a failure is rule
        5's whole point."""
        lines = notes.not_asked({"listing": {
            "sbn": {"asked": False, "why_not": "no accepted SBN work for this question"},
            "open_library": {"asked": True}}})
        assert lines == ["no accepted SBN work for this question"]

    def test_a_probe_refused_for_its_script_names_the_title(self):
        lines = notes.not_asked({"recovery": {"routes": {"title_probes": [
            {"title": "Преступление", "asked": False,
             "why_not": "not Latin script: the OPAC discards the term (F15)"}]}}})
        assert lines == ["'Преступление': not Latin script: the OPAC discards "
                         "the term (F15)"]

    def test_a_sweep_with_no_authority_says_so(self):
        lines = notes.not_asked({"recovery": {"routes": {"author_sweep": {
            "asked": False,
            "why_not": "no SBN name authority was accepted for this person"}}}})
        assert lines == ["no SBN name authority was accepted for this person"]

    def test_the_recovery_stage_can_decline_as_a_whole(self):
        lines = notes.not_asked({"recovery": {"why_not": "no accepted SBN work"}})
        assert lines == ["no accepted SBN work"]

    def test_nothing_declined_is_an_empty_list(self):
        assert notes.not_asked({}) == []


class TestTheDuplicateSearch:
    """Step 13's searches read one page each. The totals are E01's, N06's and
    N23's as Open Library answered on 2026-09-25."""

    def test_one_search_past_its_page_is_named(self):
        lines = notes.truncations({"duplicates": {"queries": [
            {"title": "Cien años de soledad", "docs": 100, "total": 101},
            {"title": "Cent'anni di solitudine", "docs": 3, "total": 3}]}})
        assert lines == ["the search for Open Library's other records under "
                         "'Cien años de soledad' read 100 of 101 results"]

    def test_several_are_one_line_not_five(self):
        lines = notes.truncations({"duplicates": {"queries": [
            {"title": "Odyssey", "docs": 100, "total": 1835},
            {"title": "Odissea", "docs": 100, "total": 127},
            {"title": "Odysseia", "error": "timed out"}]}})
        assert lines == ["the 2 searches for Open Library's other records read the "
                         "first 100 results each, and each found more (up to 1,835)"]

    def test_a_search_read_whole_is_not_a_truncation(self):
        assert notes.truncations({"duplicates": {"queries": [
            {"title": "1984", "docs": 3, "total": 3}]}}) == []

    def test_no_main_work_means_nothing_was_looked_for_and_it_says_so(self):
        lines = notes.not_asked({"duplicates": {
            "asked": False, "why_not": "no Open Library work for this question"}})
        assert lines == ["no Open Library work for this question"]


class TestTitleOnly:
    def test_the_byline_says_where_the_author_came_from(self):
        assert notes.author_adopted(["Wikidata", "Open Library"]) == \
            "author from Open Library and Wikidata — none was typed"
        assert notes.author_adopted(["SBN"]) == "author from SBN — none was typed"
        assert notes.author_adopted(["SBN", "Open Library", "Wikidata"]) == \
            "author from Open Library, SBN and Wikidata — none was typed"
