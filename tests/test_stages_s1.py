"""S1 — `lookup/stages.identify`, offline, with the catalogues stubbed out.

The gates S1 calls are tested in `test_core_identity.py`; what is tested here is
the **wiring**, which is where this step can go wrong without any gate being
wrong: asking the OPAC a question F15 says it will silently mis-answer, letting
a weak work state an original, searching Open Library with the typed title
before the work's own, or losing an identity because one source was down.

Every catalogue call is monkeypatched. `conftest.py` blocks sockets for the
whole session, so a stub that forgets to intercept fails loudly rather than
quietly measuring live data.
"""

import pytest

from core import identity as gate
from lookup import stages


# ---------------------------------------------------------------------------
# Stubs. Each one is the shape `catalog/` actually returns.
# ---------------------------------------------------------------------------

def facet(value, count=9, label=None, total=20, items=None):
    return {"items": items if items is not None else
            [{"value": value, "results": count, "label": label or value}],
            "total": total, "first": {}}


def entity(label="Bruits", it="Rumori", sitelinks=(), p1476=None, lang="fr",
           year="1977", authors=("Q2",), p31=("Q571",)):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": c}}}} for c in p31],
              "P50": [{"mainsnak": {"datavalue": {"value": {"id": a}}}} for a in authors],
              "P407": [{"mainsnak": {"datavalue": {"value": {"id": "Q150"}}}}],
              "P577": [{"mainsnak": {"datavalue": {"value": {"time": f"+{year}-01-01T00:00:00Z"}}}}]}
    if p1476:
        claims["P1476"] = [{"mainsnak": {"datavalue": {"value": {"text": p1476,
                                                                 "language": lang}}}}]
    return {"labels": {"fr": {"value": label}, "it": {"value": it}},
            "sitelinks": {f"{w}wiki": {"title": t} for w, t in sitelinks},
            "claims": claims}


def doc(key="OL1W", title="Bruits", authors=("Jacques Attali",), count=12, ddc=("780.07",)):
    return {"key": f"/works/{key}", "title": title, "author_name": list(authors),
            "author_key": [], "edition_count": count, "ddc": list(ddc),
            "first_publish_year": 1977, "language": ["fre"], "publisher": ["Fayard"],
            "isbn": [], "subject": []}


@pytest.fixture
def catalogues(monkeypatch):
    """Every source answering nothing, and a handle to make one answer."""
    empty = {"rows": [], "total": 0, "pages": 1, "failed": [], "truncated": False}
    state = {"facet": {"items": [], "total": 0, "first": {}},
             "query_rows": empty, "work_rows": empty,
             "entities": {}, "candidates": [], "docs": [], "authorities": {"rows": [], "total": 0},
             "labels": {"Q2": "Jacques Attali"}, "asked": [],
             "languages": [], "links": [], "authority": {"language": None, "variants": []},
             "in_language": empty}

    def all_rows(body, **kw):
        """The guard asks twice: `ANY + AUTHOR`, then the same plus `W` (F2 —
        keeping ANY returns the intersection). They are different questions and
        the stub answers them separately, or B is 1.0 by construction."""
        if stages.sbn_opac.LANGUAGE in body:
            state["asked"].append(("language page", body[stages.sbn_opac.LANGUAGE]))
            return state["in_language"]
        return state["work_rows"] if stages.sbn_opac.WORK in body else state["query_rows"]

    def work_languages(work, author):
        state["asked"].append(("work authority", work, author))
        return {"items": state["languages"], "total": 1,
                "first": state.get("listing_first") or
                {"results": [{"id": "ITICCURMS2685379",
                              "title": {"info": "x", "text": "y"}, "infos": []}]}}

    def work_facet(title, author):
        state["asked"].append(("opac", title, author))
        if not (title and author):
            raise ValueError("the OPAC work query always carries the author")
        return state["facet"]

    def search(q=None, **kw):
        state["asked"].append(("ol", q))
        return state["docs"]

    monkeypatch.setattr(stages.sbn_opac, "work_facet", work_facet)
    monkeypatch.setattr(stages.sbn_opac, "all_rows", all_rows)
    monkeypatch.setattr(stages.sbn_opac, "work_languages", work_languages)
    monkeypatch.setattr(stages.sbn_opac, "record", lambda bid: {})
    monkeypatch.setattr(stages.sbn_opac, "work_links", lambda payload: state["links"])
    monkeypatch.setattr(stages.sbn_opac, "work_authority", lambda wid: state["authority"])
    monkeypatch.setattr(stages.sbn_opac, "authorities", lambda text, **k: state["authorities"])
    monkeypatch.setattr(stages.wikidata, "page_to_qid", lambda wiki, title: None)
    monkeypatch.setattr(stages.wikidata, "search_pages", lambda wiki, q, **k: [])
    monkeypatch.setattr(stages.wikidata, "titles_to_qids", lambda wiki, titles: {})
    monkeypatch.setattr(stages.wikidata, "entities", lambda qids, **k: state["entities"])
    monkeypatch.setattr(stages.wikidata, "labels", lambda qids, **k: state["labels"])
    monkeypatch.setattr(stages.wikidata, "names", lambda qids, **k: state.get("names") or {
        q: [v] for q, v in state["labels"].items()})
    monkeypatch.setattr(stages, "_candidate_qids", lambda t, a: state["candidates"])
    monkeypatch.setattr(stages.ol, "search", search)
    monkeypatch.setattr(stages.ol, "author_keys", lambda author, **k: [])
    return state


# ---------------------------------------------------------------------------
# S0
# ---------------------------------------------------------------------------

