"""Author mode's stages with the catalogues stubbed (Step 14, decision AJ).

The judgements are `core.authors`' and have their own suite. What is tested
here is the wiring: Wikidata's aliases are asked of the OPAC and the typed name
is asked first; only candidates whose name agrees are counted; a works list
under 50 costs one request and one at 50 is split by language and then by
year, stopping as soon as the leaves add up; a leaf that fails is uncovered
rather than empty; several ids list as one person; and a source that fails
says so without losing the others.
"""

import pytest

from catalog.http import SourceError
from lookup import stages

BATESON = {"id": "CFIV034892", "heading": "Bateson , Gregory", "kind": "Persona"}
FINKE = {"id": "RT1V031559", "heading": "Finke , Peter  <1942->", "kind": "Persona"}


def items(values):
    return [{"value": v, "label": v, "results": 1} for v in values]


class Catalogue:
    """Every call author mode makes, answered from a table, and counted."""

    def __init__(self, monkeypatch, autori=None, facets=None, works=None, people=None,
                 wd_works=None, entities=None, ol_docs=None, under_name=None,
                 whole_works=None):
        self.asked = []
        self.autori = autori or {}
        self.facets = facets or {}
        self.works = works or {}
        self.people_ = people if people is not None else []
        self.wd_works = wd_works or {"qids": [], "total": 0}
        self.entities_ = entities or {}
        self.ol_docs = ol_docs or []
        self.under_name = under_name or {}
        self.whole_works = whole_works or {}
        m = monkeypatch
        m.setattr(stages.sbn_opac, "authority_work_records", self.authority_work_records)
        m.setattr(stages.sbn_opac, "records_by_authority", self.records_by_authority)
        m.setattr(stages.sbn_opac, "authorities", self.authorities)
        m.setattr(stages.sbn_opac, "authority_facets", self.authority_facets)
        m.setattr(stages.sbn_opac, "authority_work", self.authority_work)
        m.setattr(stages.wikidata, "people", self.people)
        m.setattr(stages.wikidata, "works_by", lambda qid: self.wd_works)
        m.setattr(stages.wikidata, "entities",
                  lambda qids, *a: {q: self.entities_[q] for q in qids if q in self.entities_})
        m.setattr(stages.ol, "author_keys", lambda name: [{"key": "OL1A", "name": name}])
        m.setattr(stages.ol, "works_by_author",
                  lambda name: {"docs": self.ol_docs, "total": len(self.ol_docs)})

    def _answer(self, table, key):
        got = table.get(key)
        if isinstance(got, Exception):
            raise got
        return got

    def authorities(self, form):
        self.asked.append(("autori", form))
        return self._answer(self.autori, form) or {"rows": [], "total": 0}

    def authority_facets(self, aid, language=None, year=None):
        self.asked.append(("facets", aid, language, year))
        got = self._answer(self.facets, (aid, language, year))
        return got or {"works": [], "languages": [], "years": [], "total": 0}

    def authority_work(self, aid, work):
        self.asked.append(("work", aid, work))
        return self._answer(self.works, (aid, work)) or {
            "rows": [{"title": f"{work.title()} / Gregory Bateson", "author": "Bateson, Gregory"}],
            "languages": [{"value": "eng"}], "years": [{"value": "1972"}], "total": 1}

    def authority_work_records(self, aid, work, cap):
        self.asked.append(("whole work", aid, work, cap))
        return self._answer(self.whole_works, (aid, work))

    def records_by_authority(self, aid, cap=None):
        self.asked.append(("under name", aid, cap))
        got = self._answer(self.under_name, aid)
        return got or {"rows": [], "total": 0, "pages": 1, "failed": [], "truncated": False}

    def people(self, name):
        self.asked.append(("people", name))
        if isinstance(self.people_, Exception):
            raise self.people_
        return self.people_


PERSON = {"qid": "Q314252", "names": ["Gregory Bateson", "G. Bateson", "Грегори Бейтсон"],
          "born": 1904}


