"""Answer 1 input: would Wikidata agreement rescue the works the Step 5 guard refuses?

    python q1_second_signal.py

For every Stage 1 entry whose SBN W is weak or rejected, take the item
Wikidata's Step 4 rule accepted for the same entry, and score W against that
item's labels, sitelinks (disambiguator stripped) and P1476, as Step 4 scores
the query. Agreement at >= 0.6 is the candidate second signal.

Positive control: strong entries' W against their own Step 4 item.
Negative control: every W against the Step 4 items of the other books.
Reads the Stage 1 Wikidata cache; a miss goes to the network with the contact
User-Agent and is counted.
"""

import json
from functools import cache

import common

net = common.setup("stage-1/a1-wd", user_agent=common.UA_CONTACT)
from lookup import wikidata  # noqa: E402
from lookup.matching import strip_disambiguator  # noqa: E402
from stage1_a1 import LABEL_LANGS, THRESHOLD, sim  # noqa: E402

sbn = json.loads((common.RESULTS / "a1_sbn.json").read_text())["books"]
wd = json.loads((common.RESULTS / "a1_wd.json").read_text())["books"]
SKIP = {"E10", "E11"}  # generic titles, not scored in Stage 1


@cache
def forms(qid):
    ent = wikidata._entities([qid], "labels|sitelinks|claims", LABEL_LANGS).get(qid) or {}
    out = [v["value"] for v in (ent.get("labels") or {}).values()]
    out += [strip_disambiguator(v["title"]) for v in (ent.get("sitelinks") or {}).values()]
    p1476 = wikidata._claim_first(ent.get("claims") or {}, "P1476") or {}
    if p1476.get("text"):
        out.append(p1476["text"])
    return out


def agreement(w, qid):
    best = max(((sim(w, f), f) for f in forms(qid)), default=(0.0, None))
    return round(best[0], 3), best[1]


pairs = []
for book, v in sbn.items():
    if book in SKIP:
        continue
    for key, e in v["entries"].items():
        if e.get("W"):
            pairs.append((book, key, e["W"], e["tier"], wd[book]["entries"][key]["step4"].get("qid")))

refused, positive = [], []
for book, key, w, tier, qid in pairs:
    row = {"book": book, "entry": key, "W": w, "tier": tier, "qid": qid}
    if qid:
        row["score"], row["closest"] = agreement(w, qid)
    (positive if tier == "strong" else refused).append(row)

items = {}
for book, key, w, tier, qid in pairs:
    if qid and tier == "strong":
        items.setdefault(book, qid)
negative = []
for book, key, w, tier, _ in pairs:
    for other, qid in items.items():
        if other != book:
            score, closest = agreement(w, qid)
            if score >= THRESHOLD:
                negative.append({"book": book, "entry": key, "W": w, "other": other, "qid": qid,
                                 "score": score, "closest": closest})

summary = {
    "refused": refused,
    "refused_with_item": sum(1 for r in refused if r["qid"]),
    "refused_rescued": [f"{r['book']} {r['entry']}" for r in refused if r.get("score", 0) >= THRESHOLD],
    "positive_control": {"pairs": sum(1 for r in positive if r["qid"]),
                         "agree": sum(1 for r in positive if r.get("score", 0) >= THRESHOLD),
                         "disagree": [r for r in positive if r["qid"] and r["score"] < THRESHOLD]},
    "negative_control": {"pairs": sum(1 for b, *_ in pairs for o in items if o != b),
                         "false_agreements": negative},
    "requests": common.summarise(), "failures": common.failures(),
}
common.save_json(common.BENCH / "results" / "stage-2" / "q1_second_signal.json", summary)
for r in refused:
    print(r)
print(json.dumps({k: v for k, v in summary.items() if k != "refused"}, ensure_ascii=False, indent=1))
