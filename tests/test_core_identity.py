"""`core/identity.py` — the four gates, as assertions.

The identifying-signal gate itself is covered by `tests/test_gate.py`, which
holds `docs/limits.md`'s counterexamples against `core.identity` directly (until
Step 16 it reached the gate through `lookup/pipeline.py`'s aliases). What is
here is what that file could not reach before Step 5:

- **the SBN work guard (A/B)** and its tiers, whose numbers lived only in
  the benchmark's Stage 1 script;
- **the Wikidata title test** and **the second signal** (decision A), likewise;
- **`language_contradicts_itself`**, which was pure and untested (Step 1B's
  *Noticed*, assigned to this step);
- **`pick_work`**, which used to live inside `lookup/opac.work_for` where nothing
  could get at it.

Every threshold asserted here is settled against being loosened, and the
counterexamples are named beside them.
"""

import pytest

from catalog import langs
from core import identity as I
from core.model import Provenance, Record

P = Provenance("SBN", "work listing", "uniform title")


def rec(title="", **kw) -> Record:
    return Record(source="SBN", id="MIL0871878", provenance=P, title=title, **kw)


def row(rec_id, title):
    return {"id": rec_id, "title": title}


# ---------------------------------------------------------------------------
# 1. Picking W
# ---------------------------------------------------------------------------

class TestPickWork:
    ITEMS = [{"value": "cien anos de soledad", "label": "Cien anos de soledad",
              "results": 89},
             {"value": "autunno del patriarca", "label": "Autunno del patriarca",
              "results": 12}]

    def test_the_highest_count_value_is_w(self):
        assert I.pick_work(self.ITEMS)["value"] == "cien anos de soledad"
        assert I.pick_work(self.ITEMS)["count"] == 89

    def test_an_adaptation_is_never_w(self):
        """A film or a TV series is linked to the work and is not an edition of
        it: 'nome della rosa <serie tv ; 2018>'."""
        items = [{"value": "nome della rosa <serie tv ; 2018>",
                  "label": "Nome della rosa <serie tv ; 2018>", "results": 400},
                 {"value": "nome della rosa", "label": "Nome della rosa", "results": 232}]
        assert I.pick_work(items)["value"] == "nome della rosa"

    def test_nothing_but_adaptations_is_no_work(self):
        assert I.pick_work([{"value": "x <film ; 1986>", "label": "X <film ; 1986>",
                             "results": 9}]) is None

    def test_an_empty_facet_is_no_work(self):
        assert I.pick_work([]) is None
        assert I.pick_work(None) is None

    def test_a_tie_is_reported_rather_than_broken_silently(self):
        items = [{"value": "a", "label": "A", "results": 5},
                 {"value": "b", "label": "B", "results": 5}]
        top = I.pick_work(items)
        assert top["ties"] == ["b"] if top["value"] == "a" else ["a"]


# ---------------------------------------------------------------------------
# 2. The guard: A, B and the tiers
# ---------------------------------------------------------------------------

class TestAffinityA:
    def test_the_typed_title_matching_the_uniform_title_is_strong(self):
        assert I.affinity_a("Il nome della rosa", "nome della rosa") == 1.0

    def test_a_subtitle_on_one_side_only_does_not_cost_the_match(self):
        assert I.affinity_a(
            "Rumori", "bruits : essai sur l'economie politique de la musique") == 0.0
        assert I.affinity_a("Noise: The Political Economy of Music",
                            "noise") == pytest.approx(1.0)

    def test_a_translation_scores_zero_against_its_original_title(self):
        """Which is the whole problem: cross-language title similarity is
        worthless, `title_similarity('Noise', 'Rumori')` is exactly 0.0. A is the
        cheap half of the guard and B is why there is a second half."""
        assert I.affinity_a("Rumori", "noise") == 0.0


class TestShareB:
    QUERY = [row("A", "Cent'anni di solitudine"), row("B", "Cent'anni di solitudine"),
             row("C", "L'autunno del patriarca"), row("D", "Cent'anni di solitudine")]

    def test_b_is_the_share_of_really_matching_rows_that_w_also_holds(self):
        b, matched, in_work = I.share_b("Cent'anni di solitudine", self.QUERY,
                                        [row("A", "x"), row("B", "x")])
        assert matched == {"A", "B", "D"}
        assert in_work == {"A", "B"}
        assert b == pytest.approx(2 / 3)

    def test_a_row_whose_title_does_not_match_is_not_counted_either_way(self):
        b, matched, _ = I.share_b("Cent'anni di solitudine", self.QUERY,
                                  [row("C", "x")])
        assert "C" not in matched and b == 0.0

    def test_nothing_matching_is_none_and_not_zero(self):
        """A different answer: 0.0 means W holds none of this title's records,
        None means the query returned no record of this title at all."""
        b, matched, _ = I.share_b("Rumori", [row("A", "Quale socialismo")], [])
        assert b is None and matched == set()


