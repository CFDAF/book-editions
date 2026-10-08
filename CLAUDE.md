# CLAUDE.md — book_editions

**The build is finished** (2026-09-28). Work is whatever the user asks, and it
follows the rules below.

**`docs/DECISIONS.md` is the one record**: the aim (UC1–UC5), the timeline,
every decision (A–BD), the verified facts F1–F20, the pitfalls, what was
discarded, the thresholds, and the build rules the code cites as *build rule N*.
Read the section a change touches, not the file. `docs/sbn-api.md` is the
reverse-engineered SBN API and the traps in its data; `docs/limits.md` the known
limits and the regression cases. They are expensive to rediscover and some of it
is counter-intuitive: **read the part a change touches before changing
anything.** What is still open, and whose call each item is, is
`docs/BACKLOG.md` — add to it what you notice and do not fix.

## The short version

A book-editions lookup: give it a title in any language and it shows when the
work first appeared and every edition since, grouped by language, plus where to
get a copy. A title with no author adopts the one author the sources agree on,
else offers a chooser of books (decision AN). An author with no title lists
their whole bibliography instead.

Python stdlib + `requests`. No API keys. `python3 server.py` → localhost:8000, or
`python3 book_editions.py "<title>"`. Three sources, but **four** endpoints — SBN
is reached through two unrelated APIs. Knowing only the first is how the
project's central premise came to be recorded as verified fact and be wrong
(`docs/DECISIONS.md` §5). Check the record *type* before concluding a field is
absent.

**One tree.** `catalog/` fetches and parses and **never decides**; `core/` is
pure, network-free and holds **every gate**; `lookup/stages.py` holds the stages
S0 to S4; `app/` is the job-id transport (decision M) and the page, and decides
nothing. `server.py` launches `app.server` on :8000; `book_editions.py` runs
`app.jobs.run_to_end`. **No module in `catalog/` may import `core/`** —
`tests/test_tree_layering.py` fails on one. Where a helper encodes a single
catalogue's own convention it lives with that catalogue's parser rather than in
`core/text.py`: `title_of` (ISBD's ` / `) in `catalog/sbn_mobile.py`,
`strip_disambiguator` (`1984 (romanzo)`) in `catalog/wikidata.py`.

## Rules specific to this project

1. **The header is a publication history, not a verdict.** An earlier version led
   with "Translated into Italian." — the user rejected that framing. Do not
   re-introduce a yes/no hero.
2. **Never send either SBN API a parameter outside its whitelist.** Unknown
   params are silently ignored and the *unfiltered* result set comes back — a
   silent wrong answer, not an error. One whitelist per API: the mobile
   gateway's `sbn.PARAMS` (`catalog/sbn_mobile.py`), which `_request` filters
   against, and the OPAC's `PARAMS` (`catalog/sbn_opac.py`), which `post()`
   **refuses** rather than filters — an unknown key there is a programming
   error, not a query. The same goes for *values*: the OPAC silently drops
   non-Latin free text and answers with the unfiltered set (F15), so send Latin
   script and ship every new key and value class with a bogus-value control that
   must return 0.
3. **Never ask the OPAC for a work without an author.** Same failure shape on
   the other SBN API: it answers, and the answer is a different book. Bare
   *Rumori* returns Russolo; bare *The Essential Knuth* returns a book on
   economics. `catalog/sbn_opac.work_facet` and `work_records` raise on a
   missing author rather than querying; a bare title adopts an author first
   (decision AN) and asks the OPAC only after.
4. **`linguaPubblicazione` is the only language signal — and it still lies.**
   `paesePubblicazione` is a country and says nothing about language. And
   `linguaPubblicazione` sometimes names the language translated *from*: SBN has
   an English Vintage printing of *Kafka on the Shore* filed as GIAPPONESE. A
   record that names a translator while claiming the work's original language is
   disbelieved rather than corrected
   (`core.identity.language_contradicts_itself`).
5. **A failed request must never be indistinguishable from an empty result.**
   Every call goes on the `Ledger` in `catalog/http.py`, one per lookup,
   opened by `app.jobs.Job` in the job's own thread; the `partial (N failed)`
   state, the `Incomplete:` note and the slow-lookup note are readings of it,
   and **`core/notes.py` is the only place any of them, or a truncation line,
   is worded**; `app/` assembles and the page draws. It counts a failure whether
   or not the source that swallowed it says so. This was the single worst bug in
   the project. **Every thread pool in `lookup/`, `catalog/`, `core/` and
   `app/` must be `Pool`** — a plain `ThreadPoolExecutor` does not carry the
   ledger into its workers, so their failures would reach no reading at all.
   `tests/test_net_ledger.py` scans all four **by text match**, so the class's
   name stays out of their prose as well as out of their code.
6. **Don't loosen the identifying-signal gate** (`core.identity.identifies`,
   `IDENTIFYING_TITLE_MATCH = 0.6`) without re-checking the regression cases in
   `docs/limits.md` — particularly *L'ordine delle notizie* and
   *Quale socialismo, quale Europa*. The same file holds the SBN work guard,
   whose `B` threshold is settled against being loosened for the same kind of
   reason: the known *wrong* works sit at B = 0.5, **above** every refused
   classic (≤ 0.375). **A threshold is not the only way to move this gate**:
   `core/text.py`'s romanisation, fold and `STOPWORDS` move what scores 0.6
   without touching a number, so they carry the same re-check —
   `tests/test_translit_folding.py` over the corpus and `tests/test_gate.py`;
   the measurement they stand on is U2 (`docs/DECISIONS.md` §9). And note
   `STRONG` and `WORK_STRONG` are different verdicts — one about a record, one
   about a work.
