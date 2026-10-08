"""`lookup/stages.check_dates`, offline, with SBN stubbed out (decision AY).

What the answer means is `core.dates`'s and is tested in `test_dates.py`. What
is tested here is the wiring:

* only an SBN record whose date is not one plain year is asked about, and
  always with the author (`CLAUDE.md` rule 3);
* only a `dataf[]` value holding a year the imprint wrote is sent, and a range
  value is sent as SBN wrote it — asking by year would never reach it;
* the facet's 50-value cap (F11) does not silently lose a year;
* a failed request marks its records unchecked instead of leaving them looking
  answered (rule 5), and the cap is reported (rule 10).

Imprints and index values are live records' (decision AY's year probe).
"""

import pytest

from catalog.http import SourceError
from core.model import Provenance, Record, UNIFORM_TITLE, WORK_LISTING
from core.store import RecordStore
from lookup import stages


def sbn(bid, date, language="per"):
    return Record(source="SBN", id=bid, date=date, language=language,
                  provenance=Provenance("SBN", WORK_LISTING, UNIFORM_TITLE))


def identity(author="Dostoevskij"):
    return stages.Identity(work=None, evidence={"question": {"author": author}})


@pytest.fixture
def opac(monkeypatch):
    """`facet` is the `dataf[]` facet page 1 returns; `filed[value]` the ids
    SBN files under that value; `fail` the values whose request fails."""
    state = {"facet": [], "filed": {}, "fail": set(), "facet_fails": False,
             "posts": [], "lists": []}

    def post(body):
        state["posts"].append(dict(body))
        if state["facet_fails"]:
            raise SourceError("down")
        return {"facets": [{"name": "dataf[]",
                            "items": [{"value": v} for v in state["facet"]]}]}

    def all_rows(body, cap=12, **_):
        state["lists"].append(dict(body))
        value = body["dataf[]"]
        failed = [{"page": 2, "error": "down"}] if value in state["fail"] else []
        return {"rows": [{"id": i} for i in state["filed"].get(value, [])],
                "failed": failed, "truncated": False}

    monkeypatch.setattr(stages.sbn_opac, "post", post)
    monkeypatch.setattr(stages.sbn_opac, "all_rows", all_rows)
    return state


def test_asks_only_the_values_holding_an_imprint_year(opac):
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]"))
    store.put(sbn("MOD1783518", "2015", language="tur"))      # plain: never asked
    opac["facet"] = ["2007", "2008", "1977-1991"]
    opac["filed"] = {"2007": ["TO01804900"]}
    done = stages.check_dates(identity(), store)
    assert [p["item:1003:Autore:@and@"] for p in opac["posts"]] == ["Dostoevskij"]
    assert opac["posts"][0]["lingua[]"] == "per"
    assert [b["dataf[]"] for b in opac["lists"]] == ["2007"]
    assert all(b["item:1003:Autore:@and@"] == "Dostoevskij" for b in opac["lists"])
    assert store.get("SBN", "TO01804900").date_indexed == ["2007"]
    assert store.get("SBN", "MOD1783518").date_indexed is None
    assert done.evidence == {"rows": 1, "checked": 1, "cap": stages.DATE_CHECK_CAP,
                             "truncated": False, "requests": 2, "failed": 0,
                             "reconcile_wanted": 0, "reconcile_requests": 0,
                             "reconcile_cap": stages.RECONCILE_CAP,
                             "reconcile_truncated": False, "contradicted": 0,
                             "sources": {"SBN": "ok"}}


def test_a_range_value_is_sent_as_sbn_wrote_it(opac):
    store = RecordStore()
    store.put(sbn("GEA0000001", "[tra 1905 e 1910]", language="lat"))
    opac["facet"] = ["1905-1910", "1900"]
    opac["filed"] = {"1905-1910": ["GEA0000001"]}
    stages.check_dates(identity("Homerus"), store)
    assert [b["dataf[]"] for b in opac["lists"]] == ["1905-1910"]
    assert store.get("SBN", "GEA0000001").date_indexed == ["1905-1910"]


