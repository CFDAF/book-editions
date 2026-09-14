"""A8: does a contact User-Agent change Wikimedia throttling?

Plain `requests`, no cache, no retries, and deliberately not `lookup.net`
(its thread-local session fixes the User-Agent when created). One request at a
time, one every 1-2 s. Phases:

  alternating  120 requests, UA A and B interleaved
  AB           60 requests as A, cool-down, 60 as B
  BA           60 requests as B, cool-down, 60 as A

with a cool-down between every block. Each request carries a unique
`requestid` (a documented Action API parameter that is echoed back) so no
response can be served from an edge cache and flatter a later block.

Requests are built from the corpus: Wikipedia pageprops lookups on enwiki,
search queries on itwiki, and Wikidata wbgetentities by enwiki title, in
rotation, so every block has the same host mix.
"""

import json
import random
import statistics
import sys
import time

import requests

import common

UA = {
    "A": "book-editions-lookup/3.0 (personal research tool)",
    "B": "book-editions-lookup/3.0 (https://github.com/CFDAF/book-editions)",
}
COOLDOWN_S = int(sys.argv[1]) if len(sys.argv) > 1 else 300
STALL_S = 5.0
OUT = common.RESULTS / "a8.json"
RAW = common.RAW / "a8.jsonl"


def build_requests() -> list:
    corpus = common.load_corpus()
    titles = [e["title"] for b in corpus["books"] for e in b["entries"]]
    titles = list(dict.fromkeys(titles))
    reqs = []
    for i, t in enumerate(titles * 4):
        kind = i % 3
        if kind == 0:
            reqs.append(("https://en.wikipedia.org/w/api.php",
                         {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                          "redirects": "1", "titles": t, "format": "json"}))
        elif kind == 1:
            reqs.append(("https://it.wikipedia.org/w/api.php",
                         {"action": "query", "list": "search", "srsearch": t,
                          "srlimit": "4", "format": "json"}))
        else:
            reqs.append(("https://www.wikidata.org/w/api.php",
                         {"action": "wbgetentities", "sites": "enwiki", "titles": t,
                          "props": "labels|claims", "languages": "en|it", "format": "json"}))
    return reqs


def main():
    reqs = build_requests()
    sessions = {k: requests.Session() for k in UA}
    for k, s in sessions.items():
        s.headers["User-Agent"] = UA[k]
    RAW.parent.mkdir(parents=True, exist_ok=True)
    raw = open(RAW, "w", encoding="utf-8")
    log = []
    cursor = [0]

    def send(ua, phase):
        url, params = reqs[cursor[0] % len(reqs)]
        cursor[0] += 1
        params = {**params, "requestid": f"{phase}-{cursor[0]}"}
        t0 = time.time()
        entry = {"phase": phase, "ua": ua, "host": url.split("/")[2], "t": round(t0, 3)}
        try:
            r = sessions[ua].get(url, params=params, timeout=(10, 30))
            entry["status"] = r.status_code
            entry["headers"] = {k: v for k, v in r.headers.items()
                                if any(s in k.lower() for s in ("retry", "rate", "x-cache", "age"))}
            if r.status_code != 200:
                entry["body"] = r.text[:300]
        except requests.RequestException as exc:
            entry["status"] = None
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        entry["elapsed"] = round(time.time() - t0, 3)
        log.append(entry)
        raw.write(json.dumps(entry, ensure_ascii=False) + "\n")
        raw.flush()
        # Steady pace: the next request starts 1-2 s after this one started.
        time.sleep(max(0.0, t0 + random.uniform(1.0, 2.0) - time.time()))

    def cooldown(label):
        print(f"cool-down {COOLDOWN_S}s before {label}", flush=True)
        time.sleep(COOLDOWN_S)

    started = time.time()
    for i in range(120):
        send("A" if i % 2 == 0 else "B", "alternating")
    for order in ("AB", "BA"):
        for ua in order:
            cooldown(f"block {order}:{ua}")
            for _ in range(60):
                send(ua, f"block-{order}-{ua}")
    raw.close()

    def stats(entries):
        el = sorted(e["elapsed"] for e in entries)
        codes = {}
        for e in entries:
            codes[str(e["status"])] = codes.get(str(e["status"]), 0) + 1
        return {
            "requests": len(entries),
            "http_429": sum(1 for e in entries if e["status"] == 429),
            "non_200": sum(1 for e in entries if e["status"] != 200),
            "errors": sum(1 for e in entries if e.get("error")),
            "stalls_over_5s": sum(1 for e in entries if e["elapsed"] > STALL_S),
            "p50_s": round(statistics.median(el), 3) if el else None,
            "p95_s": round(el[int(0.95 * (len(el) - 1))], 3) if el else None,
            "max_s": round(el[-1], 3) if el else None,
            "status_counts": codes,
            "by_host": {h: sum(1 for e in entries if e["host"] == h and e["status"] != 200)
                        for h in sorted({e["host"] for e in entries})},
        }

    phases = {}
    for e in log:
        phases.setdefault(e["phase"], []).append(e)
    summary = {
        "user_agents": UA,
        "cooldown_s": COOLDOWN_S,
        "wall_s": round(time.time() - started, 1),
        "per_phase_and_ua": {p: {ua: stats([e for e in es if e["ua"] == ua])
                                 for ua in UA if any(e["ua"] == ua for e in es)}
                             for p, es in phases.items()},
        "per_ua_all_phases": {ua: stats([e for e in log if e["ua"] == ua]) for ua in UA},
        "first_non_200": {ua: next(({"phase": e["phase"], "status": e["status"],
                                     "headers": e.get("headers"), "body": e.get("body")}
                                    for e in log if e["ua"] == ua and e["status"] != 200), None)
                          for ua in UA},
    }
    common.save_json(OUT, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
