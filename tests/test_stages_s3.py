"""S3 — `lookup/stages.recover`, offline, with the catalogues stubbed out.

The gate itself is `core.identity`'s and is tested in `test_core_identity.py`
and `test_gate.py`; the threshold is theirs too, and nothing here restates it.
What is tested here is the **wiring**, which is where this step can go wrong
while every gate is right:

* running the routes where the plan says they do not run — a book with no
  accepted work is the class Step 2 measured at 0.166, and asking anyway would
  buy leaks nothing can then explain;
* dropping a refused record instead of storing it with its score, which loses
  the loose-match band (decision N) and makes a refusal unauditable;
* letting a refusal overwrite a record the *listing* already admitted, which
  would turn a catalogue statement into an inference;
* sending a free-text probe that can only come back looking like an answer —
  non-Latin text the OPAC discards (F15), or a single `/` Solr reads as an
  unterminated regex (`docs/sbn-api.md` trap 8);
* judging a Dewey-only record on its own instead of judging the set
  (`CLAUDE.md` rule 7);
* letting one failing route lose the other's records (`CLAUDE.md` rule 5);
* running decision Q's widened gate anywhere but on a book with no identity.

Every catalogue call is monkeypatched. `conftest.py` blocks sockets for the
whole session, so a stub that forgets to intercept fails loudly rather than
quietly measuring live data.
"""

import pytest

from catalog.http import SourceError
from core.model import Provenance, Record, Work
from core.store import RecordStore
from lookup import stages


def opac_row(bid, title, author="Bateson, Gregory",
             imprint="Milano : Adelphi, 1976", medium="Testo"):
    return {"id": bid, "title": title, "author": author, "imprint": imprint,
            "infos": [imprint], "medium": medium, "level": "Monografia",
            "type": "text", "language": None}


def brief(bid, title, isbn=None, dewey=None, lingua=None):
    """One mobile-gateway brief record, as `search.json` returns it."""
    return {"codiceIdentificativo": f"IT\\ICCU\\{bid}", "titolo": title,
            "pubblicazione": "Milano : Adelphi, 1976", "isbn": isbn,
            "classificazioneDewey": dewey, "linguaPubblicazione": lingua,
            "tipo": "Testo a stampa"}


def work(**kw):
    base = dict(sbn_work="steps to an ecology of mind", sbn_work_tier="strong",
                author_id="CFIV034892", ol_keys=["OL486424W"],
                ol_title="Steps to an Ecology of Mind",
                original_title="Steps to an Ecology of Mind",
                titles_by_lang={"ita": "Verso un'ecologia della mente"},
                authors=["Gregory Bateson"])
    base.update(kw)
    return Work(**base)


def identity(w=None, author="Bateson", typed="Verso un'ecologia della mente"):
    return stages.Identity(work=w if w is not None else work(),
                           evidence={"question": {"author": author,
                                                  "typed_title": typed}})


def listed(store, bid="L1", title="Steps to an ecology of mind"):
    """One record the work listing already admitted, as S2 leaves it."""
    store.put(Record(source="SBN", id=bid, title=title,
                     provenance=Provenance("SBN", stages.WORK_LISTING,
                                           stages.UNIFORM_TITLE)))
    return store


@pytest.fixture
def catalogues(monkeypatch):
    state = {
        "probe": {},          # title -> rows
        "sweep": {"rows": [], "total": 0, "pages": 1, "failed": [],
                  "truncated": False},
        "isbn": {},           # isbn -> brief records
        "asked": [],
        "full": {},           # bid -> full record
        "ol_search": {},      # author -> docs
        "ol_editions": {},    # key -> rows
    }

    def all_rows(body, **kw):
        title = body.get(stages.sbn_opac.ANY)
        state["asked"].append(("probe", title, body.get(stages.sbn_opac.AUTHOR)))
        rows = state["probe"].get(title)
        if rows is None:
            raise SourceError(f"no stub for {title!r}")
        return {"rows": rows, "total": len(rows), "pages": 1, "failed": [],
                "truncated": False}

    def records_by_authority(authority_id):
        state["asked"].append(("sweep", authority_id))
        return state["sweep"]

    def search(**kw):
        state["asked"].append(("isbn", kw.get("isbn")))
        return state["isbn"].get(kw.get("isbn"), []), []

    def full_record(bid):
        state["asked"].append(("full", bid))
        if bid not in state["full"]:
            raise SourceError(f"no stub for {bid!r}")
        return state["full"][bid]

    def ol_search(**kw):
        state["asked"].append(("ol_search", kw.get("author")))
        return state["ol_search"].get(kw.get("author"), [])

    def ol_editions(key, **kw):
        state["asked"].append(("ol_editions", key))
        return {"rows": state["ol_editions"].get(key, []), "size": 0, "failed": []}

    monkeypatch.setattr(stages.sbn_opac, "all_rows", all_rows)
    monkeypatch.setattr(stages.sbn_opac, "records_by_authority", records_by_authority)
    monkeypatch.setattr(stages.sbn_mobile, "search", search)
    monkeypatch.setattr(stages.sbn_mobile, "full_record", full_record)
    monkeypatch.setattr(stages.ol, "search", ol_search)
    monkeypatch.setattr(stages.ol, "editions", ol_editions)
    return state