class TestTier:
    def test_a_high_a_is_strong_and_costs_no_second_request(self):
        assert I.tier(1.0, None) == I.WORK_STRONG

    def test_b_above_a_half_is_strong(self):
        assert I.tier(0.0, 0.75) == I.WORK_STRONG

    def test_b_exactly_a_half_is_weak_which_is_where_the_second_signal_applies(self):
        assert I.tier(0.0, 0.5) == I.WORK_WEAK

    def test_b_below_a_half_is_refused(self):
        assert I.tier(0.0, 0.375) == I.WORK_REJECTED

    def test_no_facet_at_all_is_no_work_not_a_refusal(self):
        assert I.tier(None, None) == I.WORK_NONE

    def test_the_known_wrong_works_sit_above_every_refused_classic(self):
        """Why loosening B is settled against, and the reason the second signal
        exists instead. *Tesi di filosofia della storia* and *Angelus Novus* are
        wrong at B = 0.5; *Crime and Punishment* eng is right at 9/31, *Der
        Process* at 2/15, *Blindness* at 3/8. Any bar that admits the classics
        admits the wrong works first."""
        wrong = 0.5
        classics = [9 / 31, 2 / 15, 3 / 8]
        assert all(c < wrong for c in classics)
        assert I.tier(0.0, wrong) == I.WORK_WEAK
        assert all(I.tier(0.0, c) == I.WORK_REJECTED for c in classics)


# ---------------------------------------------------------------------------
# 3. The Wikidata title test
# ---------------------------------------------------------------------------

class TestTitleTest:
    FORMS = ["Cien años de soledad", "One Hundred Years of Solitude",
             "Cent'anni di solitudine"]

    def test_an_item_naming_the_typed_title_is_accepted(self):
        score, form = I.title_test("Cent'anni di solitudine", self.FORMS)
        assert score == 1.0 and form == "Cent'anni di solitudine"
        assert I.item_is_accepted(score)

    def test_an_item_that_names_nothing_like_it_is_refused(self):
        score, _ = I.title_test("Quale socialismo, quale Europa", self.FORMS)
        assert not I.item_is_accepted(score)

    def test_a_disambiguator_has_to_be_gone_before_it_gets_here(self):
        """`itwiki` for `Q208460` is '1984 (romanzo)'; `catalog/wikidata.py`
        strips it, because the parenthesis costs the match."""
        from catalog.wikidata import strip_disambiguator
        assert not I.item_is_accepted(I.title_test("1984", ["1984 (romanzo)"])[0])
        assert I.item_is_accepted(
            I.title_test("1984", [strip_disambiguator("1984 (romanzo)")])[0])

    def test_no_forms_is_a_refusal_and_not_an_error(self):
        assert I.title_test("Rumori", []) == (0.0, None)
        assert not I.item_is_accepted(0.0)

    def test_the_threshold_is_the_same_number_as_the_guards(self):
        assert I.WORK_TITLE_MATCH == 0.6 == I.IDENTIFYING_TITLE_MATCH


# ---------------------------------------------------------------------------
# 4. The second signal (decision A)
# ---------------------------------------------------------------------------

class TestSecondSignal:
    def test_an_item_that_names_w_rescues_a_refused_work(self):
        """N22 *Le Capital au XXIe siècle*: the entry's W was refused on B, and
        the accepted item's own French label names it."""
        agrees, score, form = I.second_signal(
            "capital au xxie siecle",
            ["Le Capital au XXIe siècle", "Capital in the Twenty-First Century"])
        assert agrees and score == 1.0 and form == "Le Capital au XXIe siècle"

    def test_an_item_about_another_book_rescues_nothing(self):
        """0 agreements in 2,024 cross-book pairs — the measurement that makes
        this an acceptance signal rather than a loosening."""
        agrees, _, _ = I.second_signal("bruits : essai sur l'economie politique",
                                       ["Quale socialismo, quale Europa"])
        assert not agrees

    def test_it_compares_w_against_the_item_never_against_the_typed_title(self):
        """The typed title is what the guard already doubted, so it may not be
        the thing that rescues it. Signature enforces it: there is nowhere to
        pass one."""
        import inspect
        assert list(inspect.signature(I.second_signal).parameters) \
            == ["work_title", "item_forms"]

    def test_a_refused_work_with_no_accepted_item_stays_refused(self):
        """The 3 wrong-W refusals have no Step 4 item at all."""
        assert not I.second_signal("angelus novus", [])[0]