def bateson(monkeypatch, **kw):
    kw.setdefault("autori", {"Gregory Bateson": {"rows": [BATESON, FINKE], "total": 2},
                             "G. Bateson": {"rows": [BATESON], "total": 1}})
    kw.setdefault("people", [PERSON])
    kw.setdefault("facets", {("CFIV034892", None, None): {
        "works": items(["steps to an ecology of mind", "naven"]),
        "languages": items(["ita", "eng"]), "years": [], "total": 134}})
    return Catalogue(monkeypatch, **kw)


class TestResolve:

    def test_the_typed_name_first_then_the_aliases(self, monkeypatch):
        cat = bateson(monkeypatch)
        got = stages.resolve_author("Gregory Bateson")
        assert got.evidence["forms"] == ["Gregory Bateson", "G. Bateson"]
        assert got.resolved == "CFIV034892" and not got.skip
        assert [c.id for c in got.candidates] == ["CFIV034892", "RT1V031559"]
        assert got.person["qid"] == "Q314252"

    def test_only_a_name_that_agrees_is_counted(self, monkeypatch):
        cat = bateson(monkeypatch)
        got = stages.resolve_author("Gregory Bateson")
        counted = [a[1] for a in cat.asked if a[0] == "facets"]
        assert counted == ["CFIV034892"]
        assert (got.candidates[0].records, got.candidates[0].languages) == (134, 2)
        assert got.candidates[1].records is None

    def test_a_failed_count_is_not_a_zero(self, monkeypatch):
        bateson(monkeypatch, facets={("CFIV034892", None, None): SourceError("503")})
        got = stages.resolve_author("Gregory Bateson")
        assert got.candidates[0].records is None

    def test_a_failed_form_says_so_and_keeps_the_others(self, monkeypatch):
        bateson(monkeypatch, autori={"Gregory Bateson": SourceError("503"),
                                     "G. Bateson": {"rows": [BATESON], "total": 1}})
        got = stages.resolve_author("Gregory Bateson")
        assert got.evidence["sources"]["SBN"].startswith("error:")
        assert [c.id for c in got.candidates] == ["CFIV034892"]
        assert got.resolved is None

    def test_wikidata_failing_asks_the_typed_name_alone(self, monkeypatch):
        bateson(monkeypatch, people=SourceError("429"))
        got = stages.resolve_author("Gregory Bateson")
        assert got.evidence["forms"] == ["Gregory Bateson"]
        assert got.evidence["sources"]["Wikidata"].startswith("error:")

    def test_a_name_in_its_own_script_takes_the_first_person(self, monkeypatch):
        """村上春樹 is never sent to the OPAC; the person's Latin names are."""
        person = {"qid": "Q134798", "names": ["Haruki Murakami", "村上春樹"], "born": 1949}
        murakami = {"id": "LO1V086706", "heading": "Murakami , Haruki", "kind": "Persona"}
        cat = Catalogue(monkeypatch, people=[person],
                        autori={"Haruki Murakami": {"rows": [murakami], "total": 1}})
        got = stages.resolve_author("村上春樹")
        assert got.evidence["forms"] == ["Haruki Murakami"]
        assert ("autori", "村上春樹") not in cat.asked
        assert got.skip and got.resolved == "LO1V086706"

    def test_nobody_found(self, monkeypatch):
        Catalogue(monkeypatch, people=[])
        got = stages.resolve_author("Zzqx Nobody")
        assert got.candidates == [] and got.resolved is None and not got.skip