class TestPrepare:
    def test_cyrillic_and_greek_are_romanised_and_said_to_be(self):
        q = stages.prepare("Доктор Живаго", "Pasternak")
        assert (q.title, q.author) == ("Doktor Zhivago", "Pasternak")
        assert q.typed_title == "Доктор Живаго"
        assert q.sendable and "romanised" in q.notes[0]

    def test_a_script_that_cannot_be_romanised_is_not_sendable_and_says_why(self):
        """F15: the OPAC discards the term and answers with the unfiltered set,
        so this is the difference between no answer and a wrong one."""
        q = stages.prepare("海辺のカフカ", "Murakami Haruki")
        assert not q.sendable
        assert "F15" in q.notes[0] and "not sent" in q.notes[0]

    def test_latin_input_is_left_exactly_as_typed(self):
        q = stages.prepare("  Cien años de soledad ", "Garcia Marquez")
        assert (q.title, q.author) == ("Cien años de soledad", "Garcia Marquez")
        assert q.notes == [] and q.sendable

    def test_a_missing_half_is_not_sendable(self):
        assert not stages.prepare("Rumori", "").sendable
        assert not stages.prepare("", "Attali").sendable


# ---------------------------------------------------------------------------
# S1
# ---------------------------------------------------------------------------

class TestTheOpacIsNotAskedWhatItCannotAnswer:
    def test_a_non_latin_question_never_reaches_the_opac(self, catalogues):
        ident = stages.identify("海辺のカフカ", "村上春樹")
        assert [a for a in catalogues["asked"] if a[0] == "opac"] == []
        assert "F15" in ident.evidence["sbn_work"]["state"]
        assert ident.evidence["authority"]["state"].startswith("not asked")

    def test_a_latin_question_does(self, catalogues):
        stages.identify("Rumori", "Attali")
        assert ("opac", "Rumori", "Attali") in catalogues["asked"]


class TestTheWorkGuard:
    def test_a_title_that_is_the_uniform_title_is_strong_on_one_request(self, catalogues):
        catalogues["facet"] = facet("rumori")
        ident = stages.identify("Rumori", "Attali")
        assert ident.work.sbn_work == "rumori"
        assert ident.work.sbn_work_tier == gate.WORK_STRONG
        assert ident.evidence["sbn_work"]["b_requests"] == 0

    def test_b_runs_only_below_the_bar_and_is_counted(self, catalogues):
        catalogues["facet"] = facet("bruits : essai sur l'economie politique de la musique")
        one = {"rows": [{"id": "RAV1", "title": "Rumori"}],
               "total": 1, "pages": 1, "failed": [], "truncated": False}
        catalogues["query_rows"] = catalogues["work_rows"] = one
        ev = stages.identify("Rumori", "Attali").evidence["sbn_work"]
        assert ev["A"] == 0.0 and ev["B"] == 1.0
        assert ev["tier"] == gate.WORK_STRONG
        assert ev["b_requests"] == 1        # (query pages - 1) + work pages

    def test_a_weak_work_no_item_agrees_with_is_not_the_work(self, catalogues):
        """*Tesi di filosofia della storia* and *Angelus Novus* sit at B = 0.5,
        above every refused classic. Weak on its own states nothing."""
        catalogues["facet"] = facet("angelus novus")
        catalogues["query_rows"] = {"rows": [{"id": "A", "title": "Tesi"},
                                             {"id": "B", "title": "Tesi"}],
                                    "total": 2, "pages": 1, "failed": [], "truncated": False}
        catalogues["work_rows"] = {"rows": [{"id": "A", "title": "Tesi"}],
                                   "total": 1, "pages": 1, "failed": [], "truncated": False}
        monkey = stages.gate.share_b
        ident = stages.identify("Tesi", "Benjamin")
        assert ident.evidence["sbn_work"]["tier"] == gate.WORK_WEAK
        assert ident.work.sbn_work is None
        assert ident.work.original_title is None
        assert monkey is stages.gate.share_b     # the gate itself was not swapped

    def test_an_adaptation_is_never_the_work(self, catalogues):
        catalogues["facet"] = facet(None, items=[
            {"value": "nome della rosa <film ; 1986>", "results": 40,
             "label": "nome della rosa <film ; 1986>"},
            {"value": "nome della rosa", "results": 10, "label": "nome della rosa"}])
        ident = stages.identify("Il nome della rosa", "Eco")
        assert ident.work.sbn_work == "nome della rosa"


class TestTheSecondSignal:
    def test_it_rescues_a_weak_work_the_item_agrees_with(self, catalogues):
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="Odysseia", it="The Odyssey",
                                              p1476="Ὀδύσσεια")}
        catalogues["labels"] = {"Q2": "Homer"}
        catalogues["facet"] = facet("odyssea")
        catalogues["query_rows"] = {"rows": [{"id": "A", "title": "Odissea"},
                                             {"id": "B", "title": "Odissea"}],
                                    "total": 2, "pages": 1, "failed": [], "truncated": False}
        catalogues["work_rows"] = {"rows": [{"id": "A", "title": "Odissea"}],
                                   "total": 1, "pages": 1, "failed": [], "truncated": False}
        ident = stages.identify("The Odyssey", "Homer")
        assert ident.evidence["sbn_work"]["tier"] in (gate.WORK_WEAK, gate.WORK_REJECTED)
        assert ident.evidence["second_signal"]["agrees"]
        assert ident.work.sbn_work == "odyssea"
        assert ident.work.sbn_work_via_second_signal

    def test_it_is_not_asked_when_the_guard_was_already_strong(self, catalogues):
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity()}
        catalogues["facet"] = facet("bruits")
        ident = stages.identify("Bruits", "Attali")
        assert ident.evidence["second_signal"] is None
        assert not ident.work.sbn_work_via_second_signal