def test_a_capped_facet_asks_the_missing_years_directly(opac):
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]"))
    opac["facet"] = [str(y) for y in range(1950, 2000)]       # 50 values, no 2007
    opac["filed"] = {"2007": ["TO01804900"]}
    stages.check_dates(identity(), store)
    assert sorted(b["dataf[]"] for b in opac["lists"]) == ["1386", "2007"]
    assert store.get("SBN", "TO01804900").date_indexed == ["2007"]


def test_a_record_without_a_language_is_asked_without_one(opac):
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]", language="unknown"))
    stages.check_dates(identity(), store)
    assert "lingua[]" not in opac["posts"][0]


def test_no_author_sends_nothing(opac):
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]"))
    stages.check_dates(identity(author=None), store)
    assert opac["posts"] == [] and opac["lists"] == []
    assert store.get("SBN", "TO01804900").date_indexed is None


def test_a_failed_facet_marks_the_language_unchecked(opac):
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]"))
    opac["facet_fails"] = True
    done = stages.check_dates(identity(), store)
    held = store.get("SBN", "TO01804900")
    assert (held.date_indexed, held.date_check_failed) == ([], True)
    assert done.evidence["failed"] == 1


def test_a_failed_page_marks_only_the_records_it_could_have_answered(opac):
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]"))
    store.put(sbn("RMS0184828", "1316 s"))
    opac["facet"] = ["2007", "1316"]
    opac["filed"] = {"2007": ["TO01804900"]}
    opac["fail"] = {"1316"}
    stages.check_dates(identity(), store)
    assert store.get("SBN", "TO01804900").date_check_failed is False
    assert store.get("SBN", "RMS0184828").date_check_failed is True


def test_the_cap_is_reported(opac, monkeypatch):
    monkeypatch.setattr(stages, "DATE_CHECK_CAP", 1)
    store = RecordStore()
    store.put(sbn("TO01804900", "1386 [2007]"))
    store.put(sbn("TO01804756", "1386 [2007]"))
    done = stages.check_dates(identity(), store)
    assert (done.evidence["rows"], done.evidence["checked"],
            done.evidence["truncated"]) == (2, 1, True)
    assert store.get("SBN", "TO01804756").date_indexed is None


# ---------------------------------------------------------------------------
# The listing's plain years, reconciled with SBN's counts
# ---------------------------------------------------------------------------

def plain(bid, date, language="fre"):
    return sbn(bid, date, language)


def bucket(ids, years, complete=True, language="fre", work="etranger."):
    return {"work": work, "language": language, "complete": complete, "ids": ids,
            "years": [{"value": v, "results": n} for v, n in years]}


def test_only_the_years_whose_counts_disagree_are_asked(opac):
    # URB0413776 is `Paris : Stock, 1930` and SBN files it under 1925.
    store = RecordStore()
    store.put(plain("URB0413776", "1930"))
    store.put(plain("URB0000002", "1942"))
    opac["filed"] = {"1925": ["URB0413776"], "1930": []}
    done = stages.check_dates(identity("Camus"), store,
                              buckets=[bucket(["URB0413776", "URB0000002"],
                                              [("1925", 1), ("1930", 0), ("1942", 1)])])
    assert sorted(b["dataf[]"] for b in opac["lists"]) == ["1925", "1930"]
    assert all(b["titolo_uniformef[]"] == "etranger." and b["lingua[]"] == "fre"
               and b["item:1003:Autore:@and@"] == "Camus" for b in opac["lists"])
    assert store.get("SBN", "URB0413776").date_indexed == ["1925"]
    assert store.get("SBN", "URB0000002").date_indexed is None
    assert (done.evidence["reconcile_wanted"], done.evidence["contradicted"]) == (2, 1)


def test_a_year_sbn_does_not_list_is_not_asked(opac):
    store = RecordStore()
    store.put(plain("URB0413776", "1930"))
    opac["filed"] = {"1925": ["URB0413776"]}
    stages.check_dates(identity("Camus"), store,
                       buckets=[bucket(["URB0413776"], [("1925", 1)])])
    assert [b["dataf[]"] for b in opac["lists"]] == ["1925"]
    assert store.get("SBN", "URB0413776").date_indexed == ["1925"]


def test_counts_that_agree_ask_nothing(opac):
    store = RecordStore()
    store.put(plain("URB0413776", "1930"))
    stages.check_dates(identity("Camus"), store,
                       buckets=[bucket(["URB0413776"], [("1930", 1)])])
    assert opac["lists"] == []