# ---------------------------------------------------------------------------
# The record-level judgements
# ---------------------------------------------------------------------------

class TestLanguageContradictsItself:
    """`UBO4636099` is 'Kafka on the shore / Haruki Murakami ; translated from
    the Japanese by Philip Gabriel', London : Vintage, 2005 — and carries
    `linguaPubblicazione: GIAPPONESE`. It is the English translation. Believed, it
    put a 2005 edition under 'first published 2002 in giapponese'.

    `linguaPubblicazione` is the only language signal there is, so the record
    stops being evidence of a language rather than being corrected.
    """

    KAFKA = "Kafka on the shore / Haruki Murakami ; translated from the Japanese by Philip Gabriel"

    def test_the_trap_record_is_disbelieved(self):
        assert I.language_contradicts_itself(rec(self.KAFKA, language="jpn"), "jpn")

    def test_a_record_really_in_the_original_language_is_believed(self):
        assert not I.language_contradicts_itself(
            rec("海辺のカフカ", language="jpn"), "jpn")

    def test_a_translation_into_another_language_is_not_a_contradiction(self):
        """It says it is a translation *and* it says it is in Italian. Both true."""
        assert not I.language_contradicts_itself(
            rec("Kafka sulla spiaggia", language="ita",
                translators=["Amitrano, Giorgio"]), "jpn")

    def test_a_translator_in_nomi_is_enough_without_the_title_saying_so(self):
        assert I.language_contradicts_itself(
            rec("Kafka on the shore", language="jpn",
                translators=["Gabriel, Philip"]), "jpn")

    def test_an_unrecorded_language_cannot_contradict_anything(self):
        assert not I.language_contradicts_itself(
            rec(self.KAFKA, language=langs.UNKNOWN), "jpn")

    def test_with_no_original_language_known_there_is_nothing_to_contradict(self):
        assert not I.language_contradicts_itself(rec(self.KAFKA, language="jpn"), None)

    def test_evidence_in_a_note_counts_too(self):
        """`CFI1183309` has no [Traduttore] and no translator in `nomi`: the only
        trace is '…traduzione italiana a cura di Boris Yousef.' in `note`."""
        assert I.language_contradicts_itself(
            rec("Qualcosa", language="ita",
                evidence=["traduzione italiana a cura di Boris Yousef."]), "ita")


class TestLanguageContradictsScript:
    """The other half of `CLAUDE.md` rule 4's lie, added in Step 7.

    `Преступлéние и наказáние. 1/2` is a real SBN record of *Crime and
    Punishment* filed INGLESE. Since Step 6 romanises, it reaches the candidate
    set and carries that claim with it (decision Y routed the rule here).
    """

    def test_a_cyrillic_title_is_not_an_english_edition(self):
        assert I.language_contradicts_script(
            rec("Преступлéние и наказáние. 1/2", language="eng"))

    def test_a_greek_title_is_not_an_italian_edition(self):
        assert I.language_contradicts_script(rec("Ὀδύσσεια", language="ita"))

    def test_a_cyrillic_title_filed_as_russian_is_no_contradiction(self):
        assert not I.language_contradicts_script(
            rec("Преступление и наказание", language="rus"))

    def test_a_language_written_in_two_scripts_is_never_disbelieved(self):
        """Serbian is written in both alphabets, so `srp` is absent from
        `LATIN_SCRIPT` and a Cyrillic title there proves nothing."""
        assert not I.language_contradicts_script(rec("Злочин и казна", language="srp"))

    def test_a_script_with_no_romanisation_is_not_judged_at_all(self):
        """Nothing here can read Japanese, Chinese or Arabic, so a claim about
        one is left alone rather than guessed at."""
        assert not I.language_contradicts_script(rec("海辺のカフカ", language="eng"))
        assert not I.language_contradicts_script(rec("بين القصرين", language="ita"))

    def test_an_unrecorded_language_cannot_be_contradicted(self):
        assert not I.language_contradicts_script(
            rec("Преступление и наказание", language=langs.UNKNOWN))

    def test_a_latin_title_in_a_latin_script_language_is_fine(self):
        assert not I.language_contradicts_script(rec("Nineteen eighty-four",
                                                     language="eng"))

    def test_one_greek_letter_in_a_latin_title_is_not_a_contradiction(self):
        """`LIGE001533` is `4: Odyssea P-Ω`, a Greek/Latin parallel edition of
        the *Odysseia* filed `lat`. The Ω is a volume range, not the language:
        the first version of this rule disbelieved it, which is why the rule
        counts letters instead of looking for one."""
        assert not I.language_contradicts_script(rec("4: Odyssea P-Ω", language="lat"))

    def test_a_record_with_no_title_is_not_judged(self):
        assert not I.language_contradicts_script(rec("", language="eng"))


