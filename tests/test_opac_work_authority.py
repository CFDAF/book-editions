"""`catalog/sbn_opac.py` — SBN's work authority, and the link that names it.

Every literal is cut from a live body fetched 2026-09-27 (Step 15B): the
*Titolo di opera* row of record `RMS2685379` (*L'invenzione delle notizie*,
Einaudi 2015), and `title?core=opere` for work `RMS2685380` (*The invention of
news*) and `CFI0193626` (*bain el-qasrain.*, which SBN files ITALIANO — the
reason `core.identity.work_language_contradicted` exists). The rows kept are
verbatim; rows the parser does not read were left out.
"""

from catalog import sbn_opac as opac


def _payload(rows):
    return {"status": "success",
            "data": {"results": [{"contents": [{"type": "table", "body": rows}]}]}}


INVENTION_RECORD = _payload([
    [{"type": "table-title", "value": "Titolo di opera"},
     {"type": "table-list", "contents": [{"type": "table-list", "style": "inline", "contents": [
         {"type": "table-links", "values": [
             {"href": "/c/search/opac?groupId=20122&item:8006:Titolo_uniforme:@frase@=RMS2685380",
              "value": "The invention of news", "label": "| Pettegree, Andrew"}]},
         {"type": "icon", "class": "fas fa-angle-right"},
         {"type": "link", "href": "/c/opac/opere/view?groupId=20122&id=RMS2685380",
          "label": "Scheda di autorità"}]}]}],
])

INVENTION_WORK = _payload([
    [{"type": "table-title", "value": "Lingua"}, {"type": "table-text", "value": "INGLESE"}],
    [{"type": "table-title", "value": "Identificativo SBN"},
     {"type": "table-text", "value": "RMS2685380"}],
])

MAHFOUZ_WORK = _payload([
    [{"type": "table-title", "value": "Lingua"}, {"type": "table-text", "value": "ITALIANO"}],
    [{"type": "table-title", "value": "Identificativo SBN"},
     {"type": "table-text", "value": "CFI0193626"}],
])

LIQUID_WORK = _payload([
    [{"type": "table-title", "value": "Forme varianti"},
     {"type": "table-list", "contents": [{"type": "table-text", "value": "Modernità liquida"}]}],
])


def test_a_record_names_the_work_it_is_filed_under_by_id():
    assert opac.work_links(INVENTION_RECORD) == [
        {"id": "RMS2685380", "label": "The invention of news"}]


def test_a_record_with_no_work_row_names_none():
    assert opac.work_links({"status": "success", "data": None}) == []


def test_the_work_states_its_language_as_catalogued(monkeypatch):
    bodies = {"RMS2685380": INVENTION_WORK, "CFI0193626": MAHFOUZ_WORK,
              "RAV0823160": LIQUID_WORK, "ZZZ9999999": {"status": "success", "data": None}}
    asked = []

    def get(url, params, **kw):
        asked.append(params)
        return bodies[params["id"]]

    monkeypatch.setattr(opac, "cached_get_json", get)
    assert opac.work_authority("RMS2685380")["language"] == "INGLESE"
    # Read as stated — whether to believe it is core's question, not this one's.
    assert opac.work_authority("CFI0193626")["language"] == "ITALIANO"
    assert opac.work_authority("RAV0823160") == {"language": None,
                                                 "variants": ["Modernità liquida"]}
    assert opac.work_authority("ZZZ9999999") == {"language": None, "variants": []}
    assert {p["core"] for p in asked} == {"opere"}