class TestWikidata:
    def test_an_item_the_title_test_refuses_states_nothing(self, catalogues):
        catalogues["candidates"] = ["Q9"]
        catalogues["entities"] = {"Q9": entity(label="Quale socialismo, quale Europa")}
        ident = stages.identify("Bruits", "Attali")
        assert ident.work.qid is None
        assert ident.work.original_title is None and ident.work.stated_by == ""
        assert "title 0.00" in ident.evidence["wikidata"]["rejected"][0][1]

    def test_an_accepted_item_states_the_original_and_says_so(self, catalogues):
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(p1476="Bruits")}
        ident = stages.identify("Rumori", "Attali")
        w = ident.work
        assert w.qid == "Q1" and w.original_title == "Bruits"
        assert w.original_year == "1977" and w.stated_by == "Wikidata"
        assert "accepted" in w.basis and w.authors == ["Jacques Attali"]

    def test_a_work_by_another_author_is_refused_before_the_title_test(self, catalogues):
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(p1476="Bruits")}
        ident = stages.identify("Rumori", "Russolo")
        assert ident.work.qid is None
        assert ident.evidence["wikidata"]["rejected"] == [("Q1", "author disagrees")]

    def test_the_author_is_judged_on_every_label_the_person_carries(self, catalogues):
        """N04: Q991 is *Fyodor Dostoyevsky* in English, which shares no token
        with what was typed, and *Fëdor Dostoevskij* in Italian, which does."""
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="Crime and Punishment",
                                              it="Delitto e castigo", lang="ru")}
        catalogues["labels"] = {"Q2": "Fyodor Dostoyevsky"}
        catalogues["names"] = {"Q2": ["Fyodor Dostoyevsky", "Fëdor Dostoevskij"]}
        ident = stages.identify("Delitto e castigo", "Fëdor Dostoevskij")
        assert ident.work.qid == "Q1"
        assert ident.work.authors == ["Fyodor Dostoyevsky"]     # the shown name

    def test_an_item_titled_in_kanji_is_found_by_the_titles_sbn_files_under_w(
            self, catalogues):
        """E04: `umibe no kafuka` matches none of Q579744's names, but SBN's
        records under that work are titled *Kafka sulla spiaggia*, which is its
        Italian label. Open Library is then asked again with the item's titles,
        and finds the work it files under `海辺のカフカ`."""
        catalogues["facet"] = facet("umibe no kafuka")
        catalogues["listing_first"] = {"results": [
            {"id": f"ITICCUUBO{n}", "title": {"info": t, "text": "Murakami, Haruki"},
             "infos": []} for n, t in enumerate([
                 "Kafka sulla spiaggia / Haruki Murakami", "Kafka sulla spiaggia / Haruki Murakami",
                 "Umibe no Kafuka / Murakami Haruki"])]}
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="Kafka on the Shore",
                                              it="Kafka sulla spiaggia",
                                              p1476="海辺のカフカ", lang="ja", year="2002")}
        catalogues["labels"] = {"Q2": "Haruki Murakami"}
        catalogues["docs"] = [doc(key="OL2625431W", title="海辺のカフカ",
                                  authors=("Haruki Murakami",))]
        ident = stages.identify("Umibe no Kafuka", "Murakami Haruki")
        assert ident.evidence["wikidata_by_records"]["titles"] == ["Kafka sulla spiaggia"]
        assert ident.work.qid == "Q1" and ident.work.original_year == "2002"
        assert "a title SBN files under its work" in ident.work.basis
        assert ident.work.ol_keys == ["OL2625431W"]
        assert ident.evidence["open_library_again"]["found_by"] == "original title"

    def test_no_title_is_asked_twice_and_none_in_another_script(self, catalogues):
        catalogues["facet"] = facet("huozhe")
        catalogues["listing_first"] = {"results": [
            {"id": f"ITICCUX{n}", "title": {"info": t, "text": ""}, "infos": []}
            for n, t in enumerate(["Huozhe / Yu Hua", "活着 / 余华", "Vivere! / Yu Hua"])]}
        ident = stages.identify("Huozhe", "Yu Hua")
        assert ident.evidence["wikidata_by_records"]["titles"] == ["Vivere!"]

    def test_an_edition_of_the_work_is_not_the_work(self, catalogues):
        """Step 11. `Q138528911` is the 2024 Spanish translation of
        *Müdigkeitsgesellschaft*, labelled *The Burnout Society* and with no
        `P629` back to the work: believed, it makes the header say the book was
        first published in 2024 in Spanish. It is refused with its reason, and
        the entry then states no original, which is the honest answer."""
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(p1476="Bruits",
                                               p31=("Q47461344", "Q3331189"))}
        ident = stages.identify("Rumori", "Attali")
        assert ident.work.qid is None
        assert ident.work.original_title is None and ident.work.stated_by == ""
        assert ident.evidence["wikidata"]["rejected"] == [
            ("Q1", "an edition of a work, not the work")]

    def test_the_refusal_is_the_class_and_not_the_absence_of_a_link(self, catalogues):
        """An item with the same shape but no edition class is still believed:
        the rule reads P31, and a work with a thin record is not an edition."""
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(p1476="Bruits", p31=("Q47461344",))}
        assert stages.identify("Rumori", "Attali").work.qid == "Q1"


class TestTheWorksOwnTitles:
    """Step 15B, decision AN. A typed title is often one no item carries —
    *Vita da uomo* scores 0.00 against Q183883 — so once a catalogue has said
    what the work is called, the item is judged again against that."""

    def _catcher(self, catalogues):
        catalogues["labels"] = {"Q2": "J. D. Salinger"}
        catalogues["facet"] = facet("catcher in the rye")
        rows = {"rows": [{"id": "UM1", "title": "Vita da uomo"}],
                "total": 1, "pages": 1, "failed": [], "truncated": False}
        catalogues["query_rows"] = catalogues["work_rows"] = rows
        catalogues["candidates"] = ["Q1"]

    def test_the_item_refused_on_the_typed_title_is_accepted_on_the_works(self, catalogues):
        self._catcher(catalogues)
        catalogues["entities"] = {"Q1": entity(label="The Catcher in the Rye",
                                               it="Il giovane Holden",
                                               p1476="The Catcher in the Rye", lang="en",
                                               year="1951")}
        ident = stages.identify("Vita da uomo", "Salinger")
        w = ident.work
        assert "title 0.00" in ident.evidence["wikidata"]["rejected"][0][1]
        assert w.qid == "Q1" and w.stated_by == "Wikidata"
        assert w.original_title == "The Catcher in the Rye" and w.original_year == "1951"
        assert "the work's title" in w.basis

    def test_an_item_titled_like_neither_is_still_refused(self, catalogues):
        self._catcher(catalogues)
        catalogues["entities"] = {"Q1": entity(label="Franny and Zooey", it="Franny e Zooey")}
        ident = stages.identify("Vita da uomo", "Salinger")
        assert ident.work.qid is None and ident.work.stated_by == ""
        assert ident.evidence["wikidata_by_work"]["rejected"]

    def test_with_no_work_named_wikidata_is_not_asked_again(self, catalogues):
        catalogues["candidates"] = ["Q9"]
        catalogues["entities"] = {"Q9": entity(label="Quale socialismo, quale Europa")}
        assert stages.identify("Bruits", "Attali").evidence["wikidata_by_work"] is None


