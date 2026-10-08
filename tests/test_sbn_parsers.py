"""`catalog/sbn_mobile.py` — the parsers, and the data traps of `docs/sbn-api.md`.

Every literal in this file was taken from a real body among the 2,707 recorded
catalogue responses (778 of them are `tests/data/fixtures/`) or quoted verbatim
from `docs/sbn-api.md`.
None of it is invented: the traps are counter-intuitive enough that a plausible
made-up example tests the wrong thing.
"""

import pytest

from catalog import langs, sbn_mobile
from catalog import sbn_mobile as sbn
from catalog.http import SourceError
from catalog.sbn_mobile import title_of as sbn_title_of
from core.identity import has_translation_evidence, is_book_medium
from core.model import REFUSED, WORK_LISTING, Provenance, Record
from lookup.stages import full_fields


def to_record(rec: dict) -> Record:
    """A full SBN record the way the product builds one: the parser's plain
    fields, then the dataclass (`lookup.stages.full_fields`)."""
    return Record(**full_fields(sbn.parse_record(rec)),
                  provenance=Provenance("SBN", WORK_LISTING, REFUSED))


class TestCleanText:
    def test_strips_the_c1_non_sorting_article_markers(self):
        r"""SBN wraps non-sorting articles in \x88 … \x89 — invisible markup.

        331 titles in the fixture bundle carry them.
        """
        assert sbn.clean_text("\x88L'\x89étranger / Albert Camus") == "L'étranger / Albert Camus"
        assert sbn.clean_text("\x88The \x89stranger") == "The stranger"
        assert sbn.clean_text("\x88Il \x89disoriente") == "Il disoriente"

    def test_the_cleaned_title_still_cuts_at_the_responsibility(self):
        raw = "\x88L'\x89étranger / Albert Camus"
        assert sbn_title_of(sbn.clean_text(raw)) == "L'étranger"

    def test_collapses_whitespace(self):
        assert sbn.clean_text("Cent'anni   di\tsolitudine ") == "Cent'anni di solitudine"

    def test_empty_becomes_none(self):
        assert sbn.clean_text("") is None
        assert sbn.clean_text(None) is None
        assert sbn.clean_text("   ") is None


class TestShortBid:
    @pytest.mark.parametrize("codice,expected", [
        ("IT\\ICCU\\MIL\\0871878", "MIL0871878"),
        ("IT/ICCU/UBO/4636099", "UBO4636099"),     # the Kafka record of trap 1b
        ("IT\\ICCU\\CFI\\1172094", "CFI1172094"),  # the Pesaro '1984' of trap 1
        ("MIL0871878", "MIL0871878"),
        (None, None),
        ("", None),
    ])
    def test_permalink_form(self, codice, expected):
        assert sbn.short_bid(codice) == expected


class TestParseLabelled:
    def test_splits_the_label_from_the_value(self):
        items = ["[Autore]  García Márquez, Gabriel", "[Traduttore]  Manferlotti, Stefano"]
        assert sbn.parse_labelled(items) == [
            ("Autore", "García Márquez, Gabriel"),
            ("Traduttore", "Manferlotti, Stefano"),
        ]

    def test_an_unlabelled_item_keeps_an_empty_label(self):
        assert sbn.parse_labelled(["Attali, Jacques"]) == [("", "Attali, Jacques")]

    def test_empty(self):
        assert sbn.parse_labelled([]) == []
        assert sbn.parse_labelled(None) == []


