"""A2, one cold run of today's pipeline, exactly as the CLI runs it.

    python stage2_today.py <run id> <title> <author>        title + author
    python stage2_today.py <run id> "" <author>             author only (--file "|<author>")
    python stage2_today.py <run id> <title> <author> --ua-contact

The process calls `book_editions.main()` with the argv docs/Task.md gives, so
the report is the CLI's own JSON. `common.setup(gated=False)` only logs: the
pipeline keeps its own concurrency and User-Agent, and its cache is a fresh
directory under bench/cache/stage-2/today/. `--ua-contact` is the control that
swaps in the contact User-Agent (A8), written under raw/stage-2/runs-ua-contact/.
"""

import json
import sys
import time

import common

run_id, title, author = sys.argv[1:4]
contact = "--ua-contact" in sys.argv
variant = "today-ua-contact" if contact else "today"
common.RESULTS = common.BENCH / "results" / "stage-2"
common.RAW = common.BENCH / "raw" / "stage-2"
net = common.setup(f"stage-2/{variant}/{run_id}", fresh=True, log_name=f"{variant}/{run_id}",
                   user_agent=common.UA_CONTACT if contact else None, gated=False)

import book_editions  # noqa: E402

# Full reports run to ~0.5 MB each (holdings, buy links): raw evidence, not a
# committed summary. stage2_analyse.py keeps what it scores.
out = common.RAW / ("runs-ua-contact" if contact else "runs") / f"{run_id}.json"
out.parent.mkdir(parents=True, exist_ok=True)
argv = ["book_editions.py"]
if title:
    argv += [title, "--author", author]
else:
    books = common.RAW / "files" / f"{run_id}.txt"
    books.parent.mkdir(parents=True, exist_ok=True)
    books.write_text(f"|{author}\n", encoding="utf-8")
    argv += ["--file", str(books)]
argv += ["--format", "json", "-o", str(out)]

sys.argv = argv
t0 = time.time()
book_editions.main()
wall = round(time.time() - t0, 1)

common.save_json(common.RESULTS / ("meta-ua-contact" if contact else "meta") / f"{run_id}.json", {
    "run": run_id, "title": title, "author": author, "argv": argv[1:],
    "user_agent": net.USER_AGENT, "wall_s": wall,
    "requests": common.summarise(), "retries": common.retries(), "failures": common.failures(),
})
print(json.dumps({"run": run_id, "wall_s": wall,
                  "requests": sum(h["requests"] for h in common.summarise().values()),
                  "retries": common.retries()}))
