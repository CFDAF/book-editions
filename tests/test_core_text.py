"""`core/text.py` — the two functions Step 5 added, and what has not arrived.

`normalize`, `core_title`, `title_similarity` and the rest are covered by
`tests/test_matching.py`. What is new here is `similarity` and
`variant_affinity`: the max-over-core-titles comparison that the SBN guard, the
Wikidata title test and the recovery-route gate had each written out separately.
That triplication was a *Noticed* item assigned to this step.
"""

from core import text as T
from core import identity as I


class TestSimilarity:
    def test_it_is_the_better_of_the_full_and_the_core_comparison(self):
        """One title with a subtitle and one without are the same title."""
        assert T.title_similarity("Noise: The Political Economy of Music", "Noise") < 1.0
        assert T.similarity("Noise: The Political Economy of Music", "Noise") == 1.0

    def test_it_is_symmetric(self):
        a, b = "Noise: The Political Economy of Music", "Noise"
        assert T.similarity(a, b) == T.similarity(b, a)

    def test_a_translation_still_scores_zero_against_its_original(self):
        """`similarity` is not a fix for the cross-language problem; nothing is.
        That is why the uniform title exists."""
        assert T.similarity("Noise", "Rumori") == 0.0

    def test_an_empty_side_is_zero_and_not_an_error(self):
        assert T.similarity("", "Rumori") == 0.0
        assert T.similarity("Rumori", "") == 0.0


class TestVariantAffinity:
    VARIANTS = ["Bruits", "Noise", "Rumori"]

    def test_the_best_variant_is_the_one_that_counts(self):
        assert T.variant_affinity("Rumori", self.VARIANTS) == 1.0

    def test_a_title_no_variant_names_scores_zero(self):
        assert T.variant_affinity("Quale socialismo, quale Europa", self.VARIANTS) == 0.0

    def test_no_variants_is_zero_and_not_an_error(self):
        """A book with no identity is normal (A1), so this is reached often."""
        assert T.variant_affinity("Rumori", []) == 0.0

    def test_it_is_the_one_the_gate_reads(self):
        """`core.identity` scores with this function, so the counterexamples in
        `tests/test_gate.py` are asserted against it."""
        assert I.variant_affinity is T.variant_affinity


class TestTheGateCounterexamples:
    """`CLAUDE.md` rule 6's two, at the shared threshold. They are the reason the
    bar is 0.6 and not 0.45, and they are re-checked on every gate change —
    including the transliteration fold, which is Step 6's."""

    def test_lordine_delle_notizie_is_not_an_edition_of_linvenzione(self):
        score = T.variant_affinity("L'ordine delle notizie",
                                   ["L'invenzione delle notizie", "The Invention of News"])
        assert score == 0.5 < I.IDENTIFYING_TITLE_MATCH

    def test_quale_socialismo_quale_europa_is_not_an_edition_of_bruits(self):
        score = T.variant_affinity("Quale socialismo, quale Europa",
                                   ["Bruits", "Noise", "Rumori"])
        assert score == 0.0 < I.IDENTIFYING_TITLE_MATCH