class TestTheSbnWorkAuthority:
    """SBN's work record states a language (`title?core=opere`), and is
    believed unless the work's own records in that language contradict it."""

    def _invention(self, catalogues, language="INGLESE", languages=(), titles=()):
        catalogues["facet"] = facet("invention of news")
        rows = {"rows": [{"id": "RMS2685379", "title": "L'invenzione delle notizie"}],
                "total": 1, "pages": 1, "failed": [], "truncated": False}
        catalogues["query_rows"] = catalogues["work_rows"] = rows
        catalogues["links"] = [{"id": "RMS2685380", "label": "The invention of news"}]
        catalogues["authority"] = {"language": language, "variants": []}
        catalogues["languages"] = [{"value": code, "results": 1} for code in languages]
        catalogues["in_language"] = {"rows": [{"id": f"R{i}", "title": t}
                                              for i, t in enumerate(titles)],
                                     "total": len(titles), "pages": 1, "failed": [],
                                     "truncated": False}
        catalogues["labels"] = {"Q2": "Andrew Pettegree"}

    def test_a_stated_language_with_no_records_in_it_is_believed(self, catalogues):
        self._invention(catalogues)
        w = stages.identify("L'invenzione delle notizie", "Pettegree").work
        assert w.original_language == "eng" and w.original_year is None
        assert w.stated_by == "SBN work authority" and "RMS2685380" in w.basis

    def test_records_titled_like_the_work_keep_it(self, catalogues):
        self._invention(catalogues, languages=("eng",),
                        titles=("The invention of news : how the world came to know about itself",))
        w = stages.identify("L'invenzione delle notizie", "Pettegree").work
        assert w.original_language == "eng"

    def test_records_in_that_language_all_titled_otherwise_refuse_it(self, catalogues):
        """*bain el-qasrain* is filed ITALIANO, and every Italian record of it
        is *Tra i due palazzi*. Disbelieved, never corrected."""
        catalogues["facet"] = facet("bain el-qasrain")
        catalogues["links"] = [{"id": "CFI0193626", "label": "Bain el-Qasrain"}]
        catalogues["authority"] = {"language": "ITALIANO", "variants": []}
        catalogues["languages"] = [{"value": "ita", "results": 3}]
        catalogues["in_language"] = {"rows": [{"id": "R1", "title": "Tra i due palazzi"}],
                                     "total": 1, "pages": 1, "failed": [], "truncated": False}
        ident = stages.identify("Bain el-Qasrain", "Mahfuz")
        assert ident.work.original_language is None and ident.work.stated_by == ""
        assert ident.evidence["sbn_work_language"]["contradicted"] is True

    def test_not_asked_when_wikidata_stated_the_language(self, catalogues):
        catalogues["facet"] = facet("rumori")
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(p1476="Bruits")}
        ident = stages.identify("Rumori", "Attali")
        assert ident.work.original_language == "fre"
        assert not any(a[0] == "work authority" for a in catalogues["asked"])

    def test_a_link_to_another_work_is_not_read(self, catalogues):
        self._invention(catalogues)
        catalogues["links"] = [{"id": "X1", "label": "Postille a il nome della rosa"}]
        ident = stages.identify("L'invenzione delle notizie", "Pettegree")
        assert ident.work.original_language is None
        assert ident.evidence["sbn_work_language"]["id"] is None


