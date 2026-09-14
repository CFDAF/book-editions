"""A1: does every (entry title, author) reach one identity per source?

    python stage1_a1.py sbn    SBN work: W, A, B and tier, exactly as STRATEGY Step 5
    python stage1_a1.py ol     Open Library main work (original title) and entry-title work
    python stage1_a1.py wd     Wikidata QID: lookup.wikidata.resolve today, and Step 4's rule

Each part writes bench/results/stage-1/a1_<part>.json. The author sent is the
corpus `query_author`. When SBN has no record at all for that form, the
surname alone is tried as a separately labelled fallback, so an author-form
miss is visible rather than mistaken for a missing work.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import common

PART = sys.argv[1]
net = common.setup(f"stage-1/a1-{PART}", log_name=f"a1_{PART}",
                   user_agent=common.UA_CONTACT if PART == "wd" else None)
from lookup import opac, openlibrary, wikidata  # noqa: E402
from lookup.matching import author_matches, core_title, sbn_title_of, strip_disambiguator, surname, title_similarity  # noqa: E402
from lookup.sbn import clean_text  # noqa: E402

THRESHOLD = 0.6
MAX_PAGES = 100


def sim(query: str, candidate: str) -> float:
    return max(title_similarity(query, candidate),
               title_similarity(core_title(query), core_title(candidate)))


# ---------------------------------------------------------------- SBN -----

def post(body):
    return opac._post(body)


def facet(data, name):
    f = next((f for f in data.get("facets") or [] if f.get("name") == name), None)
    return (f or {}).get("items") or []


def rows(data) -> list:
    """[(short bid, catalogued title)], the title being title.info before ' / '."""
    out = []
    for row in data.get("results") or []:
        m = opac.BID.match(str(row.get("id") or "").strip())
        if not m:
            continue
        t = row.get("title") or {}
        info = t.get("info") if isinstance(t, dict) else t
        out.append((m.group(1), sbn_title_of(clean_text(info) or "")))
    return out


def all_pages(body, first=None) -> tuple:
    """Every row of a query, pages 2..n fetched 4 at a time. (rows, total, truncated)."""
    first = first if first is not None else post({**body, "page": "1"})
    total = first.get("total") or 0
    n = min((total + 19) // 20, MAX_PAGES)
    out = rows(first)
    if n > 1:
        with ThreadPoolExecutor(4) as ex:
            for d in ex.map(lambda p: post({**body, "page": str(p)}), range(2, n + 1)):
                out += rows(d)
    return out, total, (total + 19) // 20 > MAX_PAGES


def sbn_identity(title: str, author: str) -> dict:
    m0 = common.mark()
    base = {"core": "sbn", opac.ANY: title, opac.AUTHOR: author}
    first = post({**base, "page": "1"})
    items = [i for i in facet(first, opac.FACET)
             if i.get("value") and not opac.ADAPTATION.search(str(i.get("label") or ""))]
    res = {"author_sent": author, "total": first.get("total") or 0,
           "facet_top": [(i.get("value"), i.get("results")) for i in
                         sorted(items, key=lambda i: -(i.get("results") or 0))[:5]]}
    if not items:
        res.update(W=None, tier="no work", A=None, B=None,
                   guard_requests=common.mark() - m0, b_requests=0)
        return res
    top = max(items, key=lambda i: i.get("results") or 0)
    w = top["value"]
    res["W"] = w
    res["W_count"] = top.get("results")
    res["W_ties"] = [i["value"] for i in items if i.get("results") == top.get("results") and i is not top]
    res["A"] = round(sim(title, w), 3)
    res["guard_requests"] = common.mark() - m0
    if res["A"] >= THRESHOLD:
        res.update(tier="strong", B=None, b_requests=0)
        return res
    m1 = common.mark()
    q_rows, q_total, q_trunc = all_pages(base, first)
    w_rows, w_total, w_trunc = all_pages({**base, opac.WORK: w})
    matching = {bid for bid, t in q_rows if sim(title, t) >= THRESHOLD}
    in_w = matching & {bid for bid, _ in w_rows}
    b = len(in_w) / len(matching) if matching else None
    res.update(
        B=round(b, 3) if b is not None else None,
        B_counts=[len(in_w), len(matching)],
        query_rows=len(q_rows), work_rows=len(w_rows), work_total=w_total,
        truncated=q_trunc or w_trunc,
        b_requests=common.mark() - m1,
        tier="strong" if b is not None and b > 0.5 else "weak" if b == 0.5 else "rejected",
    )
    return res


def run_sbn(corpus):
    out = {}
    for book in corpus["books"]:
        t0 = time.time()
        per_title, entries = {}, {}
        for e in book["entries"]:
            if e["title"] not in per_title:
                try:
                    r = sbn_identity(e["title"], book["query_author"])
                    if r["total"] == 0 and surname(book["query_author"]) != book["query_author"]:
                        r["fallback_surname"] = sbn_identity(e["title"], surname(book["query_author"]))
                except net.SourceError as exc:
                    r = {"error": str(exc)[:300], "tier": "failed"}
                per_title[e["title"]] = r
            entries[e["key"]] = {"title": e["title"], **per_title[e["title"]]}
        out[book["id"]] = {"entries": entries, "wall_s": round(time.time() - t0, 1)}
        print(book["id"], json.dumps({k: (v.get("W"), v.get("tier"), v.get("A"), v.get("B"))
                                      for k, v in entries.items()}, ensure_ascii=False), flush=True)
    return out


# ------------------------------------------------------- Open Library -----

OL_FIELDS = "key,title,author_name,author_key,edition_count,first_publish_year,language"


def _pick(matching):
    if not matching:
        return {"key": None}
    rank, best = max(matching, key=lambda rd: rd[1].get("edition_count") or 0)
    return {"key": best["key"], "title": best.get("title"), "edition_count": best.get("edition_count"),
            "rank": rank, "first_publish_year": best.get("first_publish_year"),
            "author_name": best.get("author_name"),
            "others": [(d["key"], d.get("title"), d.get("edition_count")) for _, d in matching if d is not best][:4]}


def ol_author_keys(author: str) -> list:
    """Author keys from Open Library's own author search (top 10, unfiltered).

    Diagnostic only: `matching.author_matches` compares ASCII tokens, so it
    cannot match an author Open Library files under 村上春樹 or نجيب محفوظ.
    """
    data = net.cached_get_json(f"{openlibrary.BASE}/search/authors.json", {"q": author, "limit": 10})
    return [d["key"] for d in data.get("docs") or []]


def ol_work(q: str, author: str, author_keys: list) -> dict:
    """strict: author_matches on names (the spec's rule, as the pipeline matches authors).
    keyed: the doc's author_key is among Open Library's author-search keys for the author."""
    try:
        data = net.cached_get_json(f"{openlibrary.BASE}/search.json",
                                   {"q": q, "fields": OL_FIELDS, "limit": 20})
    except net.SourceError as exc:
        return {"q": q, "error": str(exc)[:200], "key": None, "keyed": {"key": None}}
    docs = data.get("docs") or []
    strict = [(r, d) for r, d in enumerate(docs) if author_matches(author, d.get("author_name") or [])]
    keyed = [(r, d) for r, d in enumerate(docs)
             if {f"/authors/{k}" if not k.startswith("/") else k for k in d.get("author_key") or []}
             & {k if k.startswith("/") else f"/authors/{k}" for k in author_keys}]
    res = {"q": q, "num_found": data.get("numFound"), "docs": len(docs),
           "author_docs": len(strict), "keyed_author_docs": len(keyed)}
    res.update(_pick(strict))
    res["keyed"] = _pick(keyed)
    return res


def run_ol(corpus):
    out = {}
    for book in corpus["books"]:
        a = book["query_author"]
        try:
            keys = ol_author_keys(a)
        except net.SourceError:
            keys = []
        main = {"original": ol_work(f"{book['original_title']} {a}", a, keys)}
        if book.get("original_title_romanised"):
            main["romanised"] = ol_work(f"{book['original_title_romanised']} {a}", a, keys)
        if core_title(book["original_title"]) != book["original_title"]:
            main["original_core"] = ol_work(f"{core_title(book['original_title'])} {a}", a, keys)
        per_title, entries = {}, {}
        for e in book["entries"]:
            if e["title"] not in per_title:
                per_title[e["title"]] = ol_work(f"{e['title']} {a}", a, keys)
            entries[e["key"]] = {"title": e["title"], **per_title[e["title"]]}
        out[book["id"]] = {"author_keys": keys, "main": main, "entries": entries}
        print(book["id"], {k: (v.get("key"), v["keyed"].get("key")) for k, v in main.items()},
              {k: (v.get("key"), v["keyed"].get("key")) for k, v in entries.items()}, flush=True)
    return out


# ----------------------------------------------------------- Wikidata -----

LABEL_LANGS = "it|en|fr|es|de|pt|la"


def step4_resolve(title: str, author: str) -> dict:
    """wikidata.resolve's candidate loop with Step 4's title rule added."""
    candidates = wikidata._candidate_qids(title, author)
    ents = wikidata._entities(candidates, "labels|sitelinks|claims", LABEL_LANGS)
    tried = []
    for qid in candidates:
        ent = ents.get(qid) or {}
        claims = ent.get("claims") or {}
        if not wikidata._is_written_work(claims):
            tried.append((qid, "not a written work"))
            continue
        author_qids = wikidata._claim_ids(claims, "P50")
        names = wikidata._label_map(author_qids)
        author_names = [names[q] for q in author_qids if q in names]
        if author and author_names and not author_matches(author, author_names):
            tried.append((qid, "author disagrees"))
            continue
        forms = [v["value"] for v in (ent.get("labels") or {}).values()]
        forms += [strip_disambiguator(v["title"]) for v in (ent.get("sitelinks") or {}).values()]
        p1476 = wikidata._claim_first(claims, "P1476") or {}
        if p1476.get("text"):
            forms.append(p1476["text"])
        best = max(((sim(title, f), f) for f in forms), default=(0.0, None))
        if best[0] < THRESHOLD:
            tried.append((qid, f"title {best[0]:.2f} < 0.6 (closest {best[1]!r})"))
            continue
        return {"qid": qid, "matched_form": best[1], "score": round(best[0], 3),
                "candidates": len(candidates), "rejected_before": tried}
    return {"qid": None, "candidates": len(candidates), "rejected_before": tried}


def run_wd(corpus):
    out = {}
    for book in corpus["books"]:
        a = book["query_author"]
        per_title, entries = {}, {}
        for e in book["entries"]:
            if e["title"] not in per_title:
                tally = net.Tally()
                m0 = common.mark()
                cluster, asked = wikidata.resolve(e["title"], a, tally)
                today = {"qid": cluster.qid if cluster else None,
                         "original_title": cluster.original_title if cluster else None,
                         "original_language": cluster.original_language if cluster else None,
                         "original_year": cluster.original_year if cluster else None,
                         "failures": tally.failures}
                rule = step4_resolve(e["title"], a)
                per_title[e["title"]] = {"today": today, "step4": rule,
                                         "requests": common.mark() - m0}
            entries[e["key"]] = {"title": e["title"], **per_title[e["title"]]}
        out[book["id"]] = {"entries": entries}
        print(book["id"], {k: (v["today"]["qid"], v["step4"]["qid"]) for k, v in entries.items()}, flush=True)
    return out


if __name__ == "__main__":
    corpus = common.load_corpus()
    t0 = time.time()
    result = {"sbn": run_sbn, "ol": run_ol, "wd": run_wd}[PART](corpus)
    common.save_json(common.RESULTS / f"a1_{PART}.json",
                     {"books": result, "wall_s": round(time.time() - t0, 1),
                      "requests": common.summarise(), "failures": common.failures()})
    print(json.dumps(common.summarise(), indent=1))
