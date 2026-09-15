"""Stage 2 analysis: A2, today's pipeline against listing by identity.

    python stage2_analyse.py            fetch the loss evidence (cached), then score
    python stage2_analyse.py --offline  score from results/stage-2/loss_evidence.json only

A loss is a record today's run shows that the book's Stage 1 listing lacks:
an SBN BID outside every listed W, or an Open Library edition key outside the
main work's editions. Evidence, one request per distinct record:
  SBN            OPAC /o/opac-api/title?id=<BID>: its "Titolo di opera" rows.
                 A bogus BID returns data: null, so "no work row" is not
                 "no record".
  Open Library   the edition's works[] from the run's own cached editions.json,
                 else /books/<key>.json; a separate work's title from
                 /works/<key>.json.
Classes (docs/Task.md): not linked to W in SBN · held in a separate Open Library
work record · a wrong-work leak in today's tool · other (named). Records of a
book with no Stage 1 listing in that source are counted apart (answer 7).
Whether a record is the same work is decided by title similarity >= 0.6 to the
book's known titles or its uniform titles, else by the hand judgements in
judgements.STAGE2; what neither covers stays unexplained.

Writes results/stage-2/{loss_evidence,losses,summary}.json, tables.md and
bench/baseline/<run>.json (structural fields only).
"""

import itertools
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

import common

OFFLINE = "--offline" in sys.argv
ONLY = {a for a in sys.argv[1:] if not a.startswith("--")}  # book ids, for trying the script on a few
common.RESULTS = common.BENCH / "results" / "stage-2"
common.RAW = common.BENCH / "raw" / "stage-2"
R1, R2, RAW = common.BENCH / "results" / "stage-1", common.RESULTS, common.RAW
if not OFFLINE:
    net = common.setup("stage-2/analyse", log_name="analyse")

from judgements import INSIGHTS, NOT_A_WORK, RIGHT_W, STAGE2, known_titles, sim  # noqa: E402
from lookup.matching import title_similarity  # noqa: E402

THRESHOLD = 0.6
OPAC_TITLE = "https://opac.sbn.it/o/opac-api/title"
OL = "https://openlibrary.org"
corpus = common.load_corpus()
BOOKS = {b["id"]: b for b in corpus["books"]}


def runs_dir(name):
    moved = RAW / name
    return moved if moved.exists() else R2 / name


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------ inputs -----

def records(report) -> list:
    out = []
    for code, eds in report["editions_by_language"].items():
        for e in eds:
            m = re.search(r"openlibrary\.org(/(?:books|works)/OL\d+[MW])", e.get("url") or "")
            out.append({"bid": e.get("sbn_bid"), "ol": m.group(1) if m else None, "lang": code,
                        "title": e["title"], "year": e.get("year"), "publisher": e.get("publisher"),
                        "authors": e.get("authors") or [], "reasons": e.get("match_reasons") or [],
                        "source": e["source"], "role": e.get("role")})
    return out


def stage1_listing(book_id):
    L = load(R1 / "listings" / f"{book_id}.json")
    listed = [s for s in L["sbn"] if "items" in s]
    sbn = None
    if listed:
        sbn = {r["bid"] for s in listed for r in s["items"]}
        sbn |= {r["bid"] for s in listed for r in s.get("records_on_no_language_page", [])}
    return {"sbn": sbn, "W": {s["W"] for s in listed},
            "ol": {i["key"] for i in L["ol"]["items"]} if L["ol"] else None,
            "ol_main": L["ol"]["key"] if L["ol"] else None}


RUNLOG = [json.loads(l) for l in (R2 / "runlog.jsonl").read_text().splitlines()]
entries = [(b["id"], e["key"]) for b in corpus["books"] for e in b["entries"] if not ONLY or b["id"] in ONLY]
TODAY, UA, NEW, META, META_UA = {}, {}, {}, {}, {}
for book_id, key in entries:
    rid = f"{book_id}__{key}"
    if (rep := load(runs_dir("runs") / f"{rid}.json")) is not None:
        TODAY[rid] = rep[0]
        META[rid] = load(R2 / "meta" / f"{rid}.json")
    if (rep := load(runs_dir("runs-ua-contact") / f"{rid}.json")) is not None:
        UA[rid] = rep[0]
        META_UA[rid] = load(R2 / "meta-ua-contact" / f"{rid}.json")
    if (n := load(R2 / "newpath" / f"{rid}.json")) is not None:
        NEW[rid] = n
