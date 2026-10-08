"""Author mode's judgements, offline (Step 14, decision AJ).

Every id, heading and uniform title below is one Step 14's probe read
live on 2026-09-25/26, or one
this step's smoke runs printed: Bateson's `CFIV034892` beside Peter Finke, the
four Mahfouz ids, *Steps to an Ecology of Mind* as SBN and Wikidata file it.
"""

import pytest

from core import authors, dates, notes
from core.model import AUTHOR_SWEEP, Provenance, Record
from core.authors import Candidate, WorkRow

BATESON = {"id": "CFIV034892", "heading": "Bateson , Gregory", "kind": "Persona"}
FINKE = {"id": "RT1V031559", "heading": "Finke , Peter  <1942->", "kind": "Persona"}
HAN = {"id": "RAVV673297", "heading": "Han , Byung-Chul", "kind": "Persona"}
FONDAZIONE = {"id": "UBOV162090", "heading": "Fondazione Umberto Eco", "kind": "Ente"}
MAHFOUZ = [{"id": "BMCV001724", "heading": "Mahfouz , Naguib", "kind": "Persona"},
           {"id": "TSAV609028", "heading": "Mahfouz , Naguib Pacha", "kind": "Persona"},
           {"id": "CFIV093786", "heading": "Maḥfūẓ , Naǧīb", "kind": "Persona"}]


class TestWhoIsMeant:

    def test_only_persons_are_authors(self):
        assert authors.persons([BATESON, FONDAZIONE, {"id": "X"}]) == [BATESON]

    def test_the_forms_asked_are_latin_and_distinct(self):
        forms = authors.latin_forms("Naguib Mahfouz", [
            "Naguib Mahfouz", "mahfouz naguib", "Nagib Mahfuz", "نجيب محفوظ", "", "Naǧīb Maḥfūẓ"])
        # `Naǧīb Maḥfūẓ` folds to `Nagib Mahfuz`'s tokens, so it is the same question.
        assert forms == ["Naguib Mahfouz", "Nagib Mahfuz"]

    def test_the_wikidata_person_is_the_one_whose_names_agree(self):
        people = [{"qid": "Q1", "names": ["Nagib Surur"]},
                  {"qid": "Q7176", "names": ["Naguib Mahfouz", "نجيب محفوظ"]}]
        assert authors.person_of(people, ["Nagib Mahfuz"])["qid"] == "Q7176"
        assert authors.person_of(people, ["Kodwo Eshun"]) is None
        assert authors.person_of([], ["x"]) is None

    def test_one_person_on_every_form_skips_the_chooser(self):
        """Han answers both forms with one Persona: decision AJ's skip."""
        answers = [{"form": "Byung-Chul Han", "rows": [HAN], "total": 1},
                   {"form": "Han Byung-Chul", "rows": [HAN], "total": 1}]
        got = authors.candidates(answers, "Byung-Chul Han")
        assert got["skip"] and got["resolved"] == "RAVV673297"
        assert got["candidates"][0].forms == ["Byung-Chul Han", "Han Byung-Chul"]

    def test_a_form_that_finds_nobody_contradicts_nothing(self):
        answers = [{"form": "Byung-Chul Han", "rows": [HAN], "total": 1},
                   {"form": "Pyŏng-ch'ŏl Han", "rows": [], "total": 0}]
        assert authors.candidates(answers, "Byung-Chul Han")["skip"]

    def test_a_namesake_anywhere_means_the_reader_chooses(self):
        """Bateson resolves, and Peter Finke is on the same answer."""
        answers = [{"form": "Gregory Bateson", "rows": [BATESON, FINKE], "total": 2}]
        got = authors.candidates(answers, "Gregory Bateson")
        assert got["resolved"] == "CFIV034892" and not got["skip"]
        assert {c.id: c.agrees for c in got["candidates"]} == {
            "CFIV034892": True, "RT1V031559": False}

    def test_an_alias_reaching_a_second_id_means_the_reader_chooses(self):
        answers = [{"form": "Naguib Mahfouz", "rows": MAHFOUZ[:1], "total": 1},
                   {"form": "Nagib Mahfuz", "rows": MAHFOUZ[2:], "total": 1}]
        got = authors.candidates(answers, "Naguib Mahfouz")
        assert got["resolved"] == "BMCV001724" and not got["skip"]
        assert len(got["candidates"]) == 2

    def test_nothing_found_resolves_nobody(self):
        got = authors.candidates([], "Nobody")
        assert got == {"candidates": [], "resolved": None, "rule": "no match", "skip": False}

    def test_the_chooser_order(self):
        cands = [Candidate("A", "Eco , Stefano", agrees=True, records=1),
                 Candidate("B", "Barbieri , Daniele"),
                 Candidate("C", "Eco , Umberto", agrees=True, records=2575),
                 Candidate("D", "Eco , Renate", agrees=True, records=11)]
        assert [c.id for c in authors.order(cands, "C")] == ["C", "D", "A", "B"]
        assert cands[2].display == "Umberto Eco"


    @pytest.mark.parametrize("a,b,same", [
        ("Nagib Surur", "Nagib Mahfuz", False),
        ("Umberto Saba", "Umberto Eco", False),
        ("Murakami Haruki", "Haruki Murakami", True),
        ("Maḥfūẓ , Naǧīb", "Naguib Mahfouz", True),
        ("Dostoevskij , Fëdor Mihajlovič", "Dostoïevski", True),
        ("Eco , Renate", "Umberto Eco", True),
    ])
    def test_a_forename_alone_is_not_the_same_name(self, a, b, same):
        assert authors.same_name(a, b) is same


