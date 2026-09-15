"""A4 ground truth: the full SBN record of every row in one book's Stage 1 listing.

    python stage3_fetch.py <book id>

One `sbn.full_record(bid)` per row, through the mobile gateway, one request at a
time (F13: it cannot batch). Fresh cache, so every request is cold and logged.

Controls and checks:
  - a bogus BID first: F13 says it returns the same empty body as a batch, so
    an empty body must never be read as "a record with no ISBN";
  - every record must carry `codiceIdentificativo` naming the BID asked for,
    otherwise it counts as a mismatch, not as a record;
  - a request that fails is retried once at the end; if it fails again the row
    is reported as failed, never as lacking an ISBN.

Raw records go to raw/stage-3/full/<id>.json (gitignored); requests, retries
and failures to results/stage-3/fetch/<id>.json.
"""

import json
import sys
import time

import common

book_id = sys.argv[1]
common.RESULTS = common.BENCH / "results" / "stage-3"
common.RAW = common.BENCH / "raw" / "stage-3"
net = common.setup(f"stage-3/full/{book_id}", fresh=True, log_name=f"fetch/{book_id}")

from lookup import sbn  # noqa: E402

BOGUS_BID = "ZZQ9999999"

listing = json.loads((common.BENCH / "results" / "stage-1" / "listings" / f"{book_id}.json").read_text())
bids = list(dict.fromkeys(r["bid"] for s in listing["sbn"] or [] for r in s.get("items") or []))


def fetch(bid):
    try:
        rec = sbn.full_record(bid)
    except net.SourceError as exc:
        return None, f"SourceError: {str(exc)[:200]}"
    if not isinstance(rec, dict) or not rec:
        return rec, "empty body"
    got = sbn.short_bid(rec.get("codiceIdentificativo"))
    if got != bid:
        return rec, f"mismatch: asked {bid}, got {got}"
    return rec, None


def forget(bid):
    """Drop a cached error payload so the retry reaches the network again.

    Only ever a file under bench/cache/stage-3/, never the project's .cache/.
    """
    path = net._cache_path(f"{sbn.BASE}/full.json", {"bid": bid})
    assert common.BENCH / "cache" in path.parents
    path.unlink(missing_ok=True)


t0 = time.time()
m0 = common.mark()
control_body, control_problem = fetch(BOGUS_BID)
control = {"bid": BOGUS_BID, "problem": control_problem,
           "body": control_body if not isinstance(control_body, dict) or len(json.dumps(control_body)) < 500
           else {"keys": sorted(control_body)[:20]}}

records, problems = {}, {}
for n, bid in enumerate(bids, 1):
    rec, problem = fetch(bid)
    if problem:
        problems[bid] = [problem]
    else:
        records[bid] = rec
    if n % 25 == 0:
        print(book_id, n, len(bids), len(problems), round(time.time() - t0, 1), flush=True)

first_pass_problems = len(problems)
if problems:
    time.sleep(20)
    for bid in list(problems):
        forget(bid)
        rec, problem = fetch(bid)
        if problem:
            problems[bid].append(problem)
        else:
            records[bid] = rec
            problems[bid].append("ok on retry")

wall = round(time.time() - t0, 1)
out = common.RAW / "full" / f"{book_id}.json"
common.save_json(out, {"id": book_id, "records": records})
meta = {
    "id": book_id, "rows": len(bids), "fetched": len(records),
    "not_fetched": sorted(b for b in bids if b not in records),
    "problems": problems, "first_pass_problems": first_pass_problems,
    "control": control, "wall_s": wall,
    "requests": common.summarise(m0), "retries": common.retries(), "failures": common.failures(m0),
}
common.save_json(common.RESULTS / "fetch" / f"{book_id}.json", meta)
print(json.dumps({k: meta[k] for k in ("id", "rows", "fetched", "first_pass_problems", "wall_s", "retries")}
                 | {"control": control_problem, "not_fetched": len(meta["not_fetched"])}), flush=True)
sys.exit(0 if not meta["not_fetched"] else 3)