class TestCreditedToAnother:
    """The non-edition label. It labels; it never filters (F16)."""

    def test_the_penguin_readers_retelling_is_credited_to_its_reteller(self):
        """`TO10037839`, linked to *Nineteen Eighty-Four*, headed by SBN under
        MacKenzie rather than Orwell."""
        assert I.credited_to_another(rec("Nineteen eighty-four",
                                         authors=["MacKenzie, Fiona"]),
                                     ["George Orwell"]) == "Fiona MacKenzie"

    def test_the_work_s_own_author_is_not_labelled(self):
        assert I.credited_to_another(rec("x", authors=["Orwell, George"]),
                                     ["George Orwell"]) is None

    def test_a_second_romanisation_of_the_same_man_is_not_labelled(self):
        """SBN heads ten *Bayn al-qasrayn* records `Maḥfūẓ, Naǧīb` where the
        reader typed `Naguib Mahfouz`. Its authority cannot settle it — SBN
        holds him under four ids — so `names_agree` does."""
        assert I.credited_to_another(rec("Palace walk", authors=["Maḥfūẓ, Naǧīb"]),
                                     ["Naguib Mahfouz"]) is None

    def test_a_latinised_form_of_the_same_name_is_not_labelled(self):
        """SBN heads 848 of the corpus's *Odysseia* records `Homerus`, and S1
        reaches no authority id for a bare `Homer` at all."""
        assert I.credited_to_another(rec("Odyssea", authors=["Homerus"]),
                                     ["Homer"]) is None

    def test_one_matching_name_of_several_is_enough(self):
        assert I.credited_to_another(
            rec("x", authors=["Manara, Milo", "Eco, Umberto"]), ["Umberto Eco"]) is None

    def test_a_record_with_no_author_is_not_labelled(self):
        assert I.credited_to_another(rec("x"), ["George Orwell"]) is None

    def test_a_work_with_no_author_labels_nothing(self):
        """With nothing to compare against, silence is the only honest answer."""
        assert I.credited_to_another(rec("x", authors=["Manara, Milo"]), []) is None
        assert I.credited_to_another(rec("x", authors=["Manara, Milo"]), None) is None

    def test_the_study_guide_and_the_omnibus_are_missed_and_that_is_stated(self):
        """`VIA0214939` (York Notes) and `TO02081267` (*Romanzi e saggi*) are
        both headed by Orwell. The label is not a filter and does not claim to
        catch them — the reason the list says so once, in prose."""
        assert I.credited_to_another(
            rec("George Orwell: Nineteen eighty-four / notes by Robert Welch",
                authors=["Orwell, George"]), ["George Orwell"]) is None
        assert I.credited_to_another(rec("Romanzi e saggi", authors=["Orwell, George"]),
                                     ["George Orwell"]) is None


class TestNamesAgree:
    def test_the_ordinary_case_is_token_agreement(self):
        assert I.names_agree("George Orwell", "Orwell, George")

    def test_two_romanisations_of_one_surname_agree(self):
        assert I.names_agree("Naguib Mahfouz", "Maḥfūẓ, Naǧīb")

    def test_a_latinised_form_agrees_with_its_stem(self):
        assert I.names_agree("Homer", "Homerus")

    def test_different_people_do_not(self):
        assert not I.names_agree("George Orwell", "MacKenzie, Fiona")
        assert not I.names_agree("Umberto Eco", "Manara, Milo")

    def test_a_short_stem_never_matches_on_its_prefix(self):
        """`Eco` reduces to one consonant. Below NAME_STEM_MIN the prefix rule
        is off, or every name starting with a `c` would be Umberto Eco."""
        assert I.name_skeleton("Eco") == {"c"}
        assert not I.names_agree("Eco", "Calvino, Italo")

    def test_nothing_in_gives_nothing_out(self):
        """An empty skeleton must never match everything."""
        assert I.name_skeleton("") == set()
        assert I.name_skeleton(None) == set()
        assert not I.names_agree("Homer", "")


