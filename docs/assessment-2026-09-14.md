# Assessment — does the tool answer the aim? (2026-09-14)

An assessment of the tool at `main` @ `77b80db` against the user's stated aim,
made before any further work on `STRATEGY.md`. It asks two questions: how well
the current tool serves each use case, and whether a better strategy or data
backbone exists, up to starting from scratch.

Status: **input to a decision, not a plan.** `STRATEGY.md` stays authoritative
until the user answers the decisions below and the revised plan is recorded
there.

**Evidence tags:** **V** verified with a control · **M** measured · **D**
documented by the source (link given) · **I** inferred from code or reasoning.

**Provenance:** *(audit)*, *(libraries)* and *(community)* mark claims reported
by the three investigating subagents and not re-checked. *(own)* marks claims
checked directly in this session. The raw evidence (scripts, response bodies,
request logs) lived in the session's scratch directory and is not preserved;
the enumeration probe is reproduced in the appendix.

---

## 1. Verdict

**Keep the data sources and rebuild the lookup's core.**

- No source reachable without payment beats SBN + Open Library + Wikidata
  (§3).
- The lookup searches with the typed title, collects far too many candidates,
  then filters them through rules of thumb. That shape is why the three entry
  titles of one book give different edition lists, why the filters misbehave,
  and why a cold lookup takes about a minute (§2).
- Identifying the work once, then listing its editions by that identity, took
  17 s instead of 52 s on the largest test book, with no full-record fetches
  (§4).
- `STRATEGY.md`'s direction (authority-first) survives the evidence, but the
  plan fixes only the SBN half and leaves the gaps listed in §6.

---

## 2. The current tool against the use cases

Runs: CLI `--format json`, scored by script, not by eye *(audit)*.

| Use case | Status | Evidence |
|---|---|---|
| UC1 English title + author | Partly | Header "Cien años de soledad · first published 1967 in spagnolo"; the 1967 Sudamericana edition (`BVE0917706`) is marked original **V** *(audit)*. 241 editions, 16 languages. 36 editions (15%) have no language recorded. |
| UC2 Italian title + author | Partly | Same header, 241 editions, 58 Italian (UC1 shows 40) **V** *(audit)*. |
| UC3 original title + author | Partly | Same header, 242 editions **V** *(audit)*. |
| UC4 author only | Not served | `--author` alone is rejected (`book_editions.py:180`) **V** *(own)*. Rows are titles, not works: 10 works take 53 rows, and *Steps to an Ecology of Mind* alone is 10 rows in 7 language groups **M** *(audit)*. Books *about* Bateson are included. Clicking a row reruns nothing: `wire()` in `web/app.js` has no handler for it **I** *(own)*. |
| UC5 title only | Partly | *Noise* offers 4 books (Kahneman, Patterson, Wild, Nihei) but misses Attali's **M** *(audit)*. Choices carry no publisher or first edition. Choosing one filters the page rather than rerunning **I**. A single-work title (*Verso un'ecologia della mente*) shows no confirmation **V** *(audit)*. |
| Filters | Partly, one wrong | No language filter in the CLI or server **V** *(audit)*. The 1990–99 filter shows 18 editions and misses 41 of the 59 in range, because the year span is applied to the Open Library *work's* `first_publish_year` (`openlibrary.py:57-58`) **V** *(own)*. Publisher "Mondadori" is exact (29 of 29). Filters run after all 150 full-record fetches **M**. |
| *Il dottor Živago* + Pasternak | Wrong | Header "Доктор Живаго · first published 1957 in russo". 1957 was the Italian Feltrinelli edition (`LO10333186`), which is labelled a translation **V** *(audit)*. |

### Convergence (UC1–UC3)

Record overlap (Jaccard) between the three *Cent'anni* entry titles **M**
*(audit)*:

