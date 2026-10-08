"""`catalog/sbn_opac.py` — reading a listing row, and the three traps in one.

Every literal here is a real OPAC row, copied from a live
`titles-search-full-post` body for `{core: sbn, AUTHOR, titolo_uniformef[]}`
(*Nineteen Eighty-Four* + Orwell, *Umibe no Kafuka* + Murakami, *Bruits* +
Attali). None of it is invented: `infos` is positional and the exceptions are
exactly the point.

Three things a row is read for and one it is not:

* **`title.info` is the catalogued title with its statement of responsibility**
  and **`title.text` is the main author heading** — not the responsibility,
  which is what this module's docstring said until a hundred rows were read.
* **`infos[0]` is the imprint on 2,577 of 2,603 rows and something else on 26**
  (`docs/sbn-api.md` trap 10), so it is recognised rather than trusted.
* **`infos` also carries the record type**, `Testo - Monografia [IT\\ICCU\\…]`,
  which is the same vocabulary the full record's `tipo` uses — so a row can be
  told from an audiobook without a second request.
* It is **not** read for an ISBN, a Dewey class, holdings or a named translator:
  a row has none of them (F5), and S4's full record is where they come from.
"""

import pytest

from catalog import langs, sbn_opac as opac

# One page of the *Nineteen Eighty-Four* listing, verbatim.
ORWELL_ROWS = {
    "results": [
        {"id": "ITICCUVIA0214939",
         "title": {"info": "George Orwell: Nineteen eighty-four / notes by Robert Welch",
                   "text": "Orwell, George"},
         "infos": ["Harlow : Longman ; Beirut : York Press, 1983",
                   "Testo - Monografia [IT\\ICCU\\VIA\\0214939] "],
         "type": "text"},
        {"id": "ITICCUTO10037839",
         "title": {"info": "Nineteen eighty-four / George Orwell ; retold by Fiona "
                           "Mackenzie ; series editor: Sorrel Pitts",
                   "text": "MacKenzie, Fiona"},
         "infos": ["London : Penguin books, 2020",
                   "Testo - Monografia [IT\\ICCU\\TO1\\0037839] "],
         "type": "text"},
        {"id": "ITICCURMS1138995",
         "title": {"info": "1984 / George Orwell", "text": "Orwell, George"},
         "infos": ["12. rist", "Testo - Monografia [IT\\ICCU\\RMS\\1138995] "],
         "type": "text"},
        {"id": "ITICCUPUV1569110",
         "title": {"info": "1984 / George Orwell", "text": "Orwell, George"},
         "infos": ["Testo - Monografia [IT\\ICCU\\PUV\\1569110] "],
         "type": "text"},
        {"id": "ITICCULIA0173444",
         "title": {"info": "1984 / George Orwell", "text": "Orwell, George"},
         "infos": ["Milano :A. Mondadori, stampa 1976",
                   "Testo - Monografia [IT\\ICCU\\LIA\\0173444] "],
         "type": "text"},
    ],
    "total": 173,
}

# UBO4636099 and the Feltre audiobook, from the *Umibe no Kafuka* listing.
KAFKA_ROWS = {
    "results": [
        {"id": "ITICCUUBO4636099",
         "title": {"info": "Kafka on the shore / Haruki Murakami ; translated from "
                           "the Japanese by Philip Gabriel",
                   "text": "Murakami, Haruki"},
         "infos": ["London : Vintage, 2005",
                   "Testo - Monografia [IT\\ICCU\\UBO\\4636099] "],
         "type": "text"},
        {"id": "ITICCUUBO4414630",
         "title": {"info": "Kafka sulla spiaggia / Murakami Haruki ; legge Vincenzo "
                           "Liguori", "text": "Murakami, Haruki"},
         "infos": ["Feltre : Centro Internazionale del Libro Parlato, 2019",
                   "Registrazione sonora non musicale - Monografia "
                   "[IT\\ICCU\\UBO\\4414630] "],
         "type": "audio"},
    ],
    "total": 20,
}


# Step 15B's live cache, the OPAC's answer for *Delitto e castigo* +
# Dostoevskij (Step 15B): one volume of Carabba's 1922 set, verbatim.
VOLUME_ROWS = {
    "results": [
        {"id": "ITICCURAV1944722",
         "title": {"text": "",
                   "info": "{Delitto e castigo : romanzo}2 / di Fjòdor Dostojevskij"},
         "infos": ["Lanciano : G. Carabba, [1922]", "Fa parte di: Delitto e castigo : romanzo",
                   "Testo - Monografia [IT\\ICCU\\RAV\\1944722] "],
         "type": "text"},
    ]
}