class TestTheSplit:

    def test_under_fifty_costs_one_request(self, monkeypatch):
        cat = bateson(monkeypatch)
        got = stages._authority_works("CFIV034892", "Gregory Bateson", 1904, 2026)
        assert got["evidence"]["split"] is False and got["evidence"]["covered"] == 134
        assert [a for a in cat.asked if a[0] == "facets"] == [
            ("facets", "CFIV034892", None, None)]

    def test_fifty_splits_by_language_then_by_year(self, monkeypatch):
        fifty = items([f"w{i}" for i in range(50)])
        facets = {
            ("A", None, None): {"works": fifty, "languages": items(["ita", "eng"]),
                                "years": [], "total": 300},
            ("A", "eng", None): {"works": items(["e1"]), "languages": [], "years": [],
                                 "total": 40},
            ("A", "ita", None): {"works": fifty, "languages": [],
                                 "years": items(["1990", "1992"]), "total": 260},
            ("A", "ita", "1990"): {"works": items(["i1"]), "total": 100},
            ("A", "ita", "1992"): {"works": fifty, "total": 150},
        }
        Catalogue(monkeypatch, facets=facets)
        got = stages._authority_works("A", "Umberto Eco", 1932, 2026)
        ev = got["evidence"]
        assert ev["split"] and ev["covered"] == 140 and ev["capped_leaves"] == ["ita 1992"]
        assert {"e1", "i1", "w0"} <= set(got["works"])

    def test_a_capped_year_facet_asks_the_quiet_years_until_they_add_up(self, monkeypatch):
        fifty = items([f"w{i}" for i in range(50)])
        years = items([str(y) for y in range(1960, 2010)])
        facets = {("A", None, None): {"works": fifty, "languages": items(["ita"]),
                                      "years": [], "total": 1010},
                  ("A", "ita", None): {"works": fifty, "languages": [], "years": years,
                                       "total": 1010}}
        for y in range(1960, 2010):
            facets[("A", "ita", str(y))] = {"works": items([f"y{y}"]), "total": 20}
        facets[("A", "ita", "1959")] = {"works": items(["late"]), "total": 10}
        facets[("A", "ita", "1958")] = SourceError("503")
        cat = Catalogue(monkeypatch, facets=facets)
        got = stages._authority_works("A", "Umberto Eco", 1932, 2026)
        assert got["evidence"]["covered"] == 1010 and "late" in got["works"]
        asked = [a[3] for a in cat.asked if a[0] == "facets" and a[3]]
        # One batch of quiet years (1959 down to 1952), then it stopped.
        assert "1952" in asked and "1951" not in asked

    def test_a_language_that_fails_is_uncovered_not_empty(self, monkeypatch):
        fifty = items([f"w{i}" for i in range(50)])
        facets = {("A", None, None): {"works": fifty, "languages": items(["ita", "eng"]),
                                      "years": [], "total": 100},
                  ("A", "ita", None): SourceError("503"),
                  ("A", "eng", None): {"works": items(["e"]), "total": 30}}
        Catalogue(monkeypatch, facets=facets)
        ev = stages._authority_works("A", "x", None, 2026)["evidence"]
        assert ev["covered"] == 30 and ev["total"] == 100
        assert ev["requests"] == 2


