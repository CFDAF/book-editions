"""`core/text.py` — the scoring the identifying-signal gate rests on, plus the two
catalogue conventions that live with their parsers (`CLAUDE.md`, two trees)."""

import pytest

from catalog.sbn_mobile import title_of as sbn_title_of
from catalog.wikidata import strip_disambiguator
from core.text import (STOPWORDS, author_display, author_matches, core_title,
                       normalize, surname, title_similarity)


class TestNormalize:
    def test_lowercases_strips_accents_and_punctuation(self):
        assert normalize("Cien años de soledad!") == {"cien", "anos", "soledad"}

    def test_the_bare_de_and_en_became_stopwords_in_step_6(self):
        """The gap this test used to record, closed where it was measured.

        Step 1B measured it as latent: 3 of 103 corpus entry titles carry a bare
        `de` or `en` and **0 of 5,152 cross-book pairs** reach the gate either
        way. Step 6 measured the population that matters — U2's 700 judged
        records — and closing it took the wrong-work records let through from
        **18 to 16** while admitting exactly as many same-work records (393).
        The two it blocks are *Apostille au Nom de la rose* at 0.6 and *Una
        unidad sagrada* at 0.625, each a different book clearing the bar on a
        shared function word.
        """
        assert "de" in STOPWORDS and "en" in STOPWORDS
        assert normalize("Veinte poemas de amor") == {"veinte", "poemas", "amor"}

    def test_drops_stopwords(self):
        assert normalize("The Invention of News") == {"invention", "news"}

    def test_drops_single_characters(self):
        # 'a' is a stopword anyway; 'l' survives an apostrophe split and must not.
        assert normalize("L'ordine") == {"ordine"}

    def test_empty_and_none_give_an_empty_set(self):
        assert normalize("") == set()
        assert normalize(None) == set()

    def test_delle_is_a_stopword(self):
        """The regression the STOPWORDS comment records.

        With 'della' listed but not 'delle', 'delle' counted as a meaningful
        token and "L'ordine delle notizie" scored 0.67 against "L'invenzione
        delle notizie" — ranking a different book above the right one.
        """
        assert "delle" not in normalize("L'ordine delle notizie")


class TestCoreTitle:
    @pytest.mark.parametrize("raw,expected", [
        ("Bruits : essai sur l'economie politique de la musique", "Bruits"),
        ("Noise - The Political Economy of Music", "Noise"),
        ("Noise — The Political Economy of Music", "Noise"),
        ("Cent'anni di solitudine", "Cent'anni di solitudine"),
        ("  padded  ", "padded"),
    ])
    def test_strips_subtitle(self, raw, expected):
        assert core_title(raw) == expected


class TestTitleSimilarity:
    def test_identical_titles_score_one(self):
        assert title_similarity("Cent'anni di solitudine", "Cent'anni di solitudine") == 1.0

    def test_is_symmetric(self):
        a, b = "The Invention of News", "L'invenzione delle notizie"
        assert title_similarity(a, b) == title_similarity(b, a)

    def test_empty_side_scores_zero(self):
        assert title_similarity("", "Rumori") == 0.0
        assert title_similarity("Rumori", "") == 0.0

    def test_a_title_of_only_stopwords_scores_zero(self):
        # normalize() empties it, and an empty set must not divide by zero.
        assert title_similarity("of the and", "Rumori") == 0.0

    def test_cross_language_similarity_is_worthless(self):
        """`docs/DECISIONS.md` pitfall 13, and the reason four bridges exist.

        This is not a defect to fix — it is why the gate cannot be a title
        comparison across languages, and why the uniform-title authority is the
        strongest bridge.
        """
        assert title_similarity("Noise", "Rumori") == 0.0
        assert title_similarity("One Hundred Years of Solitude", "Cien años de soledad") == 0.0


class TestAuthorMatches:
    def test_no_query_author_does_not_penalise(self):
        assert author_matches(None, ["Anyone At All"]) is True
        assert author_matches("", ["Anyone At All"]) is True

    def test_matches_on_a_shared_token(self):
        assert author_matches("Garcia Marquez", ["García Márquez, Gabriel"]) is True

    def test_rejects_an_unrelated_author(self):
        assert author_matches("Attali", ["Russolo, Luigi"]) is False

    def test_empty_candidate_list(self):
        assert author_matches("Attali", []) is False
        assert author_matches("Attali", None) is False


class TestSurname:
    @pytest.mark.parametrize("name,expected", [
        ("García Márquez, Gabriel", "García Márquez"),   # SBN's inverted form
        ("Gabriel García Márquez", "Márquez"),           # Open Library's plain form
        ("Attali", "Attali"),
        ("", ""),
        (None, ""),
    ])
    def test_best_effort_surname(self, name, expected):
        assert surname(name) == expected


class TestStripDisambiguator:
    @pytest.mark.parametrize("raw,expected", [
        ("1984 (romanzo)", "1984"),                       # itwiki sitelink for Q208460
        ("Il nome della rosa (film 1986)", "Il nome della rosa"),
        ("Rumori", "Rumori"),
        (None, ""),
    ])
    def test_drops_a_trailing_parenthetical(self, raw, expected):
        assert strip_disambiguator(raw) == expected

    def test_keeps_a_parenthetical_that_is_not_trailing(self):
        assert strip_disambiguator("(1984) revisited") == "(1984) revisited"


class TestAuthorDisplay:
    @pytest.mark.parametrize("raw,expected", [
        ("Pettegree, Andrew <1957- >", "Andrew Pettegree"),
        ("García Márquez, Gabriel", "Gabriel García Márquez"),
        ("Gabriel García Márquez", "Gabriel García Márquez"),
        ("Attali, Jacques <1943- >", "Jacques Attali"),
        ("", ""),
        (None, ""),
    ])
    def test_brings_sbn_and_open_library_into_one_form(self, raw, expected):
        assert author_display(raw) == expected

    def test_leaves_a_two_comma_name_alone(self):
        # Two commas is not 'Surname, Forename' and guessing would garble it.
        assert author_display("Ruesch, Jurgen, 1910-1995") == "Ruesch, Jurgen, 1910-1995"


class TestSbnTitleOf:
    def test_cuts_the_statement_of_responsibility(self):
        raw = "Rumori : saggio sull'economia politica della musica / Jacques Attali"
        assert sbn_title_of(raw) == "Rumori : saggio sull'economia politica della musica"

    def test_leaves_a_title_with_no_responsibility(self):
        assert sbn_title_of("Cent'anni di solitudine") == "Cent'anni di solitudine"

    def test_empty(self):
        assert sbn_title_of(None) == ""