def by_id(rows):
    return {r["id"]: r for r in rows}


class TestParseRows:
    def test_the_bid_loses_its_iticcu_prefix(self):
        rows = opac.parse_rows(ORWELL_ROWS)
        assert [r["id"] for r in rows][:2] == ["VIA0214939", "TO10037839"]

    def test_title_info_is_the_title_and_title_text_is_the_main_author(self):
        row = by_id(opac.parse_rows(ORWELL_ROWS))["TO10037839"]
        assert row["title"].startswith("Nineteen eighty-four / George Orwell")
        assert row["author"] == "MacKenzie, Fiona"

    def test_the_language_is_the_page_the_row_came_back_on(self):
        """A row carries no language of its own. The `lingua[]` page it was
        fetched with is the language, which is what makes a listing enough."""
        rows = opac.parse_rows(ORWELL_ROWS, language="eng")
        assert {r["language"] for r in rows} == {"eng"}

    def test_a_row_whose_id_is_not_a_bid_is_dropped(self):
        assert opac.parse_rows({"results": [{"id": "not a bid"}]}) == []

    def test_a_title_that_is_a_bare_string_is_still_read(self):
        rows = opac.parse_rows({"results": [{"id": "ITICCUVIA0214939",
                                             "title": "Plain title"}]})
        assert rows[0]["title"] == "Plain title" and rows[0]["author"] is None


class TestImprintOf:
    def test_the_usual_row_has_it_first(self):
        assert opac.imprint_of(["Harlow : Longman ; Beirut : York Press, 1983",
                                "Testo - Monografia [IT\\ICCU\\VIA\\0214939] "]) \
            == "Harlow : Longman ; Beirut : York Press, 1983"

    @pytest.mark.parametrize("first", ["12. rist", "533 p", "3. ed"])
    def test_an_extent_or_edition_statement_is_not_an_imprint(self, first):
        """26 of 2,603 rows put one of these in `infos[0]`. Trusted, they
        publish `12. rist` as the publisher."""
        assert opac.imprint_of([first, "Testo - Monografia [IT\\ICCU\\RMS\\1138995] "]) is None

    @pytest.mark.parametrize("first", ["121 p. : ill. ; 24 cm", "1 DVD (89 min. ca) : color",
                                       "[316 p. compl.] ((Relazioni/comunicazioni distribuite "
                                       "al convegno, Roma 5-6 ottobre 1995"])
    def test_an_extent_with_a_colon_or_a_year_is_not_an_imprint(self, first):
        """The colon or year test alone took these: 35 of 29,164 rows' `infos`."""
        assert opac.imprint_of([first, "Testo - Monografia [IT\\ICCU\\RLZ\\0026655] "]) is None

    def test_a_row_with_only_the_record_type_has_no_imprint(self):
        assert opac.imprint_of(["Testo - Monografia [IT\\ICCU\\PUV\\1569110] "]) is None

    def test_a_host_record_reference_is_not_an_imprint(self):
        assert opac.imprint_of(["Fa parte di: Romanzi e saggi",
                                "Testo - Monografia [IT\\ICCU\\TO0\\2081267] "]) is None

    def test_an_imprint_missing_its_space_after_the_colon_is_still_one(self):
        assert opac.imprint_of(["Milano :A. Mondadori, stampa 1976"]) \
            == "Milano :A. Mondadori, stampa 1976"

    def test_an_imprint_with_no_year_is_still_one(self):
        assert opac.imprint_of(["Milano : Adelphi"]) == "Milano : Adelphi"

    def test_it_looks_past_a_bad_first_element(self):
        assert opac.imprint_of(["3. ed", "Torino : Einaudi, 1958"]) \
            == "Torino : Einaudi, 1958"

    def test_nothing_in_is_nothing_out(self):
        assert opac.imprint_of([]) is None and opac.imprint_of(None) is None


class TestRecordTypeOf:
    def test_it_reads_the_medium_and_the_level(self):
        assert opac.record_type_of(["London : Vintage, 2005",
                                    "Testo - Monografia [IT\\ICCU\\UBO\\4636099] "]) \
            == ("Testo", "Monografia")

    def test_an_audiobook_says_so(self):
        assert opac.record_type_of(
            ["Feltre : Centro Internazionale del Libro Parlato, 2019",
             "Registrazione sonora non musicale - Monografia [IT\\ICCU\\UBO\\4414630] "]) \
            == ("Registrazione sonora non musicale", "Monografia")

    def test_a_row_without_one_answers_with_neither(self):
        assert opac.record_type_of(["Milano : Adelphi, 1985"]) == (None, None)

    def test_it_does_not_separate_a_study_guide_from_an_edition(self):
        """F16, stated as a test: every one of the three known non-editions is
        `Testo - Monografia`, so the medium cannot be the filter."""
        rows = by_id(opac.parse_rows(ORWELL_ROWS))
        assert rows["VIA0214939"]["medium"] == rows["TO10037839"]["medium"] == "Testo"


