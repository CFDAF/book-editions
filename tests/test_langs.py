"""`catalog/langs.py` — one vocabulary for four sources, and the rule that an
unknown language stays unknown.

The 21 SBN labels at the bottom were **known-red** (strict xfail) from Step 1B
to Step 7: a measured gap, armed so the suite would go red the day it was
closed. Step 7 closed it, and each label now asserts the code **SBN's own
listing files those records under** — read off the `lingua[]` facet beside the
label, never guessed from the Italian name. The gap's size is still asserted, so
a future one cannot appear unnoticed.
"""

import pytest

from catalog import langs


class TestFromSbn:
    @pytest.mark.parametrize("label,code", [
        ("ITALIANO", "ita"), ("INGLESE", "eng"), ("FRANCESE", "fre"),
        ("TEDESCO", "ger"), ("SPAGNOLO", "spa"), ("GIAPPONESE", "jpn"),
        ("GRECO ANTICO", "grc"), ("MULTILINGUE", "mul"),
    ])
    def test_maps_the_labels_it_knows(self, label, code):
        assert langs.from_sbn(label) == code

    def test_is_case_and_whitespace_insensitive(self):
        assert langs.from_sbn("  italiano  ") == "ita"

    def test_an_unknown_label_stays_unknown(self):
        """The rule the module exists to enforce.

        The original script folded a blank language into English
        (`if "eng" in langs or not langs`), which inflated the English list with
        records whose language was simply not recorded.
        """
        assert langs.from_sbn("KLINGON") == langs.UNKNOWN
        assert langs.from_sbn("") == langs.UNKNOWN
        assert langs.from_sbn(None) == langs.UNKNOWN


# The labels SBN actually returned across the 778 full records of the Stage 3
# fetch, that `langs._SBN` had no code for until Step 7 — recounted from
# the recorded bodies in Step 1B and reproducing F7's re-check exactly: 21 labels
# over 38 records.
#
# **The codes are SBN's own.** Stage 3 recorded each record's `full_lang` label
# beside the `lingua[]` codes its listing came back under
# (`tests/data/results/stage-3/records.json`), so the pair is the catalogue's
# statement and not a reading of the Italian name — which is how `SLOVACCO`
# would have become `slk` where SBN says `slo`, and `ISLANDESE` `isl` where SBN
# says `ice`.
UNMAPPED_SBN_LABELS = [
    ("ALBANESE", 7, "alb"), ("RUMENO, MOLDAVO", 5, "rum"), ("UCRAINO", 4, "ukr"),
    ("TURCO MODERNO (DAL 1928)", 4, "tur"), ("SLOVACCO", 2, "slo"),
    ("COREANO", 1, "kor"), ("GRECO MODERNO (DAL 1453)", 1, "gre"),
    ("ESPERANTO", 1, "epo"), ("ESTONE", 1, "est"),
    ("OLANDESE, FIAMMINGO", 1, "dut"), ("LITUANO", 1, "lit"), ("SARDO", 1, "srd"),
    ("ISLANDESE", 1, "ice"), ("LETTONE", 1, "lav"), ("SERBO-CROATO", 1, "hbs"),
    ("PERSIANO MODERNO", 1, "per"), ("INDONESIANO", 1, "ind"),
]

# A bilingual label names two languages and `Record.language` holds one. SBN's
# own listing files such a record under **both** codes — verified on all four —
# so `from_sbn` answers with the first language named, which is always one of
# the two, rather than inventing `mul` for a parallel text SBN did not call
# multilingual.
BILINGUAL_SBN_LABELS = [
    ("FRANCESE - ITALIANO", 1, "fre", ("fre", "ita")),
    ("FRANCESE - FRANCESE", 1, "fre", ("fre",)),
    ("ITALIANO - INGLESE", 1, "ita", ("eng", "ita")),
    ("CECO - ITALIANO", 1, "cze", ("cze", "ita")),
]


class TestTheLabelsStepSevenMapped:
    def test_the_gap_was_twenty_one_labels_over_thirty_eight_records(self):
        """The size of the gap, asserted so a new one cannot drift in unnoticed."""
        assert len(UNMAPPED_SBN_LABELS) + len(BILINGUAL_SBN_LABELS) == 21
        total = (sum(n for _, n, _ in UNMAPPED_SBN_LABELS)
                 + sum(n for _, n, _, _ in BILINGUAL_SBN_LABELS))
        assert total == 38

    @pytest.mark.parametrize("label,code",
                             [(l, c) for l, _, c in UNMAPPED_SBN_LABELS])
    def test_each_label_maps_to_the_code_sbn_files_it_under(self, label, code):
        assert langs.from_sbn(label) == code

    @pytest.mark.parametrize("label,code,listed",
                             [(l, c, s) for l, _, c, s in BILINGUAL_SBN_LABELS])
    def test_a_bilingual_label_answers_with_the_first_language_named(
            self, label, code, listed):
        assert langs.from_sbn(label) == code
        # And it is one of the codes SBN's listing actually used for the record,
        # so the answer is never a language the catalogue did not name.
        assert code in listed

    def test_an_unseen_pair_still_answers_rather_than_giving_up(self):
        """The pair rule is structural, not four literals: SBN can pair any two."""
        assert langs.from_sbn("TEDESCO - RUSSO") == "ger"

    def test_a_pair_whose_first_half_is_unknown_stays_unknown(self):
        assert langs.from_sbn("KLINGON - ITALIANO") == langs.UNKNOWN


