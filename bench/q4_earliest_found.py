"""Answer 4 check: what would "earliest edition found" say for each book?

    python q4_earliest_found.py

Offline, on the Stage 1 listings (SBN ∪ Open Library). The rule as decided:
the earliest dated edition, leaving out editions dated before the original's
known year. The original's year is the one the lookup would have: P577 of the
Wikidata item Step 4 accepts for most of the book's entries (as in A5), else
none, and then nothing is left out.

Each book's statement is scored against ground truth (the first edition
overall where it differs, else the original-language first edition):
  right                  year and language of the first edition
  right, tie             right, with other languages dated the same year
  right year, not its language
  later                  the first edition is not in the listings
  earlier                a date older than the first edition survives the rule
"""

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
R1 = HERE / "results" / "stage-1"
corpus = json.loads((HERE / "corpus.json").read_text())
wd = json.loads((R1 / "a1_wd.json").read_text())["books"]
NOT_A_WORK, INSIGHTS = {"E10", "E11"}, {"N23"}
ACCEPTED_YEARS = {"N04": {1866, 1867}}  # serial 1866, book 1867


def rows(bid):
    L = json.loads((R1 / "listings" / f"{bid}.json").read_text())
    out = [(int(r["year"]), tuple(r["langs"]), "SBN", r["bid"], r["imprint"])
           for s in L["sbn"] for r in s.get("items", []) if r["year"]]
    if L["ol"]:
        out += [(int(r["year"]), tuple(r["languages"]), "OL", r["key"], f"{r['publishers'][:1]} {r['publish_date']}")
                for r in L["ol"]["items"] if r["year"]]
    return [r for r in out if 1400 < r[0] <= 2026]


def original_year(bid, book):
    q = Counter(wd[bid]["entries"][e["key"]]["step4"]["qid"] for e in book["entries"]
                if wd[bid]["entries"][e["key"]]["step4"]["qid"])
    if not q:
        return None, None
    qid = q.most_common(1)[0][0]
    cl = next(wd[bid]["entries"][e["key"]]["today"] for e in book["entries"]
              if wd[bid]["entries"][e["key"]]["today"]["qid"] == qid)
    y = cl.get("original_year")
    return qid, int(y) if y and str(y).isdigit() else None


books, counts = {}, Counter()
for book in corpus["books"]:
    bid = book["id"]
    if bid in NOT_A_WORK:
        continue
    gt = book["ground_truth"]
    first = gt.get("first_edition_overall") or {}
    gt_lang = {first.get("language") or gt["original_language"]}
    if bid == "N02":
        gt_lang.add(gt["original_language"])  # English and French at once
    gt_year = first.get("year") or (gt.get("original_first_edition") or {}).get("year")
    gt_years = ACCEPTED_YEARS.get(bid) or ({int(gt_year)} if gt_year and str(gt_year).isdigit() else set())

    qid, oy = original_year(bid, book)
    all_rows = rows(bid)
    kept = [r for r in all_rows if oy is None or r[0] >= oy]
    dropped = [r for r in all_rows if r not in kept]
    if not kept:
        outcome, earliest, langs = "no dated listing", None, set()
    else:
        earliest = min(r[0] for r in kept)
        at = [r for r in kept if r[0] == earliest]
        langs = {c for r in at for c in r[1]}
        if not gt_years:
            outcome = "no ground-truth year"
        elif earliest < min(gt_years):
            outcome = "earlier"
        elif earliest > max(gt_years):
            outcome = "later"
        elif langs & gt_lang:
            outcome = "right, tie" if langs - gt_lang else "right"
        else:
            outcome = "right year, not its language"
    if bid not in INSIGHTS:
        counts[outcome] += 1
    books[bid] = {
        "wikidata": qid, "original_year_used": oy,
        "ground_truth": {"year": sorted(gt_years), "language": sorted(gt_lang)},
        "earliest_found": earliest, "languages_at_earliest": sorted(langs),
        "rows_at_earliest": [r[2:] for r in kept if r[0] == earliest][:4] if kept else [],
        "dropped_before_original_year": [(r[0], r[2], r[3], str(r[4])[:50]) for r in dropped][:6],
        "dropped_count": len(dropped), "outcome": outcome, "insights_only": bid in INSIGHTS,
    }

summary = {"rule": __doc__.split("\n\n")[1], "counts": dict(counts), "books": books}
out = HERE / "results" / "stage-2" / "q4_earliest_found.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
for bid, b in books.items():
    print(bid, b["original_year_used"], b["ground_truth"], b["earliest_found"], b["languages_at_earliest"],
          b["dropped_count"], b["outcome"])
print(dict(counts))