| Pair | All records | SBN records |
|---|---|---|
| English vs Italian | 0.668 | 0.380 |
| English vs Spanish | 0.695 | 0.422 |
| Italian vs Spanish | 0.909 | 0.806 |
| Same query, warm vs cold (noise floor) | 0.955 | 0.929 |

- All three share 188 of 291 records, and 44 of 130 SBN records. Of the Italian
  SBN records (38, 57, 55), only 25 appear in all three.
- The header and the set of languages are identical across the three.
- Cause: the SBN work pull keeps the typed title as a search term
  (`opac.py:126,146`) **V** *(own)*. It links 13, 89 or 143 records depending on
  the entry title, and all of them compete for 150 full fetches out of 642–712
  candidates.

### Speed and reliability

**M** *(audit)*:

- Cold: 51.9 s for UC1, 95.0 s for *Živago*, about 200 requests per title
  lookup. 150 of them (74%) are SBN full-record fetches.
- Warm: 0.02–10.5 s, except one run at 56.4 s caused by a single
  it.wikipedia request stalling for 54.8 s.
- Wikipedia stalled in 2 of 10 runs; Open Library failed a request in 3 of 10.
- Author mode: 57 requests.

### Structure

- `pipeline.py`: 1308 lines (812 of code, 40% of all Python), 41 functions
  **M** *(audit)*.
- 6 named constants, 33 inline thresholds and weights, 14 hand-written rules;
  0.6 is hard-coded 4 times beside `IDENTIFYING_TITLE_MATCH` **M** *(audit)*.
- Author mode is a second pipeline keyed on sorted title words
  (`pipeline.py:1212-1213`), with no Wikidata or SBN work lookup **I** *(audit)*.
- No tests and no request counter.

### Root causes

1. **Identity is rebuilt from the typed title.** Every source is queried with
   it, so the result depends on how you asked.
2. **Filters come after the flood** and push year and publisher to Open
   Library at the wrong level.
3. **Author mode has no notion of a work.**
4. **The header is two unrelated Wikidata claims** (language of work,
   publication date), not a first-edition record.

---

## 3. Is there a better data backbone?

### Institutional catalogues *(libraries)*

| Source | Access | Translations grouped? | Distinct languages found (B1–B5) | Verdict |
|---|---|---|---|---|
| WorldCat Search API v2 | Paid: Cataloging **and** Discovery subscriptions plus OAuth; worldcat.org terms ban bots and bulk capture. Classify shut 31 Jan 2024; xISBN retired 2016; Entities API needs OAuth **D** | Yes, `groupRelatedEditions` **D** | Not testable | Best on paper, closed |
| VIAF | Keyless; ODC-BY **D** | Work cluster lists translations (language, translator, title, year), mostly from WorldCat **M** | ~33 (44 raw labels, folding **I**) / ~5 / 6 / 1 / 17+5 **M** | Best one-request language census, ~0.2 s. No editions or publishers. Misses Italian titles for B2–B5; splits works across clusters (B1 into 4) |
| LoC id.loc.gov hubs + LC SRU | Keyless **M** | Typed `translatedas` / `translationof` links, every back-link true **M** | 12 / 4 / 2 / 2 / 11 **M** | Cleanest translation graph, sparse. SRU supports no language, publisher or year-range filter **V**; needs accents stripped client-side |
| ICCU triplestore (SBN linked data) | Keyless SPARQL, no file dump **D** | 770,620 edition→uniform-title links across 11.2M editions **M** | B1: 26 works in 4 languages **M** | Carries uniform titles, far thinner than the OPAC route |
| K10plus / DNB SRU | Keyless; CC0 dumps **D** | GND work ID in the uniform-title field, sparse **V** | B1: 78 records, 7 languages, only 4 linked **M** | Real IDs, sparse linking. DNB language filter passed its control **V** |
| BnF data.bnf.fr | Keyless SPARQL; CC0 **D** | Edition → expression → work **M** | 3 / – / – / 1 / 2 **M** | French holdings; author search pulls in namesakes |
| LIBRIS XL (Sweden) | Keyless **M** | Per-language work records; `translationOf` is text, no ID **M** | Not benchmarked | Swedish coverage, no cross-language ID |
| Index Translationum | UNESCO DataHub, 1978–2008, relaunched May 2026 **D** | By original title, per country | B1: 0 hits in 3 attempts **M** | Query form not found within budget; coverage unknown |
| BNE datos.bne.es | 403 from this machine **M** | Versions of one work **D** | Not tested | Blocked |