class TestIsBookMedium:
    def test_a_documentary_about_the_author_is_not_an_edition_of_the_text(self):
        """'An ecology of mind: a daughter's portrait of Gregory Bateson' scored
        0.67 against 'Steps to an Ecology of Mind', so it has to be excluded on
        what it is, not what it is called."""
        assert not I.is_book_medium(rec("x", medium="documento da proiettare o video"))

    def test_an_audiobook_is_an_edition_of_the_text(self):
        assert I.is_book_medium(rec("x", medium="registrazione sonora"))

    def test_a_record_with_no_medium_is_a_book(self):
        assert I.is_book_medium(rec("x"))


class TestHasTranslationEvidence:
    def test_a_named_translator_is_evidence(self):
        assert I.has_translation_evidence(rec("x", translators=["Cicogna, Enrico"]))

    def test_free_text_is_evidence(self):
        assert I.has_translation_evidence(rec("x", evidence=["traduzione di X"]))

    def test_neither_is_not(self):
        assert not I.has_translation_evidence(rec("x"))


# ---------------------------------------------------------------------------
# The rest of the gate's arithmetic
# ---------------------------------------------------------------------------

class TestTierWithNoSecondSignalToRead:
    def test_a_low_a_and_no_b_at_all_is_refused(self):
        """B is only computed when A is below the bar, and it can come back None
        — no record of this title in the query at all. That is not a pass."""
        assert I.tier(0.0, None) == I.WORK_REJECTED


# ---------------------------------------------------------------------------
# 5. Step 6: accepting a work, the Open Library work, the name authority
# ---------------------------------------------------------------------------

class TestWorkIsAccepted:
    """Which tiers may be used as the work's identity, and which may not."""

    def test_strong_is_the_work(self):
        assert I.work_is_accepted(I.WORK_STRONG)
        assert I.work_is_accepted(I.WORK_STRONG, False)

    def test_weak_on_its_own_is_not(self):
        """B = 0.5 is where *Tesi di filosofia della storia* and *Angelus Novus*
        sit — above every refused classic. It states nothing by itself."""
        assert not I.work_is_accepted(I.WORK_WEAK)
        assert not I.work_is_accepted(I.WORK_REJECTED)

    def test_the_second_signal_is_the_way_in_for_both(self):
        """Decision A: the rescue is an agreement with an item the Wikidata
        title test already accepted, not a lower bar."""
        assert I.work_is_accepted(I.WORK_WEAK, True)
        assert I.work_is_accepted(I.WORK_REJECTED, True)

    def test_no_work_at_all_is_never_rescued(self):
        """There is nothing to agree with: the facet held no usable value."""
        assert not I.work_is_accepted(I.WORK_NONE, True)


def ol_doc(key, title, authors=("Jacques Attali",), count=1, keys=()):
    return {"id": key, "title": title, "authors": list(authors),
            "edition_count": count, "author_keys": list(keys)}


class TestPickOlWork:
    def test_the_title_test_decides_and_the_count_only_breaks_ties(self):
        """Open Library ranks *Animal Farm* above *1984* on edition count, so
        'the most-published work by this author' picks the wrong book outright."""
        docs = [ol_doc("OL9W", "Animal Farm", ("George Orwell",), 900),
                ol_doc("OL2W", "1984", ("George Orwell",), 300)]
        assert I.pick_ol_work(docs, ["1984"], "Orwell")["key"] == "OL2W"

    def test_the_count_separates_two_docs_the_title_cannot(self):
        docs = [ol_doc("OL1W", "Bruits", count=3), ol_doc("OL2W", "Bruits", count=40)]
        picked = I.pick_ol_work(docs, ["Bruits"], "Attali")
        assert picked["key"] == "OL2W" and picked["edition_count"] == 40
        assert picked["others"] == [("OL1W", "Bruits", 3)]

    def test_a_doc_by_another_author_is_not_this_work(self):
        docs = [ol_doc("OL1W", "Bruits", ("Luigi Russolo",))]
        assert I.pick_ol_work(docs, ["Bruits"], "Attali") is None

    def test_an_author_key_stands_in_for_a_name_it_cannot_read(self):
        """`author_matches` compares ASCII tokens, so it cannot match an author
        Open Library files under 村上春樹 (A7)."""
        docs = [ol_doc("OL1W", "海辺のカフカ", ("村上春樹",), keys=["/authors/OL1A"])]
        picked = I.pick_ol_work(docs, ["海辺のカフカ"], "Murakami Haruki", ["OL1A"])
        assert picked["key"] == "OL1W" and picked["by"] == "author key"

    def test_a_title_below_the_bar_is_refused_however_big_the_work(self):
        docs = [ol_doc("OL1W", "Quale socialismo, quale Europa", count=900)]
        assert I.pick_ol_work(docs, ["Bruits", "Rumori"], "Attali") is None

    def test_any_title_the_work_is_known_by_can_match(self):
        """Open Library files *Umibe no Kafuka* under `海辺のカフカ` and the
        romanised uniform title matches neither it nor the English record."""
        docs = [ol_doc("OL2W", "Kafka on the Shore", ("Haruki Murakami",), 61)]
        titles = ["海辺のカフカ", "Kafka sulla spiaggia", "Kafka on the Shore"]
        assert I.pick_ol_work(docs, titles, "Murakami")["key"] == "OL2W"

    def test_nothing_at_all_is_None_and_not_an_error(self):
        assert I.pick_ol_work([], ["Bruits"], "Attali") is None
        assert I.pick_ol_work([{"title": "Bruits"}], ["Bruits"], "Attali") is None