# ---------------------------------------------------------------------------

class TestWhereTheRoutesRun:
    def test_they_run_beside_an_accepted_work(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        evidence = stages.recover(identity()).evidence
        assert evidence["asked"] is True
        assert ("sweep", "CFIV034892") in catalogues["asked"]

    def test_they_run_for_an_identity_with_no_accepted_work(self, catalogues):
        """Decision AP: N04 and N16's English entry have a work with titles and
        no W, and the routes were all that could reach their SBN records."""
        w = work(sbn_work=None, sbn_work_tier=None)
        catalogues["probe"] = {t: [] for t in stages.gate_variants(w)}
        evidence = stages.recover(identity(w)).evidence
        assert evidence["asked"] is True
        assert evidence["routes"]["titles"] == stages.gate_variants(w)
        assert ("sweep", "CFIV034892") in catalogues["asked"]

    def test_they_do_not_run_for_an_identity_with_no_title(self, catalogues):
        w = work(sbn_work=None, ol_title=None, original_title=None, titles_by_lang={})
        evidence = stages.recover(identity(w)).evidence
        assert evidence["asked"] is False and evidence["reverse"] is None
        assert evidence["why_not"]
        assert catalogues["asked"] == []

    def test_the_sweep_is_not_asked_without_an_authority_id(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        evidence = stages.recover(identity(work(author_id=None))).evidence
        assert evidence["routes"]["author_sweep"]["asked"] is False
        assert not [a for a in catalogues["asked"] if a[0] == "sweep"]

    def test_the_uniform_title_is_in_the_gate_set_and_titles_is_not_enough(self):
        """`Work.titles()` leaves W out — it is a search key. U2 scored the gate
        with it in, so it goes back in here or the shipped gate is not the
        measured one. SBN files *Kafka on the Shore* under `umibe no kafuka`,
        which is a title nothing else in the set carries."""
        w = work(sbn_work="umibe no kafuka", original_title="Kafka on the Shore",
                 ol_title="Kafka on the Shore", titles_by_lang={})
        assert "umibe no kafuka" not in w.titles()
        assert stages.gate_variants(w) == ["Kafka on the Shore", "umibe no kafuka"]


class TestWhatIsNotAsked:
    def test_a_non_latin_title_is_not_probed(self, catalogues):
        w = work(sbn_work="prestuplenie i nakazanie",
                 original_title="Преступление и наказание", titles_by_lang={})
        catalogues["probe"] = {"prestuplenie i nakazanie": []}
        evidence = stages.recover(identity(w)).evidence
        skipped = [p for p in evidence["routes"]["title_probes"] if not p["asked"]]
        assert [p["title"] for p in skipped] == ["Преступление и наказание"]
        assert "F15" in skipped[0]["why_not"]

    def test_a_title_holding_a_slash_is_not_probed(self, catalogues):
        w = work(ol_title="Die Verwandlung / la Metamorfosi")
        catalogues["probe"] = {t: [] for t in stages.gate_variants(w)}
        evidence = stages.recover(identity(w)).evidence
        skipped = [p for p in evidence["routes"]["title_probes"] if not p["asked"]]
        assert [p["title"] for p in skipped] == ["Die Verwandlung / la Metamorfosi"]
        assert "Solr" in skipped[0]["why_not"]
        assert not [a for a in catalogues["asked"]
                    if a[0] == "probe" and "/" in (a[1] or "")]

    def test_only_isbns_already_in_hand_are_probed(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        store = RecordStore()
        store.put(Record(source="Open Library", id="OL1M", isbn="978-0226039053",
                         isbns_raw=["978-0226039053"],
                         provenance=Provenance("Open Library", stages.WORK_EDITIONS,
                                               stages.WORK_KEY)))
        stages.recover(identity(), store)
        assert [a for a in catalogues["asked"] if a[0] == "isbn"] == [
            ("isbn", "9780226039053")]


class TestTheGate:
    def test_a_matching_title_is_admitted_with_its_score(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        catalogues["probe"]["Steps to an Ecology of Mind"] = [
            opac_row("UFI0556368", "Steps to an ecology of mind : collected essays")]
        store = stages.recover(identity()).store
        record = store.get("SBN", "UFI0556368")
        assert record.provenance.evidence == stages.TITLE_MATCH
        assert record.provenance.route == stages.TITLE_PROBE
        assert record.provenance.score == 1.0
        assert not store.refused()

    def test_a_record_that_nothing_ties_to_the_work_is_stored_refused(self, catalogues):
        """Not dropped. Decision N shows it in the band, and a record that was
        thrown away cannot be audited."""
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        catalogues["sweep"] = {"rows": [opac_row("X1", "Naven / Gregory Bateson")],
                               "total": 1, "pages": 1, "failed": [],
                               "truncated": False}
        recovery = stages.recover(identity())
        refused = recovery.store.refused()
        assert [r.id for r in refused] == ["X1"]
        assert refused[0].provenance.route == stages.AUTHOR_SWEEP
        assert refused[0].provenance.score == 0.0
        assert recovery.evidence["gate"]["refused"] == 1
        assert recovery.evidence["gate"]["admitted"] == 0

    def test_a_refusal_never_unadmits_what_the_listing_admitted(self, catalogues):
        """The listing's record is there because SBN said so. One route having
        failed to prove it does not unprove it."""
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        catalogues["sweep"] = {"rows": [opac_row("L1", "Naven / Gregory Bateson")],
                               "total": 1, "pages": 1, "failed": [],
                               "truncated": False}
        store = listed(RecordStore())
        stages.recover(identity(), store)
        assert store.get("SBN", "L1").provenance.evidence == stages.UNIFORM_TITLE
        assert not store.refused()
        assert [p.route for p in store.routes(store.get("SBN", "L1"))] == [
            stages.WORK_LISTING, stages.AUTHOR_SWEEP]

    def test_an_isbn_probe_hit_is_admitted_by_the_isbn_and_not_by_its_title(
            self, catalogues):
        """A shared ISBN is the catalogue agreeing on an object. The title of
        this row scores 0.0 against the work's titles and it is still in."""
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        catalogues["isbn"] = {"9780226039053": [brief("B1", "Naven")]}
        store = RecordStore()
        store.put(Record(source="Open Library", id="OL1M", isbn="9780226039053",
                         isbns_raw=["9780226039053"],
                         provenance=Provenance("Open Library", stages.WORK_EDITIONS,
                                               stages.WORK_KEY)))
        stages.recover(identity(), store)
        assert store.get("SBN", "B1").provenance.evidence == stages.ISBN_MATCH


class TestFailure:
    def test_a_failing_probe_loses_neither_the_other_probe_nor_the_sweep(
            self, catalogues):
        """`CLAUDE.md` rule 5 — a failed request is never an empty result, and
        it never costs a source that answered."""
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        del catalogues["probe"]["Steps to an Ecology of Mind"]      # raises
        catalogues["sweep"] = {"rows": [opac_row("UFI0556368",
                                                 "Steps to an ecology of mind")],
                               "total": 1, "pages": 1, "failed": [],
                               "truncated": False}
        recovery = stages.recover(identity())
        states = [p["state"] for p in recovery.evidence["routes"]["title_probes"]]
        assert any(s.startswith("error:") for s in states)
        assert recovery.store.get("SBN", "UFI0556368") is not None
        assert recovery.evidence["sources"]["SBN"].startswith("error:")

    def test_a_truncated_sweep_says_so(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        catalogues["sweep"] = {"rows": [], "total": 4000, "pages": 12,
                               "failed": [], "truncated": True}
        evidence = stages.recover(identity()).evidence
        assert evidence["routes"]["author_sweep"]["truncated"] is True
        assert evidence["routes"]["author_sweep"]["total"] == 4000

    def test_the_author_switch_s_other_name_records_are_swept_and_gated(
            self, catalogues, monkeypatch):
        """Decision AV. Each other name authority is swept like the first, and
        what it brings is title-gated like every S3 row."""
        rows = {"CFIV034892": [],
                "X2": [opac_row("X2A", "Steps to an ecology of mind / Gregory Bateson"),
                       opac_row("X2B", "Naven / Gregory Bateson")],
                "X3": []}

        def records_by_authority(authority_id):
            catalogues["asked"].append(("sweep", authority_id))
            return {"rows": rows[authority_id], "total": 700 if authority_id == "X3" else
                    len(rows[authority_id]), "pages": 1, "failed": [],
                    "truncated": authority_id == "X3"}
        monkeypatch.setattr(stages.sbn_opac, "records_by_authority", records_by_authority)
        w = work(author_other_ids=["X2", "X3"])
        catalogues["probe"] = {t: [] for t in stages.gate_variants(w)}
        recovery = stages.recover(identity(w))
        swept = [a[1] for a in catalogues["asked"] if a[0] == "sweep"]
        assert sorted(swept) == ["CFIV034892", "X2", "X3"]
        others = recovery.evidence["routes"]["other_author_sweeps"]
        assert [(o["authority"], o["rows"]) for o in others] == [("X2", 2), ("X3", 0)]
        assert recovery.store.get("SBN", "X2A").provenance.evidence == stages.TITLE_MATCH
        assert recovery.store.get("SBN", "X2B").provenance.evidence == stages.REFUSED

    def test_with_the_switch_off_only_the_one_name_is_swept(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        evidence = stages.recover(identity()).evidence
        assert evidence["routes"]["other_author_sweeps"] == []
        assert [a for a in catalogues["asked"] if a[0] == "sweep"] == [("sweep", "CFIV034892")]


class TestTheReversePath:
    """The typed title's branch. It runs only where there is no identity at all."""

    def unidentified(self):
        return identity(Work(author_id="CFIV023341"), author="Attali",
                        typed="Per una economia positiva")

    def test_it_does_not_run_where_anything_identified_the_work(self, catalogues):
        catalogues["probe"] = {t: [] for t in stages.gate_variants(work())}
        assert stages.recover(identity()).evidence["reverse"] is None

    def test_it_widens_the_gate_to_the_typed_title_and_says_so(self, catalogues):
        catalogues["probe"] = {"Per una economia positiva": [
            opac_row("R1", "Per una economia positiva / Jacques Attali",
                     author="Attali, Jacques")]}
        catalogues["full"] = {"R1": brief("R1", "Per una economia positiva",
                                          dewey="330.1", lingua="ITALIANO")}
        evidence = stages.recover(self.unidentified()).evidence
        assert evidence["reverse"]["widened_gate"] is True
        assert evidence["reverse"]["seeds"] == 1
        assert evidence["reverse"]["typed_title"] == "Per una economia positiva"

    def test_a_seed_is_enriched_because_a_brief_row_has_no_language(self, catalogues):
        catalogues["probe"] = {"Per una economia positiva": [
            opac_row("R1", "Per una economia positiva / Jacques Attali",
                     author="Attali, Jacques")]}
        catalogues["full"] = {"R1": brief("R1", "Per una economia positiva",
                                          dewey="330.1", lingua="ITALIANO")}
        recovery = stages.recover(self.unidentified())
        assert ("full", "R1") in catalogues["asked"]
        assert recovery.store.get("SBN", "R1").language == "ita"

    def test_no_original_is_inferred_and_open_library_is_not_asked(self, catalogues):
        """Decision AH: the Dewey half is gone. *La matrice sociale della
        psichiatria* shares 616.89 and both authors with Ruesch and Bateson's
        *Communication*, and that is no longer a way to name an original."""
        catalogues["probe"] = {"La matrice sociale della psichiatria": [
            opac_row("R1", "La matrice sociale della psichiatria / J. Ruesch",
                     author="Ruesch, Jurgen")]}
        catalogues["full"] = {"R1": {**brief("R1", "La matrice sociale della psichiatria",
                                             dewey="616.89", lingua="ITALIANO"),
                                     "nomi": ["[Autore] Ruesch, Jurgen"]}}
        question = identity(Work(author_id="CFIV005099"), author="Ruesch",
                            typed="La matrice sociale della psichiatria")
        recovery = stages.recover(question)
        assert recovery.store.get("SBN", "R1").provenance.evidence == stages.TITLE_MATCH
        assert not question.work.original_title and not question.work.stated_by
        assert not [a for a in catalogues["asked"] if a[0].startswith("ol_")]


class TestTheParsersSeam:
    def test_a_full_record_s_holdings_become_the_dataclass(self):
        """`catalog/` may not import `core/`, so its parsers hand back plain
        dicts. A `Record` whose holdings are dicts derives an `Edition` that
        raises the first time the view reads one, and no S2 row carries a
        holding at all — so the suite cannot see it and the sweep did."""
        fields = stages.full_fields({"holdings": [{"library": "BNCF", "city": "",
                                                   "isil": "IT-FI0098"}]})
        assert fields["holdings"] == [stages.Holding(library="BNCF", city="",
                                                     isil="IT-FI0098")]
