"""Stage 2 question 3: can a duplicate Open Library work's editions be reached, and how?

    python s2_q3_duplicate_works.py [--warm]

Duplicate works: the work records Stage 2 found holding editions of a corpus
book outside its Stage 1 main work (losses.json classes 'separate OL work
record' and 'no OL listing', works from loss_evidence.json).

Three probes, Open Library gated to 1 request a second, fresh cache:
  A. by title: the Stage 1 main-work rule (stage1_a1.ol_work, q="<title>
     <author>", 20 docs, most editions among author-matching docs) run with the
     duplicate's own title. Does it pick the duplicate, or the main work again?
  B. finding duplicates to list: search.json, 100 docs, with the original
     title and with each entry title. Which duplicates appear among the
     author-matching docs, and how many other author-matching docs pass the
     0.6 title test against the book's known titles (not judged)?
  C. by key: /works/<duplicate>/editions.json. Does it return the editions
     Stage 2 found in that work?
Controls: a bogus work key; a bogus free-text query.
"""

import collections
import json
import sys
import time

import common

common.RESULTS = common.BENCH / "results" / "stage-3"
common.RAW = common.BENCH / "raw" / "stage-3"
net = common.setup("stage-3/q3", fresh="--warm" not in sys.argv, log_name="q3_duplicate_works",
                   user_agent=common.UA_CONTACT)

import stage1_a1 as a1  # noqa: E402
from judgements import known_titles, sim  # noqa: E402
from lookup import openlibrary  # noqa: E402
from lookup.matching import author_matches  # noqa: E402

OUT = common.RESULTS / "q3_duplicate_works.json"
S2 = common.BENCH / "results" / "stage-2"
S1 = common.BENCH / "results" / "stage-1"
SEARCH_FIELDS = "key,title,author_name,author_key,edition_count"


def duplicates():
    evidence = json.loads((S2 / "loss_evidence.json").read_text())
    out = collections.defaultdict(lambda: collections.defaultdict(set))
    for loss in json.loads((S2 / "losses.json").read_text()):
        if loss["source"] == "OL" and loss["class"] in ("separate OL work record", "no OL listing"):
            book = loss["run"].split("__")[0]
            for work in evidence["ol"].get(loss["id"], {}).get("works", []):
                out[book][work].add(loss["id"])
    return out, evidence["ol_work_titles"]


def search(q):
    try:
        return net.cached_get_json(f"{openlibrary.BASE}/search.json", {"q": q, "fields": SEARCH_FIELDS, "limit": 100})
    except net.SourceError as exc:
        return {"error": str(exc)[:200]}


def author_docs(docs, author, keys):
    keyset = {k if k.startswith("/") else f"/authors/{k}" for k in keys}
    return [d for d in docs if author_matches(author, d.get("author_name") or [])
            or {f"/authors/{k}" if not k.startswith("/") else k for k in d.get("author_key") or []} & keyset]