class TestParsePublication:
    @pytest.mark.parametrize("raw,expected", [
        # `docs/sbn-api.md`: SBN marks supplied/uncertain data with \…! and […].
        ("Milano : Adelphi, \\1976!", ("Adelphi", "1976", "Milano")),
        ("Torino : Einaudi, \\1996!", ("Einaudi", "1996", "Torino")),
        ("\\Bergamo! : Euroclub, 1985", ("Euroclub", "1985", "Bergamo")),
        ("[Paris! : Gallimard, 1986", ("Gallimard", "1986", "Paris")),
        ("[Paris! : Gallimard, stampa 1994", ("Gallimard", "1994", "Paris")),
        ("[Bergamo! : Euroclub, 1983, stampa 1989)", ("Euroclub", "1983", "Bergamo")),
        ("Milano : Mazzotta, c1978, (stampa 1977)", ("Mazzotta", "1978", "Milano")),
        ("Novara : Mondadori-De Agostini, \\1999!", ("Mondadori-De Agostini", "1999", "Novara")),
        ("Firenze ; Milano : Giunti, 2018", ("Giunti", "2018", "Firenze ; Milano")),
    ])
    def test_real_bundle_values(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    def test_a_record_with_no_date_yields_no_year(self):
        """'s. d.' is sine data — no date. The year is correctly None, and the
        marker is not left glued to the publisher (Step 12: 13 of 11,333
        publisher strings carried it)."""
        publisher, year, place = sbn.parse_publication("Athena : Libane, \\s. d.!")
        assert year is None
        assert place == "Athena"
        assert publisher == "Libane"

    def test_a_publisher_ending_in_the_letters_sd_is_not_cut(self):
        assert sbn.parse_publication("Roma : Edizioni Isd, 1990")[0] == "Edizioni Isd"

    @pytest.mark.parametrize("raw,expected", [
        # The words before a supplied year open the date; they were read as
        # the end of the publisher. Every form the 16,143 imprints hold.
        (", [tra il 1970 e il 1990]", (None, "1970", None)),
        (", [dal 1970 al 1990]", (None, "1970", None)),
        ("Al Qahira : Maktabat Misr, [tra il 1900 e il 1999]",
         ("Maktabat Misr", "1900", "Al Qahira")),
        ("Milano : Bietti, [tra 1920 e 1930]", ("Bietti", "1920", "Milano")),
        ("Berlin : Th. Knaur, [dopo il 1920]", ("Th. Knaur", "1920", "Berlin")),
        ("Leipzig : P. Reclam, [dopo 1880]", ("P. Reclam", "1880", "Leipzig")),
        ("Milano : Rizzoli, \\dopo il 1959!", ("Rizzoli", "1959", "Milano")),
        ("Paris : Hachette, <dopo il 1880>", ("Hachette", "1880", "Paris")),
        ("Lipsiae : ex officina Car. Tauchnitii, [prima del 1833]",
         ("ex officina Car. Tauchnitii", "1833", "Lipsiae")),
        ("[S.l. : s.n., non prima del 1832]", ("s.n.", "1832", "S.l.")),
        ("Ann Arbor, Michigan : Ardis, [ca. 1976]", ("Ardis", "1976", "Ann Arbor, Michigan")),
        ("Milano : C. Cioffi, [ca 1860]", ("C. Cioffi", "1860", "Milano")),
        ("Burbank CA : Warner Bros. Records, [circa 2015]",
         ("Warner Bros. Records", "2015", "Burbank CA")),
        ("Torino : Einaudi, [post. 1996]", ("Einaudi", "1996", "Torino")),
        ("Torino : S.A.S., [post 1948]", ("S.A.S.", "1948", "Torino")),
        # The same leak with no date word: `<` was left on 10 publishers.
        ("Milano : A.Mondadori, <1993>", ("A.Mondadori", "1993", "Milano")),
        ("Paris : Gallimard, <1940?>", ("Gallimard", "1940", "Paris")),
    ])
    def test_a_date_qualifier_is_not_part_of_the_publisher(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        # A year in a calendar whose numbers the year search does not take,
        # before the Gregorian one: it was left on the publisher. Real
        # imprints, 2026-09-30; the year was right all along.
        ("Yerushalaim : Hozahat ha-sepharim a. sh. Y. L. Magnes, ha-Universitah "
         "ha-Ivrit, c5760 [i.e. 1999/00]",
         ("Hozahat ha-sepharim a. sh. Y. L. Magnes, ha-Universitah ha-Ivrit", "1999",
          "Yerushalaim")),
        ("Yrẇšalayim : [Šŵqen], [5]718-[5]719 [1959]", ("Šŵqen", "1959", "Yrẇšalayim")),
        ("Pressburg : Jakob Lemberger (gedruḳṭ bey Anton Edlen von Shmid), 599 [1839]",
         ("Jakob Lemberger (gedruḳṭ bey Anton Edlen von Shmid)", "1839", "Pressburg")),
        ("Bangkok : Bodthajorn, 2559 [2016]", ("Bodthajorn", "2016", "Bangkok")),
        ("al-Qāhirah : Maṭba‘at laǧnat al-ta’līf wa-al-tarǧamah wa-al-našr, 11353 h. 1935 m",
         ("Maṭba‘at laǧnat al-ta’līf wa-al-tarǧamah wa-al-našr", "1935", "al-Qāhirah")),
        # A number beside a word is a name.
        ("Ankara : 1001 Çiçek kitaplar, 2015", ("1001 Çiçek kitaplar", "2015", "Ankara")),
        ("Milano : 360 gradi, ©1997", ("360 gradi", "1997", "Milano")),
        ("Modugno : Grafica 080, 2009", ("Grafica 080", "2009", "Modugno")),
    ])
    def test_another_calendars_year_is_not_part_of_the_publisher(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        # A bracket before the year that holds a name, not a date word.
        ("[Los Angeles : Virgin records America, CA], 1997",
         ("Virgin records America, CA", "1997", "Los Angeles")),
        ("[S.l.] : [Luigi Russolo], [tra 1910 e 1914]", ("Luigi Russolo", "1910", "S.l.")),
        ("Udine : Del Bianco, [dopo il 1973]", ("Del Bianco", "1973", "Udine")),
    ])
    def test_a_name_that_looks_like_a_date_word_is_kept(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        # A colon without ISBD's spaces left the place on the publisher. Real
        # imprints, 2026-09-30.
        ("Barcelona: Plaza & Janes, 2000", ("Plaza & Janes", "2000", "Barcelona")),
        ("Milano :Adelphi, 2005", ("Adelphi", "2005", "Milano")),
        ("Baltimore: The Johns Hopkins University Press, c2013",
         ("The Johns Hopkins University Press", "2013", "Baltimore")),
        ("[Paris!: Gallimard, 1973", ("Gallimard", "1973", "Paris")),
        ("[S.l. :s.n., dopo 2010?]", ("s.n.", "2010", "S.l.")),
        ("A S. Vincent [i.e. Ginevra]: par Paul Marceau, 1607",
         ("par Paul Marceau", "1607", "A S. Vincent i.e. Ginevra")),
        # Only a year after the colon: what precedes it is the publisher.
        ("R. Piper & Co., München: 1980", ("R. Piper & Co., München", "1980", None)),
    ])
    def test_a_colon_without_spaces_still_ends_the_place(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        # A date known only to the decade or century was left on the
        # publisher. Real imprints, 2026-09-30; the year is None either way.
        ("Ann Arbor : Ardis, [19..]", ("Ardis", None, "Ann Arbor")),
        ("Baarn (NL) : Philips, 195.", ("Philips", None, "Baarn (NL)")),
        ("Al-Qahirah : Maktabat Misr, [198.?]", ("Maktabat Misr", None, "Al-Qahirah")),
        ("Breslau : Julius Hainauer, [18--?]", ("Julius Hainauer", None, "Breslau")),
        ("Pariz : Ymca Press, <196.>", ("Ymca Press", None, "Pariz")),
        ("Roma : Ciranna, ?19..?- .", ("Ciranna", None, "Roma")),
        ("Milano : FMR, [198.] (Milano : ColorBlack)", ("FMR", None, "Milano")),
        ("Torino : Einaudi, [197...] ; Edito-Service : Ginevra, [197...]",
         ("Einaudi ; Edito-Service : Ginevra", None, "Torino")),
        ("Leipzig : Insel-Verlag, 192", ("Insel-Verlag", None, "Leipzig")),
        ("[Venezia : copia], inizi 18. sec", ("copia", None, "Venezia")),
        ("[S.l. : autografo, 1. metà del 20. sec.]", ("autografo", None, "S.l.")),
        # A number in a name stays.
        ("[Venezia : Aldo Manuzio <1.> & Andrea Torresano <1.>]",
         ("Aldo Manuzio <1.> & Andrea Torresano <1.>", None, "Venezia")),
        ("Napoli : presso il cartajo, strada s. Biagio de' librai n.° 13",
         ("presso il cartajo, strada s. Biagio de' librai n.° 13", None, "Napoli")),
    ])
    def test_a_partial_date_is_not_part_of_the_publisher(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    @pytest.mark.parametrize("raw", [
        # An extent, a carrier or an edition statement where the imprint should
        # be. Real `pubblicazione` values, 2026-09-30.
        "157 p. ; 21 cm", "121 p. : ill. ; 24 cm", "xxxv, 191 p. ; 20 cm.", "[2]c. : 29 cm",
        "v. 2", "5 volumi", "1 DVD-video", "1 CD-ROM : son. ; 12 cm", "P. 133-141",
        "[162], 108, 54 p. : ill., 30 cm. (Catalogo della mostra tenuta a Kassel nel 1982",
        "18 ed", "12. rist", ", 226. ed", "1st U.S. ed", "2. ed. riveduta", "5. tirage",
        "Diciottesima edizione", "[Rev. ed.]", "\\Rist. anast.!",
        "Edizione terza. In cui si è aggiunta una nuova traduzione della Batracomiomachia",
    ])
    def test_an_extent_or_edition_statement_is_no_imprint(self, raw):
        assert sbn.parse_publication(raw) == (None, None, None)

    @pytest.mark.parametrize("raw,expected", [
        # An edition statement before the place was read as part of it.
        ("18. ed. Milano : Bompiani, 2002", ("Bompiani", "2002", "Milano")),
        ("4. ed. Roma-Bari : Laterza, 2004", ("Laterza", "2004", "Roma-Bari")),
        ("2° Ed. Milano : Feltrinelli, 2018", ("Feltrinelli", "2018", "Milano")),
        ("11. ed.- Madrid : Espasa calpe, 1990", ("Espasa calpe", "1990", "Madrid")),
        ("5. ed. -Bombay : Tukaram Jawaji, 1917", ("Tukaram Jawaji", "1917", "Bombay")),
        ("2. ed. riv. e accresciuta - Milano : V. Bompiani, 1970",
         ("V. Bompiani", "1970", "Milano")),
        ("[4. ed.] - [Roma ; Bari] : GLF editori Laterza, [2007]",
         ("GLF editori Laterza", "2007", "Roma ; Bari")),
        (", 154. ed. ; Paris : Gallimard, 1929 [ristampa 1949]", ("Gallimard", "1929", "Paris")),
        ("6 edizione, con saggi delle versioni di G. Leopardi, P. Maspero, G. Mazzoni, "
         "G. Pascoli ; con 99 illustrazioni ; nuova tiratura. - Firenze : Sansoni, 1926",
         ("Sansoni", "1926", "Firenze")),
        ("Rist. anast.- Oxford : Clarendon Press, 1955", ("Clarendon Press", "1955", "Oxford")),
        ("Edizione speciale per Famiglia Cristiana - Edizioni San Paolo, 1995",
         ("Edizioni San Paolo", "1995", None)),
        # Where a worded one ends is not known, so it stays.
        ("Edizione abbreviata per le scuole, Milano : Hoepli, 1893",
         ("Hoepli", "1893", "Edizione abbreviata per le scuole, Milano")),
        # An extent after the publisher, and one whose ` : ` was taken for ISBD's.
        ("Baroda : Oriental Institute. - 2 voll. ; 25 cm.", ("Oriental Institute", None, "Baroda")),
        ("Lipsiae : in aedibus B.G. Teubneri. - volumi ; 17 cm",
         ("in aedibus B.G. Teubneri", None, "Lipsiae")),
        ("Milano : feltrinelli, 20 cm", ("feltrinelli", None, "Milano")),
        ("Milano ; Messina : Principato, [195..] - VIII, 597 p. : ill. ; 22 cm.",
         ("Principato", None, "Milano ; Messina")),
        ("Tokyo: Seidosha, 1984. 380 p. : 19 cm", ("Seidosha", "1984", "Tokyo")),
        # A reprint after the publisher.
        ("Milano : A. Mondadori, 2. rist. 1990", ("A. Mondadori", "1990", "Milano")),
        ("Roma : Edizioni e/o, ristampa 2016", ("Edizioni e/o", "2016", "Roma")),
        ("Torino : SEI, terza edizione ristampa 1948", ("SEI", "1948", "Torino")),
        # Names that look like one stay.
        ("Italia : DVD Storm, 2002", ("DVD Storm", "2002", "Italia")),
        ("[India] : CM DVD, 2006", ("CM DVD", "2006", "India")),
        ("[Milano] : Edizione Club, 1981", ("Edizione Club", "1981", "Milano")),
        ("Barcelona : Ed. Bruguera, 1981", ("Ed. Bruguera", "1981", "Barcelona")),
    ])
    def test_an_extent_or_edition_statement_leaves_the_imprint(self, raw, expected):
        assert sbn.parse_publication(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("Milano : Mondadori, 2014. -IX, 123 p. ; 19 cm.", "2014"),
        ("Paris : Maison Quantin, 1889, 30 p. [1] c. di tav. ripieg. : ill. ; 23 cm.", "1889"),
        ("Torino : Einaudi, 1971, stampa 1978 - 221 p. ; 20 cm.", "1971, stampa 1978"),
        ("Tokyo: Seidosha, 1984. 380 p. : 19 cm", "1984"),
    ])
    def test_the_date_statement_stops_before_the_extent(self, raw, expected):
        assert sbn.date_statement(raw) == expected

    def test_empty(self):
        assert sbn.parse_publication(None) == (None, None, None)
        assert sbn.parse_publication("") == (None, None, None)

    def test_a_year_outside_the_recognised_range_is_not_picked_up(self):
        # _YEAR_RE covers 1000-1999 and 2000-2099 only.
        _, year, _ = sbn.parse_publication("Roma : Tipografia, 897")
        assert year is None


