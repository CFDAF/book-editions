"""A2: every cold run, serially, one process each.

    python stage2_runs.py

Per entry title, today's pipeline (stage2_today.py) and listing by identity
(stage2_newpath.py) run back to back, their order alternating from one entry to
the next so neither side always meets the catalogues' own caches first. For
UA_CONTROL entries a third run repeats today's pipeline with the contact
User-Agent (A8), to size how much of today's latency is Wikimedia throttling.
Author-only runs follow, one per Latin-script variant (answer 2).

Every attempt is appended to results/stage-2/runlog.jsonl with its wall time
and exit code; stdout and stderr go to raw/stage-2/stdout/. A run that exits
non-zero or times out is retried once, and both attempts stay in the log. A
rerun of this script skips what already exited 0.
"""

import json
import re
import subprocess
import sys
import time

import common

HERE = common.BENCH
LOG = HERE / "results" / "stage-2" / "runlog.jsonl"
OUT = HERE / "raw" / "stage-2" / "stdout"
TIMEOUT_S = 30 * 60
UA_CONTROL = {("E01", "ita"), ("E02", "ita"), ("E03", "eng"), ("E06", "eng"), ("E09", "ita"),
              ("E14", "ita"), ("E16", "ita"), ("N02", "ita"), ("N03", "ita"), ("N06", "ita"),
              ("N08", "eng"), ("N10", "ita"), ("N12", "ita"), ("N13", "eng"), ("N18", "ita"),
              ("N24", "ita")}


def plan(corpus):
    runs, i, c = [], 0, 0
    for book in corpus["books"]:
        for e in book["entries"]:
            rid = f"{book['id']}__{e['key']}"
            today = ("today", rid, [e["title"], book["query_author"]])
            newpath = ("newpath", rid, [book["id"], e["key"]])
            if (book["id"], e["key"]) in UA_CONTROL:
                group = [newpath, today, ("today-ua-contact", rid, [e["title"], book["query_author"], "--ua-contact"])]
                group = group[c % 3:] + group[:c % 3]
                c += 1
            else:
                group = [newpath, today] if i % 2 == 0 else [today, newpath]
            runs += group
            i += 1
    for person in corpus["authors"]:
        for n, variant in enumerate(person["variants"], 1):
            runs.append(("today", f"{person['id']}__{n}", ["", variant]))
    return runs


def done() -> set:
    if not LOG.exists():
        return set()
    return {(r["kind"], r["run"]) for r in map(json.loads, LOG.read_text().splitlines()) if r["exit"] == 0}


def attempt(kind, rid, args, n):
    script = "stage2_newpath.py" if kind == "newpath" else "stage2_today.py"
    # /usr/bin/time -l appends the process's peak memory to its log (the first
    # attempt of this job was killed when the machine ran low on memory).
    cmd = ["/usr/bin/time", "-l", sys.executable, script, *([rid] if script == "stage2_today.py" else []), *args]
    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"{kind}__{rid}__{n}.log"
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as f:
        try:
            code = subprocess.run(cmd, cwd=HERE, stdout=f, stderr=subprocess.STDOUT,
                                  timeout=TIMEOUT_S).returncode
        except subprocess.TimeoutExpired:
            code = "timeout"
    entry = {"kind": kind, "run": rid, "attempt": n, "args": args,
             "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0)),
             "wall_s": round(time.time() - t0, 1), "exit": code,
             "tail": log.read_text(encoding="utf-8", errors="replace")[-400:]}
    rss = re.search(r"(\d+)\s+maximum resident set size", log.read_text(encoding="utf-8", errors="replace"))
    entry["max_rss_mb"] = round(int(rss.group(1)) / 2**20) if rss else None
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(kind, rid, n, entry["exit"], entry["wall_s"], flush=True)
    return code


def main():
    finished = done()
    runs = [r for r in plan(common.load_corpus()) if (r[0], r[1]) not in finished]
    print(f"{len(runs)} runs to go", flush=True)
    for kind, rid, args in runs:
        if attempt(kind, rid, args, 1) != 0:
            time.sleep(30)
            attempt(kind, rid, args, 2)
        time.sleep(2)


if __name__ == "__main__":
    main()