def auth(id_, heading, kind="Persona"):
    return {"id": id_, "heading": heading, "kind": kind}


class TestPickAuthority:
    GIACOMO = auth("CFIV1", "Leopardi , Giacomo  <1798-1837>")
    MONALDO = auth("CFIV2", "Leopardi , Monaldo")

    def test_a_heading_that_is_the_name_wins(self):
        rows = [auth("A1", "Eco , Umberto  <1932-2016>"), auth("A2", "Eco , Roberto")]
        picked = I.pick_authority(rows, "Umberto Eco", 2)
        assert picked["id"] == "A1" and picked["display"] == "Umberto Eco"

    def test_a_corporate_body_is_never_the_author(self):
        """`Comite impulsor del juicio de responsabilidades contra Luis Garcia
        Marquez y sus colaboradores` contains both tokens and is not a person."""
        rows = [auth("E1", "Comite impulsor ... Luis Garcia Marquez y sus colaboradores", "Ente"),
                auth("P1", "García Márquez , Gabriel")]
        assert I.pick_authority(rows, "Garcia Marquez", 2)["id"] == "P1"

    def test_the_fullest_form_is_tried_first(self):
        """*Pasternak* alone reaches E. V. Pasternak, the novelist's son."""
        rows = [auth("S1", "Pasternak , E. V."), auth("B1", "Pasternak , Boris Leonidovič")]
        assert I.pick_authority(rows, "Pasternak", 2)["id"] == "S1"
        assert I.pick_authority(rows, "Pasternak", 2, ["Boris Pasternak"])["id"] == "B1"

    def test_two_people_are_no_answer(self):
        picked = I.pick_authority([self.GIACOMO, self.MONALDO], "Leopardi", 2)
        assert picked["id"] is None and picked["rule"].startswith("ambiguous")
        assert len(picked["candidates"]) == 2

    def test_one_person_under_two_ids_is_one_person(self):
        """SBN holds *Pasternak , Boris Leonidovič* twice, once with life dates."""
        rows = [auth("CFIV1", "Pasternak , Boris Leonidovič"),
                auth("RMSV1", "Pasternak , Boris Leonidovič  <1890-1960>")]
        picked = I.pick_authority(rows, "Boris Pasternak", 2)
        assert picked["id"] == "CFIV1" and picked["duplicate_ids"] == ["RMSV1"]

    def test_a_bare_surname_against_a_truncated_set_is_not_resolvable(self):
        """`core=autori` matches the name anywhere and returns rows
        *alphabetically*: 184 for *Leopardi*, of which the first 40 are A–C."""
        picked = I.pick_authority([auth("X1", "Ciriaco Greto , Leopardi")], "Leopardi", 184)
        assert picked["id"] is None and picked["rule"].startswith("not resolved")

    def test_the_same_row_in_an_untruncated_set_is_an_answer(self):
        picked = I.pick_authority([auth("X1", "Leopardi , Giacomo")], "Leopardi", 1)
        assert picked["id"] == "X1"

    def test_the_sole_persona_carries_a_transliteration_the_tokens_miss(self):
        rows = [auth("R1", "Dostoevskij , Fëdor Mihajlovič"), auth("E1", "Biblioteca", "Ente")]
        picked = I.pick_authority(rows, "Dostoyevsky", 2)
        assert picked["id"] == "R1" and picked["rule"].startswith("sole Persona")

    def test_a_big_result_set_does_not_get_the_sole_persona_rule(self):
        rows = [auth("R1", "Dostoevskij , Fëdor Mihajlovič")]
        assert I.pick_authority(rows, "Dostoyevsky", 5000)["id"] is None

    def test_namesakes_are_named_so_a_refusal_can_be_read(self):
        picked = I.pick_authority([self.GIACOMO, self.MONALDO], "Leopardi", 2)
        assert picked["namesakes"] == [self.GIACOMO["heading"], self.MONALDO["heading"]]

    def test_no_name_is_no_answer_rather_than_an_arbitrary_row(self):
        assert I.pick_authority([self.GIACOMO], "")["id"] is None
        assert I.pick_authority([], "Eco", 0)["id"] is None


