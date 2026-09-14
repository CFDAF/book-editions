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
| UC5 title only | Partly | *Noise* offers 4 books (Kahneman, Patterson, Wild, Nihei) but misses Attali's **M** *(audit)*. SBN holds it: `title=noise` matches 2,867 records and it is not among the first 500 the tool reads, while `title=noise&author=attali` returns only `LO10442107`. The control `zzqxnoise` returns 0 **V** *(own)*. This is ranking plus truncation, not an SBN bug. Choices carry no publisher or first edition. Choosing one filters the page rather than rerunning **I**. A single-work title (*Verso un'ecologia della mente*) shows no confirmation **V** *(audit)*. |
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

### Decisions taken (user, 2026-09-14)

| # | Decision |
|---|---|
| 1 | No reachable source lists every edition. The result says what was found against what is known. |
| 2 | When the original and the first edition differ, show them separately. |
| 3 | Buy links and library holdings are fetched when a row is expanded, not during the lookup. The ISBN-collision dedup workaround is to be tested before it is adopted. |
| 4 | Enumerate the whole work, filter locally, then fetch details. The original, first edition and counts are computed unfiltered. |
| 5 | Editions stay grouped by language. |
| 6 | Author-only search resolves the author first, then lists works. Several author candidates can be selected together, for variants of one person (typos, diacritics, transliteration). |
| 7 | UC5 (title only) is dropped. A title lookup needs an author. |

These supersede the 2026-09-14 decision-log rows in `STRATEGY.md` on upfront
details (3) and on rerunning the lookup when a filter changes (4). They are
recorded there once the wider benchmark (§9) has run.

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
| G7 | Wikipedia stalls are attributed to the environment. Wikimedia's 2026 limits for the Action and REST APIs give 10 req/min to requests identifiable only by IP, and 200 req/min to bots with a compliant User-Agent such as `CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org) generic-library/0.0`. No registration is needed for that tier **D** ([policy](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits), "new in 2026 and subject to experimentation"). `net.py:29` sends `book-editions-lookup/3.0 (personal research tool)`, with no contact **V** *(own)*. A first test was inconclusive (3 successes then 12 × 429, not reproduced in reversed order) *(community)* | reopen the "Settled" row with a proper test |

---

## 7. Recommended plan

It replaces the ordering of `STRATEGY.md` Steps 2 and 4–11. Steps 1 and 3
stay. It is revised for the decisions in §5, and the benchmark in §9 runs
before it is recorded in `STRATEGY.md`.

1. **Safety net:** Step 1 on the §9 corpus, plus two baseline metrics:
   cross-entry record overlap (§2) and cold latency.
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
5. **Filter locally, then fetch details.**
   - Filters apply to the lean list (decision 4).
   - Holdings and buy links are fetched when a row is expanded (decision 3).
   - Cross-source duplicates are merged by the ISBN-collision workaround only
     if §9 (A4) supports it.
   - The header shows the original and the first edition separately when they
     differ (decision 2), plus coverage against a census (decision 1).
6. **Fall back** to today's inference routes (author sweep, Dewey, reverse
   expansion) only when no strong identity exists, marked as inferred. Drop the
   Open Library sibling probes (Step 8: 0 editions from 512 candidates).
7. **Author mode** (Step 10 plus G5, decision 6):
   - Resolve author candidates, pre-grouped by authority (SBN name authority,
     VIAF) where one exists.
   - Let the user select one or several.
   - List works titled in their original language, newest first.
   - Selecting a work runs the title + author lookup.
8. **Correct the record** (Step 2), once the new path is in. Title-only
   disambiguation (Step 11) is dropped (decision 7). A title lookup without an
   author asks for one.

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
- Duplicate detection across SBN and Open Library without ISBNs (the decision 3
  workaround; §9 A4).
- The enumeration probe on *Verso un'ecologia della mente* (the script stopped
  on Open Library's empty result before reaching SBN).