class TestTheCap:

    def test_fifty_is_capped(self):
        assert authors.capped([{}] * 50) and not authors.capped([{}] * 49)
        assert not authors.capped(None)

    def test_extra_years_fill_the_gaps_then_go_down_then_up(self):
        got = authors.extra_years(["2000", "1998", "x", ""], floor=1995, ceiling=2002)
        assert got == ["1999", "1997", "1996", "1995", "2001", "2002"]

    def test_no_birth_year_stops_at_the_floor(self):
        got = authors.extra_years(["1452"], floor=None, ceiling=1452)
        assert got == ["1451", "1450"]
        assert authors.extra_years(["1452"], floor=1200, ceiling=1452) == ["1451", "1450"]

    def test_no_years_nothing_to_ask(self):
        assert authors.extra_years([], 1900, 2026) == []

    def test_the_union_is_by_value(self):
        nodes = [{"works": [{"value": "naven", "label": "naven"}, {"value": None}]},
                 {"works": [{"value": "naven", "label": "other"},
                            {"value": "sacred unity"}]}, {}]
        assert authors.works_union(nodes) == {"naven": "naven", "sacred unity": "sacred unity"}


STEPS = {"value": "steps to an ecology of mind", "label": "steps to an ecology of mind",
         "rows": [{"title": "Verso un'ecologia della mente / Gregory Bateson",
                   "author": "Bateson, Gregory"},
                  {"title": "Steps to an ecology of mind : collected essays",
                   "author": "Bateson, Gregory"}],
         "languages": [{"value": "ita"}, {"value": "eng"}, {}],
         "years": [{"value": "1976"}, {"value": "1972"}, {"value": "s.d."}], "total": 26}
ITEM = {"qid": "Q1970551", "typed": True, "edition": False,
        "forms": ["Steps to an Ecology of Mind", "Verso un'ecologia della Mente"],
        "original_title": "Steps to an Ecology of Mind", "original_language": "eng",
        "year": 1972}