class TestDuplicateWorks:
    """The list of Open Library's other records a reader may add (Step 13).

    The docs are E16's, as Open Library answered *Doctor Zhivago Pasternak* on
    2026-09-25 (Step 13's live run): the main work, two of
    Stage 2's known duplicates, a companion volume that passes, and a book about
    the heroine's model that does not.
    """

    TITLES = ["Доктор Живаго", "Doctor Zhivago", "Le Docteur Jivago",
              "Doktor Schiwago", "Il dottor Živago", "El doctor Zhivago"]

    def docs(self):
        return [
            ol_doc("OL258301W", "Доктор Живаго", ("Boris Pasternak",), 176),
            ol_doc("OL38068744W", "Doctor Zhivago", ("Boris Pasternak",), 11),
            ol_doc("OL31357567W", "Doctor Zhivago", ("Boris Pasternak",), 13),
            ol_doc("OL31702700W", "The Poems Of Doctor Zhivago", ("Boris Pasternak",), 5),
            ol_doc("OL19743505W", "Lara", ("Boris Pasternak",), 6),
            ol_doc("OL1W", "Doctor Zhivago", ("Robert Bolt",), 3),
        ]

    def test_the_main_work_is_not_its_own_duplicate(self):
        rows = I.duplicate_works(self.docs(), self.TITLES, "Pasternak",
                                 main_keys=["/works/OL258301W"])
        assert "OL258301W" not in [r["key"] for r in rows]

    def test_the_title_and_author_tests_decide_and_nothing_else(self):
        """*Lara* is by the right man and scores 0.0; the screenplay is the
        right title by another. Neither is offered. The companion volume
        scores 0.667 and is — which is why a row carries its count."""
        rows = I.duplicate_works(self.docs(), self.TITLES, "Pasternak",
                                 main_keys=["OL258301W"])
        assert [r["key"] for r in rows] == ["OL31357567W", "OL38068744W", "OL31702700W"]
        assert rows[-1]["score"] == 0.667 and rows[-1]["editions"] == 5

    def test_most_editions_first_whatever_order_the_searches_gave(self):
        once = I.duplicate_works(self.docs(), self.TITLES, "Pasternak")
        again = I.duplicate_works(list(reversed(self.docs())), self.TITLES, "Pasternak")
        assert once == again and once[0]["key"] == "OL258301W"

    def test_a_doc_two_searches_found_is_listed_once(self):
        docs = self.docs() + self.docs()
        rows = I.duplicate_works(docs, self.TITLES, "Pasternak", main_keys=["OL258301W"])
        assert len(rows) == 3

    def test_an_author_key_stands_in_for_a_name_it_cannot_read(self):
        """The same fallback `pick_ol_work` has, for an author filed as 村上春樹."""
        docs = [ol_doc("OL9W", "Kafka on the Shore", ("村上春樹",),
                       keys=["/authors/OL2A"]), {"title": "no key"}]
        rows = I.duplicate_works(docs, ["Kafka on the Shore"], "Murakami Haruki", ["OL2A"])
        assert [(r["key"], r["by"]) for r in rows] == [("OL9W", "author key")]
        assert I.duplicate_works(docs, ["Kafka on the Shore"], "Murakami Haruki") == []


def _rows(*titles):
    return [{"title": t.split(" / ")[0], "full": t} for t in titles]


class TestWorkLanguageContradicted:
    """Step 15B. SBN's work authority states a language; its own records can
    contradict it. Literals from live OPAC listings, 2026-09-27."""

    def test_records_in_the_language_all_titled_otherwise_contradict(self):
        assert I.work_language_contradicted("bain el-qasrain.", _rows("Tra i due palazzi"))

    def test_no_records_in_the_language_contradict_nothing(self):
        assert not I.work_language_contradicted("umibe no kafuka", [])

    def test_a_record_titled_like_the_work_agrees(self):
        assert not I.work_language_contradicted("nome della rosa", _rows("Il nome della rosa"))

    def test_pinyin_split_into_syllables_agrees(self):
        assert not I.work_language_contradicted("huozhe", _rows("Huo zhe"))

    def test_a_record_translated_from_that_language_is_not_evidence_of_it(self):
        """`UBO4636099`, an English translation SBN files GIAPPONESE (trap 1b),
        is the only 'Japanese' *Kafka*. Rule 4: it stops being evidence of a
        language, so nothing contradicts GIAPPONESE."""
        assert not I.work_language_contradicted("umibe no kafuka", _rows(
            "Kafka on the shore / Haruki Murakami ; translated from the Japanese "
            "by Philip Gabriel"))

    def test_an_untranslated_record_titled_otherwise_still_contradicts(self):
        assert I.work_language_contradicted("umibe no kafuka", _rows(
            "Kafka on the shore / Haruki Murakami"))