- Repeat cold runs of the enumeration probe (n = 1).

---

## 9. Wider benchmark (draft, for review)

Most §3–§4 evidence rests on 3–5 books. The assumptions below are tested on a
wider corpus before the plan is recorded. The corpus then becomes Step 1's
regression set, so the work is not done twice.

### Assumptions under test

| # | Assumption | Metric | Fails if |
|---|---|---|---|
| A1 | Every entry title + author reaches one identity | Wikidata item, SBN work (tier) and Open Library main work, per entry title | any entry title of a book resolves differently |
| A2 | Listing by identity loses nothing today's tool finds | records in today's result missing from the listing, each explained; requests; cold latency | an unexplained loss, or cold latency worse than today |
| A3 | Listing rows are enough to filter | year, publisher, language parse rates per source | < 90% year parse on SBN rows |
| A4 | ISBN-collision dedup (decision 3) | on books whose full records are fetched as ground truth: precision and recall of (language, year, normalised publisher) collisions against shared ISBNs; detail fetches needed against all | precision < 95%, or no fetch saving |
| A5 | Original vs first edition is detectable (decision 2) | Wikidata original (title, language, year) against the earliest catalogued edition | a wrong original; a missed or false "first edition differs" |
| A6 | A census can state coverage (decision 1) | VIAF work languages (normalised) against languages found | census unavailable or smaller than found for most books |
| A7 | Authorities group author variants (decision 6) | variant forms reaching one SBN / VIAF authority | variants split, leaving only manual multi-select |
| A8 | A contact User-Agent removes Wikimedia throttling (G7) | same request sequence with each User-Agent: 429s, stalls > 5 s | no difference |

### Corpus

Already in `STRATEGY.md` (kept): *Cien años de soledad*, *Steps to an Ecology
of Mind*, *Bruits*, *Umibe no Kafuka*, *The Invention of News*, *More
Brilliant Than the Sun*, *Liquid Modernity*, *Communication: The Social Matrix
of Psychiatry*, *Il nome della rosa*, *Opere* (Leopardi), *Poesie* (Montale),
*Über den Begriff der Geschichte*, *Angelus Novus*, *Per una economia
positiva*, *The Essential Knuth*, plus *Doktor Živago* (this assessment).

New. Facts below are from memory. Establishing ground truth for each is the
run's first stage, and is itself a test of A5.