class TestRows:

    def test_verso_is_steps_once(self):
        """The gate's own case: one row, the Italian and the Open Library
        record titled in Italian both joined to it."""
        docs = [{"key": "OL19909593W", "title": "Verso un'ecologia della mente", "year": 2001,
                 "languages": ["ita"]},
                {"key": "OL486407W", "title": "Ökologie des Geistes", "year": 2001}]
        got = authors.rows([STEPS], [ITEM], docs, ["Bateson , Gregory"])
        (row,) = got["rows"]
        assert row.qid == "Q1970551" and row.title == "Steps to an Ecology of Mind"
        assert row.uniform_titles == ["steps to an ecology of mind"]
        assert [d["key"] for d in row.ol] == ["OL19909593W"]
        assert [d["key"] for d in got["band"]] == ["OL486407W"]
        assert row.year == 1972 and row.year_kind == authors.ORIGINAL
        assert row.earliest_year == 1972 and row.languages == {"ita", "eng"}
        assert row.main_author

    def test_an_sbn_only_work_says_its_year_is_the_earliest_found(self):
        naven = {"value": "naven", "rows": [{"title": "Naven / Gregory Bateson",
                                             "author": "Bateson, Gregory"}],
                 "years": [{"value": "1958"}], "total": 2}
        (row,) = authors.rows([naven], [], [], ["Bateson , Gregory"])["rows"]
        assert row.title == "Naven" and row.year_kind == authors.EARLIEST
        assert row.key == "sbn:naven" and row.year == 1958

    def test_a_record_headed_by_somebody_else_is_not_their_work(self):
        garroni = {"value": "ricognizione della semiotica",
                   "rows": [{"title": "Ricognizione della semiotica : tre lezioni / Emilio Garroni",
                             "author": "Garroni, Emilio"}]}
        (row,) = authors.rows([garroni], [], [], ["Eco , Umberto"])["rows"]
        assert not row.main_author and row.credited == ["Garroni, Emilio"]
        shown = authors.view([row], [], ["Umberto Eco"])
        assert shown["works"] == [] and shown["contributed"][0]["credited_to"] == ["Emilio Garroni"]

    def test_a_book_written_jointly_shows_who_wrote_it(self):
        # SBN gives a joint work no main heading (D1): the head says nobody,
        # the statement of responsibility names all three.
        informazione = {"value": "informazione", "rows": [
            {"title": "Informazione : consenso e dissenso / Umberto Eco, Marino Livolsi, "
                      "Giovanni Panozzo ; prefazione di Piero Ottone"},
            {"title": "Informazione : consenso e dissenso"}]}
        (row,) = authors.rows([informazione], [], [], ["Eco , Umberto"])["rows"]
        shown = authors.view([row], [], ["Umberto Eco"])["contributed"][0]
        assert shown["credited_to"] == []
        assert shown["statement"] == ("Umberto Eco, Marino Livolsi, Giovanni Panozzo ; "
                                      "prefazione di Piero Ottone")

    def test_a_row_with_no_statement_has_none(self):
        (row,) = authors.rows([{"value": "naven", "rows": [{"title": "Naven"}]}], [], [],
                              ["Bateson , Gregory"])["rows"]
        assert authors.view([row], [], [])["contributed"][0]["statement"] is None

    def test_a_work_whose_records_failed_stays_theirs(self):
        (row,) = authors.rows([{"value": "naven", "failed": True}], [], [], ["x"])["rows"]
        assert row.main_author and row.unanswered
        assert authors.view([row], [], ["x"])["works"][0]["unanswered"]

    def test_a_film_is_labelled_not_filtered(self):
        film = {"value": "bathing babies in three cultures <film>",
                "label": "bathing babies in three cultures <film>", "rows": []}
        (row,) = authors.rows([film], [], [])["rows"]
        assert row.medium == "film" and row.title == "Bathing babies in three cultures"

    def test_what_was_made_from_a_book_is_drawn_under_it(self):
        """Decision BC, on Eco's own uniform titles (2026-10-02). The TV series,
        Annaud's film under three titles and the documentary reach the novel's
        row; they once made it a *serie tv* and counted 254 records as the book."""
        rosa = {"value": "nome della rosa", "label": "nome della rosa", "total": 233,
                "rows": [{"title": "Il nome della rosa / Umberto Eco", "author": "Eco, Umberto"}],
                "years": [{"value": "1981"}], "languages": [{"value": "ita"}]}
        series = {"value": "nome della rosa <serie tv ; 2018>",
                  "label": "nome della rosa <serie tv ; 2018>", "total": 9,
                  "rows": [{"title": "{Il nome della rosa}Episodio 4"}],
                  "years": [{"value": "2019"}], "languages": [{"value": "eng"}]}
        film = [{"value": v, "label": v, "total": n, "years": [{"value": "1986"}],
                 "rows": [{"title": "Il nome della rosa / un film di Jean-Jacques Annaud"}]}
                for v, n in (("name der rose <film ; 1986>", 8),
                             ("name of the rose <film ; 1986>", 2),
                             ("nome della rosa <film ; 1986>", 1))]
        doc = {"value": "rosa dei nomi <documentario ; 1987>",
               "label": "rosa dei nomi <documentario ; 1987>", "total": 1,
               "years": [{"value": "2002"}], "rows": [{"title": "Il nome della rosa / regia "
                                                                "di Jean-jacques Annaud"}]}
        item = {"qid": "Q172850", "typed": True, "year": 1980,
                "original_title": "Il nome della rosa", "original_language": "ita",
                "forms": ["Il nome della rosa", "The Name of the Rose", "Der Name der Rose"]}
        (row,) = authors.rows([series, *film, doc, rosa], [item], [], ["Eco , Umberto"])["rows"]
        assert row.medium is None and row.uniform_titles == ["nome della rosa"]
        assert row.sbn_records == 233 and row.languages == {"ita"}
        assert row.earliest_year == 1981 and row.main_author
        (shown,) = authors.view([row], [], ["Umberto Eco"])["works"]
        assert [(d["title"], d["medium"], d["year"], d["records"]) for d in shown["derived"]] == [
            ("Il nome della rosa", "film", 1986, 11),
            ("Il nome della rosa", "documentario", 1987, 1),
            ("Il nome della rosa", "serie tv", 2018, 9)]
        assert shown["lookup"]["variants"] == authors.lookup_variants(row)
        assert not any("<" in v for v in shown["lookup"]["variants"])

    def test_a_film_reaches_a_book_sbn_alone_holds(self):
        book = {"value": "notti bianche", "total": 40,
                "rows": [{"title": "Le notti bianche / Fëdor Dostoevskij",
                          "author": "Dostoevskij, Fëdor Michajlovič"}]}
        film = {"value": "notti bianche <film ; 1957>", "total": 3, "rows": []}
        (row,) = authors.rows([film, book], [], [], ["Dostoevskij , Fëdor Michajlovič"])["rows"]
        assert row.key == "sbn:notti bianche" and row.medium is None
        assert [(d["medium"], d["year"]) for d in row.derived] == [("film", 1957)]

    def test_an_adaptation_still_joins_what_belongs_to_its_book(self):
        """Decision BC keeps a film's titles out of the book's, not out of the
        join: Open Library's *Hakuchi* (OL27301921W, 1994, jpn) is the novel in
        Japanese and joined *Idiot* only through Kurosawa's film, and SBN files
        the series' episodes under no uniform title (`MOD1691543`)."""
        item = {"qid": "Q210784", "typed": True, "year": 1869, "original_title": "Идиот",
                "forms": ["Der Idiot", "The Idiot", "El idiota", "L'Idiot", "L'idiota"]}
        hakuchi = {"value": "hakuchi <film ; 1951>", "total": 2, "rows": [
            {"title": "Hakuchi / regia Akira Kurosawa ; soggetto tratto dall'omonimo romanzo "
                      "di F. Dostoevskij"},
            {"title": "L'idiota / regia e montaggio: Akira Kurosawa ; sceneggiatura: Eijiro "
                      "Hisaita, Akira Kurosawa (dal romanzo di Fyodor Dostoevskij)"}]}
        doc = {"key": "OL27301921W", "title": "Hakuchi", "year": 1994, "languages": ["jpn"]}
        got = authors.rows([hakuchi], [item], [doc], ["Dostoevskij , Fëdor Michajlovič"])
        (row,) = got["rows"]
        assert [d["key"] for d in row.ol] == ["OL27301921W"] and got["band"] == []
        assert "hakuchi" not in [t.casefold() for t in row.titles]

        amica = {"value": "amica geniale", "total": 120,
                 "rows": [{"title": "L'amica geniale / Elena Ferrante", "author": "Ferrante, Elena"}]}
        series = {"value": "amica geniale <serie tv ; 2018- >", "total": 13, "rows": [
            {"title": "Episodio 5: le scarpe / una serie di Saverio Costanzo ; tratto dal "
                      "romanzo di Elena Ferrante"},
            {"title": "Episodio 8: la fata blu / una serie di Saverio Costanzo ; regia di "
                      "Saverio Costanzo e Alice Rohrwacher"}]}
        (row,) = authors.rows([amica, series], [], [], ["Ferrante , Elena"])["rows"]
        records = [{"id": "MOD1691543", "title": "Episodio 3: le metamorfosi", "year": 2018}]
        assert authors.unlinked(records, [row]) == []

    @pytest.mark.parametrize("label,medium", [
        ("fratelli karamazov <sceneggiato tv ; 1969>", "sceneggiato tv"),
        ("demoni <sceneggiato televisivo ; 1972>", "sceneggiato televisivo"),
        ("delitto e castigo <videoregistrazione ; 2007>", "videoregistrazione"),
        ("rosa dei nomi <documentario ; 1987>", "documentario"),
        ("quiproquo <interviste>", None), ("arte programmata <mostra ; 1962 ; trieste>", None),
        ("suites <versione per orchestra>, op. 145a", None)])
    def test_the_media_sbn_names(self, label, medium):
        assert authors.medium_of(label) == medium

    def test_editions_and_untyped_items_are_not_works(self):
        edition = {**ITEM, "qid": "Q126712481", "edition": True}
        article = {**ITEM, "qid": "Q9", "typed": False}
        assert authors.rows([], [edition, article], [])["rows"] == []

    def test_a_wikidata_work_sbn_does_not_hold_is_a_row(self):
        (row,) = authors.rows([], [{**ITEM, "original_title": None}], [])["rows"]
        assert row.title == "Steps to an Ecology of Mind" and row.main_author

    def test_two_uniform_titles_join_one_work(self):
        spu = [{"value": v, "rows": []} for v in ("suputoniku no koibito", "sputoniku no koibito.")]
        item = {"qid": "Q1", "typed": True, "forms": ["Suputoniku no koibito"], "year": 1999}
        (row,) = authors.rows(spu, [item], [])["rows"]
        assert row.uniform_titles == ["suputoniku no koibito", "sputoniku no koibito."]

    def test_a_tie_joins_neither(self):
        a = {"qid": "Q1", "typed": True, "forms": ["Communication"]}
        b = {"qid": "Q2", "typed": True, "forms": ["Communication"]}
        doc = {"key": "OL1W", "title": "Communication"}
        got = authors.rows([], [a, b], [doc])
        assert got["band"] == [doc]

    # Decision AZ. Forms abridged from `wikidata.item_forms(wikipedias_only=True)`
    # and records from `list_works`, both on the regress cache, 2026-09-30.
    WHITE_NIGHTS = {"qid": "Q600461", "typed": True,
                    "forms": ["Weiße Nächte", "White Nights", "Le notti bianche"]}
    WHITE_NIGHTS_AGAIN = {"qid": "Q60714471", "typed": True, "forms": ["White Nights"]}
    BELYE = {"value": "belye noci", "rows": [
        {"id": "ITICCUUBO4748344", "author": "Dostoevskij, Fëdor Mihajlovič",
         "title": "White Nights / Fyodor Dostoyevsky ; translated by Ronald Meyer"}]}

    def test_a_tie_between_one_work_held_twice_joins_its_main_item(self):
        got = authors.rows([self.BELYE], [self.WHITE_NIGHTS, self.WHITE_NIGHTS_AGAIN], [],
                           ["Dostoevskij, Fëdor Mihajlovič"])["rows"]
        assert {r.key: r.uniform_titles for r in got} == {"Q600461": ["belye noci"],
                                                          "Q60714471": []}

    def test_a_part_and_its_whole_are_not_one_work(self):
        novel = {"qid": "Q22263533", "typed": True, "part_of": ["Q22981812"],
                 "forms": ["My Brilliant Friend", "L'amica geniale"]}
        series = {"qid": "Q22981812", "typed": True,
                  "forms": ["Neapolitan Novels", "L'amica geniale"]}
        sbn = [{"value": "amica geniale : infanzia, adolescenza", "rows": []}]
        got = authors.rows(sbn, [novel, series], [])["rows"]
        assert "sbn:amica geniale : infanzia, adolescenza" in {r.key for r in got}

    def test_a_tie_between_two_works_still_joins_neither(self):
        postille = {"qid": "Q135409498", "typed": True,
                    "forms": ["Postscript to The name of the rose",
                              "Postille a «Il nome della rosa»"]}
        rosa = {"qid": "Q172850", "typed": True,
                "forms": ["The Name of the Rose", "Il nome della rosa"]}
        sbn = [{"value": "postille a il nome della rosa",
                "rows": [{"id": "ITICCUTO00851756", "author": "Eco, Umberto",
                          "title": "Il nome della rosa"}]}]
        got = authors.rows(sbn, [postille, rosa], [])["rows"]
        assert "sbn:postille a il nome della rosa" in {r.key for r in got}

    def test_nothing_to_join_to(self):
        assert authors.rows([], [], [{"key": "OL1W", "title": "Men are grass"}])["band"]

    def test_a_row_with_no_year_sorts_last(self):
        dated = WorkRow("b", "B", original_year=1990)
        undated = WorkRow("a", "A")
        older = WorkRow("c", "C", sbn_years=[1950])
        assert authors.sort_rows([undated, older, dated]) == [dated, older, undated]
        assert undated.year_kind is None

    def test_the_display_title_falls_back(self):
        near = WorkRow("k", "", uniform_titles=["mind and nature : a necessary unity"],
                       titles=["mind and nature : a necessary unity",
                               "Mind and nature : a necessary unity"])
        assert authors._display_title(near) == "Mind and nature : a necessary unity"
        far = WorkRow("k", "", uniform_titles=["noruwei no mori"],
                      titles=["noruwei no mori", "Tokyo blues"])
        assert authors._display_title(far) == "Noruwei no mori"
        assert authors._display_title(WorkRow("k", "", titles=["Naven"])) == "Naven"
        assert authors._display_title(WorkRow("k", "")) == "k"

    def test_the_click_sends_a_latin_title(self):
        murakami = WorkRow("Q1", "海辺のカフカ", original_title="海辺のカフカ",
                           uniform_titles=["umibe no kafuka"])
        assert authors.lookup_title(murakami) == "umibe no kafuka"
        only = WorkRow("Q2", "海辺のカフカ", original_title="海辺のカフカ")
        assert authors.lookup_title(only) == "海辺のカフカ"
        shown = authors.view([murakami], [], [])["contributed"][0]
        assert shown["lookup"] == {"title": "umibe no kafuka", "author": "", "variants": []}

    def test_the_view_carries_the_band(self):
        doc = {"key": "OL486410W", "title": "Men are grass", "year": 1980,
               "edition_count": 1, "languages": ["eng"]}
        assert authors.view([], [doc], ["Gregory Bateson"])["band"] == [
            {"key": "OL486410W", "title": "Men are grass", "year": 1980, "editions": 1,
             "languages": ["eng"]}]


