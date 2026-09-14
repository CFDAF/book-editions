"""Re-check the verified facts Stage 1 relies on, each with its control.

F1 titolo_uniformef[] filters · F4 lingua[] filters · F5 row shape · F8
tiporec[]/level[] filter · F9 fixed page size · F11 facet cap. Also the paging
controls A3 depends on: a page past the end is empty and pages do not repeat
rows. Open Library: editions.json honours limit, and a bogus work key fails
rather than returning another work's editions.
"""

import json

import common

net = common.setup("stage-1/facts", fresh=True, log_name="facts")
from lookup import opac  # noqa: E402

A = "Garcia Marquez"
W = "cien anos de soledad"


def post(body):
    return net.cached_post_json(opac.SEARCH, body)["data"]


def facet(data, name):
    f = next((f for f in data.get("facets") or [] if f.get("name") == name), None)
    return (f or {}).get("items") or []


out = {}
base = {"core": "sbn", opac.AUTHOR: A, opac.WORK: W, "page": "1"}
d = post(base)
out["F1"] = {
    "work_total": d.get("total"),
    "bogus_work_total": post({**base, opac.WORK: "zzqx bogus work"}).get("total"),
    "bare_core_total": post({"core": "sbn", "page": "1"}).get("total"),
}
langs = {i["value"]: i["results"] for i in facet(d, "lingua[]")}
out["F4"] = {
    "facet_ita_spa_eng": [langs.get("ita"), langs.get("spa"), langs.get("eng")],
    "ita_total": post({**base, "lingua[]": "ita"}).get("total"),
    "bogus_lingua_total": post({**base, "lingua[]": "zzz"}).get("total"),
    "ita_alone_total": post({"core": "sbn", "lingua[]": "ita", "page": "1"}).get("total"),
    "facet_sum": sum(langs.values()),
    "facet_items": len(langs),
}
row = (d.get("results") or [{}])[0]
out["F5"] = {"row_keys": sorted(row), "title_keys": sorted(row.get("title") or {}),
             "infos0": (row.get("infos") or [None])[0], "id": row.get("id")}
out["F8"] = {
    "tiporec": {i["value"]: i["results"] for i in facet(d, "tiporec[]")},
    "level": {i["value"]: i["results"] for i in facet(d, "level[]")},
    "tiporec_a_total": post({**base, "tiporec[]": "a"}).get("total"),
    "bogus_tiporec_total": post({**base, "tiporec[]": "zz"}).get("total"),
}
p1 = d.get("results") or []
p_rows = post({**base, "rows": "100"}).get("results") or []
last = (d["total"] + 19) // 20
beyond = post({**base, "page": str(last + 1)}).get("results") or []
p2 = post({**base, "page": "2"}).get("results") or []
out["F9"] = {
    "page1_rows": len(p1), "rows_param_100_rows": len(p_rows),
    "page_past_end_rows": len(beyond),
    "page1_page2_overlap": len({r["id"] for r in p1} & {r["id"] for r in p2}),
}
attali = post({"core": "sbn", opac.AUTHOR: "Jacques Attali", "page": "1"})
out["F11"] = {"attali_total": attali.get("total"),
              "attali_titolo_uniformef_items": len(facet(attali, "titolo_uniformef[]"))}

ol = net.cached_get_json("https://openlibrary.org/works/OL274505W/editions.json", {"limit": 1000})
try:
    net.cached_get_json("https://openlibrary.org/works/OL0000000000W/editions.json", {"limit": 5})
    bogus = "answered"
except net.SourceError as exc:
    bogus = f"failed: {str(exc)[-60:]}"
small = net.cached_get_json("https://openlibrary.org/works/OL274505W/editions.json", {"limit": 5})
out["OL_editions"] = {"limit1000_entries": len(ol.get("entries") or []), "size": ol.get("size"),
                      "links": sorted((ol.get("links") or {})),
                      "limit5_entries": len(small.get("entries") or []),
                      "limit5_has_next": "next" in (small.get("links") or {}),
                      "bogus_work": bogus}
out["requests"] = common.summarise()
common.save_json(common.RESULTS / "facts.json", out)
print(json.dumps(out, ensure_ascii=False, indent=1))
