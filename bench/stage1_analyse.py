"""Stage 1 analysis: score A1, A3, A5, A6, A7 and A8 against the fail criteria.

Offline: reads corpus.json and results/stage-1/*.json, writes
results/stage-1/summary.json and results/stage-1/tables.md.

The judgements below say which identity is the *right* one for each book.
They were made by hand from the ground truth and the labels each source
returned (the evidence is in the result files named beside them), and are
kept here so every PASS/FAIL can be traced to them.
"""

import json
import re
import statistics
import sys
import unicodedata
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lookup.matching import core_title, normalize, title_similarity  # noqa: E402
from lookup.sbn import parse_publication  # noqa: E402
from judgements import (INSIGHTS, NOT_A_WORK, RIGHT_OL, RIGHT_QID, RIGHT_W, SPLIT_OL,  # noqa: E402
                        known_titles, sim)

R = HERE / "results" / "stage-1"
corpus = json.loads((HERE / "corpus.json").read_text())
BOOKS = {b["id"]: b for b in corpus["books"]}
load = lambda name: json.loads((R / name).read_text())

# A5: N02 appeared in English and French in the same month; reported, not scored.
A5_REPORT_ONLY = {"N02"}


def same_script_title(a, b):
    f = lambda s: unicodedata.normalize("NFKC", re.sub(r"\s*\(.*\)\s*$", "", s or "")).strip().casefold()
    return bool(a and b) and (f(a) == f(b) or sim(f(a), f(b)) >= 0.6)


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


summary, tables = {}, []

# --- A1 ----------------------------------------------------------------------
wd, sbn, ol = load("a1_wd.json")["books"], load("a1_sbn.json")["books"], load("a1_ol.json")["books"]


def verdict_wd(bid, qid):
    if not qid:
        return "none"
    if bid in RIGHT_QID:
        return "right" if qid == RIGHT_QID[bid] else "wrong"
    return "wrong"  # every QID returned for a book without a verified item was read and is another work


def verdict_w(bid, e):
    w, tier = e.get("W"), e.get("tier")
    right = w in RIGHT_W.get(bid, set())
    if tier == "strong":
        return "right" if right else "wrong"
    if w is None:
        return "none"
    return f"none ({tier}; W {'right' if right else 'wrong'})"


def verdict_ol(bid, r, entry_key):
    key = r.get("key") or r["keyed"].get("key")
    how = "" if r.get("key") else (" [keyed]" if key else "")
    if not key:
        return "none", key
    if bid in RIGHT_OL and key == RIGHT_OL[bid]:
        return "main" + how, key
    if (bid, entry_key) in SPLIT_OL:
        return "split record" + how, key
    doc = r if r.get("key") else r["keyed"]
    if any(sim(t, doc.get("title") or "") >= 0.6 or same_script_title(t, doc.get("title")) for t in known_titles(BOOKS[bid])):
        return "split record" + how, key
    return "wrong" + how, key


a1_rows, a1 = [], {"wikidata_today": Counter(), "wikidata_step4": Counter(), "sbn": Counter(), "ol": Counter()}
book_conv = {"wikidata_today": 0, "wikidata_step4": 0, "sbn": 0, "ol": 0}
a1_guard = Counter()
scored_books = [b for b in BOOKS if b not in NOT_A_WORK | INSIGHTS]
b_cost = []
for bid, book in BOOKS.items():
    per = {"wikidata_today": [], "wikidata_step4": [], "sbn": [], "ol": []}
    for e in book["entries"]:
        k = e["key"]
        w = wd[bid]["entries"][k]
        s = sbn[bid]["entries"][k]
        o = ol[bid]["entries"][k]
        vt, vs = verdict_wd(bid, w["today"]["qid"]), verdict_wd(bid, w["step4"]["qid"])
        vw = verdict_w(bid, s)
        vo, okey = verdict_ol(bid, o, k)
        per["wikidata_today"].append((w["today"]["qid"], vt))
        per["wikidata_step4"].append((w["step4"]["qid"], vs))
        per["sbn"].append((s.get("W") if s.get("tier") == "strong" else None, vw))
        per["ol"].append((okey, vo))
        b_cost.append(s.get("b_requests") or 0)
        a1_rows.append([bid, k, e["title"][:38], f"{w['today']['qid']} ({vt})", f"{w['step4']['qid']} ({vs})",
                        f"{(s.get('W') or '—')[:34]} · {s.get('tier')} · A={s.get('A')} B={s.get('B')} {s.get('B_counts') or ''} · +{s.get('b_requests', 0)} req",
                        f"{okey} ({vo})"])
    if bid in NOT_A_WORK | INSIGHTS:
        continue
    for src, vals in per.items():
        for _, v in vals:
            a1[src][v.split(" ")[0]] += 1
            if src == "sbn" and v.startswith("none ("):
                a1_guard[v] += 1
        if src == "ol":
            ok = all(v.startswith("main") for _, v in vals)
        else:
            ok = all(v == "right" for _, v in vals) and len({x for x, _ in vals}) == 1
        book_conv[src] += ok