class TestOpenLibraryDocs:

    def test_by_key(self):
        assert authors.doc_is_by({"author_keys": ["/authors/OL1A"]}, [], ["/authors/OL1A"])

    def test_by_name_in_another_romanisation(self):
        assert authors.doc_is_by({"authors": ["Fyodor Dostoevsky"]},
                                 ["Fëdor Mihajlovič Dostoevskij"], [])

    def test_a_coauthor_alone_is_not_the_person(self):
        assert not authors.doc_is_by({"authors": ["Margaret Mead"]}, ["Gregory Bateson"], [])


class TestNotes:

    def test_a_whole_list_says_nothing(self):
        assert notes.author_truncations({"sbn": [{"total": 134, "covered": 134}]}) == []

    def test_what_no_split_covered_is_a_count(self):
        lines = notes.author_truncations({
            "sbn": [{"name": "Umberto Eco", "total": 2575, "covered": 2300, "split": True,
                     "languages_capped": True, "capped_leaves": ["ita 1990"]}],
            "wikidata": {"read": 500, "total": 612},
            "open_library": {"read": 20, "total": 20}, "years_capped": 2})
        assert lines[0].startswith("SBN names at most 50 languages for Umberto Eco")
        assert "at least 275 of 2,575 records fell in no answer" in lines[1]
        assert lines[2] == "1 of those questions still stopped at 50 works (ita 1990)"
        assert lines[3] == "read 500 of 612 Wikidata works naming this person"
        assert lines[4].startswith("2 works have SBN editions in more than 50 years")

    def test_one_work_with_many_years(self):
        (line,) = notes.author_truncations({"years_capped": 1, "sbn": [{}]})
        assert line.startswith("1 work has SBN editions")