class TestListWorks:

    def resolution(self, monkeypatch, **kw):
        cat = bateson(monkeypatch, **kw)
        return cat, stages.resolve_author("Gregory Bateson")

    def test_records_no_work_names_are_their_own_group(self, monkeypatch):
        """Decision AN. `RMS2809373` is under Bateson's name and filed under no
        uniform title; `RAV0017793` is listed by a work's first page."""
        balinese = {"id": "RMS2809373", "title": "Balinese character : a photographic "
                    "analysis / by Gregory Bateson and Margaret Mead",
                    "author": "Bateson, Gregory", "imprint": "New York : Academy of "
                    "Sciences, 1962", "infos": [], "medium": "Testo", "level": "Monografia",
                    "type": "text", "language": None}
        verso = {**balinese, "id": "RAV0017793",
                 "title": "Verso un'ecologia della mente / Gregory Bateson",
                 "imprint": "Milano : Adelphi, 1987"}
        facets = {("CFIV034892", None, None): {"works": [{"value": "steps to an ecology of mind",
                                                          "label": "steps to an ecology of mind"}],
                                               "languages": [], "years": [], "total": 2}}
        works = {("CFIV034892", "steps to an ecology of mind"): {
            "rows": [{"id": "RAV0017793", "title": "Verso un'ecologia della mente / Gregory "
                      "Bateson", "author": "Bateson, Gregory"}],
            "languages": [{"value": "ita"}], "years": [{"value": "1987"}], "total": 1}}
        under = {"CFIV034892": {"rows": [balinese, verso], "total": 2, "pages": 1,
                                "failed": [], "truncated": False}}
        cat, res = self.resolution(monkeypatch, facets=facets, works=works, under_name=under)
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert [u["title"] for u in got.unlinked] == [
            "Balinese character : a photographic analysis"]
        assert got.unlinked[0]["first_year"] == 1962
        assert ("under name", "CFIV034892", stages.UNLINKED_MAX_PAGES) in cat.asked
        assert got.evidence["unlinked"]["records"] == 1

    def test_reading_the_rest_reads_every_page_and_moves_only_the_group(self, monkeypatch):
        """Decision BA. The cap cut the read at 25 pages of 129; the full read
        asks for all 129, and only the group filed under no work moves."""
        row = {"title": "Balinese character / Gregory Bateson", "author": "Bateson, Gregory",
               "imprint": "Cambridge : University Press, 1936", "infos": [],
               "medium": "Testo", "level": "Monografia", "type": "text", "language": None}
        first = [{**row, "id": "CFI0000001"}]
        whole = first + [{**row, "id": "CFI0000002", "title": "Mind and nature / G. Bateson",
                          "imprint": "New York : Dutton, 1979"}]
        under = {"CFIV034892": {"rows": first, "total": 2575, "pages": 25, "failed": [],
                                "truncated": True}}
        cat, res = self.resolution(monkeypatch, under_name=under)
        listed = stages.list_works(res, ["CFIV034892"], 2026)
        assert stages.unread_under_name(listed.evidence) == {"records": 2574, "pages": 104}
        cat.under_name["CFIV034892"] = {"rows": whole, "total": 2575, "pages": 129,
                                        "failed": [], "truncated": False}
        cat.asked.clear()
        got = stages.read_rest(listed, 2026)
        assert cat.asked == [("under name", "CFIV034892", 129)]
        assert [u["title"] for u in listed.unlinked] == ["Balinese character"]
        assert {u["title"] for u in got.unlinked} == {"Balinese character", "Mind and nature"}
        assert got.works == listed.works and got.contributed == listed.contributed
        assert stages.unread_under_name(got.evidence) is None
        assert got.evidence["unlinked"]["records"] == 2

    def test_a_record_a_work_links_past_its_first_page_is_that_works(self, monkeypatch):
        """Decision BB. *Ökologie des Geistes* is SBN's own link to `steps to an
        ecology of mind` on page 2 of 45 records, and scores below 0.6 against
        it, so only the whole work's read keeps it out of the group."""
        row = {"author": "Bateson, Gregory", "infos": [], "medium": "Testo",
               "level": "Monografia", "type": "text", "language": None}
        oekologie = {**row, "id": "UBO0000001", "imprint": "Frankfurt : Suhrkamp, 1981",
                     "title": "Ökologie des Geistes : anthropologische, psychologische, "
                              "biologische und epistemologische Perspektiven"}
        balinese = {**row, "id": "RMS2809373", "imprint": "New York : Academy, 1962",
                    "title": "Balinese character / by Gregory Bateson and Margaret Mead"}
        facets = {("CFIV034892", None, None): {"works": items(["steps to an ecology of mind"]),
                                               "languages": [], "years": [], "total": 46}}
        works = {("CFIV034892", "steps to an ecology of mind"): {
            "rows": [], "languages": [], "years": [], "total": 45}}
        under = {"CFIV034892": {"rows": [oekologie, balinese], "total": 2, "pages": 1,
                                "failed": [], "truncated": False}}
        whole = {("CFIV034892", "steps to an ecology of mind"): {
            "rows": [oekologie], "total": 45, "pages": 3, "failed": [], "truncated": False}}
        cat, res = self.resolution(monkeypatch, facets=facets, works=works,
                                   under_name=under, whole_works=whole)
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert ("whole work", "CFIV034892", "steps to an ecology of mind", 3) in cat.asked
        assert [u["title"] for u in got.unlinked] == ["Balinese character"]
        assert got.evidence["sources"]["SBN"] == "ok"

        whole[("CFIV034892", "steps to an ecology of mind")] = SourceError("503")
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert {u["title"] for u in got.unlinked} == {
            "Balinese character", "Ökologie des Geistes : anthropologische, psychologische, "
                                  "biologische und epistemologische Perspektiven"}
        assert got.evidence["sources"]["SBN"].startswith("partial")

    def test_a_work_on_one_page_is_not_read_again(self, monkeypatch):
        cat, res = self.resolution(monkeypatch)
        stages.list_works(res, ["CFIV034892"], 2026)
        assert not [a for a in cat.asked if a[0] == "whole work"]

    def test_a_failed_read_under_the_name_is_a_source_state(self, monkeypatch):
        cat, res = self.resolution(monkeypatch,
                                   under_name={"CFIV034892": SourceError("503")})
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert got.unlinked == [] and got.evidence["sources"]["SBN"].startswith("error:")

    def test_a_page_lost_under_the_name_is_partial(self, monkeypatch):
        under = {"CFIV034892": {"rows": [], "total": 40, "pages": 2,
                                "failed": [{"page": 2, "error": "503"}], "truncated": False}}
        cat, res = self.resolution(monkeypatch, under_name=under)
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert got.evidence["sources"]["SBN"].startswith("partial")

    def test_the_works_the_contributed_and_the_band(self, monkeypatch):
        entity = {"labels": {"en": {"value": "Steps to an Ecology of Mind"},
                             "it": {"value": "Verso un'ecologia della Mente"}},
                  "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q571"}}}}],
                             "P577": [{"mainsnak": {"datavalue": {"value": {
                                 "time": "+1972-00-00T00:00:00Z"}}}}]}}
        works = {("CFIV034892", "naven"): {
            "rows": [{"title": "Naven / Gregory Bateson", "author": "Mead, Margaret"}],
            "languages": [], "years": [{"value": "1936"}], "total": 2}}
        docs = [{"key": "/works/OL486407W", "title": "Ökologie des Geistes",
                 "author_name": ["Gregory Bateson"], "first_publish_year": 2001},
                {"key": "/works/OL1W", "title": "Coming of Age in Samoa",
                 "author_name": ["Margaret Mead"]},
                {"key": "", "title": "no key"}]
        cat, res = self.resolution(monkeypatch, works=works, ol_docs=docs,
                                   wd_works={"qids": ["Q1970551"], "total": 1},
                                   entities={"Q1970551": entity})
        got = stages.list_works(res, ["CFIV034892"], 2026)
        # No P407, so no original title: the item's own name, closest to SBN's.
        assert [w["title"] for w in got.works] == ["Steps to an Ecology of Mind"]
        assert got.works[0]["year_kind"] == "original"
        assert [w["title"] for w in got.contributed] == ["Naven"]
        assert got.contributed[0]["credited_to"] == ["Margaret Mead"]
        assert [b["key"] for b in got.band] == ["OL486407W"]
        assert got.evidence["sources"] == {"SBN": "ok", "Wikidata": "ok",
                                           "Open Library": "ok"}

    def test_nobody_chosen_is_refused(self, monkeypatch):
        _, res = self.resolution(monkeypatch)
        with pytest.raises(ValueError):
            stages.list_works(res, ["NOT-OFFERED"], 2026)

    def test_every_source_failing_says_so(self, monkeypatch):
        cat, res = self.resolution(monkeypatch)
        cat.facets[("CFIV034892", None, None)] = SourceError("503")
        monkeypatch.setattr(stages.wikidata, "works_by",
                            lambda qid: (_ for _ in ()).throw(SourceError("429")))
        monkeypatch.setattr(stages.ol, "works_by_author",
                            lambda name: (_ for _ in ()).throw(SourceError("503")))
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert got.works == [] and got.band == []
        assert all(v.startswith("error:") for v in got.evidence["sources"].values())

    def test_a_work_whose_records_fail_is_partial(self, monkeypatch):
        cat, res = self.resolution(monkeypatch)
        cat.works[("CFIV034892", "naven")] = SourceError("503")
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert got.evidence["sources"]["SBN"].startswith("partial")
        # Not moved to the contributed group: its records never said whose it is.
        assert len(got.works) == 2 and got.contributed == []

    def test_no_person_asks_no_wikidata_and_searches_the_heading(self, monkeypatch):
        cat, res = self.resolution(monkeypatch, people=[])
        res.person = None
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert got.evidence["wikidata"] == {"read": 0, "total": 0}
        assert ("people", "Gregory Bateson") in cat.asked

    def test_the_chosen_name_finds_the_person_the_typed_one_missed(self, monkeypatch):
        """Han Byung-Chul finds no Wikidata item; Byung-Chul Han does."""
        cat, res = self.resolution(monkeypatch)
        res.person = None
        cat.wd_works = {"qids": ["Q1"], "total": 1}
        got = stages.list_works(res, ["CFIV034892"], 2026)
        assert got.evidence["wikidata"] == {"read": 1, "total": 1}

    def test_two_ids_list_as_one_person(self, monkeypatch):
        cat, res = self.resolution(monkeypatch)
        cat.facets[("RT1V031559", None, None)] = {"works": items(["naven", "extra"]),
                                                  "languages": [], "years": [], "total": 3}
        got = stages.list_works(res, ["CFIV034892", "RT1V031559"], 2026)
        assert got.evidence["sbn_works"] == 3
        assert ("work", "RT1V031559", "naven") in cat.asked

    def test_a_year_in_another_calendar_is_settled_under_no_work(self, monkeypatch):
        """Decision AY in author mode. Shamlu's records, live: SBN files the
        first under 2010, the imprint's bracketed year, and the second under
        1994, a year its imprint does not write."""
        shamlu = {"id": "RMBV243388", "heading": "Shamlu , Ahmad", "kind": "Persona"}
        rows = [{"id": "RMB0775153", "title": "Az zakhm-e ghalb : gozineh-e she'rha va "
                 "khanesh-e she'r / Ahmad Shamlu", "author": "Shamlu, Ahmad",
                 "imprint": "Teheran : Nashr-e Cheshmeh, 1388 [2010]", "language": "per"},
                {"id": "RMS1560500", "title": "Hafez-e Siraz / Ahmed Samlu",
                 "author": "Shamlu, Ahmad", "imprint": "Tehran : Morvarid, 1373H",
                 "language": "per"}]
        cat = Catalogue(monkeypatch, autori={"Ahmad Shamlu": {"rows": [shamlu], "total": 1}},
                        under_name={"RMBV243388": {"rows": rows, "total": 2, "pages": 1,
                                                   "failed": [], "truncated": False}})
        filed = {"2010": ["RMB0775153"], "1994": ["RMS1560500"]}
        sent = []
        monkeypatch.setattr(stages.sbn_opac, "post", lambda body: sent.append(body) or {
            "facets": [{"name": "dataf[]", "items": [{"value": "2010"}, {"value": "1994"}]}]})
        monkeypatch.setattr(stages.sbn_opac, "all_rows", lambda body, cap=None: sent.append(
            body) or {"rows": [{"id": i} for i in filed.get(body["dataf[]"], [])],
                      "failed": [], "truncated": False})
        res = stages.resolve_author("Ahmad Shamlu")
        got = stages.list_works(res, ["RMBV243388"], 2026)
        by_title = {u["title"]: u for u in got.unlinked}
        zakhm = by_title["Az zakhm-e ghalb : gozineh-e she'rha va khanesh-e she'r"]
        assert (zakhm["first_year"], zakhm["year_note"]["label"]) == (2010, "year inferred")
        hafez = by_title["Hafez-e Siraz"]
        assert hafez["first_year"] is None
        assert hafez["year_note"]["label"] == "other calendar"
        assert all(b["item:5032:Nomi::@frase@"] == "RMBV243388" for b in sent)
        assert got.evidence["dates"]["checked"] == 2


def test_no_name_asks_nothing():
    assert stages._open_library_works("", []) == {"state": "ok", "docs": [], "read": 0,
                                                   "total": 0}
