"""`core/model.py` — Work, Edition, Record, and what each one may say.

The three types exist to stop one class standing in for three things. So the
assertions here are mostly about what a type *refuses* to do: an `Edition` does
not hide its printings, a `Work` does not invent an original, a `Record` does not
turn a country into a language.
"""

from catalog import langs
from core.model import (REFUSED, TITLE_MATCH, UNIFORM_TITLE, WORK_LISTING,
                        Edition, Holding, Provenance, Record, Work)

ADMITTED = Provenance("SBN", WORK_LISTING, UNIFORM_TITLE)
BAND = Provenance("SBN", "author sweep", REFUSED, 0.5)


def rec(rec_id, source="SBN", provenance=ADMITTED, **kw) -> Record:
    return Record(source=source, id=rec_id, provenance=provenance, **kw)


class TestRecord:
    def test_a_record_is_identified_by_source_and_id(self):
        assert rec("MIL0871878").key == ("SBN", "MIL0871878")

    def test_the_same_id_in_two_catalogues_is_two_records(self):
        assert rec("X").key != rec("X", source="Open Library").key

    def test_a_language_nothing_stated_stays_unknown(self):
        """Never inferred from the country of publication, and never folded into
        English because it is blank — the original script did the latter and
        inflated the English list."""
        assert rec("MIL0871878").language == langs.UNKNOWN

    def test_provenance_says_whether_the_gate_refused_it(self):
        assert not rec("A").provenance.refused
        assert rec("B", provenance=BAND).provenance.refused
        assert rec("B", provenance=BAND).provenance.score == 0.5

    def test_re_provenancing_leaves_the_original_record_alone(self):
        original = rec("A")
        moved = original.with_provenance(BAND)
        assert moved.provenance.refused and not original.provenance.refused


class TestEdition:
    def test_an_isbn_names_an_edition_and_the_printings_stay_visible(self):
        """One SBN ISBN spans up to 31 records over 41 years (F17). A row that
        showed only one year would be hiding thirty."""
        e = Edition(id="9788845906862", isbn="9788845906862", records=[
            rec("A", year="1985"), rec("B", year="2026"), rec("C", year="1985")])
        assert e.printings == ["1985", "2026"]
        assert e.year == "1985"

    def test_the_first_stated_language_wins_and_a_blank_one_does_not(self):
        e = Edition(id="x", isbn=None, records=[rec("A"), rec("B", language="ita")])
        assert e.language == "ita"

    def test_an_edition_no_source_gave_a_language_reports_unknown(self):
        e = Edition(id="x", isbn=None, records=[rec("A")])
        assert e.language == langs.UNKNOWN

    def test_fields_come_from_the_first_record_that_has_them(self):
        e = Edition(id="x", isbn=None, records=[
            rec("A", title="Rumori"), rec("B", publisher="Mazzotta", series="Oscar")])
        assert (e.title, e.publisher, e.series) == ("Rumori", "Mazzotta", "Oscar")

    def test_lists_are_unioned_in_order_without_repeats(self):
        e = Edition(id="x", isbn=None, records=[
            rec("A", authors=["Attali, Jacques"], evidence=["traduzione di X"]),
            rec("B", authors=["Attali, Jacques", "Eshun, Kodwo"])])
        assert e.authors == ["Attali, Jacques", "Eshun, Kodwo"]
        assert e.evidence == ["traduzione di X"]

    def test_holdings_are_deduplicated_across_the_records_behind_the_row(self):
        h = Holding("Biblioteca Nazionale", "Roma", "IT-RM0267")
        e = Edition(id="x", isbn=None, records=[
            rec("A", holdings=[h]), rec("B", holdings=[Holding(*vars(h).values())])])
        assert len(e.holdings) == 1

    def test_sources_are_named_once_each(self):
        e = Edition(id="x", isbn=None, records=[
            rec("A"), rec("B"), rec("C", source="Open Library")])
        assert e.sources == ["Open Library", "SBN"]

    def test_one_admitted_record_admits_the_whole_row(self):
        """The ISBN said the rows are the same book, so a route having failed to
        prove it does not unprove it."""
        e = Edition(id="x", isbn="9788845906862", records=[
            rec("A", provenance=BAND), rec("B")])
        assert not e.refused

    def test_a_row_every_record_of_which_was_refused_is_the_band(self):
        e = Edition(id="x", isbn=None, records=[rec("A", provenance=BAND)])
        assert e.refused


class TestWork:
    def test_no_original_where_none_is_stated(self):
        """Rule 8. A refused Wikidata candidate, a weak W or an impossible year
        means no original — not a guess."""
        w = Work(sbn_work="bruits", sbn_work_tier="weak")
        assert w.original_title is None
        assert w.original_language is None
        assert w.original_year is None

    def test_titles_never_include_what_the_user_typed(self):
        """Rule 11: nothing after identity uses the typed title, so there is no
        field here to leak it. `titles()` holds only titles a catalogue stated."""
        w = Work(original_title="Bruits", titles_by_lang={"ita": "Rumori"})
        assert w.titles() == ["Bruits", "Rumori"]
        assert not hasattr(w, "query_title")

    def test_titles_are_ordered_and_deduplicated_case_insensitively(self):
        w = Work(original_title="Bruits",
                 titles_by_lang={"ita": "Rumori", "fre": "bruits", "eng": "Noise"})
        assert w.titles() == ["Bruits", "Noise", "Rumori"]

    def test_the_uniform_title_is_not_one_of_the_titles(self):
        """It is normalised, accent-stripped and sometimes punctuated
        ('cien anos des soledad. -'): a search key, never a title."""
        w = Work(sbn_work="cien anos de soledad", original_title="Cien años de soledad")
        assert w.titles() == ["Cien años de soledad"]

    def test_a_book_with_no_identity_is_a_normal_answer(self):
        """A1: no source reaches one identity for every entry title — SBN 22 of
        37 books, Wikidata 14, Open Library 13. The lookup still has to answer."""
        assert not Work().identified
        assert Work(qid="Q178869").identified
        assert Work(sbn_work="bruits").identified
        assert Work(ol_keys=["OL685250W"]).identified


class TestProvenanceVocabulary:
    def test_the_evidence_that_needs_no_corroboration_is_named_apart(self):
        """`UNIFORM_TITLE` is SBN stating the link; everything else here is this
        tool inferring it, and the two must not be spelled the same."""
        assert UNIFORM_TITLE == "uniform title"
        assert TITLE_MATCH != UNIFORM_TITLE

    def test_a_provenance_is_immutable(self):
        import dataclasses
        import pytest
        with pytest.raises(dataclasses.FrozenInstanceError):
            ADMITTED.route = "somewhere else"


class TestEditionCoverImage:
    def test_a_cover_comes_from_the_first_record_that_has_one(self):
        """SBN puts it on the full record only, so the brief sighting of the same
        row has none and must not shadow it."""
        e = Edition(id="x", isbn=None, records=[
            rec("A"), rec("B", cover_url="https://opac.sbn.it/cover/B.jpg")])
        assert e.cover_url == "https://opac.sbn.it/cover/B.jpg"

    def test_no_record_having_one_is_none_and_not_an_empty_string(self):
        assert Edition(id="x", isbn=None, records=[rec("A")]).cover_url is None