class TestOpenLibrary:
    def test_the_original_title_is_searched_before_the_typed_one(self, catalogues):
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(p1476="Bruits")}
        catalogues["docs"] = [doc()]
        ident = stages.identify("Rumori", "Attali")
        searched = [a[1] for a in catalogues["asked"] if a[0] == "ol"]
        assert searched[0] == "Bruits Attali"
        assert ident.work.ol_keys == ["OL1W"] and ident.work.ol_title == "Bruits"
        assert ident.evidence["open_library"]["found_by"] == "original title"

    def test_the_title_test_beats_the_edition_count(self, catalogues):
        """The count alone picks *Animal Farm* for *1984*."""
        catalogues["labels"] = {"Q2": "George Orwell"}
        catalogues["docs"] = [doc(key="OL9W", title="Animal Farm", count=900,
                                  authors=("George Orwell",)),
                              doc(key="OL2W", title="1984", count=300,
                                  authors=("George Orwell",))]
        ident = stages.identify("1984", "Orwell")
        assert ident.work.ol_keys == ["OL2W"]

    def test_a_work_found_by_the_uniform_title_states_the_original(self, catalogues):
        """The uniform title is never displayed; what it finds in Open Library is
        the same work properly spelled, and that is a catalogue statement."""
        catalogues["facet"] = facet("more brilliant than the sun")
        rows = {"rows": [{"id": "UM1", "title": "Più brillante del sole"}],
                "total": 1, "pages": 1, "failed": [], "truncated": False}
        catalogues["query_rows"] = catalogues["work_rows"] = rows
        catalogues["docs"] = [doc(key="OL7W", title="More Brilliant Than the Sun",
                                  authors=("Kodwo Eshun",))]
        ident = stages.identify("Più brillante del sole", "Eshun")
        assert ident.work.original_title == "More Brilliant Than the Sun"
        assert ident.work.stated_by == "SBN uniform title, spelled by Open Library"
        assert ident.work.original_language is None      # the title only

    def test_a_work_found_by_the_typed_title_states_no_original(self, catalogues):
        """Rule 8. Open Library agreeing that a work exists under the title that
        was typed is not a statement about what the work was first called."""
        catalogues["docs"] = [doc(key="OL5W", title="Rumori")]
        ident = stages.identify("Rumori", "Attali")
        assert ident.work.ol_keys == ["OL5W"]
        assert ident.work.original_title is None and ident.work.stated_by == ""

    def test_a_title_in_a_script_that_tokenises_to_nothing_still_matches_itself(
            self, catalogues):
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="Kafka on the Shore",
                                              it="Kafka sulla spiaggia",
                                              p1476="海辺のカフカ", lang="ja")}
        catalogues["labels"] = {"Q2": "Haruki Murakami"}
        catalogues["docs"] = [doc(key="OL2625431W", title="海辺のカフカ",
                                  authors=("Haruki Murakami",))]
        ident = stages.identify("Kafka sulla spiaggia", "Murakami Haruki")
        assert ident.work.ol_keys == ["OL2625431W"]

    def _search(self, monkeypatch, answer):
        asked = []

        def search(**kw):
            asked.append(kw)
            return answer(kw)
        monkeypatch.setattr(stages.ol, "search", search)
        return asked

    def test_title_and_author_are_fielded_when_no_free_text_names_a_work(
            self, catalogues, monkeypatch):
        """N13: `Müdigkeitsgesellschaft Byung-Chul Han` as free text finds no
        doc at all, and in their own fields they find the work."""
        catalogues["labels"] = {"Q2": "Byung-Chul Han"}
        found = doc(key="OL17795654W", title="Müdigkeitsgesellschaft",
                    authors=("Byung-Chul Han",))
        asked = self._search(monkeypatch, lambda kw: [found] if "title" in kw else [])
        ident = stages.identify("Müdigkeitsgesellschaft", "Byung-Chul Han")
        assert ident.work.ol_keys == ["OL17795654W"]
        assert ident.evidence["open_library"]["found_by"] == "typed title, fielded"
        assert asked[-1]["title"] == "Müdigkeitsgesellschaft"
        assert asked[-1]["author"] == "Byung-Chul Han"
        assert all("q" in kw for kw in asked[:-1])

    def test_every_free_text_search_goes_before_any_fielded_one(self, catalogues,
                                                                  monkeypatch):
        """*To Live*: fielded first, the original `活着` found a one-edition
        record before the typed title's free text found the work."""
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="To Live", it="Vivere!",
                                              p1476="活着", lang="zh")}
        catalogues["labels"] = {"Q2": "Yu Hua"}
        small = doc(key="OL25129388W", title="活着", authors=("Yu Hua",), count=1)
        work = doc(key="OL25686018W", title="To Live", authors=("Yu Hua",), count=3)
        self._search(monkeypatch, lambda kw: [small] if "title" in kw
                     else [work] if kw["q"].startswith("To Live") else [])
        ident = stages.identify("To Live", "Yu Hua")
        assert ident.work.ol_keys == ["OL25686018W"]

    def test_an_accepted_item_s_english_title_is_searched(self, catalogues, monkeypatch):
        """N07: Open Library files Calvino's novel under the English title."""
        e = entity(label="Se una notte d'inverno un viaggiatore",
                   it="Se una notte d'inverno un viaggiatore", lang="it")
        e["labels"]["en"] = {"value": "If on a Winter's Night a Traveler"}
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": e}
        catalogues["labels"] = {"Q2": "Italo Calvino"}
        found = doc(key="OL15321W", title="Se una notte d'inverno un viaggiatore",
                    authors=("Italo Calvino",))
        self._search(monkeypatch, lambda kw: [found] if str(kw.get("q", "")).startswith("If on")
                     else [])
        ident = stages.identify("Se una notte d'inverno un viaggiatore", "Italo Calvino")
        assert ident.work.ol_keys == ["OL15321W"]
        assert ident.evidence["open_library"]["found_by"] == "English title"

    def test_the_closest_refusals_are_named(self, catalogues):
        catalogues["docs"] = [doc(key="OL3W", title="Quale socialismo, quale Europa")]
        ident = stages.identify("Rumori", "Attali")
        assert ident.work.ol_keys == []
        assert ident.evidence["open_library"]["tried"][0]["closest"][0][1] == \
            "Quale socialismo, quale Europa"


class TestTheAuthorAuthority:
    def test_the_fullest_name_is_asked_first(self, catalogues, monkeypatch):
        asked = []

        def authorities(text, **kw):
            asked.append(text)
            return {"rows": [{"id": "CFIV1", "heading": "Pasternak , Boris Leonidovič",
                              "kind": "Persona"}], "total": 1}

        monkeypatch.setattr(stages.sbn_opac, "authorities", authorities)
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="Doktor Zhivago", p1476="Доктор Живаго")}
        catalogues["labels"] = {"Q2": "Boris Pasternak"}
        ident = stages.identify("Doktor Zhivago", "Pasternak")
        assert asked[0] == "Boris Pasternak"
        assert ident.work.author_id == "CFIV1"

    def test_no_id_rather_than_a_namesake(self, catalogues):
        catalogues["authorities"] = {"rows": [
            {"id": "A1", "heading": "Leopardi , Giacomo", "kind": "Persona"},
            {"id": "A2", "heading": "Leopardi , Monaldo", "kind": "Persona"}], "total": 184}
        ident = stages.identify("Opere", "Leopardi")
        assert ident.work.author_id is None
        assert ident.evidence["authority"]["rule"].startswith("ambiguous")