def main():
    t0 = time.time()
    corpus = {b["id"]: b for b in common.load_corpus()["books"]}
    a1_ol = json.loads((S1 / "a1_ol.json").read_text())["books"]
    dups, work_titles = duplicates()
    books = {}

    for book_id in sorted(dups):
        book = corpus[book_id]
        author, keys = book["query_author"], a1_ol[book_id]["author_keys"]
        listing = json.loads((S1 / "listings" / f"{book_id}.json").read_text())
        main_key = (listing.get("ol") or {}).get("key")
        dup_keys = set(dups[book_id])
        titles = known_titles(book)

        # A and C, per duplicate work
        per_dup = {}
        for work, lost in sorted(dups[book_id].items()):
            title = work_titles.get(work)
            picked = a1.ol_work(f"{title} {author}", author, keys) if title else {"key": None, "keyed": {"key": None}}
            chosen = picked.get("key") or picked["keyed"].get("key")
            outcome = ("the duplicate" if chosen == work else "the main work" if chosen == main_key
                       else "another duplicate" if chosen in dup_keys else "other work" if chosen else "none")
            try:
                eds = net.cached_get_json(f"{openlibrary.BASE}{work}/editions.json", {"limit": 1000})
                entries = {e.get("key") for e in eds.get("entries") or []}
                by_key = {"size": eds.get("size"), "entries": len(entries),
                          "stage2_editions": len(lost), "stage2_editions_returned": len(lost & entries)}
            except net.SourceError as exc:
                by_key = {"error": str(exc)[:200]}
            per_dup[work] = {"title": title, "stage2_editions": len(lost),
                             "by_title": {"q": picked.get("q"), "strict": picked.get("key"),
                                          "keyed": picked["keyed"].get("key"), "picked": chosen,
                                          "picked_title": picked.get("title") or picked["keyed"].get("title"),
                                          "picked_editions": picked.get("edition_count") or picked["keyed"].get("edition_count"),
                                          "outcome": outcome, "error": picked.get("error")},
                             "by_key": by_key}
            print(book_id, work, repr(title), outcome, by_key, flush=True)

        # B, per query
        queries = [("original", book["original_title"])]
        if book.get("original_title_romanised"):
            queries.append(("romanised", book["original_title_romanised"]))
        queries += [(f"entry {e['key']}", e["title"]) for e in book["entries"]]
        seen_q, per_query = set(), []
        for label, title in queries:
            q = f"{title} {author}"
            if q in seen_q:
                continue
            seen_q.add(q)
            data = search(q)
            docs = data.get("docs") or []
            mine = author_docs(docs, author, keys)
            mine_keys = {d["key"] for d in mine}
            gated_others = [(d["key"], d.get("title"), d.get("edition_count")) for d in mine
                            if d["key"] != main_key and d["key"] not in dup_keys
                            and max(sim(d.get("title") or "", t) for t in titles) >= 0.6]
            per_query.append({
                "label": label, "q": q, "num_found": data.get("numFound"), "docs": len(docs), "error": data.get("error"),
                "main_in_author_docs": main_key in mine_keys,
                "duplicates_in_author_docs": sorted(dup_keys & mine_keys),
                "duplicates_in_any_doc": sorted(dup_keys & {d["key"] for d in docs}),
                "duplicates_passing_title_test": sorted(
                    d["key"] for d in mine if d["key"] in dup_keys
                    and max(sim(d.get("title") or "", t) for t in titles) >= 0.6),
                "other_author_docs_passing_title_test": gated_others,
            })
        original = per_query[0]
        union = set().union(*(set(q["duplicates_in_author_docs"]) for q in per_query))
        books[book_id] = {
            "author": author, "main_work": main_key, "duplicates": len(dup_keys), "per_duplicate": per_dup,
            "queries": per_query,
            "duplicates_found_by_original_title": len(original["duplicates_in_author_docs"]),
            "duplicates_found_by_any_query": len(union),
        }

    control_key = "/works/OL0000000W"
    try:
        body = net.cached_get_json(f"{openlibrary.BASE}{control_key}/editions.json", {"limit": 1000})
        control_work = {"size": body.get("size"), "entries": len(body.get("entries") or [])}
    except net.SourceError as exc:
        control_work = {"error": str(exc)[:200]}
    bogus = search("zzqxvqzz qxzzvq")
    control_q = {"num_found": bogus.get("numFound"), "docs": len(bogus.get("docs") or []), "error": bogus.get("error")}

    all_dups = [d for b in books.values() for d in b["per_duplicate"].values()]
    summary = {
        "duplicates": len(all_dups), "books": len(books),
        "by_title_outcomes": dict(collections.Counter(d["by_title"]["outcome"] for d in all_dups)),
        "by_key_returned_all_stage2_editions": sum(1 for d in all_dups if d["by_key"].get("stage2_editions_returned")
                                                   == d["by_key"].get("stage2_editions")),
        "by_key_errors": sum(1 for d in all_dups if "error" in d["by_key"]),
        "found_by_original_title": sum(b["duplicates_found_by_original_title"] for b in books.values()),
        "found_by_any_query": sum(b["duplicates_found_by_any_query"] for b in books.values()),
        "other_author_docs_passing_title_test_by_original_title": sum(
            len(b["queries"][0]["other_author_docs_passing_title_test"]) for b in books.values()),
        "control_bogus_work_key": control_work, "control_bogus_query": control_q,
        "wall_s": round(time.time() - t0, 1), "requests": common.summarise(), "retries": common.retries(),
        "failures": common.failures(),
    }
    common.save_json(OUT, {"summary": summary, "books": books})
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