AUTHORS = {}
for person in ([] if ONLY else corpus["authors"]):
    for n, variant in enumerate(person["variants"], 1):
        rid = f"{person['id']}__{n}"
        if (rep := load(runs_dir("runs") / f"{rid}.json")) is not None:
            AUTHORS[rid] = {"person": person["id"], "variant": variant, "report": rep[0],
                            "meta": load(R2 / "meta" / f"{rid}.json")}
LISTINGS = {b: stage1_listing(b) for b in BOOKS}


# ---------------------------------------------------------- evidence -----

def lost_ids():
    sbn, ol = set(), set()
    for rid, rep in TODAY.items():
        L = LISTINGS[rid.split("__")[0]]
        for r in records(rep):
            if r["bid"] and (L["sbn"] is None or r["bid"] not in L["sbn"]):
                sbn.add(r["bid"])
            if r["ol"] and r["ol"].startswith("/books/") and (L["ol"] is None or r["ol"] not in L["ol"]):
                ol.add(r["ol"])
    return sbn, ol


def work_rows(node) -> list:
    """The uniform-title links under a 'Titolo di opera' table title, anywhere in the detail."""
    def links(x):
        if isinstance(x, dict):
            if "Titolo_uniforme:@frase@=" in str(x.get("href", "")) and x.get("value"):
                yield {"id": x["href"].rsplit("=", 1)[-1], "title": x["value"], "label": x.get("label")}
            for v in x.values():
                yield from links(v)
        elif isinstance(x, list):
            for v in x:
                yield from links(v)

    found = []
    if isinstance(node, list):
        for i, x in enumerate(node):
            if isinstance(x, dict) and x.get("type") == "table-title" and x.get("value") == "Titolo di opera":
                found += list(links(node[i + 1:i + 2]))
            else:
                found += work_rows(x)
    elif isinstance(node, dict):
        for x in node.values():
            found += work_rows(x)
    return found


def sbn_evidence(bid):
    try:
        d = net.cached_get_json(OPAC_TITLE, {"id": bid, "core": "sbn", "page": 1})
    except net.SourceError as exc:
        return {"error": str(exc)[:200]}
    if not d.get("data"):
        return {"found": False}
    return {"found": True, "works": work_rows(d["data"])}