class TestAFailingSourceIsNotAnEmptyAnswer:
    def test_the_state_says_which_source_failed_and_identity_survives(
            self, catalogues, monkeypatch):
        def boom(*a, **k):
            raise stages.SourceError("opac.sbn.it: HTTP 503")

        monkeypatch.setattr(stages.sbn_opac, "work_facet", boom)
        catalogues["docs"] = [doc(key="OL5W", title="Rumori")]
        ident = stages.identify("Rumori", "Attali")
        assert ident.evidence["sources"]["SBN"].startswith("error:")
        assert ident.work.ol_keys == ["OL5W"] and ident.work.identified

    def test_one_failing_open_library_call_degrades_the_source_not_the_other(
            self, catalogues, monkeypatch):
        def boom(*a, **k):
            raise stages.SourceError("openlibrary.org: HTTP 500")

        monkeypatch.setattr(stages.ol, "author_keys", boom)
        ident = stages.identify("Rumori", "Attali")
        assert ident.evidence["sources"]["Open Library"].startswith("error:")
        assert ident.evidence["sources"]["SBN"] == "ok"


class TestAnUnidentifiedWorkIsANormalAnswer:
    def test_nothing_found_is_a_work_that_says_so(self, catalogues):
        """A1: no source reaches one identity for every entry title. The lookup
        still has to answer, so this returns rather than raising."""
        ident = stages.identify("Più brillante del sole", "Eshun")
        assert not ident.work.identified
        assert ident.work.titles() == []
        assert ident.evidence["sources"] == {"Wikidata": "ok", "SBN": "ok",
                                             "Open Library": "ok", "SBN authority": "ok"}


# ---------------------------------------------------------------------------
# Other spellings, from an author-mode row (Step 14)
# ---------------------------------------------------------------------------

class TestSpellings:
    """N17's shape: SBN files *Bayn al-Qasrayn* under `bain el-qasrain.` (8
    records) and `bayn al-qasrayn` (the one Wikidata agrees with)."""

    @pytest.fixture
    def mahfouz(self, catalogues, monkeypatch):
        facets = {"bain el-qasrain": facet("bain el-qasrain.", total=9),
                  "bayn al-qasrayn": facet("bayn al-qasrayn", total=2),
                  "Palace Walk": facet("bain el-qasrain.", total=9)}

        def work_facet(title, author):
            catalogues["asked"].append(("opac", title, author))
            return facets.get(title, {"items": [], "total": 0, "first": {}})
        monkeypatch.setattr(stages.sbn_opac, "work_facet", work_facet)
        item = entity(label="Palace Walk", it="Tra i due palazzi", p1476="Bayn al-Qasrayn",
                      lang="ar", authors=("Q7176",))
        monkeypatch.setattr(stages, "_candidate_qids",
                            lambda t, a: ["Q3149381"] if t == "bayn al-qasrayn" else [])
        catalogues["entities"] = {"Q3149381": item}
        catalogues["labels"] = {"Q7176": "Naguib Mahfouz"}
        return catalogues

    def test_no_spellings_asks_exactly_what_it_did(self, mahfouz):
        ident = stages.identify("bain el-qasrain", "Naguib Mahfouz")
        assert ident.work.sbn_work == "bain el-qasrain." and ident.work.qid is None
        assert ident.work.sbn_other_works == [] and ident.evidence["spellings"] == []

    def test_a_spelling_reaches_the_item_and_a_second_uniform_title(self, mahfouz):
        ident = stages.identify("bain el-qasrain", "Naguib Mahfouz",
                                ["bayan al-qasrayn", "bayn al-qasrayn", "Palace Walk",
                                 "بين القصرين", "bain  el-qasrain"])
        w = ident.work
        assert w.qid == "Q3149381" and w.original_title == "Bayn al-Qasrayn"
        assert w.sbn_work == "bain el-qasrain."
        assert w.sbn_other_works == ["bayn al-qasrayn"]
        asked = [a[1] for a in mahfouz["asked"] if a[0] == "opac"]
        # Arabic is never sent (F15); a spelling with the typed title's tokens
        # is the same question and is not asked twice.
        assert "بين القصرين" not in asked and asked.count("bain el-qasrain") == 1
        assert [t["spelling"] for t in ident.evidence["spellings"]] == [
            "bayan al-qasrayn", "bayn al-qasrayn", "Palace Walk"]

    def test_a_spelling_the_guard_refuses_adds_nothing(self, mahfouz, monkeypatch):
        refused = facet("tutt'altro", total=40)
        orig = stages.sbn_opac.work_facet
        monkeypatch.setattr(stages.sbn_opac, "work_facet",
                            lambda t, a: refused if t == "Zqx" else orig(t, a))
        ident = stages.identify("bain el-qasrain", "Naguib Mahfouz", ["Zqx"])
        assert ident.work.sbn_other_works == []

    def test_the_typed_title_finding_nothing_lets_a_spelling_be_w(self, mahfouz):
        ident = stages.identify("Qasr", "Naguib Mahfouz", ["bayn al-qasrayn"])
        assert ident.work.sbn_work == "bayn al-qasrayn"
        assert ident.work.sbn_other_works == []
        # Case-insensitively the original title already, so not listed twice.
        assert [v.lower() for v in stages.gate_variants(ident.work)].count("bayn al-qasrayn") == 1

    def test_at_most_max_variants_are_asked(self):
        many = [f"titolo {i}" for i in range(20)]
        assert len(stages._spellings("x", many)) == stages.MAX_VARIANTS
        assert len(stages._spellings("x", many, cap=None)) > stages.MAX_VARIANTS


# ---------------------------------------------------------------------------
# The reader's spelling switches (decision AV)
# ---------------------------------------------------------------------------