class TestParseDewey:
    def test_several_classes_run_together_without_a_separator(self):
        """`docs/sbn-api.md` trap 4, verbatim.

        A letter-to-digit transition is not a `\\b`, so a word-boundary regex
        read '616.85' as '85'. Both classes are as good a matching signal.
        """
        raw = "616.89 (18.) PSICHIATRIA616.85 (19.) MALATTIE NERVOSE"
        assert sbn.parse_dewey_all(raw) == ["616.89", "616.85"]
        assert sbn.parse_dewey(raw) == "616.89"

    @pytest.mark.parametrize("raw,expected", [
        ("780.07 (19.) MUSICA. RAPPORTO CON LA SOCIETA", ["780.07"]),
        ("863.64 (23.) NARRATIVA SPAGNOLA, 1945-1999", ["863.64"]),
        # A class with a letter suffix, from the Cent'anni records.
        ("863.44CO (20.) NARRATIVA IN LINGUA SPAGNOLA. COLOMBIA. 1945-", ["863.44"]),
        ("070.9", ["070.9"]),
    ])
    def test_real_bundle_values(self, raw, expected):
        assert sbn.parse_dewey_all(raw) == expected

    def test_empty(self):
        assert sbn.parse_dewey_all(None) == []
        assert sbn.parse_dewey_all("") == []
        assert sbn.parse_dewey(None) is None

    def test_does_not_repeat_a_class(self):
        assert sbn.parse_dewey_all("616.89 (18.) X616.89 (19.) Y") == ["616.89"]