def test_a_bucket_read_in_part_is_not_reconciled(opac):
    store = RecordStore()
    store.put(plain("URB0413776", "1930"))
    stages.check_dates(identity("Camus"), store,
                       buckets=[bucket(["URB0413776"], [("1925", 1)], complete=False)])
    assert opac["lists"] == [] and store.get("SBN", "URB0413776").date_indexed is None


def test_a_failed_year_leaves_the_stated_one(opac):
    store = RecordStore()
    store.put(plain("URB0413776", "1930"))
    opac["fail"] = {"1930"}
    done = stages.check_dates(identity("Camus"), store,
                              buckets=[bucket(["URB0413776"], [("1925", 1), ("1930", 0)])])
    assert store.get("SBN", "URB0413776").date_indexed is None
    assert done.evidence["failed"] == 1


def test_the_reconcile_cap_is_reported(opac, monkeypatch):
    monkeypatch.setattr(stages, "RECONCILE_CAP", 1)
    store = RecordStore()
    store.put(plain("URB0413776", "1930"))
    done = stages.check_dates(identity("Camus"), store,
                              buckets=[bucket(["URB0413776"], [("1925", 1), ("1930", 0)])])
    assert len(opac["lists"]) == 1
    assert (done.evidence["reconcile_requests"], done.evidence["reconcile_wanted"],
            done.evidence["reconcile_truncated"]) == (1, 2, True)


def test_the_listing_keeps_each_language_page_s_year_facet(monkeypatch):
    def work_languages(work, author):
        return {"items": [{"value": "per", "results": 1}], "total": 1, "first": {}}

    def work_records(work, author, code):
        return {"rows": [{"id": "TO01804900"}], "total": 1, "pages": 1,
                "truncated": False, "failed": [], "years": [{"value": "2007", "results": 1}]}

    monkeypatch.setattr(stages.sbn_opac, "work_languages", work_languages)
    monkeypatch.setattr(stages.sbn_opac, "work_records", work_records)
    got = stages._sbn_listing_one("prestuplenie i nakazanie", "Dostoevskij")
    assert got["date_buckets"] == [{"work": "prestuplenie i nakazanie", "language": "per",
                                    "years": [{"value": "2007", "results": 1}],
                                    "ids": ["TO01804900"], "complete": True}]


# -- author mode: the records filed under no work ---------------------------

def test_author_mode_asks_under_the_name_authority(opac):
    """`docs/BACKLOG.md` *Author mode's years are not settled*: the name
    authority is the author term (rule 3), and a plain year is not asked."""
    store = RecordStore()
    shamlu = store.put(sbn("RMB0775153", "1388 [2010]"))
    plain = store.put(sbn("UBO3328060", "2003"))
    opac["facet"] = ["2010", "2003"]
    opac["filed"] = {"2010": ["RMB0775153"]}
    ev = stages.check_name_dates([("RMBV243388", shamlu), ("RMBV243388", plain)], store)
    assert [p["item:5032:Nomi::@frase@"] for p in opac["posts"]] == ["RMBV243388"]
    assert all("item:1003:Autore:@and@" not in b for b in opac["posts"] + opac["lists"])
    assert [(b["item:5032:Nomi::@frase@"], b["dataf[]"]) for b in opac["lists"]] == [
        ("RMBV243388", "2010")]
    assert store.get("SBN", "RMB0775153").date_indexed == ["2010"]
    assert store.get("SBN", "UBO3328060").date_indexed is None
    assert ev == {"rows": 1, "checked": 1, "cap": stages.DATE_CHECK_CAP,
                  "truncated": False, "requests": 2, "failed": 0}


def test_author_mode_asks_one_record_once_and_reports_the_cap(opac, monkeypatch):
    monkeypatch.setattr(stages, "DATE_CHECK_CAP", 1)
    store = RecordStore()
    one = store.put(sbn("RMB0775153", "1388 [2010]"))
    two = store.put(sbn("UBO3899257", "1388 H [2010]"))
    ev = stages.check_name_dates([("A", one), ("B", one), ("A", two)], store)
    assert (ev["rows"], ev["checked"], ev["truncated"]) == (2, 1, True)
    assert store.get("SBN", "UBO3899257").date_indexed is None