7. **A Dewey class does not identify a work, and none is used.** It is a
   *subject*, and one author's books are mostly on one subject — García
   Márquez is `863.44` and so is every novel he wrote. Both Dewey routes were
   measured (3 of 4 admissions other books, 0 of 3 saves) and deleted
   (decision AH); re-adding one needs new evidence first.
8. **Google Books was removed deliberately.** Keyless quota permanently
   exhausted; it contributed nothing. Don't re-add it as "another source".
9. **Stop the server by its own pattern.** `pkill -f server.py` for
   `python3 server.py` — macOS reports it as `Python server.py`, so
   `pkill -f "python3 server.py"` matches nothing — and `pkill -f 'app.server'`
   for `python3 -m app.server`, whose command line holds no `server.py`. A
   miss silently leaves a stale instance serving the code it started with.
10. Cold lookups cache to `.cache/` for 24h; repeats are instant. Delete
    `.cache/` to force fresh data. Every per-stage cap (`stages.ENRICH_CAP`
    and the rest) is reported on the page when it binds (build rule 10);
    lowering one to go faster hides records rather than fixing anything.
11. **`net.USER_AGENT` keeps its contact URL.** Wikimedia throttles an agent
    that gives no way to be contacted — 102 of 180 requests `429`d against 0 of
    180 (F18). It is the policy's form, `<client>/<version> (<contact>)
    <library>/<version>`, and shortening it costs 35% of request time.
12. **Keep this file small.** It is loaded into every session. Numbers go in
    `docs/DECISIONS.md` or beside the code that measured them, open items in
    `docs/BACKLOG.md`. Add a **rule** here only when a future change could get
    it wrong without one (decision X).

## Tests

**`python3 -m pytest`** — the offline suite, all passing, **no xfail**, in about
two seconds. `pytest`'s console script is **not on `PATH`**: always go through
`python3 -m`.

- **`python3 tools/core_coverage.py` gates `core/` at 100% of executable
  lines**, stdlib only — `coverage` is deliberately not installed. It exits
  non-zero and names any line the suite never ran.
- **S1, S2 and S3 are covered with the catalogues stubbed**; the gates are
  `core/`'s, so what is tested is the wiring. **The transport too, with the
  stages stubbed**: the handler is driven over a **fake connection**, never a
  port — do not relax the socket ban to test a server.
- **`tests/` is offline by construction**: `conftest.py` blocks
  `socket.connect` for the whole session. The recorded bodies it reads are
  under `tests/data/` (`catalog/fixtures.py` replays `tests/data/fixtures`
  under `BOOK_FIXTURES`; the product never sets it).
- **The offline suite cannot see everything.** Because `catalog/` may not
  import `core/`, its parsers hand back **plain dicts**: a producer builds the
  dataclass (`stages.full_fields`), and a `Record` whose `holdings` are dicts
  raises only where the view reads one. Green is not "the pipeline runs", nor
  "the server runs": that takes a real port and a cold lookup.
- `xfail_strict` is on. **A language code is read off SBN's `lingua[]` facet,
  never inferred from the Italian name** — `SLOVACCO` is `slo`, not `slk`;
  `ISLANDESE` is `ice`, not `isl`.
- Every literal in `tests/test_sbn_parsers.py` and `tests/test_opac_rows.py`
  came from a real recorded body, from a live OPAC listing, or verbatim from
  `docs/sbn-api.md`. Do not replace one with a plausible invention — the traps
  are counter-intuitive and a made-up example tests the wrong thing.