summary["A1"] = {"entries_by_verdict": {k: dict(v) for k, v in a1.items()},
                 "sbn_no_identity_detail": dict(a1_guard),
                 "books_fully_converged_and_right": book_conv, "books_scored": len(scored_books),
                 "b_requests": {"total": sum(b_cost), "entries_needing_B": sum(1 for x in b_cost if x),
                                "max": max(b_cost)}}
tables.append("### A1 — identity per (entry title, author)\n\n" + md_table(
    ["book", "entry", "title", "Wikidata today", "Wikidata Step 4", "SBN W · tier · A/B · B cost", "Open Library"], a1_rows))

# --- A3 ----------------------------------------------------------------------
a3 = load("a3.json")["books"]
a3_rows, tot = [], Counter()
for bid, b in a3.items():
    for s in b["sbn"]:
        tot["sbn_rows"] += s["rows"]; tot["sbn_year"] += s["year_parsed"]
        tot["sbn_pub"] += s["publisher_present"]; tot["sbn_lang"] += s["language_present"]
        tot["sbn_req"] += s["requests"]; tot["sbn_missing"] += s["records_on_no_language_page"]
        tot["bogus_nonzero"] += bool(s["bogus_lingua_total"])
    o = b["ol"]
    if o:
        tot["ol_rows"] += o["rows"]; tot["ol_year"] += o["year_parsed"]
        tot["ol_pub"] += o["publisher_present"]; tot["ol_lang"] += o["language_present"]; tot["ol_req"] += o["requests"]
    s = b["sbn"][0] if b["sbn"] else None
    per_host = b["requests"]
    sbn_req = (per_host.get("opac.sbn.it/o") or {}).get("requests", 0)
    ol_req = (per_host.get("openlibrary.org") or {}).get("requests", 0) + sum(
        v["requests"] for v in ((o or {}).get("retry") or {}).get("requests", {}).values())
    tot["sbn_req_host"] += sbn_req
    tot["ol_req_host"] += ol_req
    pct = lambda n, d: f"{100 * n / d:.0f}%" if d else "—"
    a3_rows.append([
        bid,
        f"{s['rows']}/{s['total']} · {s['languages']} lang" if s else "no strong work",
        pct(s["year_parsed"], s["rows"]) if s else "—", pct(s["publisher_present"], s["rows"]) if s else "—",
        f"{sbn_req} req · {s['wall_s']} s · ctl {s['bogus_lingua_total']}" if s else "—",
        f"{o['rows']} · {o['languages']} lang" if o else "no main work",
        pct(o["year_parsed"], o["rows"]) if o else "—", pct(o["publisher_present"], o["rows"]) if o else "—",
        pct(o["language_present"], o["rows"]) if o else "—",
        f"{ol_req} req · {o['wall_s']} s" + (" (2nd attempt)" if o.get("retry") else "") if o else "—",
        b["wall_s"]])
sbn_year_rate = tot["sbn_year"] / tot["sbn_rows"]
fail_kinds = Counter()
fail_list = []
for bid in a3:
    L = json.loads((R / "listings" / f"{bid}.json").read_text())
    for s in L["sbn"]:
        for f in s["year_parse_failures"]:
            imp = f["imprint"] or ""
            if re.search(r"Monografia \[IT|^Fa parte di|^\d+\.? ?(ed|rist)|^\d+ p\b|^\[Rev|p\. :|p\. ;", imp):
                kind = "infos[0] is not the imprint"
            elif re.search(r"\b(1[5-9]\d\d|20[0-2]\d)\b", imp):
                kind = "year present, parser missed it"
            else:
                kind = "no year in the record"
            fail_kinds[kind] += 1
            fail_list.append({"book": bid, "bid": f["bid"], "imprint": imp, "kind": kind})