class TestParseRecord:
    def test_the_skeleton_body_a_bogus_bid_returns(self):
        """F13's control, recorded in every Stage 3 fetch run.

        `full.json?bid=ZZQ9999999` answers 200 with a body carrying no
        `codiceIdentificativo` — it does not error. A parser that assumes a
        record came back produces an Edition for a book that does not exist.
        """
        skeleton = {"numeri": [], "note": [], "nomi": [], "luogoNormalizzato": [],
                    "localizzazioni": [],
                    "citazioni": [{"standard": "mla", "valore": ","},
                                  {"standard": "apa", "valore": "."}]}
        e = to_record(skeleton)
        assert e.id is None
        assert e.url is None
        assert e.title == ""
        assert e.language == langs.UNKNOWN

    def test_country_of_publication_is_never_read_as_a_language(self):
        """`docs/sbn-api.md` trap 1. CFI1172094 is an English '1984' printed in Pesaro."""
        rec = {"codiceIdentificativo": "IT\\ICCU\\CFI\\1172094",
               "titolo": "Nineteen eighty-four / George Orwell",
               "pubblicazione": "Pesaro : Metauro, 2003",
               "linguaPubblicazione": "INGLESE", "paesePubblicazione": "ITALIA"}
        assert to_record(rec).language == "eng"

    def test_an_unmapped_language_label_leaves_the_language_unknown(self):
        """Step 7 mapped `ALBANESE`, so the example moved; the rule did not.

        A label the table has no row for still becomes `unknown` rather than a
        guess from its Italian name — the whole point of `catalog/langs.py`.
        """
        rec = {"codiceIdentificativo": "IT\\ICCU\\XXX\\1", "titolo": "T",
               "linguaPubblicazione": "KLINGON"}
        assert to_record(rec).language == langs.UNKNOWN
        rec["linguaPubblicazione"] = "ALBANESE"
        assert to_record(rec).language == "alb"

    def test_translation_evidence_hides_in_the_statement_of_responsibility(self):
        """`docs/sbn-api.md` trap 1b — the Kafka record UBO4636099.

        It carries no `[Traduttore]` in `nomi` and no note. Its only trace of
        being a translation is the half of the title `sbn_title_of` cuts away,
        and records catalogued in English say 'translated from', which the
        Italian-stemmed TRANSLATION_RE never matched.
        """
        rec = {"codiceIdentificativo": "IT\\ICCU\\UBO\\4636099",
               "titolo": "Kafka on the shore / Haruki Murakami ; translated from "
                         "the Japanese by Philip Gabriel",
               "pubblicazione": "London : Vintage, 2005",
               "linguaPubblicazione": "GIAPPONESE", "nomi": [], "note": []}
        e = to_record(rec)
        assert e.evidence, "no translation evidence found on UBO4636099"
        assert has_translation_evidence(e) is True
        # The language is still taken at face value here; disbelieving it is
        # `core.identity.language_contradicts_itself`'s job, not the parser's.
        assert e.language == "jpn"

    def test_translation_evidence_in_an_italian_note(self):
        """`docs/sbn-api.md` trap 2 — CFI1183309 has it only in free text."""
        rec = {"codiceIdentificativo": "IT\\ICCU\\CFI\\1183309", "titolo": "Un titolo",
               "note": ["Testo originale a fronte; traduzione italiana a cura di Boris Yousef."]}
        assert to_record(rec).evidence

    def test_a_cura_di_alone_is_not_translation_evidence(self):
        """'a cura di' is 'edited by'; matching it makes every edited volume a
        translation. The TRANSLATION_RE comment says so deliberately."""
        rec = {"codiceIdentificativo": "IT\\ICCU\\XXX\\2", "titolo": "Opere",
               "note": ["Edizione a cura di Mario Rossi."]}
        assert to_record(rec).evidence == []

    def test_isbn_comes_from_the_labelled_numeri_field(self):
        rec = {"codiceIdentificativo": "IT\\ICCU\\XXX\\3", "titolo": "T",
               "numeri": ["[ISBN]  9788845906862"]}
        assert to_record(rec).isbn == "9788845906862"

    def test_authors_and_translators_are_separated_by_their_labels(self):
        rec = {"codiceIdentificativo": "IT\\ICCU\\XXX\\4",
               "titolo": "Cent'anni di solitudine / Gabriel García Márquez",
               "nomi": ["[Autore]  García Márquez, Gabriel",
                        "[Traduttore]  Cicogna, Enrico"]}
        e = to_record(rec)
        assert e.authors == ["García Márquez, Gabriel"]
        assert e.translators == ["Cicogna, Enrico"]

    def test_holdings_read_the_fields_that_lie_about_their_names(self):
        """`docs/sbn-api.md` trap 5: the library name is in `shelfmark`, the city in
        `invNum`. Not what the field names suggest, but consistent."""
        rec = {"codiceIdentificativo": "IT\\ICCU\\XXX\\5", "titolo": "T",
               "localizzazioni": [{"denominazione": "Biblioteca X", "isil": "IT-RM0267",
                                   "shelfmarks": [{"shelfmark": "Biblioteca nazionale",
                                                   "invNum": "Roma"}]}]}
        h = to_record(rec).holdings[0]
        assert h.library == "Biblioteca nazionale"
        assert h.city == "Roma"
        assert h.isil == "IT-RM0267"


