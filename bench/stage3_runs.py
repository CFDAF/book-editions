"""A4: fetch every listed SBN full record for the Stage 3 books, one process per book.

    python stage3_runs.py [book id ...]

Every attempt is appended to results/stage-3/runlog.jsonl with its wall time,
exit code and peak memory; stdout and stderr go to raw/stage-3/stdout/. A book
whose fetch exits non-zero (a record still missing after its own retry, or a
crash) is retried once, and both attempts stay in the log. A rerun of this
script skips books that already exited 0.
"""

import json
import re
import subprocess
import sys
import time

import common

HERE = common.BENCH
LOG = HERE / "results" / "stage-3" / "runlog.jsonl"
OUT = HERE / "raw" / "stage-3" / "stdout"
TIMEOUT_S = 60 * 60
# Mixed size (SBN rows / Open Library editions), original language and era,
# chosen before any record was fetched. Every book needs both listings: A4's
# pairs are SBN-Open Library.
BOOKS = ["N19", "E02", "N14", "N08", "N01", "E01", "N06", "N10"]


def done() -> set:
    if not LOG.exists():
        return set()
    return {r["run"] for r in map(json.loads, LOG.read_text().splitlines()) if r["exit"] == 0}


def attempt(book, n):
    cmd = ["/usr/bin/time", "-l", sys.executable, "stage3_fetch.py", book]
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"fetch__{book}__{n}.log"
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as f:
        try:
            code = subprocess.run(cmd, cwd=HERE, stdout=f, stderr=subprocess.STDOUT,
                                  timeout=TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    text = log.read_text(encoding="utf-8", errors="replace")
    rss = re.search(r"(\d+)\s+maximum resident set size", text)
    entry = {"kind": "fetch", "run": book, "attempt": n,
             "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
             "wall_s": round(time.time() - t0, 1), "exit": code, "tail": text[-400:],
             "max_rss_mb": round(int(rss.group(1)) / 2**20) if rss else None}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print("fetch", book, n, entry["exit"], entry["wall_s"], flush=True)
    return code


def main():
    only = sys.argv[1:]
    finished = done()
    books = [b for b in BOOKS if b not in finished and (not only or b in only)]
    print(f"{len(books)} books to go", flush=True)
    for book in books:
        if attempt(book, 1) != 0:
            time.sleep(60)
            attempt(book, 2)
        time.sleep(5)


if __name__ == "__main__":
    main()