- No source states the original's first edition **M**.
- BnF's earliest *Bruits* edition is right (1977, PUF). Its earliest *Cien
  años* is Havana 1968, not the 1967 Sudamericana; LIBRIS holds a 1967
  Sudamericana record.
- Nothing records the 1957 Feltrinelli *Živago* as a first printing.

### Community and aggregator sources *(community)*

| Source | Access | Translations grouped? | Distinct languages found (B1–B5) | Verdict |
|---|---|---|---|---|
| Open Library | Keyless; 1 req/s, 3 req/s with an email in the User-Agent **D** | Partly: the main work holds most, many sit in separate work records **M** | 15 / 15 / 2 / 2 / 14 **M** | Best keyless edition source. Monthly dumps (2026-08-31): editions 12.6 GB, works 4.06 GB, authors 0.78 GB gzipped **M** |
| Wikidata | Keyless **D** | Yes by model; almost no edition items **M** | Edition languages 1 / 5 / 1 / 1 / 1 **M** | Header only |
| Inventaire | Keyless | Keyed on Wikidata IDs | B1: 50 editions, 10 languages (a cap not ruled out) **M** | Marginal; B2–B5 untested |
| BookBrainz | Keyless | Translations are separate works with links **M** | B1 work found; languages untested | Too thin |
| Hardcover | Free account token; beta; 5,000/day, 60/min; backend only **D** | Yes: book → editions with language, publisher, release year **D** | Untested (no token) | The one live alternative worth a trial |
| ISBNdb | Paid, from $14.99/month **D** | No sign of it | Untested | Not justified |
| Google Books | Key; default ~1,000/day (unverified) | Untested | – | Already removed; nothing changes that |
| LibraryThing | APIs disabled **D** | – | – | Unusable |
| Goodreads / StoryGraph | No new keys since Dec 2020 / no public API **D** | – | – | Unusable |
| Anna's Archive (WorldCat scrape) | Court-ordered deletion Jan 2026; publishers sued Mar 2026 (press) | – | Not probed | Legally unacceptable |

**Ground truth for completeness** *(community)*:

- B1 *Cien años de soledad*: 46 languages ([en.wikipedia](https://en.wikipedia.org/wiki/One_Hundred_Years_of_Solitude)).
- B5 *Doctor Zhivago*: at least 18 languages; Feltrinelli sold rights in 18
  before publication ([en.wikipedia](https://en.wikipedia.org/wiki/Doctor_Zhivago_(novel))).
- B4 *Bruits*: at least French, Italian 1978, Spanish 1978, English 1985.
- B2, B3: no count found.

### Open Library details that matter *(community)*

- **Filters are real** **V**: `language:ita`, `publish_year:[1990 TO 1999]` and
  `publisher:Sudamericana` in `q` narrowed B1's 208 editions to 4, 51 and 20.
  Bogus values (`zzz`, `[3000 TO 3001]`, `Zzqxvq`) returned 0. Filters combine.
- **Silent traps** **V**: an unknown field in `q` (`translation_of:`) is read as
  free text and returns unrelated books. An unknown URL parameter is ignored and
  the unfiltered set comes back, the same failure shape as SBN.
- **Scattering** **M**: listing the author's records finds 23 extra records
  matching B1's titles and 37 matching B5's (some are study guides). For B3 and
  B4 the Italian edition exists only as a separate work record. B3's is filed
  under a different author record, so listing by author misses it. Only 9 of
  B1's 208 editions carry `translation_of`, and it is not searchable.

### Hardcover details (docs only, not probed) *(own, from saved API docs)*

**Model and fields** **D**:

- A *book* is the work; *editions* carry `language`, `publisher`,
  `release_date` / `release_year` and ISBNs.
- The book has `release_date`, documented as "Original publication date".
- Editions carry `source` ("OpenLibrary, manual, etc."), so at least part of
  the catalogue is imported from Open Library. How much it adds beyond Open
  Library is unknown **I**.

**Access** **D**:

- A personal access token from a free account, usable from a backend or
  localhost only.
- Since August 2026 tokens can be scoped and given an expiry. Beta tokens may
  be reset without notice.
- Free plan: 5,000 requests/day, 60/min, burst 10.
- At most 5 top-level queries, or 1 `search`, per request.
- `search` times out after 2 s. `_like`, `_ilike` and all regex operators are
  disabled, so fuzzy title matching goes through `search` only.
- Terms forbid using the data to train public or commercial LLMs; personal use
  is allowed.

**Untested:** coverage of non-English editions, whether translations sit under
one book, convergence from EN/IT/original titles, and filter behaviour.

### Wikidata details *(community)*

- Original-language title, year and language correct for all five **M**.
- Publisher is not the first edition's: B2 lists Kodansha and Shinchō Bunko
  rather than Shinchōsha **M**.
- Wikipedia in English, Italian and the original language reach the same item
  for B1, B2, B5 **M**.
- The French article "Bruits" is Nabokov's *Sounds*: a bare title reaches a
  different book **M**.
- `P50` finds 2 works + 3 edition items for Bateson **M**.

### Conclusions on sources

- The only near-complete catalogue (WorldCat) is closed.
- Edition-level detail comes from national catalogues, each biased to its
  country. SBN remains the strongest available for this project.
- A local Open Library dump index would speed up the part that is already
  cheap. SBN is the cost.

### Sources

- VIAF: [OpenAPI](https://developer.api.oclc.org/docs/viaf/openapi-external-prod.yaml) · [licence](https://www.oclc.org/developer/api/oclc-apis/viaf.en.html) · [redesign critique](https://ital.corejournals.org/index.php/ital/article/view/17384)
- WorldCat: [Search API](https://www.oclc.org/developer/api/oclc-apis/worldcat-search-api.en.html) · [v2 spec](https://developer.api.oclc.org/docs/wcapi/v2/openapi-external-prod.yaml) · [worldcat.org terms](https://www.oclc.org/content/dam/ext-ref/worldcat-org/terms.html) · [Classify discontinued](https://help.oclc.org/Librarian_Toolbox/Troubleshooting/Why_is_OCLC_discontinuing_OCLC_Classify) · [xISBN retired](https://github.com/xlcnd/isbnlib/issues/28)
- ICCU: [open data](https://www.iccu.sbn.it/it/attivita-servizi/dati-aperti/) · [LOD](https://www.iccu.sbn.it/en/activities/national-activities/pagina_0006.html)
- Index Translationum: [relaunch](https://www.unesco.org/en/articles/index-translationum-unescos-oldest-database-gains-new-life) · [DataHub dataset](https://data.unesco.org/explore/assets/tran001/?flg=en-us)
- Other catalogues: [datos.bne.es](https://datos.gob.es/en/noticias/national-library-spain-launches-new-version-its-open-data-portal) · [LIBRIS API](https://github.com/libris/librisxl/blob/develop/rest/API.md)
- Wikimedia: [rate limits](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)

---

## 4. The test that decides the architecture

**Question:** can a lookup list a work's editions by identity, without SBN
full-record fetches, fast enough and with enough data to filter on?

**Method** *(own)*:

- Fresh `BOOK_CACHE_DIR`, so every request is cold.
- SBN OPAC:
  1. Read the `titolo_uniformef[]` facet for title + author.
  2. Query `{AUTHOR, titolo_uniformef[]=W}` and read the `lingua[]` facet.
  3. Page each language with `lingua[]=<code>`, 4 workers.
  4. Control: `lingua[]=zzz`.
- Open Library: `search.json` with `q=<title> <author>`, then
  `/works/<key>/editions.json?limit=1000`.
- Script in the appendix.

**Results** **M**, one run each:

| Book | Records / languages | Requests | Cold time |
|---|---|---|---|
| *Cent'anni di solitudine* + Garcia Marquez | SBN 143 / 18 · Open Library 208 / 16 | 26 OPAC + 2 OL | 17.1 s (one request took 11.3 s) |
| *Rumori* + Attali | SBN 3 / 3 · Open Library 1 / 1 | 6 + 2 | 6.1 s |
| *Verso un'ecologia della mente* + Bateson | SBN not reached · Open Library search returned 0 docs | – | script stopped |

**Findings:**

- **Controls pass.** `lingua[]=zzz` returned 0 for both works **V**.
- **The listings carry what filters need.**
  - A year parses in 139/143 SBN imprints and 204/208 Open Library editions.
  - A publisher is present in 143/143 SBN imprints (crude check: `:` in the
    imprint) and 202/208 Open Library editions.
  - Language is present on 163/208 Open Library editions: **22% have none**.
- **Imprints carry sorting markers**, as `STRATEGY.md` Step 6 expects:
  `\Milano! : Euroclub, 1996`, `Vendôme : Presses universitaires de France,
  \1977!`, `Milano : Mazzotta, c1978,, stampa 1977`.
- **Compared with today:** 17 s / 28 requests against 52 s / 203 requests for
  *Cent'anni* **M**. The two runs were on different occasions, so the comparison
  is indicative, not controlled.
- **Open Library must be searched with the original title.** The Italian title
  reached only a one-edition side record for *Rumori* (`OL15764295W`), and
  nothing for *Verso un'ecologia della mente* **M**. It works only once the work
  is known. `STRATEGY.md` does not cover this.

---

## 5. Where the aim needs a decision

1. **"Every edition that exists" cannot be reached.**
   - *Cien años* is documented in 46 languages; SBN lists 18, Open Library 16.
   - **Proposal:** state coverage against a census, e.g. "editions in 20 of ~33
     known languages", with VIAF supplying the census. The VIAF integration is
     untested.
2. **The original is not always the first edition.** *Il dottor Živago* first
   appeared in Italian (Feltrinelli, 1957).
   - No source records first editions directly.
   - **Proposal:** when they differ, show the original (title, language) and the
     earliest catalogued edition separately.
3. **Fetching details upfront is what makes it slow.** The decision log fetches
   ISBN, holdings, translator and buy links during the lookup: about 150 of 200
   requests.
   - The aim as stated on 2026-09-14 does not mention holdings or buying. The
     listings already carry year, publisher and language.
   - **Catch:** SBN listings have no ISBN, so one printing held by both SBN and
     Open Library cannot be merged by ISBN without details.
   - **Workaround (untested):** fetch details only for rows that share
     language, year and publisher **I**.
4. **Filters: list everything, filter locally, then fetch details.**
   - The original, first edition and per-language counts need the unfiltered
     list anyway, and listing is the cheap part.
   - Asking the catalogues to filter saves only listing pages:
     - Language works on SBN and Open Library **V**.
     - Year ranges work only on Open Library; SBN's `dataf[]` takes exact years
       **V**.
     - SBN publisher values are exact and normalised.
   - Pushing the year to Open Library is how today's year bug happened.
   - With a complete list in hand, changing a filter can re-filter instantly
     instead of rerunning the lookup (the decision log currently says rerun).
5. **One list, or grouped by language?** "Newest first, filterable by
   language" reads as a single list; today editions are grouped per language.
6. **Author-only search needs the author pinned down first.**
   - Open Library has duplicate records for one author, and *Steps*' Italian
     edition sits under a different one.
   - "Bateson" is also William and Mary Catherine.
   - **Proposal:** choose the author, then list works.
7. **Title only with one book found.**
   - A confirmation screen repeats what the header shows and costs a click.
   - "Only one found" can be wrong: *Noise* misses Attali's.
   - **Proposal:** go straight to the result, with "other books titled X" under
     the header.

---

## 6. Gaps in `STRATEGY.md` this assessment found

| # | Gap | Evidence |
|---|---|---|
| G1 | Open Library is still searched with the typed title; Italian entry titles miss the main work | §4 **M** |
| G2 | "Details upfront" is the main latency cost and is not revisited | 150 / ~200 requests **M** |
| G3 | No rule for an original that is not the first edition | *Živago* **V** |
| G4 | No statement of coverage against "every edition" | 18–16 of 46 languages **M** |
| G5 | Author mode (Step 10) lists works without first resolving the author | duplicate Open Library authors **M** |
| G6 | Bugs outside the plan: Open Library year filter at work level; CLI `--author` alone rejected; no language filter | **V** |
| G7 | Wikipedia stalls are attributed to the environment. Wikimedia allows 10 req/min to clients without contact info in the User-Agent and 200/min with it **D**; `net.py:29` sends `book-editions-lookup/3.0 (personal research tool)` with none **V** *(own)*. A first test was inconclusive (3 successes then 12 × 429, not reproduced in reversed order) *(community)* | reopen the "Settled" row with a proper test |

---

## 7. Recommended plan

It replaces the ordering of `STRATEGY.md` Steps 2 and 4–11. Steps 1 and 3 stay.

1. **Safety net:** Step 1 as written, plus two baseline metrics: cross-entry
   record overlap (§2) and cold latency.
2. **Stop caching error payloads:** Step 3 as written.
3. **Identify the work once.** One resolver returns a `Work`:
   - the Wikidata item, accepted only when its title matches the query (Step 4);
   - the SBN work, through the tested guard (Step 5);
   - the Open Library work keys, searched with the *original* title + author;
   - the author's identity.
4. **List editions by identity:**
   - SBN per language (Step 6), plus Open Library `editions.json` for each work
     key, merged into one lean list.
   - Nothing after step 3 uses the typed title.
5. **Filter locally, then fetch details**, per decision 3.
6. **Fall back** to today's inference routes (author sweep, Dewey, reverse
   expansion) only when no strong identity exists, marked as inferred. Drop the
   Open Library sibling probes (Step 8: 0 editions from 512 candidates).
7. **Author mode:** choose the author, then list works (Step 10 plus G5).
8. **Title only** (Step 11, per decision 7).
9. **Correct the record** (Step 2), once the new path is in.

**How to build it:**

- Build steps 3–5 as a new path beside `pipeline.py` and run it against the
  Step 1 baseline. Switch over when it matches or beats every regression case.
- Keep the source clients and parsers (`sbn.py`, `opac.py`, `openlibrary.py`,
  `wikidata.py`, `net.py`, `langs.py`, `matching.py`,
  `_language_contradicts_itself`): that is where the knowledge of each
  catalogue's quirks lives.
- The session protocol (one step, stop for review) still applies.

**Rejected:**

- *Start from scratch on a different backbone:* WorldCat is closed; every free
  alternative is thinner (§3).
- *Local Open Library dump index:* it speeds up the part that is already cheap.
- *Keep `STRATEGY.md` unchanged:* it leaves G1–G7 open.

---

## 8. Not tested

- Hardcover (needs a token). Skipped by user decision, 2026-09-14.
- VIAF as a live coverage census inside the lookup; its free-text language
  labels need a normalisation table.
- The Japanese national library API, Jisc Library Hub, hbz lobid, Trove.
- LoC and BnF dump size and freshness.
- Duplicate detection across SBN and Open Library without ISBNs.
- The enumeration probe on *Verso un'ecologia della mente* (the script stopped
  on Open Library's empty result before reaching SBN).
- Repeat cold runs of the enumeration probe (n = 1).

---

## Appendix — enumeration probe

Run with a fresh cache: `BOOK_CACHE_DIR=$PWD/cold_cache python3 enum_probe.py`.

```python
"""Cold timing: enumerate a work's editions by identity, no full-record fetches."""
import os, re, sys, time, json
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/Users/carlofavero/Desktop/DEV/book_requests")
from lookup import net  # noqa: E402  (BOOK_CACHE_DIR set by caller -> cold)

OPAC = "https://opac.sbn.it/o/opac-api/titles-search-full-post"
ANY, AUTHOR = "item:1016:Any:@or@", "item:1003:Autore:@and@"
YEAR = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")
calls = []


def post(body):
    t = time.time()
    d = net.cached_post_json(OPAC, body)["data"]
    calls.append(("opac", time.time() - t))
    return d


def get(url, params):
    t = time.time()
    d = net.cached_get_json(url, params)
    calls.append(("ol", time.time() - t))
    return d


def facet(data, name):
    f = next((f for f in data.get("facets") or [] if f.get("name") == name), None)
    return (f or {}).get("items") or []


def sbn(title, author):
    base = {"core": "sbn", ANY: title, AUTHOR: author, "page": "1"}
    items = [i for i in facet(post(base), "titolo_uniformef[]") if "<" not in str(i.get("label"))]
    w = max(items, key=lambda i: i["results"])["value"]
    work = {"core": "sbn", AUTHOR: author, "titolo_uniformef[]": w, "page": "1"}
    d = post(work)
    total, langs = d.get("total"), facet(d, "lingua[]")
    control = post({**work, "lingua[]": "zzz"}).get("total")

    def pages(code, n):
        rows = []
        for p in range(1, (n + 19) // 20 + 1):
            rows += post({**work, "lingua[]": code, "page": str(p)}).get("results") or []
        return code, rows

    with ThreadPoolExecutor(4) as ex:
        out = list(ex.map(lambda i: pages(i["value"], i["results"]), langs))
    rows = [(c, r) for c, rs in out for r in rs]
    imprint = [str((r.get("infos") or [""])[0]) for _, r in rows]
    return {"work": w, "total": total, "languages": len(langs), "rows": len(rows),
            "bogus_lingua_total": control,
            "rows_with_year": sum(bool(YEAR.search(i)) for i in imprint),
            "rows_with_publisher": sum(":" in i for i in imprint),
            "sample_imprints": imprint[:4]}


def ol(title, author):
    docs = get("https://openlibrary.org/search.json",
               {"q": f"{title} {author}", "fields": "key,title,edition_count", "limit": 5})["docs"]
    key = max(docs, key=lambda d: d.get("edition_count") or 0)["key"]
    eds = get(f"https://openlibrary.org{key}/editions.json", {"limit": 1000})["entries"]
    langs = {l["key"] for e in eds for l in e.get("languages") or []}
    return {"work": key, "editions": len(eds), "languages": len(langs),
            "with_date": sum(bool(e.get("publish_date")) for e in eds),
            "with_publisher": sum(bool(e.get("publishers")) for e in eds),
            "with_language": sum(bool(e.get("languages")) for e in eds)}


for title, author in [("Cent'anni di solitudine", "Garcia Marquez"), ("Rumori", "Attali"),
                      ("Verso un'ecologia della mente", "Bateson")]:
    calls.clear()
    t = time.time()
    with ThreadPoolExecutor(2) as ex:
        s, o = ex.submit(sbn, title, author), ex.submit(ol, title, author)
        res = {"sbn": s.result(), "ol": o.result()}
    res["wall_s"] = round(time.time() - t, 1)
    res["requests"] = {k: sum(1 for c in calls if c[0] == k) for k in ("opac", "ol")}
    res["slowest_s"] = round(max(c[1] for c in calls), 2)
    print(title, json.dumps(res, ensure_ascii=False, indent=1))
```