@pytest.mark.parametrize("label,clean", [
    ("angels fear : towards an epistemology of the sacred. -",
     "angels fear : towards an epistemology of the sacred"),
    ("drive my car <film ; 2021>", "drive my car"),
    ("", "")])
def test_clean_label(label, clean):
    assert authors.clean_label(label) == clean


@pytest.mark.parametrize("a,b", [
    ("Steps to an Ecology of Mind", "steps to an ecology of mind"),
    ("Angels fear : towards an epistemology", "Angels fear"),
    ("海辺のカフカ", "海辺のカフカ"), ("海辺のカフカ", "Kafka on the shore"),
    ("Доктор Живаго", "doktor zivago"), ("Naven", ""), ("", ""),
    ("Il nome della rosa", "Postille a Il nome della rosa"),
])
def test_the_join_scores_as_the_gate_does(a, b):
    """The memoised join is a speed-up, never a second scorer."""
    from core.text import similarity
    assert authors._similar(a, b) == similarity(a, b)


def test_the_lookup_carries_the_other_spellings():
    """N17: SBN files *Bayn al-Qasrayn* under three romanisations, and the
    Wikidata item knows it by its translations too; all go with the click."""
    row = WorkRow("Q3149381", "بين القصرين", original_title="بين القصرين",
                  uniform_titles=["bain el-qasrain.", "bayan al-qasrayn", "bayn al-qasrayn"],
                  item_forms=["Palace Walk", "بين القصرين", "bayn al-qasrayn"])
    assert authors.lookup_title(row) == "bain el-qasrain"
    assert authors.lookup_variants(row) == ["bayan al-qasrayn", "bayn al-qasrayn",
                                            "Palace Walk"]