def ol_works_from_cache():
    """Edition key -> works keys, from every today run's cached editions.json."""
    out = {}
    for f in (common.BENCH / "cache" / "stage-2").glob("today*/*/*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(d, dict) and isinstance(d.get("entries"), list):
            for e in d["entries"]:
                if isinstance(e, dict) and str(e.get("key", "")).startswith("/books/"):
                    out[e["key"]] = [w.get("key") for w in e.get("works") or []]
    return out


def gather():
    old = load(R2 / "loss_evidence.json") or {"sbn": {}, "ol": {}, "ol_work_titles": {}}
    sbn_ids, ol_ids = lost_ids()
    todo = sorted(b for b in sbn_ids if b not in old["sbn"] or "error" in old["sbn"][b])
    with ThreadPoolExecutor(4) as ex:
        for bid, ev in zip(todo, ex.map(sbn_evidence, todo)):
            old["sbn"][bid] = ev
    control = sbn_evidence("ZZQX000000")
    cached = ol_works_from_cache()
    for key in sorted(k for k in ol_ids if k not in old["ol"] or "error" in old["ol"][k]):
        if key in cached:
            old["ol"][key] = {"works": cached[key], "via": "run cache"}
            continue
        try:
            d = net.cached_get_json(f"{OL}{key}.json")
            old["ol"][key] = {"works": [w.get("key") for w in d.get("works") or []], "via": "/books"}
        except net.SourceError as exc:
            old["ol"][key] = {"error": str(exc)[:200]}
    works = {w for ev in old["ol"].values() for w in ev.get("works", [])}
    mains = {L["ol_main"] for L in LISTINGS.values()}
    for w in sorted(works - mains - set(old["ol_work_titles"])):
        try:
            d = net.cached_get_json(f"{OL}{w}.json")
            old["ol_work_titles"][w] = d.get("title")
        except net.SourceError as exc:
            old["ol_work_titles"][w] = None
            old.setdefault("ol_work_title_errors", {})[w] = str(exc)[:200]
    old["control_bogus_bid"] = control
    old["requests"] = common.summarise()
    old["failures"] = common.failures()
    common.save_json(R2 / "loss_evidence.json", old)
    return old


EV = load(R2 / "loss_evidence.json") if OFFLINE else gather()


# ---------------------------------------------------------- classify -----

def same_title(book, *titles):
    forms = known_titles(BOOKS[book]) + sorted(RIGHT_W.get(book, set()))
    return max((sim(t, f) for t in titles if t for f in forms), default=0.0) >= THRESHOLD


def classify_sbn(book, r):
    L = LISTINGS[book]
    hand = STAGE2.get((book, r["bid"]))
    ev = EV["sbn"].get(r["bid"]) or {"error": "no evidence"}
    if "error" in ev:
        return "unexplained", f"evidence failed: {ev['error']}"
    if not ev["found"]:
        return "unexplained", "record not found in the OPAC"
    works = [w["title"] for w in ev["works"]]
    listed_w = L["W"] or RIGHT_W.get(book, set())
    # Full titles only: core titles make "L'amica geniale" the same as W
    # "amica geniale : infanzia, adolescenza", which is a different uniform title.
    if not hand and any(title_similarity(w, lw) >= 0.9 for w in works for lw in listed_w):
        detail = f"linked to W ({works[0]}), outside {{AUTHOR, W}}"
        return ("no SBN listing", "same work; " + detail) if L["sbn"] is None else ("other", detail)
    same = hand[0] if hand else ("same work" if same_title(book, r["title"], *works) else None)
    what = f"another uniform title: {'; '.join(works)}" if works else "no uniform title"
    if L["sbn"] is None:
        return "no SBN listing", f"{same or 'unjudged'}; {what}" + (f"; {hand[1]}" if hand else "")
    if same == "same work":
        return "not linked to W", what + (f"; {hand[1]}" if hand else "")
    if same:
        return verdict_class(same), f"{same}; {what}; {hand[1]}"
    return "unexplained", what


def verdict_class(verdict):
    """'other: volume with other works' is reported as class 'other', its kind kept in `why`."""
    return "other" if verdict.startswith("other") else verdict


def classify_ol(book, r, work_title_of):
    L = LISTINGS[book]
    hand = STAGE2.get((book, r["ol"]))
    ev = EV["ol"].get(r["ol"]) or {"error": "no evidence"}
    if "error" in ev:
        return "unexplained", f"evidence failed: {ev['error']}"
    works = ev["works"]
    if L["ol"] is not None and L["ol_main"] in works:
        return "other", "now in the main work's editions (catalogue drift since Stage 1)"
    titles = [work_title_of.get(w) for w in works]
    what = f"work {', '.join(works)} ({'; '.join(t or '?' for t in titles)})"
    same = hand[0] if hand else ("same work" if same_title(book, r["title"], *titles) else None)
    if L["ol"] is None:
        return "no OL listing", f"{same or 'unjudged'}; {what}" + (f"; {hand[1]}" if hand else "")
    if same == "same work":
        return "separate OL work record", what + (f"; {hand[1]}" if hand else "")
    if same:
        return verdict_class(same), f"{same}; {what}; {hand[1]}"
    return "unexplained", what


def jaccard(a, b):
    return round(len(a & b) / len(a | b), 3) if a | b else None


def ids(recs, sbn_only=False):
    out = {f"sbn:{r['bid']}" for r in recs if r["bid"]}
    if not sbn_only:
        out |= {f"ol:{r['ol']}" for r in recs if r["ol"]}
    return out


losses, per_run = [], {}
work_titles = EV.get("ol_work_titles", {})
for rid, rep in TODAY.items():
    book = rid.split("__")[0]
    recs = records(rep)
    L = LISTINGS[book]
    counts = Counter()
    for r in recs:
        if r["bid"] and (L["sbn"] is None or r["bid"] not in L["sbn"]):
            cls, why = classify_sbn(book, r)
            counts[("SBN", cls)] += 1
            losses.append({"run": rid, "source": "SBN", "id": r["bid"], "class": cls, "why": why,
                           **{k: r[k] for k in ("lang", "title", "year", "publisher", "reasons")}})
        if r["ol"] and r["ol"].startswith("/books/") and (L["ol"] is None or r["ol"] not in L["ol"]):
            cls, why = classify_ol(book, r, work_titles)
            counts[("OL", cls)] += 1
            losses.append({"run": rid, "source": "OL", "id": r["ol"], "class": cls, "why": why,
                           **{k: r[k] for k in ("lang", "title", "year", "publisher", "reasons")}})
    meta, new = META.get(rid) or {}, NEW.get(rid) or {}
    per_run[rid] = {
        "records": len(recs), "sbn_records": sum(1 for r in recs if r["bid"]),
        "ol_records": sum(1 for r in recs if r["ol"]),
        "listing_only": {"sbn": len(L["sbn"] - {r["bid"] for r in recs}) if L["sbn"] is not None else None,
                         "ol": len(L["ol"] - {r["ol"] for r in recs}) if L["ol"] is not None else None},
        "in_listing": {"sbn": sum(1 for r in recs if r["bid"] and L["sbn"] and r["bid"] in L["sbn"]),
                       "ol": sum(1 for r in recs if r["ol"] and L["ol"] and r["ol"] in L["ol"])},
        "losses": {f"{s} · {c}": n for (s, c), n in sorted(counts.items())},
        "sources": rep["sources"], "languages": sorted(rep["editions_by_language"]),
        "choices": len(rep["choices"]),
        "wall_s": meta.get("wall_s"),
        "requests": sum(h["requests"] for h in (meta.get("requests") or {}).values()),
        "failed": sum(h["failed"] for h in (meta.get("requests") or {}).values()),
        "retries": meta.get("retries"),
        "newpath": {"wall_s": new.get("wall_s"),
                    "requests": sum(h["requests"] for h in (new.get("requests") or {}).values()),
                    "failed": sum(h["failed"] for h in (new.get("requests") or {}).values()),
                    "sbn_tier": (new.get("sbn_identity") or {}).get("tier"),
                    "sbn_rows": (new.get("sbn_listing") or {}).get("rows"),
                    "ol_rows": (new.get("ol_listing") or {}).get("rows")} if new else None,
    }

# Overlap across one book's entry titles, today and by identity.
overlap = {}
for book_id, book in BOOKS.items():
    keys = [e["key"] for e in book["entries"] if f"{book_id}__{e['key']}" in TODAY]
    if len(keys) < 2:
        continue
    pairs = {}
    for a, b in itertools.combinations(keys, 2):
        ra, rb = records(TODAY[f"{book_id}__{a}"]), records(TODAY[f"{book_id}__{b}"])
        na, nb = NEW.get(f"{book_id}__{a}"), NEW.get(f"{book_id}__{b}")
        new_ids = lambda n: ({f"sbn:{x}" for x in ((n["sbn_listing"] or {}).get("bids") or [])}
                             | {f"ol:{x}" for x in ((n["ol_listing"] or {}).get("keys") or [])})
        pairs[f"{a}~{b}"] = {"today_all": jaccard(ids(ra), ids(rb)),
                             "today_sbn": jaccard(ids(ra, True), ids(rb, True)),
                             "identity_all": jaccard(new_ids(na), new_ids(nb)) if na and nb else None}
    overlap[book_id] = pairs

noise = {}
for rid in TODAY:
    if rid in UA:
        noise[rid] = {"today_vs_ua_contact_all": jaccard(ids(records(TODAY[rid])), ids(records(UA[rid]))),
                      "today_vs_ua_contact_sbn": jaccard(ids(records(TODAY[rid]), True), ids(records(UA[rid]), True))}


def dist(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return {"n": len(xs), "median": round(statistics.median(xs), 1), "p90": xs[int(0.9 * (len(xs) - 1))],
            "max": xs[-1], "total": round(sum(xs), 1)}


paired = [(rid, p["wall_s"], p["newpath"]["wall_s"]) for rid, p in per_run.items()
          if p["newpath"] and p["wall_s"] is not None and p["newpath"]["wall_s"] is not None]
latency = {
    "today": dist([t for _, t, _ in paired]), "identity": dist([n for _, _, n in paired]),
    "identity_slower": [(rid, t, n) for rid, t, n in paired if n >= t],
    "ratio_median": round(statistics.median(t / n for _, t, n in paired if n), 1) if paired else None,
    # Today's runs whose Wikimedia requests met no 429: the comparison A8's throttling does not tilt.
    "no_wikimedia_429": (lambda runs: {
        "today": dist([t for _, t, _ in runs]), "identity": dist([n for _, _, n in runs]),
        "identity_slower": [(rid, t, n) for rid, t, n in runs if n >= t]})(
        [x for x in paired if not any("wiki" in (h or "") and v.get("429")
                                      for h, v in (META[x[0]]["retries"] or {}).items())]),
    "ua_control": [{"run": rid, "today_s": META[rid]["wall_s"], "ua_contact_s": META_UA[rid]["wall_s"],
                    "identity_s": (NEW.get(rid) or {}).get("wall_s"),
                    "wikimedia_429_today": sum(v.get("429", 0) for h, v in (META[rid]["retries"] or {}).items()
                                               if "wiki" in (h or "")),
                    "wikimedia_429_ua_contact": sum(v.get("429", 0) for h, v in (META_UA[rid]["retries"] or {}).items()
                                                    if "wiki" in (h or ""))}
                   for rid in META_UA if rid in META],
}


def host_totals(metas):
    out = defaultdict(lambda: {"requests": 0, "failed": 0, "total_s": 0.0, "retries": Counter()})
    for m in metas:
        for h, v in (m.get("requests") or {}).items():
            out[h]["requests"] += v["requests"]
            out[h]["failed"] += v["failed"]
            out[h]["total_s"] = round(out[h]["total_s"] + v["total_s"], 1)
        for h, v in (m.get("retries") or {}).items():
            out[h]["retries"].update(v)
    return {h: {**v, "retries": dict(v["retries"])} for h, v in sorted(out.items(), key=lambda x: -x[1]["requests"])}


authors = {}
for rid, a in AUTHORS.items():
    rows = records(a["report"])
    authors[rid] = {"person": a["person"], "variant": a["variant"], "rows": len(rows),
                    "titles": sorted({r["title"] for r in rows}), "sources": a["report"]["sources"],
                    "wall_s": (a["meta"] or {}).get("wall_s"),
                    "requests": sum(h["requests"] for h in ((a["meta"] or {}).get("requests") or {}).values())}
author_overlap = {}
for person in corpus["authors"]:
    runs = [r for r in authors if authors[r]["person"] == person["id"]]
    for a, b in itertools.combinations(runs, 2):
        author_overlap[f"{a}~{b}"] = jaccard(set(authors[a]["titles"]), set(authors[b]["titles"]))

scored = [l for l in losses if l["run"].split("__")[0] not in NOT_A_WORK | INSIGHTS]
by_class = Counter((l["source"], l["class"]) for l in scored)
distinct = Counter((l["source"], l["class"]) for l in {(l["run"].split("__")[0], l["source"], l["id"]): l
                                                        for l in scored}.values())
unexplained = [l for l in scored if l["class"] == "unexplained"]
verdict = {
    "unexplained_losses": len(unexplained),
    "identity_slower_entries": len(latency["identity_slower"]),
    "A2": "FAIL" if unexplained or latency["identity_slower"] else "PASS",
}

romanised = {}
for book_id, book in BOOKS.items():
    for e in book["entries"]:
        if e.get("script_title") and (n := NEW.get(f"{book_id}__{e['key']}")):
            stage1 = json.loads((R1 / "a1_sbn.json").read_text())["books"][book_id]["entries"][e["key"]]
            romanised[f"{book_id}__{e['key']}"] = {
                "title": e["title"], "script_title": e["script_title"],
                "stage1_sbn": {k: stage1.get(k) for k in ("W", "tier", "A", "B")},
                "stage2_sbn": {k: n["sbn_identity"].get(k) for k in ("W", "tier", "A", "B")},
                "stage2_wikidata_step4": n["wikidata_step4"]["qid"], "stage2_ol_main": n["ol_main"]["key"],
                "today_records": per_run.get(f"{book_id}__{e['key']}", {}).get("records")}

summary = {"verdict": verdict, "romanised_entries": romanised, "losses_by_class_records": {f"{s} · {c}": n for (s, c), n in sorted(by_class.items())},
           "losses_by_class_distinct": {f"{s} · {c}": n for (s, c), n in sorted(distinct.items())},
           "latency": latency, "overlap": overlap, "noise_ua_pairs": noise, "per_run": per_run,
           "authors": authors, "author_overlap": author_overlap,
           "hosts_today": host_totals(META.values()), "hosts_ua_contact": host_totals(META_UA.values()),
           "hosts_identity": host_totals(NEW.values()),
           "hosts_authors": host_totals(a["meta"] for a in AUTHORS.values() if a["meta"]),
           "runlog": {"attempts": len(RUNLOG), "nonzero": [r for r in RUNLOG if r["exit"] != 0]},
           "evidence": {k: EV.get(k) for k in ("control_bogus_bid", "requests", "failures")}}
common.save_json(R2 / "summary.json", summary)
common.save_json(R2 / "losses.json", losses)


# ---------------------------------------------------------- baseline -----

def baseline(rep):
    o, c = rep["overview"], rep["cluster"]
    recs = records(rep)
    base = {"mode": rep["mode"], "query_title": rep["query_title"], "query_author": rep["query_author"],
            "languages": sorted(rep["editions_by_language"]),
            "original": {"title": c.get("original_title"), "language": c.get("original_language"),
                         "year": c.get("original_year"), "qid": c.get("qid"), "source": c.get("source")},
            "overview": {"title": o.get("title"), "original_language": o.get("original_language"),
                         "original_year": o.get("original_year"), "first_year_seen": o.get("first_year_seen"),
                         "origin": o.get("origin"), "ambiguous": o.get("ambiguous")},
            "choices": len(rep["choices"]), "sources": rep["sources"]}
    if rep["mode"] == "author":
        base["works"] = sorted({r["title"] for r in recs})
    else:
        base["bids"] = sorted({r["bid"] for r in recs if r["bid"]})
    return base


for rid, rep in list(TODAY.items()) + [(rid, a["report"]) for rid, a in AUTHORS.items()]:
    common.save_json(common.BENCH / "baseline" / f"{rid}.json", baseline(rep))

# ------------------------------------------------------------ tables -----

def md(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(out + ["| " + " | ".join("—" if c is None else str(c) for c in r) + " |" for r in rows])


def book_rows():
    rows = []
    for book_id, book in BOOKS.items():
        rids = [f"{book_id}__{e['key']}" for e in book["entries"] if f"{book_id}__{e['key']}" in per_run]
        if not rids:
            continue
        L = LISTINGS[book_id]
        mine = {(l["source"], l["id"]): l["class"] for l in losses if l["run"] in rids}
        cls = Counter(f"{s} {c}" for (s, _), c in mine.items())
        pr = [per_run[r] for r in rids]
        ov = overlap.get(book_id, {})
        lo = lambda k: min((p[k] for p in ov.values() if p[k] is not None), default=None)
        rows.append([
            book_id + (" *" if book_id in NOT_A_WORK | INSIGHTS else ""), len(rids),
            " / ".join(str(p["records"]) for p in pr),
            " / ".join(f"{p['listing_only']['sbn'] if p['listing_only']['sbn'] is not None else '—'}·"
                       f"{p['listing_only']['ol'] if p['listing_only']['ol'] is not None else '—'}" for p in pr),
            "—" if L["sbn"] is None else len(L["sbn"]), "—" if L["ol"] is None else len(L["ol"]),
            "; ".join(f"{k} {n}" for k, n in sorted(cls.items())) or "0",
            lo("today_all"), lo("today_sbn"), lo("identity_all"),
            " / ".join(str(p["wall_s"]) for p in pr),
            " / ".join(str((p["newpath"] or {}).get("wall_s")) for p in pr),
            " / ".join(f"{p['requests']}·{(p['newpath'] or {}).get('requests')}" for p in pr),
            "; ".join(sorted({f"{k} {v}" for p in pr for k, v in p["sources"].items() if v != "ok"})) or "ok",
        ])
    return rows


def host_rows(hosts):
    return [[h, v["requests"], v["failed"], v["total_s"],
             ", ".join(f"{k}×{n}" for k, n in sorted(v["retries"].items())) or "0"] for h, v in hosts.items()]


lat = latency
tables = [
    "### Losses by class\n\nRecords are counted once per run; distinct counts each (book, source, id) once. "
    "Books marked * (E10, E11 generic titles; N23 insights) are excluded.\n\n"
    + md(["source · class", "records", "distinct"],
         [[k, v, summary["losses_by_class_distinct"].get(k)] for k, v in summary["losses_by_class_records"].items()]),
    "### Per book\n\nEntry values are in corpus order. Listing = Stage 1 listing size (— = none). "
    "Losses are distinct records. Overlap = lowest Jaccard over entry pairs. Requests = today·identity.\n\n"
    + md(["book", "entries", "today records", "listing records today lacks (SBN·OL)", "SBN listing", "OL listing", "losses (distinct)",
          "overlap today all", "overlap today SBN", "overlap identity", "today s", "identity s", "requests",
          "source states"], book_rows()),
    "### Cold latency\n\n" + md(["path", "n", "median s", "p90 s", "max s", "total s"],
                                [["today's pipeline", *lat["today"].values()], ["listing by identity", *lat["identity"].values()],
                                 ["today's pipeline, runs with no Wikimedia 429", *lat["no_wikimedia_429"]["today"].values()],
                                 ["listing by identity, same entries", *lat["no_wikimedia_429"]["identity"].values()]])
    + f"\n\nIdentity slower than today in {len(lat['identity_slower'])} entries ({lat['identity_slower']}); "
      f"median ratio today / identity {lat['ratio_median']}.",
    "### User-Agent control (today's pipeline, same entry)\n\n"
    + md(["run", "today s", "contact UA s", "identity s", "Wikimedia 429 today", "Wikimedia 429 contact UA", "overlap all", "overlap SBN"],
         [[u["run"], u["today_s"], u["ua_contact_s"], u["identity_s"], u["wikimedia_429_today"], u["wikimedia_429_ua_contact"],
           noise.get(u["run"], {}).get("today_vs_ua_contact_all"), noise.get(u["run"], {}).get("today_vs_ua_contact_sbn")]
          for u in lat["ua_control"]]),
    "### Author-only runs\n\n" + md(["run", "variant", "rows", "wall s", "requests", "sources"],
                                    [[r, a["variant"], a["rows"], a["wall_s"], a["requests"],
                                      "; ".join(f"{k} {v}" for k, v in a["sources"].items())] for r, a in authors.items()])
    + "\n\nOverlap of work-row titles between variants of one person: "
    + "; ".join(f"{k} {v}" for k, v in author_overlap.items()),
    *[f"### Requests per host — {name}\n\nRetries are urllib3's, inside one logged request.\n\n"
      + md(["host", "requests", "failed", "total s", "retries"], host_rows(summary[key]))
      for name, key in (("today's pipeline", "hosts_today"), ("today's pipeline, contact UA", "hosts_ua_contact"),
                        ("listing by identity", "hosts_identity"), ("author-only runs", "hosts_authors"))],
]
(R2 / "tables.md").write_text("\n\n".join(tables) + "\n", encoding="utf-8")

print(json.dumps({k: summary[k] for k in ("verdict", "losses_by_class_records", "losses_by_class_distinct")},
                 ensure_ascii=False, indent=1))
print("latency", json.dumps({k: latency[k] for k in ("today", "identity", "ratio_median")}))
print("unexplained:")
for l in unexplained[:80]:
    print(" ", l["run"], l["source"], l["id"], l["lang"], l["year"], str(l["title"])[:60], "|", l["why"][:100], l["reasons"])