walls = sorted(b["wall_s"] for b in a3.values())
sbn_walls = sorted(s["wall_s"] for b in a3.values() for s in b["sbn"])
summary["A3_wall"] = {"book_wall_s": {"total": round(sum(walls), 1), "median": statistics.median(walls), "max": walls[-1]},
                      "sbn_listing_wall_s": {"median": statistics.median(sbn_walls), "max": sbn_walls[-1]}}
summary["A3"] = {
    "sbn": {"rows": tot["sbn_rows"], "year_parsed": tot["sbn_year"], "year_rate": round(sbn_year_rate, 4),
            "publisher_present": tot["sbn_pub"], "language_present": tot["sbn_lang"],
            "requests": tot["sbn_req_host"], "records_on_no_language_page": tot["sbn_missing"],
            "bogus_lingua_controls_nonzero": tot["bogus_nonzero"],
            "year_parse_failures_by_kind": dict(fail_kinds), "year_parse_failures": fail_list},
    "ol": {"rows": tot["ol_rows"], "year_parsed": tot["ol_year"], "publisher_present": tot["ol_pub"],
           "language_present": tot["ol_lang"], "requests": tot["ol_req_host"]},
    "verdict": "PASS" if sbn_year_rate >= 0.9 else "FAIL",
}
tables.append("### A3 — listing by identity (cold)\n\n" + md_table(
    ["book", "SBN rows/total · langs", "SBN year", "SBN publisher", "SBN requests · wall · bogus lingua",
     "OL rows · langs", "OL year", "OL publisher", "OL language", "OL requests · wall", "book wall s"], a3_rows))


# --- A5 ----------------------------------------------------------------------
def earliest(bid, lang):
    L = json.loads((R / "listings" / f"{bid}.json").read_text())
    rows = []
    for s in L["sbn"]:
        for r in s.get("items", []):
            if r["year"]:
                rows.append((int(r["year"]), r["langs"], "SBN", r["bid"], r["imprint"]))
    if L["ol"]:
        for r in L["ol"]["items"]:
            if r["year"]:
                rows.append((int(r["year"]), r["languages"], "OL", r["key"], f"{r['publishers'][:1]} {r['publish_date']}"))
    rows = [r for r in rows if 1400 < r[0] <= 2026]
    if not rows:
        return None, None, []
    first = min(r[0] for r in rows)
    at_first = [r for r in rows if r[0] == first]
    orig = [r for r in rows if lang in r[1]]
    first_orig = min((r[0] for r in orig), default=None)
    return first, first_orig, at_first[:6]


a5_rows, a5 = [], Counter()
for bid, book in BOOKS.items():
    gt = book["ground_truth"]
    if bid in NOT_A_WORK:
        continue
    # Wikidata original: the item Step 4 accepts for most entries, read from today's cluster fields.
    q4 = Counter(wd[bid]["entries"][e["key"]]["step4"]["qid"] for e in book["entries"]
                 if wd[bid]["entries"][e["key"]]["step4"]["qid"])
    qid = q4.most_common(1)[0][0] if q4 else None
    cl = next((wd[bid]["entries"][e["key"]]["today"] for e in book["entries"]
               if wd[bid]["entries"][e["key"]]["today"]["qid"] == qid), None) if qid else None
    gy = {x for x in [(gt.get("original_first_edition") or {}).get("year"),
                      (gt.get("first_edition_overall") or {}).get("year")] if x}
    if bid == "N04":
        gy.add("1866")  # serial
    if cl:
        t_ok = same_script_title(cl["original_title"], gt["original_title"]) or any(
            same_script_title(cl["original_title"], t) for t in known_titles(book))
        l_ok = cl["original_language"] == gt["original_language"]
        y_ok = cl["original_year"] in gy if cl["original_year"] else None
        wd_ok = t_ok and l_ok and y_ok is not False
        wd_txt = f"{qid}: {cl['original_title']} · {cl['original_language']} · {cl['original_year']}"
    else:
        t_ok = l_ok = y_ok = wd_ok = None
        wd_txt = "no item accepted"
    first, first_orig, at_first = earliest(bid, gt["original_language"])
    flag = None if first is None else (first_orig is None or first < first_orig)
    tie_other = first is not None and first_orig == first and any(gt["original_language"] not in r[1] for r in at_first)
    expected = gt.get("first_edition_differs")
    if bid in INSIGHTS | A5_REPORT_ONLY:
        outcome = "report only"
    elif first is None:
        outcome = "no dated listing"
    elif flag == expected:
        outcome = "right"
    else:
        outcome = "missed" if expected else "false flag"
    a5[outcome] += 1
    if bid not in INSIGHTS | A5_REPORT_ONLY:
        a5["wikidata_original_" + ("absent" if wd_ok is None else "wrong" if not wd_ok
                                   else "right, year missing" if y_ok is None else "right")] += 1
    a5_rows.append([bid, wd_txt, ("✓" + (" (no year)" if y_ok is None else "")) if wd_ok else ("✗ " + ",".join(n for n, ok in (("title", t_ok), ("lang", l_ok), ("year", y_ok)) if ok is False) if wd_ok is False else "—"),
                    f"{gt['original_language']} {(gt.get('original_first_edition') or {}).get('year')}"
                    + (f" / first {gt['first_edition_overall']['language']} {gt['first_edition_overall']['year']}" if gt.get("first_edition_overall") else ""),
                    f"{first} / {first_orig}" + (" (tie with another language)" if tie_other else ""),
                    "; ".join(f"{r[2]} {r[3]} {'+'.join(r[1]) or '?'} {str(r[4])[:40]}" for r in at_first[:2]),
                    flag, expected, outcome])