class TestTickedByWikidatasForm:
    """Step 15B. *Garcia Marquez* typed alone is Gabriel, Eligio and Vicente in
    SBN; only Gabriel is also reached by Wikidata's alias *Gabriel García
    Márquez*. Headings and ids from the live `core=autori` answers."""

    GABRIEL = {"id": "CFIV002730", "heading": "García Márquez , Gabriel", "kind": "Persona"}
    ELIGIO = {"id": "TO0V578023", "heading": "García Márquez , Eligio", "kind": "Persona"}

    def test_the_one_person_an_alias_also_reaches_is_ticked_not_skipped(self):
        got = authors.candidates([{"form": "Garcia Marquez", "rows": [self.GABRIEL, self.ELIGIO],
                             "total": 2},
                            {"form": "Gabriel García Márquez", "rows": [self.GABRIEL],
                             "total": 1}], "Garcia Marquez")
        assert got["resolved"] == "CFIV002730" and not got["skip"]

    def test_no_alias_answer_ticks_nobody(self):
        got = authors.candidates([{"form": "Garcia Marquez", "rows": [self.GABRIEL, self.ELIGIO],
                             "total": 2}], "Garcia Marquez")
        assert got["resolved"] is None


class TestUnlinked:
    """Decision AN: the records under the name that no work here names. Rows
    verbatim from `records_by_authority('CFIV034892')`, 2026-09-27."""

    VERSO = {"id": "RAV0017793", "title": "Verso un'ecologia della mente / Gregory Bateson",
             "author": "Bateson, Gregory", "year": "1987"}
    VERSO_2 = {"id": "LIA0578364", "title": "Verso un'ecologia della mente / Gregory Bateson",
               "author": "Bateson, Gregory", "year": "1998"}
    BALINESE = {"id": "RMS2809373", "title": "Balinese character : a photographic analysis "
                "/ by Gregory Bateson and Margaret Mead", "author": "Bateson, Gregory",
                "year": "1962"}
    POLIDORI = {"id": "NAP0992209", "title": "Ipotesi sull'umorismo / Fabio Polidori",
                "author": "Polidori, Fabio", "year": None}
    NOUVELLE = {"id": "TO01351294", "title": "La nouvelle communication / G. Bateson ... "
                "[et al.] ; textes recueillis et présentés par Yves Winkin ; traduction "
                "de D. Bansard ... [et al.]", "author": None, "year": "1984"}
    STEPS = WorkRow("sbn:steps to an ecology of mind", "Steps to an ecology of mind",
                    titles=["steps to an ecology of mind", "Steps to an ecology of mind"])

    def _unlinked(self, records, linked=()):
        return authors.unlinked(records, [self.STEPS], linked, ["Bateson, Gregory"])

    def test_a_record_a_work_listed_is_left_out(self):
        assert self._unlinked([self.VERSO], linked=["RAV0017793"]) == []

    def test_what_no_work_names_is_one_row_per_title_newest_first(self):
        out = self._unlinked([self.BALINESE, self.NOUVELLE, self.POLIDORI])
        assert [u["title"] for u in out] == ["La nouvelle communication",
                                             "Balinese character : a photographic analysis",
                                             "Ipotesi sull'umorismo"]
        assert out[1] == {"title": "Balinese character : a photographic analysis",
                          "records": ["RMS2809373"], "first_year": 1962, "last_year": 1962,
                          "credited_to": [], "year_note": None}

    def test_somebody_else_s_heading_is_named(self):
        assert self._unlinked([self.POLIDORI])[0]["credited_to"] == ["Fabio Polidori"]

    def test_printings_of_one_title_are_one_row(self):
        out = self._unlinked([self.VERSO, self.VERSO_2])
        assert len(out) == 1 and out[0]["records"] == ["RAV0017793", "LIA0578364"]
        assert (out[0]["first_year"], out[0]["last_year"]) == (1987, 1998)

    def test_a_title_joining_a_work_row_is_that_work_s(self):
        steps = {"id": "X1", "title": "Steps to an ecology of mind / Gregory Bateson",
                 "author": "Bateson, Gregory", "year": "1972"}
        assert self._unlinked([steps]) == []

    def test_a_title_tying_two_work_rows_is_still_a_work_s(self):
        """BACKLOG, cap probe 2026-09-29: *Le notti bianche* joins SBN's
        `belye noci` and Wikidata's Q600461 equally, so `_best` names neither
        and its 88 records stayed a book of their own. Rows, titles abridged,
        and the record from `list_works` over Dostoevskij, 2026-09-29."""
        belye = WorkRow("sbn:belye noci", "Belye noci",
                        titles=["belye noci", "Le notti bianche", "White Nights"])
        q600461 = WorkRow("Q600461", "Белые ночи",
                          titles=["White Nights", "Le notti bianche", "Белые ночи"])
        q60714471 = WorkRow("Q60714471", "White Nights", titles=["White Nights"])
        rec = {"id": "ITICCUMOD0852753", "title": "Le notti bianche / Fjodor Dostojevskij ; "
               "prafaziione di A. M. Ripellino ; traduzione di Vittoria de Gavardo",
               "author": "Dostoevskij, Fëdor Mihajlovič", "year": "1960"}
        rows_ = [belye, q600461, q60714471]
        assert authors._best(["Le notti bianche"], {r.key: r.titles for r in rows_}) is None
        assert authors.unlinked([rec], rows_, (), ["Dostoevskij, Fëdor Mihajlovič"]) == []

    def test_a_row_with_no_title_is_left_out(self):
        assert self._unlinked([{"id": "X2", "title": "", "author": None, "year": None}]) == []

    def test_a_settled_year_and_its_note_are_the_group_s(self):
        """Decision AY: the year is the one `core.dates` settled, and a group
        with any record not taken as written says so, as an edition row does.
        Shamlu's records, from decision AY's year probe."""
        def settled(bid, date, indexed):
            return dates.settled(Record(source="SBN", id=bid, date=date, date_indexed=indexed,
                                        provenance=Provenance("SBN", AUTHOR_SWEEP,
                                                              AUTHOR_SWEEP)), 2026)
        inferred = settled("RMB0775153", "1388 [2010]", ["2010"])
        unsure = settled("RMB0799787", "1376 [1997 o 1998]", ["1998"])
        out = self._unlinked([
            {"id": "RMB0775153", "title": "Az zakhm-e ghalb / Ahmad Shamlu",
             "author": None, "year": inferred.year, "record": inferred},
            {"id": "RMB0799787", "title": "Shazadeh-e kuchulu / Antoine de Saint-Exupery",
             "author": None, "year": unsure.year, "record": unsure}])
        zakhm, kucah = out
        assert (zakhm["first_year"], zakhm["year_note"]["label"]) == (2010, "year inferred")
        assert kucah["first_year"] is None
        assert kucah["year_note"]["label"] == "year unsure"
        assert kucah["year_note"]["shown"] == "1376 / 1997 / 1998"


class TestUnlinkedTruncation:
    def test_a_capped_date_check_is_a_line(self):
        ev = {"dates": {"rows": 412, "checked": 300, "truncated": True}}
        assert notes.author_truncations(ev) == [
            "dates were checked with SBN for 300 of 412 records filed under no work "
            "whose year is not plain; the rest are labelled year unsure"]

    def test_a_capped_read_is_a_line(self):
        ev = {"unlinked": {"read": [{"id": "CFIV...", "total": 2575, "read": 500,
                                     "truncated": True}]}}
        assert notes.author_truncations(ev) == [
            "read 500 of 2,575 records under this name, so a book held only by the "
            "rest is not among those filed under no work"]

    def test_a_whole_read_says_nothing(self):
        ev = {"unlinked": {"read": [{"id": "x", "total": 134, "read": 134,
                                     "truncated": False}]}}
        assert notes.author_truncations(ev) == []