class TestRomanise:
    """Decision B. Latin script only — and the reason is not tidiness.

    The OPAC does not reject non-Latin free text: it **discards the term** and
    answers with the unfiltered set (F15, verified), so a question that cannot
    be romanised must not be sent at all.
    """

    def test_it_agrees_with_the_corpus_romanisation(self):
        """The three the corpus romanised by hand, character for character."""
        assert T.romanise("Доктор Живаго") == "Doktor Zhivago"
        assert T.romanise("Преступление и наказание") == "Prestuplenie i nakazanie"
        assert T.romanise("Ὀδύσσεια") == "Odysseia"

    def test_latin_text_is_returned_untouched_accents_and_all(self):
        """It is a script change, not a normaliser: `normalize` strips the
        accents a moment later, and `romanise` has no business doing it here."""
        for text in ("Cien años de soledad", "Il dottor Živago", "L'étranger"):
            assert T.romanise(text) == text

    def test_a_script_with_no_letter_by_letter_romanisation_is_left_alone(self):
        """Japanese, Chinese and Arabic come back unchanged and `is_latin` still
        says no, so the caller refuses to send rather than sending a guess.
        UC3 is what covers them: the reader types the title romanised."""
        for text in ("海辺のカフカ", "活着", "بين القصرين"):
            assert T.romanise(text) == text
            assert not T.is_latin(text)

    def test_is_latin_reads_letters_and_ignores_everything_else(self):
        assert T.is_latin("Doktor Zhivago") and T.is_latin("Cien años, 1967!")
        assert not T.is_latin("Доктор Живаго") and not T.is_latin("Ὀδύσσεια")

    def test_empty_input_is_empty_and_not_an_error(self):
        assert T.romanise("") == "" and T.romanise(None) == ""
        assert T.is_latin("") and T.is_latin(None)

    def test_normalize_romanises_so_a_cyrillic_title_is_comparable_at_all(self):
        """Before this, the ASCII encode dropped the whole title and every
        comparison with it was 0.0 — a silent 'no match', not a refusal."""
        assert T.normalize("Доктор Живаго") == {"doktor", "zhivago"}
        assert T.similarity("Doktor Zhivago", "Доктор Живаго") == 1.0


class TestTheFold:
    """Decision G, measured twice before it shipped: U3 over the corpus's title
    pairs and U2 over 700 judged records."""

    def test_it_recovers_the_two_misses_it_exists_for(self):
        assert T.similarity("Doktor Zhivago", "doktor zivago") == 1.0
        assert T.similarity("Odysseia", "odyssea") == 1.0
        assert T.similarity("Odysseia", "Odissea") == 1.0

    def test_it_is_a_transliteration_tool_and_not_a_translation_one(self):
        assert T.similarity("Noise", "Rumori") == 0.0
        assert T.similarity("One Hundred Years of Solitude", "Cien años de soledad") == 0.0

    def test_the_fold_is_applied_to_one_token_at_a_time(self):
        assert T.fold_variants("zhivago") == "zivago"
        assert T.fold_variants("odysseia") == "odisea"

    def test_the_shipped_fold_does_not_reach_dostoevskij_and_dostoevsky(self):
        """A limit of the fold U3 measured, pinned rather than quietly widened.

        The doubled-letter collapse runs *before* `j`/`y` -> `i`, so
        `dostoevskij` folds to `dostoevskii` and `dostoevsky` to `dostoevski`.
        Reordering the two would join them — and would be a different fold from
        the one measured in U3 and U2, so it needs those measurements re-run and
        not a tweak here. It costs nothing today: the fold is applied to titles,
        and author matching does not use it.
        """
        assert T.fold_variants("dostoevskij") != T.fold_variants("dostoevsky")

    def test_it_is_not_in_normalize_so_a_catalogue_spelling_survives(self):
        """Author matching and the Dewey title key compare what the catalogue
        actually wrote; only the title comparison folds."""
        assert "zhivago" in T.normalize("Doktor Zhivago")


class TestStopwordsAfterStep6:
    def test_the_bare_de_and_en_are_function_words_after_all(self):
        """Measured over U2's 700 judged rows: leaks 18 -> 16, same-work records
        admitted unchanged at 393. The two blocked are *Apostille au Nom de la
        rose* and *Una unidad sagrada*, each a different book clearing 0.6 on a
        shared function word — the hole the missing `delle` was."""
        assert {"de", "en"} <= T.STOPWORDS
        assert "delle" in T.STOPWORDS and "des" in T.STOPWORDS

    def test_they_do_not_move_the_counterexamples(self):
        assert T.variant_affinity("L'ordine delle notizie",
                                  ["L'invenzione delle notizie"]) == 0.5
        assert T.variant_affinity("Quale socialismo, quale Europa",
                                  ["Bruits", "Noise", "Rumori"]) == 0.0