| # | Original title | Author | Original | EN / IT entry titles | Fame | What it tests |
|---|---|---|---|---|---|---|
| N1 | Nesnesitelná lehkost bytí | Milan Kundera | cze; first printed in French, Gallimard 1984 | The Unbearable Lightness of Being / L'insostenibile leggerezza dell'essere | high | original ≠ first edition; diacritics |
| N2 | Le Petit Prince | Antoine de Saint-Exupéry | fre; first printed New York 1943, in English and French | The Little Prince / Il piccolo principe | very high | first edition abroad; hundreds of languages; census |
| N3 | Se questo è un uomo | Primo Levi | ita; De Silva 1947, Einaudi 1958 | If This Is a Man, *and* Survival in Auschwitz | high | Italian original outward; two English titles; first publisher ≠ famous one |
| N4 | Преступление и наказание | Fëdor Dostoevskij | rus; serial 1866, book 1867 | Crime and Punishment / Delitto e castigo | very high | transliterated author; pre-1900; page and facet caps |
| N5 | The Catcher in the Rye | J. D. Salinger | eng 1951 | — / Il giovane Holden, *and* Vita da uomo (1952) | high | no shared words; retranslation under another title |
| N6 | Nineteen Eighty-Four | George Orwell | eng 1949 | — / 1984, Millenovecentottantaquattro | very high | pseudonym; numeric title forms |
| N7 | Se una notte d'inverno un viaggiatore | Italo Calvino | ita 1979 | If on a Winter's Night a Traveler / — | high | Italian original; long punctuated title |
| N8 | L'amica geniale | Elena Ferrante | ita 2011 | My Brilliant Friend / — | high, recent | pseudonym; recent translations; TV adaptation in facets |
| N9 | Il formaggio e i vermi | Carlo Ginzburg | ita 1976 | The Cheese and the Worms / — | mid, academic | Italian non-fiction outward |
| N10 | L'Étranger | Albert Camus | fre 1942 | The Stranger, *and* The Outsider / Lo straniero | very high | two English titles |
| N11 | La Disparition | Georges Perec | fre 1969 | A Void / La scomparsa | mid | retitled everywhere |
| N12 | Der Process | Franz Kafka | ger 1925 | The Trial / Il processo | very high | posthumous; spelling variants (Process / Prozess); many Italian translations |
| N13 | Müdigkeitsgesellschaft | Byung-Chul Han | ger 2010 | The Burnout Society / La società della stanchezza | mid, recent | name order and romanisation |
| N14 | Ensaio sobre a cegueira | José Saramago | por 1995 | Blindness / Cecità | high | Portuguese |
| N15 | 2666 | Roberto Bolaño | spa 2004 | 2666 / 2666 | mid | numeric title identical everywhere |
| N16 | 活着 | Yu Hua | chi 1993 | To Live / Vivere! | mid | Chinese script and romanisation |
| N17 | بين القصرين | Naguib Mahfouz | ara 1956 | Palace Walk / Tra i due palazzi (verify) | mid | Arabic script; transliterated author |
| N18 | Capitalist Realism | Mark Fisher | eng 2009 | — / Realismo capitalista | niche | small press; subtitle |
| N19 | Tomorrow, and Tomorrow, and Tomorrow | Gabrielle Zevin | eng 2022 | — / Domani, e domani, e domani | high, very recent | few editions; catalogue lag |
| N20 | Metaphors We Live By | George Lakoff, Mark Johnson | eng 1980 | — / Metafora e vita quotidiana | mid, academic | two authors; retitled |
| N21 | Veinte poemas de amor y una canción desesperada | Pablo Neruda | spa 1924 | Twenty Love Poems and a Song of Despair / Venti poesie d'amore e una canzone disperata | high | poetry; bilingual editions |
| N22 | Le Capital au XXIe siècle | Thomas Piketty | fre 2013 | Capital in the Twenty-First Century / Il capitale nel XXI secolo | high | recent non-fiction; roman numerals |
| N23 | Ὀδύσσεια | Homer | grc | The Odyssey / Odissea | extreme | insights only, no fail criteria applied: no meaningful first edition; thousands of records |
| N24 | Tutto per una casa: dalla Russia alla Siberia fino in Spagna | Orlando Ciprian | ita; one edition, no translations known (user) | — / — | obscure | the minimal case, likely absent from Wikidata and Open Library: exactly one edition, no invented original, translation or census; subtitle |

Author-only set (A7): Gregory Bateson · Murakami Haruki / Haruki Murakami ·
Fëdor Dostoevskij (Dostoevsky, Dostoïevski) · Elena Ferrante · Jacques Attali
(prolific; duplicate Open Library authors; 50-item facet cap) · Umberto Eco ·
Kodwo Eshun (tiny bibliography) · Byung-Chul Han.

### How it runs

- Plain scripts, not exploratory agents. Earlier in this session three
  parallel agents hit the session limit.
- Serial per host, with a fresh cache per stage.
- **Stage 1:** ground truth, then A1, A3, A5, A6, A7, A8. Cheap: identity and
  listing requests only. A8's contact User-Agent carries the project's GitHub
  URL.
- **Stage 2:** today's pipeline on every entry title, in the background, for
  A2. About 90 entry titles at ~1 min cold.
- **Stage 3:** A4 on about 8 books of mixed size, fetching full records as
  ground truth.
- Each stage reports raw numbers against the fail criteria before the next
  starts.

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