summary["A5"] = dict(a5)
tables.append("### A5 — original vs first edition\n\n" + md_table(
    ["book", "Wikidata original (Step 4 item)", "vs ground truth", "ground truth", "earliest overall / in original language (listings)",
     "earliest rows", "flag", "expected", "outcome"], a5_rows))

# --- A6 ----------------------------------------------------------------------
viaf = load("a6_viaf.json")["books"]
GT_COUNT = {"E01": 46, "E09": 40, "N02": 600, "N06": 65, "N10": 68, "N13": 35, "N24": 0}
SKIP = {"und", "mul", "zxx", "mis", "", None}
a6_rows, a6 = [], Counter()
labels = Counter()
for bid, book in BOOKS.items():
    v = viaf[bid]
    L = json.loads((R / "listings" / f"{bid}.json").read_text())
    found = set()
    for s in L["sbn"]:
        found |= {c for c, _ in s.get("lingua_facet", []) if c not in SKIP}
    if L["ol"]:
        found |= {c for c in L["ol"]["language_codes"] if c not in SKIP}
    census = set(v["census_languages"])
    for k in v["clusters_kept"]:
        for h, n in k["label_normalisation"].items():
            labels[h] += n
    if bid in NOT_A_WORK | INSIGHTS:
        state = "not scored"
    elif not census:
        state = "unavailable"
    elif len(census) >= len(found):
        state = "census ≥ found"
    else:
        state = "census < found"
    a6[state] += 1
    a6_rows.append([bid, v["work_clusters"], len(census), len(found), len(found - census), len(census - found),
                    GT_COUNT.get(bid, "—"), state])
summary["A6"] = {"books": dict(a6), "label_normalisation": dict(labels),
                 "verdict": "FAIL" if a6["unavailable"] + a6["census < found"] > a6["census ≥ found"] else "PASS"}
tables.append("### A6 — VIAF census\n\n" + md_table(
    ["book", "work clusters", "census langs", "langs found (SBN ∪ OL)", "found not in census", "census not found",
     "documented", "state"], a6_rows))