class TestIsBookMedium:
    def test_excludes_a_film(self, ed):
        """A documentary *about* the author passes a title match — 'An ecology
        of mind: a daughter's portrait of Gregory Bateson' scored 0.67 against
        'Steps to an Ecology of Mind' — so it is excluded on what it is."""
        assert is_book_medium(ed("An ecology of mind",
                                     medium="documento da proiettare o video")) is False

    def test_keeps_a_sound_recording(self, ed):
        # An audiobook is an edition of the text.
        assert is_book_medium(ed("Cent'anni", medium="registrazione sonora")) is True

    def test_keeps_a_record_with_no_medium(self, ed):
        assert is_book_medium(ed("Cent'anni")) is True


class TestParamsWhitelist:
    """The whitelist is `catalog/sbn_mobile.py`'s since Step 5, so the request
    tests patch it there."""

    def test_params_is_exactly_the_honoured_set(self):
        """CLAUDE.md rule 2 — the project's single most dangerous trap.

        An unknown parameter is silently ignored and the *unfiltered* result set
        comes back: a silent wrong answer, not an error.
        """
        assert sbn.PARAMS == {"any", "title", "author", "subject",
                              "isbn", "type", "start", "rows"}

    def test_request_drops_a_parameter_outside_the_whitelist(self, monkeypatch):
        sent = {}

        def fake_get(url, params, validate=None):
            sent.update(params)
            return {"briefRecords": [], "facetRecords": []}

        monkeypatch.setattr(sbn_mobile, "cached_get_json", fake_get)
        sbn_mobile._request("search.json", {"title": "Rumori", "titolo": "Rumori",
                                     "lingua": "ita", "fq": "x", "rows": 20})
        assert sent == {"title": "Rumori", "rows": 20}
        assert "titolo" not in sent and "lingua" not in sent and "fq" not in sent

    def test_full_json_sends_bid_and_nothing_else(self, monkeypatch):
        """'bid' is the only accepted name; id/cid/codiceIdentificativo are
        rejected, and `bid` is not itself in PARAMS."""
        sent = {}

        def fake_get(url, params, validate=None):
            sent.update(params)
            return {}

        monkeypatch.setattr(sbn_mobile, "cached_get_json", fake_get)
        sbn_mobile._request("full.json", {"bid": "MIL0871878", "rows": 500})
        assert sent == {"bid": "MIL0871878"}

    def test_search_with_no_usable_term_issues_no_request(self, monkeypatch):
        def explode(url, params, validate=None):
            raise AssertionError("a request was issued for an empty query")

        monkeypatch.setattr(sbn_mobile, "cached_get_json", explode)
        assert sbn_mobile.search(rows=200) == ([], [])

    def test_an_error_payload_raises_rather_than_returning_empty(self, monkeypatch):
        """A failed request must never be indistinguishable from an empty
        result (CLAUDE.md rule 5 — the worst bug the project had).

        Since Step 3 the judgement is the validator `_request` hands the cache,
        which is what stops the body being written; the fake below applies it
        exactly as `net` does, so this still asserts the end-to-end property.
        """
        body = {"error": {"code": 0, "msg": "org.apache.solr.client.solrj."
                                            "SolrServerException: Error executing query"}}

        def fake_get(url, params, validate=None):
            problem = validate(body) if validate else None
            if problem:
                raise SourceError(f"{url}: {problem}")
            return body

        monkeypatch.setattr(sbn_mobile, "cached_get_json", fake_get)
        with pytest.raises(SourceError):
            sbn_mobile.search(title="Rumori")
