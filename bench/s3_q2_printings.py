"""Stage 3 answer 2 ("one edition row listing its printing years"): what does it need?

    python s3_q2_printings.py

Offline, over the Stage 3 books. SBN files printings of one ISBN as separate
records, and the listing row carries no ISBN. This measures:

  - by ISBN (needs every full record): how many edition rows the SBN rows
    become, and how many rows have no ISBN to group by;
  - from listing fields only, pairs of SBN rows in different years with the
    same language, publisher (the Stage 3 containment rule) and catalogued
    title: precision and recall against sharing an ISBN, over pairs where
    both rows have one.
"""

import collections
import itertools
import json

import common
import stage3_analyse as s3
from lookup.matching import normalize

OUT = common.BENCH / "results" / "stage-3" / "q2_printings.json"


def title_key(title: str) -> str:
    return normalize((title or "").split(" / ")[0])


def components(rows):
    """Edition rows: SBN records joined transitively by a shared ISBN."""
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_isbn = collections.defaultdict(list)
    for r in rows:
        for code in r["isbns"]:
            by_isbn[code].append(r["id"])
    for ids in by_isbn.values():
        for other in ids[1:]:
            parent[find(other)] = find(ids[0])
    groups = collections.defaultdict(list)
    for r in rows:
        groups[find(r["id"])].append(r)
    return list(groups.values())


def main():
    books = {b: s3.load_book(b) for b in s3.BOOKS}
    places = set()
    for bk in books.values():
        places |= {s3._plain(s["place"]) for s in bk["sbn"] if s["place"]}
        places |= {s3._plain(p) for o in bk["ol"] for p in o["publish_places"]}
    places.discard("")

    per_book, pooled = {}, collections.Counter()
    examples = []
    for b, bk in books.items():
        rows = [s for s in bk["sbn"] if s["fetched"]]
        for s in rows:
            s["pubkeys"] = s3.publisher_keys(s3.sbn_names(s["publisher"]), places) if s["publisher"] else set()
        with_isbn = [s for s in rows if s["isbns"]]
        groups = components(with_isbn)
        multi = [g for g in groups if len(g) > 1]

        tp = fp = fn = 0
        for x, y in itertools.combinations(with_isbn, 2):
            if not (x["year"] and y["year"] and x["year"] != y["year"]):
                continue
            same = bool(x["isbns"] & y["isbns"])
            hit = bool(x["langs"] & y["langs"] and s3.pub_contained(x["pubkeys"], y["pubkeys"])
                       and title_key(x["title"]) == title_key(y["title"]))
            tp += hit and same
            fp += hit and not same
            fn += same and not hit
            if hit and not same and len(examples) < 12:
                examples.append({"book": b, "a": [x["id"], x["year"], x["imprint"], sorted(x["isbns"])],
                                 "b": [y["id"], y["year"], y["imprint"], sorted(y["isbns"])]})
        res = {
            "sbn_rows": len(rows), "rows_with_isbn": len(with_isbn), "rows_without_isbn": len(rows) - len(with_isbn),
            "edition_rows_by_isbn": len(groups), "editions_with_several_printings": len(multi),
            "records_in_those": sum(len(g) for g in multi),
            "largest": max((len(g) for g in groups), default=0),
            "listing_rule_pairs_different_year": {"tp": tp, "fp": fp, "fn": fn},
        }
        per_book[b] = res
        pooled.update({k: v for k, v in res.items() if isinstance(v, int) and k != "largest"})
        pooled.update({f"listing_rule_{k}": v for k, v in res["listing_rule_pairs_different_year"].items()})
    tp, fp, fn = pooled["listing_rule_tp"], pooled["listing_rule_fp"], pooled["listing_rule_fn"]
    summary = {
        "pooled": dict(pooled),
        "listing_rule_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "listing_rule_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "per_book": per_book, "false_positive_examples": examples,
        "listing_rule": "different years; shared language code; one publisher key contained in the other; "
                        "equal normalised catalogued title (before ' / ')",
    }
    common.save_json(OUT, summary)
    print(json.dumps({k: summary[k] for k in ("pooled", "listing_rule_precision", "listing_rule_recall")},
                     indent=1, ensure_ascii=False))
    for b, r in per_book.items():
        print(b, r)
    for e in examples[:8]:
        print(e)


if __name__ == "__main__":
    main()