class TestFromSbnCode:
    """The OPAC's `lingua[]` facet value, which is the code and not the label.

    This is the listing's own language signal — the page a row came back on —
    and it is why S2 needs no label map at all.
    """

    @pytest.mark.parametrize("code", ["ita", "eng", "srd", "hbs", "epo"])
    def test_a_three_letter_code_is_already_canonical(self, code):
        assert langs.from_sbn_code(code) == code

    @pytest.mark.parametrize("code", ["und", "mis", "zxx", "", None])
    def test_not_recorded_is_unknown_and_not_a_language(self, code):
        """SBN's facet really does return these. Passed through they would name
        a language that does not exist and put editions in a phantom group."""
        assert langs.from_sbn_code(code) == langs.UNKNOWN

    def test_it_is_case_and_whitespace_insensitive(self):
        assert langs.from_sbn_code(" ITA ") == "ita"


class TestLatinScript:
    """The set `core.identity.language_contradicts_script` reads.

    It is a fact about writing systems, and the gate only ever *disbelieves* a
    record, so a language missing from the set is the safe direction.
    """

    def test_it_names_languages_written_in_latin_script(self):
        assert {"ita", "eng", "fre", "ger", "tur", "vie"} <= langs.LATIN_SCRIPT

    def test_it_omits_languages_written_in_another_script(self):
        assert not ({"rus", "ukr", "grc", "gre", "ara", "heb", "jpn", "chi",
                     "kor", "bul", "mac", "hin"} & langs.LATIN_SCRIPT)

    def test_it_omits_languages_written_in_two_scripts(self):
        """Serbian is written in both, so a Cyrillic title is not a contradiction
        there and `srp`/`hbs` must never reach the gate."""
        assert not ({"srp", "hbs"} & langs.LATIN_SCRIPT)


class TestFromOpenLibrary:
    @pytest.mark.parametrize("key,code", [
        ("/languages/ita", "ita"), ("ita", "ita"), ("/languages/eng", "eng"),
        ("it", "ita"), ("IT", "ita"),
    ])
    def test_accepts_both_shapes(self, key, code):
        assert langs.from_openlibrary(key) == code

    @pytest.mark.parametrize("key", ["und", "mis", "zxx", "", None, "/languages/und"])
    def test_indeterminate_codes_are_unknown_not_a_language(self, key):
        """'und'/'mis'/'zxx' mean 'not recorded'. Passed through they would name
        a language that does not exist and put editions in a phantom group."""
        assert langs.from_openlibrary(key) == langs.UNKNOWN

    def test_an_unrecognised_two_letter_code_is_unknown(self):
        assert langs.from_openlibrary("qq") == langs.UNKNOWN


class TestFromTwoLetter:
    def test_maps_a_known_code(self):
        assert langs.from_two_letter("ja") == "jpn"

    def test_strips_a_regional_suffix(self):
        assert langs.from_two_letter("pt-br") == "por"

    def test_passes_through_an_unknown_three_letter_code(self):
        # A three-letter code is already canonical even when _TWO has no row.
        assert langs.from_two_letter("cat") == "cat"

    def test_unknown_and_empty(self):
        assert langs.from_two_letter("qq") == langs.UNKNOWN
        assert langs.from_two_letter(None) == langs.UNKNOWN


class TestFromWikidata:
    def test_maps_known_items(self):
        assert langs.from_wikidata("Q1860") == "eng"
        assert langs.from_wikidata("q652") == "ita"

    def test_unknown_item(self):
        assert langs.from_wikidata("Q999999") == langs.UNKNOWN
        assert langs.from_wikidata(None) == langs.UNKNOWN


class TestRoundTripAndDisplay:
    @pytest.mark.parametrize("code", ["ita", "eng", "fre", "ger", "jpn", "rus"])
    def test_two_letter_inverts_from_two_letter(self, code):
        assert langs.from_two_letter(langs.two_letter(code)) == code

    def test_two_letter_has_no_code_for_grc_or_mul(self):
        # Neither has a Wikipedia subdomain in _TWO; callers must handle None.
        assert langs.two_letter("grc") is None
        assert langs.two_letter("mul") is None

    def test_display_names(self):
        assert langs.display("ita") == "italiano"
        assert langs.display(langs.UNKNOWN) == "lingua non indicata"
        assert langs.display(None) == "lingua non indicata"

    def test_display_falls_back_to_the_code_itself(self):
        assert langs.display("zzz") == "zzz"

    def test_every_sbn_code_has_a_display_name(self):
        for code in langs._SBN.values():
            assert langs.display(code) != code, f"no display name for {code}"