def cand(source, authors, title="Noise", year=None, editions=1):
    return {"source": source, "title": title, "authors": list(authors),
            "year": year, "editions": editions}


class TestTitleBooks:
    """Decision AN. A bare title's candidates, grouped by person. The names and
    counts are the ones Step 15B's title-only probe read."""

    def test_one_person_across_sources_is_one_book(self):
        books = I.title_books([
            cand("Wikidata", ["Gregory Bateson"], "Verso un'ecologia della mente", 1972),
            cand("Open Library", ["Gregory Bateson"], "Verso un'ecologia della mente", None, 2),
            cand("SBN", ["Bateson, Gregory"], "Verso un'ecologia della mente", 1976)])
        assert books == [{"authors": ["Gregory Bateson"],
                          "title": "Verso un'ecologia della mente", "first_year": 1972,
                          "editions": 4, "sources": ["Open Library", "SBN", "Wikidata"]}]

    def test_a_shared_author_joins_two_candidates_and_another_person_does_not(self):
        books = I.title_books([
            cand("SBN", ["Ruesch, Jurgen"], "La matrice sociale della psichiatria", 1976),
            cand("Open Library", ["Jurgen Ruesch", "Gregory Bateson"], "Communication"),
            cand("SBN", ["Shepherd, Michael"], "La matrice sociale della psichiatria", 1990)])
        assert [b["authors"] for b in books] == [["Jurgen Ruesch", "Gregory Bateson"],
                                                 ["Michael Shepherd"]]

    def test_a_candidate_bridging_two_books_merges_them(self):
        books = I.title_books([cand("SBN", ["Ruesch, Jurgen"]),
                               cand("SBN", ["Bateson, Gregory"]),
                               cand("Open Library", ["Jurgen Ruesch", "Gregory Bateson"])])
        assert len(books) == 1 and books[0]["editions"] == 3

    def test_a_candidate_naming_nobody_is_not_a_book(self):
        assert I.title_books([cand("SBN", [])]) == []


class TestIsTextMedium:
    def test_a_printed_or_manuscript_text_is_one(self):
        assert I.is_text_medium("Testo a stampa") and I.is_text_medium("Testo manoscritto")

    def test_a_recording_or_a_film_is_not(self):
        assert not I.is_text_medium("Registrazione sonora")
        assert not I.is_text_medium("Documento da proiettare o video")

    def test_a_record_stating_no_medium_is_not_refused(self):
        assert I.is_text_medium(None) and I.is_text_medium("")


class TestAdoptedBook:
    def _book(self, sources, editions=1, who="X"):
        return {"authors": [who], "title": "t", "first_year": None,
                "editions": editions, "sources": list(sources)}

    def test_the_only_book_is_adopted(self):
        only = self._book(["SBN"])
        assert I.adopted_book([only]) is only

    def test_a_lone_sbn_record_does_not_outweigh_a_corroborated_book(self):
        """*Verso un'ecologia della mente*: Bateson on three sources, and one
        SBN record by Paolo Migrino."""
        bateson = self._book(["Open Library", "SBN", "Wikidata"], 28, "Gregory Bateson")
        migrino = self._book(["SBN"], 1, "Paolo Migrino")
        assert I.adopted_book([bateson, migrino]) is bateson

    def test_two_corroborated_books_are_a_choice(self):
        """*Noise*: Kahneman's and Nihei's are both on Open Library and SBN."""
        assert I.adopted_book([self._book(["Open Library", "SBN"], 23),
                               self._book(["Open Library", "SBN"], 3)]) is None

    def test_a_second_book_anybody_else_knows_is_a_choice(self):
        """*Opere*: Open Library names Machiavelli only, SBN 56 others."""
        assert I.adopted_book([self._book(["Open Library", "SBN"], 45),
                               self._book(["Open Library"], 2)]) is None
        assert I.adopted_book([self._book(["Open Library", "SBN"], 45),
                               self._book(["SBN"], 2)]) is None

    def test_nobody_agreed_on_is_a_choice(self):
        """*La matrice sociale della psichiatria*: Ruesch and Shepherd, one SBN
        record each, and nothing else."""
        assert I.adopted_book([self._book(["SBN"]), self._book(["SBN"])]) is None