class TestListingRecord:
    def test_a_row_becomes_the_fields_a_record_is_built_from(self):
        row = by_id(opac.parse_rows(ORWELL_ROWS, language="eng"))["VIA0214939"]
        rec = opac.listing_record(row)
        assert rec["source"] == "SBN"
        assert rec["id"] == "VIA0214939"
        assert rec["title"] == "George Orwell: Nineteen eighty-four"
        assert rec["year"] == "1983"
        assert rec["language"] == "eng"
        assert rec["url"] == "https://opac.sbn.it/bid/VIA0214939"
        assert rec["authors"] == ["Orwell, George"]
        assert rec["medium"] == "testo"

    def test_a_volume_of_a_set_is_titled_the_isbd_way(self):
        row = by_id(opac.parse_rows(VOLUME_ROWS))["RAV1944722"]
        assert opac.listing_record(row)["title"] == "Delitto e castigo : romanzo. 2"

    def test_volume_title_leaves_any_other_title_alone(self):
        assert opac.volume_title("{Delitto e castigo}") == "Delitto e castigo"
        assert opac.volume_title("Kafka on the shore") == "Kafka on the shore"

    def test_the_publisher_keeps_its_place(self):
        row = by_id(opac.parse_rows(ORWELL_ROWS))["TO10037839"]
        assert opac.listing_record(row)["publisher"] == "Penguin books, London"
        assert opac.listing_record(row)["places"] == ["London"]

    def test_the_isbd_statement_is_split_into_publishers(self):
        row = by_id(opac.parse_rows(ORWELL_ROWS))["VIA0214939"]
        assert opac.listing_record(row)["publisher_names"] == ["Longman", "York Press"]

    def test_a_row_with_no_usable_imprint_states_no_publisher_and_no_year(self):
        row = by_id(opac.parse_rows(ORWELL_ROWS))["RMS1138995"]
        rec = opac.listing_record(row)
        assert rec["publisher"] is None and rec["year"] is None

    def test_the_translation_evidence_of_ubo4636099_survives_into_the_record(self):
        """The one trace this record has of being a translation is in the half
        of the title `title_of` cuts away. Without it,
        `language_contradicts_itself` has nothing to fire on and an English
        printing stays filed as Japanese."""
        row = by_id(opac.parse_rows(KAFKA_ROWS, language="jpn"))["UBO4636099"]
        rec = opac.listing_record(row)
        assert rec["title"] == "Kafka on the shore"
        assert rec["evidence"] == ["Haruki Murakami ; translated from the Japanese "
                                   "by Philip Gabriel"]
        assert rec["language"] == "jpn"

    def test_an_ordinary_row_carries_no_translation_evidence(self):
        row = by_id(opac.parse_rows(ORWELL_ROWS))["LIA0173444"]
        assert opac.listing_record(row)["evidence"] == []

    def test_an_audiobook_keeps_its_medium(self):
        row = by_id(opac.parse_rows(KAFKA_ROWS, language="ita"))["UBO4414630"]
        assert opac.listing_record(row)["medium"] == "registrazione sonora non musicale"

    def test_a_language_the_facet_does_not_record_stays_unknown(self):
        """SBN's own `lingua[]` facet returns `und`, `mis` and `zxx`. They mean
        'not recorded' and must not become a language."""
        row = by_id(opac.parse_rows(ORWELL_ROWS, language="und"))["LIA0173444"]
        assert opac.listing_record(row)["language"] == langs.UNKNOWN


class TestTheListingQueryRefusesWhatWouldAnswerWrongly:
    def test_a_work_query_without_an_author_raises_rather_than_asking(self):
        """`CLAUDE.md` rule 3. Bare *Rumori* returns Russolo — it answers, and
        the answer is a different book."""
        with pytest.raises(ValueError):
            opac.work_records("bruits", "")
        with pytest.raises(ValueError):
            opac.work_languages("bruits", "")

    def test_a_parameter_outside_the_whitelist_is_refused_not_filtered(self):
        """An unknown key is not an error at the OPAC: it is the *unfiltered*
        result set (`CLAUDE.md` rule 2)."""
        with pytest.raises(ValueError):
            opac.post({"core": "sbn", "lingua": "ita"})