# SBN's name records for Naguib Mahfouz, as `core=autori` answers them
# (`tests/test_core_authors.py`, from Step 14's live probe).
BMCV = {"id": "BMCV001724", "heading": "Mahfouz , Naguib", "kind": "Persona"}
PACHA = {"id": "TSAV609028", "heading": "Mahfouz , Naguib Pacha", "kind": "Persona"}
CFIV = {"id": "CFIV093786", "heading": "Maḥfūẓ , Naǧīb", "kind": "Persona"}


class TestTheTitleSwitch:
    @pytest.fixture
    def mahfouz(self, catalogues, monkeypatch):
        facets = {"bayn al-qasrayn": facet("bayn al-qasrayn", total=2),
                  "Palace Walk": facet("bain el-qasrain.", total=9)}

        def work_facet(title, author):
            catalogues["asked"].append(("opac", title, author))
            return facets.get(title, {"items": [], "total": 0, "first": {}})
        monkeypatch.setattr(stages.sbn_opac, "work_facet", work_facet)
        item = entity(label="Palace Walk", it="Tra i due palazzi", p1476="بين القصرين",
                      lang="ar", authors=("Q7176",), sitelinks=[("en", "Palace Walk"),
                                                                ("de", "Zwischen den Palästen")])
        monkeypatch.setattr(stages, "_candidate_qids",
                            lambda t, a: ["Q3149381"] if t in ("Palace Walk", "bayn al-qasrayn")
                            else [])
        catalogues["entities"] = {"Q3149381": item}
        catalogues["labels"] = {"Q7176": "Naguib Mahfouz"}
        return catalogues

    def opac(self, state):
        return [a[1] for a in state["asked"] if a[0] == "opac"]

    def test_off_asks_exactly_what_it_did(self, mahfouz):
        ident = stages.identify("Palace Walk", "Naguib Mahfouz")
        assert self.opac(mahfouz) == ["Palace Walk"]
        assert ident.evidence["title_spellings"] is None
        assert ident.evidence["author_spellings"] is None

    def test_on_asks_the_item_s_other_names_and_reaches_another_uniform_title(self, mahfouz):
        ident = stages.identify("Palace Walk", "Naguib Mahfouz", title_spellings=True)
        # The original's own title is Arabic and never sent (F15); the typed
        # title is not asked twice.
        assert self.opac(mahfouz) == ["Palace Walk", "Tra i due palazzi",
                                      "Zwischen den Palästen"]
        assert ident.evidence["title_spellings"] == {
            "on": True, "item": "Q3149381", "offered": 2,
            "asked": ["Tra i due palazzi", "Zwischen den Palästen"]}

    def test_an_item_adopted_late_is_asked_too(self, mahfouz, monkeypatch):
        """No item on the typed title; one on a title SBN files under its work,
        adopted late. Its names are asked then, and none asked before is asked
        again."""
        monkeypatch.setattr(stages, "_candidate_qids",
                            lambda t, a: ["Q3149381"] if t == "Palace walk" else [])
        mahfouz["listing_first"] = {"results": [
            {"id": "ITICCUCFI0001234", "title": {"info": "Palace walk / Naguib Mahfouz", "text": ""},
             "infos": []}]}
        ident = stages.identify("Qasr al-shawq", "Naguib Mahfouz", ["bayn al-qasrayn"],
                                title_spellings=True)
        assert ident.work.qid == "Q3149381"
        asked = self.opac(mahfouz)
        assert asked[:2] == ["Qasr al-shawq", "bayn al-qasrayn"]
        assert sorted(asked[2:]) == ["Palace Walk", "Tra i due palazzi",
                                     "Zwischen den Palästen"]
        assert ident.work.sbn_work == "bayn al-qasrayn"
        assert ident.evidence["title_spellings"]["item"] == "Q3149381"
        assert len(ident.evidence["spellings"]) == 4

    def test_with_no_item_nothing_more_is_asked(self, mahfouz, monkeypatch):
        monkeypatch.setattr(stages, "_candidate_qids", lambda t, a: [])
        ident = stages.identify("Qasr al-shawq", "Naguib Mahfouz", title_spellings=True)
        assert self.opac(mahfouz) == ["Qasr al-shawq"]
        assert ident.evidence["title_spellings"] == {"on": True, "item": None,
                                                     "offered": 0, "asked": []}


