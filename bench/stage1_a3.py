"""A3: are listing rows, fetched by identity, enough to filter on?

Fresh BOOK_CACHE_DIR, so every request is cold. Per book, SBN and Open Library
run side by side (different hosts); books run one after another.

SBN, strong works only (from a1_sbn.json):
  1. {core, AUTHOR, titolo_uniformef[]=W} -> total and the lingua[] facet
  2. every language paged with lingua[]=<code>, 20 rows a page, 4 at a time
  3. control: lingua[]=zzqx must return 0
  4. completeness: if the language pages yield fewer distinct BIDs than the
     total, the unfiltered work is paged too, to name the records no language
     page returned (counted apart from the listing's own requests)

Open Library, main work from a1_ol.json (original title; strict author match,
then the keyed match, then the romanised or core title, each labelled):
  /works/<key>/editions.json?limit=1000, following links.next.

Listings go to results/stage-1/listings/<id>.json for Stages 2 and 3.
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import common

if __name__ == "__main__":
    net = common.setup("stage-1/a3", fresh="--warm" not in sys.argv, log_name="a3")
else:  # imported by a later stage, which has already called common.setup
    from lookup import net
from lookup import opac  # noqa: E402
from lookup.sbn import clean_text, parse_publication  # noqa: E402

OL = "https://openlibrary.org"
YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")


def post(body):
    return opac._post(body)


def facet(data, name):
    f = next((f for f in data.get("facets") or [] if f.get("name") == name), None)
    return (f or {}).get("items") or []


def sbn_row(r, code):
    m = opac.BID.match(str(r.get("id") or "").strip())
    t = r.get("title") or {}
    infos = r.get("infos") or []
    return {"bid": m.group(1) if m else r.get("id"),
            "title": clean_text(t.get("info") if isinstance(t, dict) else t),
            "author": clean_text(t.get("text") if isinstance(t, dict) else None),
            "imprint": clean_text(infos[0]) if infos else None,
            "infos_n": len(infos), "type": r.get("type"), "lang": code}


def sbn_listing(w: str, author: str) -> dict:
    m0 = common.mark()
    t0 = time.time()
    base = {"core": "sbn", opac.AUTHOR: author, opac.WORK: w}
    first = post({**base, "page": "1"})
    total = first.get("total") or 0
    langs = [(i["value"], i.get("results") or 0) for i in facet(first, "lingua[]")]
    tasks = [(code, p) for code, n in langs for p in range(1, (n + 19) // 20 + 1)]

    def page(task):
        code, p = task
        d = post({**base, "lingua[]": code, "page": str(p)})
        return code, p, d.get("total"), [sbn_row(r, code) for r in d.get("results") or []]

    failed, pages = [], []
    with ThreadPoolExecutor(4) as ex:
        futures = [ex.submit(page, t) for t in tasks]
        for t, f in zip(tasks, futures):
            try:
                pages.append(f.result())
            except net.SourceError as exc:
                failed.append({"task": t, "error": str(exc)[:200]})
    control = post({**base, "lingua[]": "zzqx"}).get("total")
    listing_requests = common.mark() - m0
    wall = round(time.time() - t0, 1)

    rows, seen = [], {}
    for code, p, _, rs in sorted(pages, key=lambda x: (x[0], x[1])):
        for r in rs:
            if r["bid"] in seen:
                seen[r["bid"]]["langs"].append(code)
                continue
            r["langs"] = [code]
            seen[r["bid"]] = r
            rows.append(r)

    missing, completeness_requests = [], 0
    if len(rows) < total:
        m1 = common.mark()
        n = (total + 19) // 20
        with ThreadPoolExecutor(4) as ex:
            for d in ex.map(lambda p: post({**base, "page": str(p)}), range(1, n + 1)):
                for r in d.get("results") or []:
                    row = sbn_row(r, None)
                    if row["bid"] not in seen:
                        row["langs"] = []
                        missing.append(row)
        completeness_requests = common.mark() - m1

    years, fails = 0, []
    for r in rows:
        publisher, year, place = parse_publication(r["imprint"])
        r["year"], r["publisher"], r["place"] = year, publisher, place
        if year:
            years += 1
        else:
            fails.append({"bid": r["bid"], "imprint": r["imprint"]})
    return {
        "W": w, "author": author, "total": total, "lingua_facet": langs,
        "lingua_facet_sum": sum(n for _, n in langs),
        "rows": len(rows), "multilingual_rows": sum(1 for r in rows if len(r["langs"]) > 1),
        "languages": len(langs), "bogus_lingua_total": control,
        "year_parsed": years, "year_parse_failures": fails,
        "publisher_present": sum(1 for r in rows if r["publisher"]),
        "language_present": sum(1 for r in rows if any(c not in ("und", "zxx", "mis") for c in r["langs"])),
        "records_on_no_language_page": missing,
        "requests": listing_requests, "completeness_requests": completeness_requests,
        "failed_pages": failed, "wall_s": wall, "items": rows,
    }


def ol_listing(key: str) -> dict:
    m0 = common.mark()
    t0 = time.time()
    entries, url, params, failed, size = [], f"{OL}{key}/editions.json", {"limit": 1000}, [], None
    while url:
        try:
            d = net.cached_get_json(url, params)
        except net.SourceError as exc:
            failed.append(str(exc)[:200])
            break
        size = d.get("size", size)
        entries += d.get("entries") or []
        nxt = (d.get("links") or {}).get("next")
        url, params = (f"{OL}{nxt}", None) if nxt else (None, None)
    items = []
    for e in entries:
        date = e.get("publish_date")
        m = YEAR.search(date or "")
        items.append({
            "key": e.get("key"), "title": e.get("title"), "publish_date": date,
            "year": m.group(1) if m else None, "publishers": e.get("publishers") or [],
            "publish_places": e.get("publish_places") or [],
            "languages": [l.get("key", "").rsplit("/", 1)[-1] for l in e.get("languages") or []],
            "isbn_10": e.get("isbn_10") or [], "isbn_13": e.get("isbn_13") or [],
            "translation_of": e.get("translation_of"), "works": [w.get("key") for w in e.get("works") or []],
        })
    langs = {c for i in items for c in i["languages"] if c not in ("und", "zxx", "mis")}
    return {
        "key": key, "size": size, "rows": len(items), "languages": len(langs),
        "language_codes": sorted(langs),
        "year_parsed": sum(1 for i in items if i["year"]),
        "year_parse_failures": [{"key": i["key"], "publish_date": i["publish_date"]} for i in items if not i["year"]],
        "publisher_present": sum(1 for i in items if i["publishers"]),
        "language_present": sum(1 for i in items if any(c not in ("und", "zxx", "mis") for c in i["languages"])),
        "requests": common.mark() - m0, "failed": failed, "wall_s": round(time.time() - t0, 1),
        "items": items,
    }


def identities():
    sbn = json.loads((common.RESULTS / "a1_sbn.json").read_text())["books"]
    ol = json.loads((common.RESULTS / "a1_ol.json").read_text())["books"]
    out = {}
    for bid in sbn:
        strong = {}
        for k, e in sbn[bid]["entries"].items():
            for r in (e, e.get("fallback_surname") or {}):
                if r.get("tier") == "strong":
                    strong.setdefault((r["W"], r["author_sent"]), []).append(k)
        main, how = None, None
        for label in ("original", "romanised", "original_core"):
            r = ol[bid]["main"].get(label)
            if not r:
                continue
            if r.get("key"):
                main, how = r["key"], f"{label}, strict author match"
                break
            if r["keyed"].get("key"):
                main, how = r["keyed"]["key"], f"{label}, keyed author match"
                break
        out[bid] = {"sbn": [{"W": w, "author": a, "entries": ks} for (w, a), ks in strong.items()],
                    "ol": main, "ol_how": how}
    return out


def retry_ol(bids):
    """Re-fetch only the Open Library listing of books whose first attempt failed.

    The SBN side and its cold timings are kept from the first run; the retry is
    recorded under `ol.retry` so its timing is not mistaken for the cold one.
    """
    ids = identities()
    summary = json.loads((common.RESULTS / "a3.json").read_text())
    for bid in bids:
        path = common.RESULTS / "listings" / f"{bid}.json"
        listing = json.loads(path.read_text())
        first_failures = listing["failures"]
        m0 = common.mark()
        res = ol_listing(ids[bid]["ol"])
        res["how"] = ids[bid]["ol_how"]
        res["retry"] = {"first_attempt_failures": first_failures, "requests": common.summarise(m0),
                        "note": "first cold attempt failed; this listing is a second attempt"}
        listing["ol"] = res
        common.save_json(path, listing)
        summary["books"][bid]["ol"] = ({k: v for k, v in res.items() if k not in ("items", "year_parse_failures")}
                                       | {"year_parse_failures": res["year_parse_failures"][:15]})
        print(bid, res["rows"], res["failed"], res["wall_s"], flush=True)
    summary.setdefault("retries", []).append({"books": bids, "requests": common.summarise(),
                                              "failures": common.failures()})
    common.save_json(common.RESULTS / "a3.json", summary)


def main():
    if "--retry-ol" in sys.argv:
        return retry_ol([a for a in sys.argv[1:] if not a.startswith("--")])
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    ids = identities()
    summary = {}
    for bid, ident in ids.items():
        if only and bid not in only:
            continue
        m0 = common.mark()
        t0 = time.time()
        with ThreadPoolExecutor(2) as ex:
            sbn_f = [ex.submit(sbn_listing, s["W"], s["author"]) for s in ident["sbn"]]
            ol_f = ex.submit(ol_listing, ident["ol"]) if ident["ol"] else None
            sbn_res, ol_res = [], None
            for s, f in zip(ident["sbn"], sbn_f):
                try:
                    sbn_res.append({**f.result(), "entries": s["entries"]})
                except net.SourceError as exc:
                    sbn_res.append({"W": s["W"], "error": str(exc)[:300]})
            if ol_f:
                ol_res = ol_f.result()
                ol_res["how"] = ident["ol_how"]
        listing = {"id": bid, "sbn": sbn_res, "ol": ol_res,
                   "wall_s": round(time.time() - t0, 1),
                   "requests": common.summarise(m0), "failures": common.failures(m0)}
        common.save_json(common.RESULTS / "listings" / f"{bid}.json", listing)
        brief = {k: v for k, v in listing.items() if k not in ("sbn", "ol")}
        brief["sbn"] = [{k: v for k, v in s.items() if k not in ("items", "year_parse_failures", "records_on_no_language_page")}
                        | {"year_parse_failures": s.get("year_parse_failures", [])[:15],
                           "records_on_no_language_page": len(s.get("records_on_no_language_page", []))}
                        for s in sbn_res]
        brief["ol"] = ({k: v for k, v in ol_res.items() if k not in ("items", "year_parse_failures")}
                       | {"year_parse_failures": ol_res["year_parse_failures"][:15]}) if ol_res else None
        summary[bid] = brief
        print(bid, json.dumps({"sbn": [(s.get("W"), s.get("rows"), s.get("total"), s.get("languages"),
                                        s.get("year_parsed"), s.get("bogus_lingua_total"), s.get("wall_s"))
                                       for s in brief["sbn"]],
                               "ol": (ol_res or {}).get("rows"), "wall": brief["wall_s"]},
                              ensure_ascii=False), flush=True)
    common.save_json(common.RESULTS / "a3.json", {"books": summary, "requests": common.summarise(),
                                                  "failures": common.failures()})


if __name__ == "__main__":
    main()