# --- A7 ----------------------------------------------------------------------
s7, v7, o7, w7 = load("a7_sbn.json")["persons"], load("a7_viaf.json")["persons"], load("a7_ol.json")["persons"], load("a7_wd.json")["persons"]
a7_rows, one_source = [], 0
for pid, p in s7.items():
    main_ol = {}
    for r in o7[pid]["variants"]:
        for d in r.get("top_docs", [])[:3]:
            main_ol[d["key"]] = max(main_ol.get(d["key"], 0), d["work_count"] or 0)
    top_key = max(main_ol, key=main_ol.get) if main_ol else None
    in_all_raw = all(any(d["key"] == top_key for d in r.get("top_docs", [])) for r in o7[pid]["variants"])
    in_all_resolved = all(top_key in r["resolve_author_keys"] for r in o7[pid]["variants"])
    splits = max(sum(1 for c in r["clusters"] if c["same_name"]) for r in v7[pid]["variants"])
    ok = {"sbn": p["one_id"], "sbn_latin": p["one_id_latin_forms"], "viaf": v7[pid]["one_id"],
          "ol_resolve": in_all_resolved, "wikidata": w7[pid]["one_id"]}
    one_source += any(ok.values())
    a7_rows.append([p["person"], len(p["variants"]),
                    f"{'one' if ok['sbn'] else 'split'} ({p['variants'][0]['chosen']}); Latin forms {'one' if ok['sbn_latin'] else 'split'}",
                    f"{'one' if ok['viaf'] else 'split'} ({v7[pid]['variants'][0]['chosen']}); same-name clusters ≤{splits}",
                    f"top {top_key} ({main_ol.get(top_key)} works): raw search {'all' if in_all_raw else 'not all'}, resolve_author_keys {'all' if in_all_resolved else 'not all'}",
                    f"{'one' if ok['wikidata'] else 'split'} ({w7[pid]['variants'][0]['chosen']})",
                    "; ".join(p["surname_probe"]["first_page_persons"][:4])])
summary["A7"] = {"persons": len(s7), "persons_with_one_id_in_some_source": one_source,
                 "verdict": "PASS" if one_source == len(s7) else "FAIL"}
tables.append("### A7 — author identity\n\n" + md_table(
    ["person", "variants", "SBN name authority", "VIAF", "Open Library", "Wikidata", "SBN surname probe (first persons)"], a7_rows))

# --- A8 ----------------------------------------------------------------------
a8 = load("a8.json")
raw8 = [json.loads(l) for l in (HERE / "raw" / "stage-1" / "a8.jsonl").read_text().splitlines()]
ok200 = {ua: sorted(e["elapsed"] for e in raw8 if e["ua"] == ua and e["status"] == 200) for ua in ("A", "B")}
summary["A8"] = {"per_ua": a8["per_ua_all_phases"],
                 "latency_200_only": {ua: {"n": len(v), "p50": round(statistics.median(v), 3),
                                           "p95": round(v[int(0.95 * (len(v) - 1))], 3)} for ua, v in ok200.items()},
                 "verdict": "PASS" if a8["per_ua_all_phases"]["A"]["http_429"] != a8["per_ua_all_phases"]["B"]["http_429"] else "FAIL"}
a8_rows = [[ph, ua, s["requests"], s["http_429"], s["stalls_over_5s"], s["p50_s"], s["p95_s"]]
           for ph, uas in a8["per_phase_and_ua"].items() for ua, s in uas.items()]
tables.append("### A8 — Wikimedia User-Agent\n\n" + md_table(["phase", "UA", "requests", "429", "stalls > 5 s", "p50 s", "p95 s"], a8_rows))

# --- Requests per host (every logged request in Stage 1) ----------------------
hosts = {}
for f in sorted((HERE / "raw" / "stage-1").glob("*.jsonl")):
    for line in f.read_text().splitlines():
        e = json.loads(line)
        h = hosts.setdefault(e["host"], {"requests": 0, "failed": 0, "over_5s": 0, "elapsed": []})
        h["requests"] += 1
        h["failed"] += bool(e.get("error") or (e.get("status") not in (200, None) and "ua" in e) or e.get("status") is None)
        h["over_5s"] += e["elapsed"] > 5
        h["elapsed"].append(e["elapsed"])
host_rows = []
for name, h in sorted(hosts.items(), key=lambda kv: -kv[1]["requests"]):
    el = sorted(h.pop("elapsed"))
    h.update(total_s=round(sum(el), 1), p50_s=round(statistics.median(el), 3), max_s=round(el[-1], 2))
    host_rows.append([name, h["requests"], h["failed"], h["over_5s"], h["total_s"], h["p50_s"], h["max_s"]])
summary["hosts"] = hosts
tables.append("### Requests per host (all Stage 1 scripts; includes A8's deliberate 429s)\n\n" + md_table(
    ["host", "requests", "failed", "> 5 s", "total s", "p50 s", "max s"], host_rows))

(R / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
(R / "tables.md").write_text("\n\n".join(tables) + "\n")
print(json.dumps({k: v for k, v in summary.items() if k != "hosts"}, ensure_ascii=False, indent=1)[:6000])