class TestTheAuthorSwitch:
    @pytest.fixture
    def mahfouz(self, catalogues, monkeypatch):
        answers = {"Naguib Mahfouz": {"rows": [BMCV, PACHA], "total": 2},
                   "Nagib Mahfuz": {"rows": [CFIV], "total": 1}}
        catalogues["people_asked"] = []

        def authorities(text, **kw):
            catalogues["asked"].append(("autori", text))
            if text not in answers:
                raise stages.SourceError(f"no stub for {text!r}")
            return answers[text]

        def people(name, **kw):
            catalogues["people_asked"].append(name)
            return [{"qid": "Q7176", "names": ["Naguib Mahfouz", "Nagib Mahfuz",
                                                "نجيب محفوظ"], "born": 1911}]
        monkeypatch.setattr(stages.sbn_opac, "authorities", authorities)
        monkeypatch.setattr(stages.wikidata, "people", people)
        catalogues["answers"] = answers
        return catalogues

    def test_off_asks_wikidata_for_no_person(self, mahfouz):
        ident = stages.identify("Palace Walk", "Naguib Mahfouz")
        assert mahfouz["people_asked"] == []
        assert ident.work.author_id == "BMCV001724"
        assert ident.work.author_other_ids == []

    def test_on_finds_the_name_record_the_typed_spelling_never_reaches(self, mahfouz):
        ident = stages.identify("Palace Walk", "Naguib Mahfouz", author_spellings=True)
        assert ident.work.author_id == "BMCV001724"
        assert ident.work.author_other_ids == ["CFIV093786"]
        found = ident.evidence["author_spellings"]
        assert found["person"] == "Q7176" and found["forms"] == ["Naguib Mahfouz",
                                                                  "Nagib Mahfuz"]
        assert found["ids"] == ["BMCV001724", "CFIV093786"]

    def test_a_spelling_that_names_two_people_adds_no_id(self, mahfouz):
        mahfouz["answers"]["Nagib Mahfuz"] = {"rows": [
            {"id": "X1", "heading": "Mahfuz , Nagib Sami", "kind": "Persona"},
            {"id": "X2", "heading": "Mahfuz , Nagib Ali", "kind": "Persona"}], "total": 2}
        ident = stages.identify("Palace Walk", "Naguib Mahfouz", author_spellings=True)
        # Both headings contain the name's tokens, none equals them, and they
        # are two people: `pick_authority` refuses rather than guessing.
        assert ident.work.author_other_ids == []
        rules = [a["rule"] for a in ident.evidence["author_spellings"]["answers"]]
        assert rules[1].startswith("ambiguous")

    def test_a_failed_spelling_is_a_degraded_source_not_an_empty_answer(self, mahfouz):
        del mahfouz["answers"]["Nagib Mahfuz"]
        ident = stages.identify("Palace Walk", "Naguib Mahfouz", author_spellings=True)
        assert ident.work.author_id == "BMCV001724"
        assert ident.evidence["sources"]["SBN authority"].startswith("error:")

    def test_wikidata_failing_degrades_wikidata(self, mahfouz, monkeypatch):
        def boom(name, **kw):
            raise stages.SourceError("www.wikidata.org: HTTP 503")
        monkeypatch.setattr(stages.wikidata, "people", boom)
        ident = stages.identify("Palace Walk", "Naguib Mahfouz", author_spellings=True)
        assert ident.evidence["sources"]["Wikidata"].startswith("error:")
        assert ident.evidence["author_spellings"]["asked"] is False

    def test_no_person_says_why(self, mahfouz, monkeypatch):
        monkeypatch.setattr(stages.wikidata, "people", lambda name, **kw: [])
        ident = stages.identify("Palace Walk", "Naguib Mahfouz", author_spellings=True)
        assert "no person" in ident.evidence["author_spellings"]["why_not"]

    def test_no_author_asks_nothing(self, mahfouz):
        found = stages._other_authorities(stages.prepare("Palace Walk", ""))
        assert found["asked"] is False and mahfouz["people_asked"] == []


class TestTitleBooks:
    """S0 for a bare title (decision AN): the OPAC is never asked, and each
    source's candidates are title-tested before they are grouped."""

    def _mobile(self, monkeypatch, records):
        asked = []

        def search(**kw):
            asked.append(kw)
            return records, []
        monkeypatch.setattr(stages.sbn_mobile, "search", search)
        return asked

    def test_three_sources_one_person_one_book_and_no_opac(self, catalogues, monkeypatch):
        catalogues["labels"] = {"Q2": "Jurgen Ruesch"}
        catalogues["candidates"] = ["Q1"]
        catalogues["entities"] = {"Q1": entity(label="La matrice sociale della psichiatria",
                                               it="La matrice sociale della psichiatria")}
        catalogues["docs"] = [doc(title="Communication", authors=("Jurgen Ruesch",)),
                              doc(key="OL2W", title="La matrice sociale della psichiatria",
                                  authors=("Jurgen Ruesch",))]
        asked = self._mobile(monkeypatch, [
            {"titolo": "La matrice sociale della psichiatria / Jurgen Ruesch, Gregory Bateson",
             "autorePrincipale": "Ruesch, Jurgen", "pubblicazione": "Bologna : Il mulino, 1976"},
            {"titolo": "La matrice sociale della psichiatria / Michael Shepherd",
             "autorePrincipale": "Shepherd, Michael", "pubblicazione": "Roma : Il pensiero scientifico, 1990"}])
        found = stages.title_books("La matrice sociale della psichiatria")
        assert [b["authors"][0] for b in found["books"]] == ["Jurgen Ruesch", "Michael Shepherd"]
        assert found["books"][0]["sources"] == ["Open Library", "SBN", "Wikidata"]
        assert found["candidates"] == 4                 # *Communication* is not titled so
        assert asked[0]["title"] == "La matrice sociale della psichiatria"
        assert not any(a[0] == "opac" for a in catalogues["asked"])

    def test_a_record_that_is_not_a_text_is_not_a_book(self, catalogues, monkeypatch):
        """§9 H03: the Modena City Ramblers' album, held twice, is no second book."""
        self._mobile(monkeypatch, [
            {"titolo": "Cent'anni di solitudine / Gabriel Garcia Marquez",
             "autorePrincipale": "García Márquez, Gabriel", "tipo": "Testo a stampa"},
            {"titolo": "Cent'anni di solitudine / Modena City Ramblers",
             "autorePrincipale": "Modena City Ramblers <gruppo musicale>",
             "pubblicazione": "[Milano] : Polygram Italia, 1998",
             "tipo": "Registrazione sonora"},
            {"titolo": "Cent'anni di solitudine / Raige", "autorePrincipale": "Raige",
             "tipo": "Registrazione sonora"}])
        found = stages.title_books("Cent'anni di solitudine")
        assert [b["authors"] for b in found["books"]] == [["Gabriel García Márquez"]]

    def test_a_title_in_another_script_is_not_sent_to_sbn(self, catalogues, monkeypatch):
        asked = self._mobile(monkeypatch, [])
        found = stages.title_books("海辺のカフカ")
        assert asked == [] and found["sources"]["SBN"].startswith("not asked")

    def test_a_source_that_fails_says_so_and_the_others_still_count(self, catalogues,
                                                                   monkeypatch):
        def boom(**kw):
            raise stages.SourceError("SBN down")
        monkeypatch.setattr(stages.sbn_mobile, "search", boom)
        catalogues["docs"] = [doc(title="Noise", authors=("Daniel Kahneman",))]
        found = stages.title_books("Noise")
        assert found["sources"]["SBN"].startswith("error")
        assert [b["authors"] for b in found["books"]] == [["Daniel Kahneman"]]
