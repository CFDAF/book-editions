"""A2, one cold run of listing by identity for one entry title.

    python stage2_newpath.py <book id> <entry key>

The assessment §7 path, built from Stage 1's own functions and run under the
same politeness gates (OPAC 4 at a time, Open Library 1 request a second):

  phase 1, side by side: the SBN guard (W, A, B, tier), Wikidata with Step 4's
    title rule (contact User-Agent, per answer 6), Open Library author keys;
  phase 2, side by side: the SBN listing of a strong W per language, and the
    Open Library search with the original title + author (original, then
    romanised, then core title) followed by that work's editions.

The original title comes from the corpus rather than from phase 1. The request
count is the same, and whether identity is right is A1's question, not this
one's. Timing is conservative: gated, with the bogus-language control included.
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor

import common

book_id, key = sys.argv[1:3]
run_id = f"{book_id}__{key}"
common.RESULTS = common.BENCH / "results" / "stage-2"
common.RAW = common.BENCH / "raw" / "stage-2"
net = common.setup(f"stage-2/newpath/{run_id}", fresh=True, log_name=f"newpath/{run_id}",
                   user_agent=common.UA_CONTACT)

import stage1_a1 as a1  # noqa: E402
import stage1_a3 as a3  # noqa: E402
from lookup.matching import core_title  # noqa: E402

book = next(b for b in common.load_corpus()["books"] if b["id"] == book_id)
entry = next(e for e in book["entries"] if e["key"] == key)
title, author = entry["title"], book["query_author"]


def guarded(fn, *args):
    try:
        return fn(*args)
    except net.SourceError as exc:
        return {"error": str(exc)[:300]}


def ol_main(author_keys):
    queries = [("original", book["original_title"])]
    if book.get("original_title_romanised"):
        queries.append(("romanised", book["original_title_romanised"]))
    if core_title(book["original_title"]) != book["original_title"]:
        queries.append(("original_core", core_title(book["original_title"])))
    tried = []
    for label, q in queries:
        r = a1.ol_work(f"{q} {author}", author, author_keys)
        tried.append({"label": label, "q": r["q"], "key": r.get("key"),
                      "keyed": r["keyed"].get("key"), "error": r.get("error")})
        if r.get("key"):
            return r["key"], f"{label}, strict author match", tried
        if r["keyed"].get("key"):
            return r["keyed"]["key"], f"{label}, keyed author match", tried
    return None, None, tried


def ol_side(author_keys):
    t0 = time.time()
    work, how, tried = ol_main(author_keys)
    listing = guarded(a3.ol_listing, work) if work else None
    return {"search": tried, "key": work, "how": how,
            "listing": listing, "wall_s": round(time.time() - t0, 1)}


t0 = time.time()
with ThreadPoolExecutor(3) as ex:
    sbn_f = ex.submit(guarded, a1.sbn_identity, title, author)
    wd_f = ex.submit(guarded, a1.step4_resolve, title, author)
    keys_f = ex.submit(guarded, a1.ol_author_keys, author)
    sbn_id, wd, author_keys = sbn_f.result(), wd_f.result(), keys_f.result()
identity_s = round(time.time() - t0, 1)
if isinstance(author_keys, dict):
    author_keys = []

t1 = time.time()
with ThreadPoolExecutor(2) as ex:
    strong = sbn_id.get("tier") == "strong"
    sbn_f = ex.submit(guarded, a3.sbn_listing, sbn_id["W"], author) if strong else None
    ol_f = ex.submit(ol_side, author_keys)
    sbn_list = sbn_f.result() if sbn_f else None
    ol = ol_f.result()
listing_s = round(time.time() - t1, 1)
wall = round(time.time() - t0, 1)


def lean_sbn(s):
    if not s or "error" in s:
        return s
    return {k: s[k] for k in ("W", "total", "rows", "languages", "lingua_facet", "bogus_lingua_total",
                              "requests", "completeness_requests", "failed_pages", "wall_s")} | {
        "bids": [r["bid"] for r in s["items"]],
        "records_on_no_language_page": [r["bid"] for r in s["records_on_no_language_page"]]}


def lean_ol(o):
    if not o or "error" in o:
        return o
    return {k: o[k] for k in ("key", "size", "rows", "languages", "requests", "failed", "wall_s")} | {
        "keys": [i["key"] for i in o["items"]]}


common.save_json(common.RESULTS / "newpath" / f"{run_id}.json", {
    "run": run_id, "book": book_id, "entry": key, "title": title, "author": author,
    "sbn_identity": {k: v for k, v in sbn_id.items() if k != "facet_top"},
    "wikidata_step4": {k: wd.get(k) for k in ("qid", "matched_form", "score", "candidates", "error")},
    "ol_main": {"key": ol["key"], "how": ol["how"], "search": ol["search"]},
    "sbn_listing": lean_sbn(sbn_list),
    "ol_listing": lean_ol(ol["listing"]),
    "phase_s": {"identity": identity_s, "listing": listing_s, "ol_search_and_listing": ol["wall_s"]},
    "wall_s": wall,
    "requests": common.summarise(), "retries": common.retries(), "failures": common.failures(),
})
print(run_id, sbn_id.get("W"), sbn_id.get("tier"), wd.get("qid"), ol["key"],
      (sbn_list or {}).get("rows"), ((ol["listing"] or {}).get("rows")), f"{wall}s", flush=True)
