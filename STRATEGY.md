# STRATEGY — identity-first lookup

The agreed plan of work for this project. It is the single plan every session
follows, so work stays on one line across sessions.

Revised **2026-09-16** on the wider benchmark (`bench/RESULTS.md`: three stages,
40 books, 91 scored entry runs) and on the user's answers to its three question
sets. Those answers are decisions. Where they disagree with
`docs/assessment-2026-09-14.md`, with `HANDOFF.md` or with an earlier row here,
they win, and the disagreement is recorded rather than quietly dropped.

Read order: `CLAUDE.md` → **Session protocol** and **Status** below → **What the
benchmark established** → the step you are on → the sections of `HANDOFF.md`
that step touches, with **Where this plan corrects the record** applied on top.

**Evidence tags**, used on every claim carried across: **V** verified with a
control · **M** measured · **D** documented (link) · **I** inferred. Every
number below comes from `bench/RESULTS.md` and `bench/results/`. Nothing was
re-measured while writing this document.

---

## The aim (the user's own specification — the source of truth)

Search a book and get **every edition of that book that exists**.

| Use case | Input | Result |
|---|---|---|
| UC1 | English title + author | The original first edition's title in its original language, then every later edition in every language — filterable by language, newest first, undated last |
| UC2 | Italian title + author | The same result as UC1 |
| UC3 | Original title + author, **Latin script**; a title in another script is typed romanised | The same result as UC1 |
| UC4 | Author only | Every book by the author, as works titled in their original language, newest first. The author is resolved first; selecting a work reruns the lookup as UC3 |
| ~~UC5~~ | ~~Title only~~ | **Dropped** (decision 7, 2026-09-14). A title lookup with no author asks for one |
| Filters | Year span, language, publisher on every lookup | Applied locally to the list already in hand; changing one re-filters instantly |

UC1–UC3 define **convergence**: the three entry titles of one book must reach
the same work, the same original, and the same edition set. It is the property
most of this plan exists to deliver — and A1 measured that no single source
reaches one identity for every entry title, so convergence is a target measured
against `bench/corpus.json`, not something any source hands over.

Still in force from earlier framing: the header is a publication history, never
a yes/no verdict.

---

## Session protocol

1. Take the first step in **Status** that is not `done`. One step per session.
2. Branch from `main`: `plan/step-N-<slug>`.
3. Before writing code, re-run the verified facts the step depends on (from
   Step 1 on, these are live tests; see **Verified facts**). A fact that no
   longer reproduces means the catalogue changed: stop and ask.
4. Implement. Run the offline tests and the live regression runner, and diff
   the output against the committed baseline.
5. Update the step's **Status** row: state, date, commit, and the measured
   numbers its gate asks for. Record any user decision in **Decision log**.
6. Stop and report to the user: the gate result, the baseline diff, cold latency
   (with a fresh `BOOK_CACHE_DIR`), and open questions. The next step waits for
   the user's go-ahead.

**Show the page before building it.** Any step that changes what the reader sees
puts the layout in front of the user first (the rule Step 11 already carried;
it now applies to Steps 8, 9, 10 and 11).

**Stop and ask**, mid-step, whenever:
- a gate fails and the only fix in sight loosens `_identifies`, the title
  threshold, or the work guard;
- a verified fact below does not reproduce;
- a change would make an existing regression case lose an edition, an original,
  or a disambiguation choice, even if the new behaviour looks better;
- measured cold latency gets worse than the step's baseline;
- the step needs a decision this document does not already record.

The plan changes only by recording the change here, with its evidence, after
the user agrees.

---

## Status

| Step | Title | State | Date / commit | Measured |
|---|---|---|---|---|
| 1 | Safety net: tests, baseline, API-fact checks | todo | | |
| 2 | Stop caching error payloads | todo | | |
| 3 | Network manners: contact User-Agent, slow-lookup notice | todo | | |
| 4 | Identify the work once | todo | | |
| 5 | List editions by identity | todo | | |
| 6 | Recovery route beside the listing | todo | | |
| 7 | Filter locally; details on expand | todo | | |
| 8 | The header: the original, and the earliest edition found | todo | | |
| 9 | Edition rows: printings, background grouping, duplicate hint | todo | | |
| 10 | Open Library duplicate work records | todo | | |
| 11 | Author mode: resolve the author first | todo | | |
| 12 | Correct the record (docs only) | todo | | |

**Where the old steps went** (the numbering changed; `HANDOFF.md` still cites the
old numbers until Step 12 lands):

| Old | New |
|---|---|
| 1 Safety net | 1, with `bench/corpus.json` as the regression set |
| 2 Correct the record | 12 (moved to the end: the record to correct now includes the benchmark's findings) |
| 3 Stop caching error payloads | 2, unchanged |
| 4 Wikidata title test | inside 4 |
| 5 Work guard | inside 4, plus the Wikidata second signal |
| 6 List the work per language | 5 |
| 7 Filters before details | 7, revised: local re-filtering, details on expand, SBN full records in the background |
| 8 Remove Open Library sibling probes | inside 6 (dropped: 0 editions from 512 candidates) |
| 9 Title-gate the author sweep | inside 6 (now the shape of the whole recovery route) |
| 10 Author mode | 11, with the author resolved first |
| 11 Title-only disambiguation | **dropped** (decision 7) |
| — | 8, 9, 10 are new: header, printings/duplicates, Open Library duplicate works |

---

## What the benchmark established

Full detail, per book and per entry, is in `bench/RESULTS.md`; raw results in
`bench/results/`. Summary of the eight assumptions:

| # | Assumption | Result | What it means here | Evidence |
|---|---|---|---|---|
| A1 | Every entry title + author reaches one identity | **FAIL** in all three sources. Books whose every entry reaches the right identity: SBN 22/37, Wikidata Step 4 14/37, Open Library 13/37. Of 91 entries, SBN 68 right · **0 wrong** · 23 none | The plan cannot assume an identity. But the guard never accepts a *wrong* work: its failures are refusals, so the answer is a second acceptance signal (decision A) and a recovery route (decision F), not a looser gate | M (OPAC facts V) |
| A2 | Listing by identity loses nothing today's tool finds | **PASS** on latency read overall; **no unexplained loss**. It does drop 334 SBN records not linked to W and 98 Open Library editions in duplicate work records — every one explained. Cold per entry: today median 34.5 s, identity **3.5 s**; requests 192 vs 19 | Listing by identity is the backbone (Step 5) and it is 8.8× faster at the median; the explained losses are what Steps 6 and 10 exist to recover | M; record classes V + 161 hand judgements |
| A3 | Listing rows are enough to filter | **PASS**. SBN 2,561/2,603 rows with a parsable year (98.4%), publisher 2,602, language 2,601; every language page summed to the work total. Open Library 98.1% dated, language **80.8%** | Filtering needs no full record (Step 7). Open Library's missing language is why a language filter must not silently drop those editions | V (control) + M |
| A4 | Cross-source duplicates can be found by a (language, year, publisher) collision | **FAIL**. Precision **82/125 = 0.656** where both sides have an ISBN; 0.664 under the strictest publisher rule, 0.636 under the loosest. Recall 0.164 (same-year truth 0.631). Fetch saving 81.2% holds | Never merge on a collision. It becomes a hint only (decision H); merging waits for an ISBN (decision I) | M; fetch control V |
| A5 | Original vs first edition is detectable | **FAIL**. Wikidata's original wrong in 3 of 26 accepted items; the listing rule gave 8 false "first edition differs" flags and 1 miss over 36 books | No inference. The header states the original and, always, the earliest edition found (decision D) | M |
| A6 | VIAF can state coverage | **FAIL** for 20 of 37 books (13 census smaller than what was found, 7 no cluster); 13 books split across clusters; results not relevance-ordered | No census; VIAF is not used anywhere in the lookup (decision C) | V (bogus index/value → 0) + M |
| A7 | Authorities group author variants | **PASS**. All 17 Latin forms of 9 people reach one VIAF cluster; **SBN's name authority gives one id per person for every Latin form** (non-Latin forms dropped); Wikidata 8/9; Open Library omits the main record for Murakami, Dostoevsky, Han | Author mode resolves the author through SBN's name authority (Step 11). VIAF's part of this pass is not used, by decision C | V (controls) + M |
| A8 | A contact User-Agent removes Wikimedia throttling | **PASS**. Today's UA: **102 × 429 of 180**; a UA with a contact URL: **0 of 180**. In the pipeline: Wikimedia 35% of request time → 3.8%; 41.1 s → 11.5 s median on the 9 throttled runs | `net.USER_AGENT` becomes the contact form (decision E) | M |

### The four failures are constraints, not a backlog

They are not defects to be fixed later. Each one closes a road, and the plan is
shaped around the closure.

- **A1 — no source reaches one identity for every entry title.** Not SBN
  (22/37 books), not Wikidata (14/37), not Open Library (13/37). So: the lookup
  must produce a usable answer with no identity at all, and a book with no
  identity is normal, not an error state. Loosening the guard is ruled out — the
  known wrong works (*Tesi*, *Angelus Novus*) sit at B = 0.5, **above** every
  refused classic (B ≤ 0.375) **M**. The classics fail because their records are
  thinly linked (*Crime and Punishment* eng 9/31, *Der Process* 2/15,
  *Blindness* 3/8), not because the guard is miscalibrated.
- **A4 — collision merging is wrong a third of the time** (precision 0.656).
  Every false positive pairs records with the same language, year and publisher
  but different ISBNs: one publisher's edition for another country (Alfaguara
  978-84 vs 978-968 **D**), another binding or line (Faber 2021
  `9780571355884` / `…891`). **I**: nothing in a listing row separates them —
  page count, series and binding live in the full record only, which is the
  fetch the workaround existed to avoid. So no rule over listing fields can
  rescue this; only an ISBN can.
- **A5 — the original is not derivable from the listings.** Bad catalogue dates
  (a Dutch translation dated 1912, CreateSpace reprints dated 1866 and 1825, an
  audiobook dated 2001) and missing originals produce confident wrong flags. So
  the header stops inferring and states two facts side by side.
- **A6 — VIAF cannot say how many languages exist.** So "found N of ~M known"
  is dropped from the product, and the honest statement replaces it.

---

## Decision log

Rows marked **superseded** stay for the record; do not act on them.

| Date | Decision | By |
|---|---|---|
| 2026-09-14 | Sessions stop after each step for review; all steps live in this document. | user |
| 2026-09-14 | The language filter **narrows** results (the aim, UC1). | user (aim) |
| 2026-09-14 | Filters apply **before** per-edition details are fetched. The original, first edition and per-language counts are always computed unfiltered. ~~Changing a filter reruns the lookup.~~ **The rerun half is superseded** by §5-4: the whole list is in hand, so a filter change re-filters locally. | user |
| 2026-09-14 | ~~Per-edition details (ISBN, holdings, translator, buy links) are fetched **upfront**, during the lookup.~~ **Superseded** by §5-3 and decision I. | user |
| 2026-09-14 | **§5-1**: No reachable source lists every edition. The result says what was found against what is known. | user |
| 2026-09-14 | **§5-3**: Buy links and library holdings are fetched when a row is expanded, not during the lookup. *Revised by decision I*: SBN full records are fetched in the background during the lookup, so SBN holdings arrive with them; Open Library details and buy links stay on expand. | user |
| 2026-09-14 | **§5-4**: Enumerate the whole work, filter locally, then fetch details. The original, first edition and counts are computed unfiltered. | user |
| 2026-09-14 | **§5-5**: Editions stay grouped by language. | user |
| 2026-09-14 | **§5-6**: Author-only search resolves the author first, then lists works. Several candidates can be selected together, for variants of one person. | user |
| 2026-09-14 | **§5-7**: UC5 (title only) is dropped. A title lookup needs an author. | user |

### Decisions from the benchmark answers (user, 2026-09-15 / 2026-09-16)

Each row: the decision, what it changes, and the evidence that stands behind it.

| # | Decision | Effect on the build | Evidence |
|---|---|---|---|
| **A** | **A second acceptance signal for a refused SBN work.** A refused or weak W is accepted when the Wikidata item Step 4 accepts for the same entry has a label, sitelink or P1476 matching W at ≥ 0.6. Loosening B stays ruled out | Step 4. The guard keeps its tiers; the second signal only adds acceptances | **M** `results/stage-2/q1_second_signal.json`: rescues **7** refusals — E16 eng, N14 eng, N21 eng, N22 eng + ita, N23 eng + ita — of the 19 refused-or-weak entries the probe scored (`RESULTS.md` states it as 7 of 16, A1's subset with a W but no strong tier; the probe's own list is 19); **0 agreements in 2,024 cross-book pairs** (weak control: few same-author pairs); positive control 44 of 47 strong entries agree; the 3 wrong-W refusals have no Step 4 item and stay refused. Misses: N12 × 3 (`prozess` vs "Der Prozess" 0.5), N17 eng (0.0), N04 and E12 (no item) |
| **B** | **Latin script only; non-Latin titles and names are romanised** before they are matched or sent | Steps 4 and 5. `corpus.json` v2 holds the romanised entry titles; names and titles that a source files in another script (Open Library 村上春樹, نجيب محفوظ; Wikidata P1476) are romanised before matching | **V** the OPAC silently drops non-Latin free text (`probe_nonlatin_any.json`), so it cannot be sent at all. **M** romanised entries reached SBN works that the script form missed: N04, N16, N17 strong. Two still missed because SBN's own romanisation differs (`zivago`, `odyssea`) → decision G |
| **C** | **No coverage census. VIAF is not used.** The result states the languages found plus a fixed note that catalogues are incomplete | Step 8. Removes the "found N of ~M known languages" line from the product and VIAF from the source list. Revises assessment decision 1 | **A6 FAIL** — V + M (above) |
| **D** | **No "first edition differs" inference.** The header shows the original and, always, "earliest edition found" (year, language, publisher) — a statement about the catalogues. Editions dated before the original's known year are left out of it | Step 8. Revises assessment decision 2 | **A5 FAIL** M. Rule checked offline on the Stage 1 listings, 37 books (`results/stage-2/q4_earliest_found.json`) **M**: the first edition's year and language 22; the right year with other languages tying 9; later than the first edition 4 (original not listed, or Wikidata's wrong P577); right year but no language / wrong year 2; **a date older than the first edition 0** |
| **E** | **`net.USER_AGENT` becomes the contact form** | Step 3, a one-line change plus its test | **A8 PASS** M: 102 × 429 of 180 → 0 of 180, same in both orders; in the pipeline, Wikimedia 35% of request time → 3.8% |
| **F** | **A recovery route beside the listing, title-gated.** Today's candidate routes stay for books that *do* have a strong work; a record is admitted only by title against the work's titles (old Step 9's shape). The Wikidata-title route carries Step 4's rule | Step 6. "The project's first need is to reach every edition of a book, or as close as possible" | **A2** M: the listing alone drops **334 SBN same-work records not linked to W** (301 with no uniform title, 33 under another) and **98 Open Library editions in duplicate work records**. The routes that find them: Wikidata title 207, author sweep 119, ISBN 25. The same routes leak: **44 wrong-work records**, 21 of them through the Wikidata-title route. The title gate's yield and leak rate are **untested** |
| **G** | **Fold transliteration variants when matching** (zh/ž/z, -eia/-ea and the like) | Step 4, in `matching` | **M**: *Doktor Zhivago* misses SBN's `doktor zivago`, *Odysseia* misses `odyssea`. **Untested**, and it cuts both ways: folding raises scores between *different* titles, so the gate counterexamples must be re-checked |
| **H** | **Cross-source duplicates are shown as a "possibly the same edition" hint, never merged silently.** A red margin bracket joins the two rows, with a tooltip giving the reason. Opening Details on either row settles it: same ISBN → the rows fold into one carrying both sources; different ISBNs → the bracket goes; no ISBN on one side → the hint stays. The language count includes both rows; a note under the list says how many pairs may be duplicates | Step 9 | **A4 FAIL** M: precision 0.656 where both ISBNs are known. Under decision I the bracket only ever survives where one side has no ISBN — 288 such collisions in Stage 3, **precision unknown** |
| **I** | **One edition row per ISBN, listing its printing years, grouped in the background.** The list shows at once; every SBN full record is fetched behind it; printings fold into editions and cross-source duplicates merge by ISBN as the ISBNs arrive; the page shows that grouping is still in progress. **Progress carries no details unless the server streams them** (2026-09-16): until the lookup has finished, the page only says grouping is running, and the counts settle when it ends | Step 9. Revises assessment decision 3: SBN details *are* fetched during the lookup, in the background, so holdings arrive with them | **M** `results/stage-3/q2_printings.json`: with every full record, 483 records carrying an ISBN become **297 edition rows** (42 editions with several printings, up to 31 — Adelphi's *L'insostenibile* `9788845906862` spans 1985–2026). **295 of 778 records have no ISBN and stay one row per printing.** Grouping from listing fields alone (language, publisher, title) has precision **0.425**, so it is not used. Background cost is one full record per SBN row (613 for N02); ~17 s for N10 at 6 at a time (**I**, from 102.3 s measured one at a time) |
| **J** | **Main Open Library work only; the duplicate work records are listed as records without their editions.** Opening one fetches its editions **by work key** and **adds them to the language groups** (2026-09-16) — not a page of its own — so they are grouped by language and go through the same printing-grouping and duplicate check. The page carries a hint of this workflow | Step 10 | **M/V** `results/stage-3/q3_duplicate_works.json`, 45 duplicate works over 21 books: *by title, no* **M** — the main-work rule with the duplicate's own title returns the main work again 24, a different book 5, the duplicate 3, nothing 1; *by key, yes* **V** — `/works/<key>/editions.json` returned every Stage 2 edition for 45 of 45, bogus key → 404. *Finding them* **M**: the original-title search shows 10 of 45; adding each entry title raises it to 39 of 45, one extra search each. **The list is not clean** (untested): the searches also return omnibus volumes and adaptations, and apparently more duplicates Stage 2 never saw — so 98 editions is a lower bound, and rows must show title and edition count |
| **K** | **A lookup that is slow for a known reason must say so.** Latency is judged overall (A2 passes) | Step 3. The network layer records, per lookup, what made it slow (urllib3 retries and their cause, `Retry-After` sleeps, requests over 10 s, pages fetched); above ~10 s cold, `report.notes` names only causes measured *in that lookup* | Proposal accepted, **untested**. Identity p90 is 5.7 s **M**, which is where the ~10 s threshold comes from. A live status line would need the server to stream progress |

---

## The shape of the lookup

Assessment §7, with the benchmark's answers folded in:

1. **Identify the work once.** One resolver returns a `Work`: the Wikidata item
   (accepted only when its title matches), the SBN work (through the guard, plus
   the Wikidata second signal), the Open Library work keys (searched with the
   *original* title + author), and the author's identity.
2. **List its editions by that identity.** SBN per language, Open Library
   `editions.json` per work key, merged into one lean list. **Nothing after
   step 1 uses the typed title** — except the recovery route, which uses it only
   to find candidates it then gates on the *work's* titles.
3. **Filter locally.** The list is complete before a filter is applied; changing
   one re-filters instantly. The original, the earliest edition found and the
   per-language counts are always computed unfiltered.
4. **Fetch details.** SBN full records in the background, for grouping and
   holdings; Open Library details and buy links when a row is expanded.

Speed follows from the same lever: identity + listing is 3.5 s at the median
against today's 34.5 s, and 19 requests against 192 **M**.

---

## The steps

### Step 1 — Safety net: tests, baseline, API-fact checks

Every later step changes what reaches the gate. Nothing below is safe to do
without a way to see what changed.

**The regression set is `bench/corpus.json`** — 40 books (E01–E16 the existing
regression books, N01–N24 new), each with its entry titles, `query_author`, and
hand-checked `ground_truth` (original title, language, first edition, which
entries were published, sources named per fact) — **plus** the 16 cases in
`HANDOFF.md` §9. E10 (*Opere*) and E11 (*Poesie*) are generic titles and N23 is
insights-only: they are asserted on refusal behaviour, not on an edition set.

Do:
- Offline `pytest` for the pure functions `CLAUDE.md` names (`matching.py`,
  `langs.py`, `sbn.py` parsers, and in `pipeline`: `_dewey_affinity`,
  `_identifies`, `_dewey_discriminates`, `_assign_groups`, `_span_is_original`,
  `_origin_phrase`), plus the gate's counterexamples as hand-built `Edition`s:
  *L'ordine delle notizie*, *Quale socialismo, quale Europa*, and the 863.44
  García Márquez set.
- A live regression runner over the corpus and §9. It asserts **structure only**
  (languages present, original title/language/year, number of choices, named
  BIDs present or absent, source states), never exact totals.
- Live API-fact tests: one per row of **Verified facts**, each with its
  bogus-value control.
- Run everything on the **unchanged** code. Commit a baseline snapshot
  (structural fields only) and list every case that fails today as
  **known-red**.

`bench/baseline/` already holds a structural baseline from Stage 2; reuse its
field set rather than inventing a second one. Known-reds to expect, and to
observe rather than assume: most convergence sets; *Per una economia positiva*
with no original; *Tesi di filosofia della storia* headed by the wrong work;
*Opere* + Leopardi headed by *Canti*; and the 23 entries where SBN reaches no
identity at all.

Gate — offline tests pass; the live runner completes every case; the baseline is
committed; the known-red list is recorded.

### Step 2 — Stop caching error payloads

`net.cached_get_json` and `cached_post_json` write any valid JSON to disk;
`sbn._request` only raises afterwards. A Solr error on a Japanese-script
Wikidata title variant was cached and replayed for 24h. `opac._post` has the
same shape for a payload with no `data` object.

Do: make the cache refuse a payload its caller rejects — a validation hook in
`net.py`, used by `sbn._request` (an `error` key) and `opac._post` (no `data`
object). Failures still raise `SourceError` and still reach `Tally`.

Note from Stage 2 **I**: the pipeline reported `SBN partial (1 request failed)`
in 10 runs where no HTTP request failed — one per book for E04, N03 and N12.
An error payload is the likely cause; this step should make it visible.

Gate — a test with a faked error payload leaves no cache file; a replayed
request after a transient error goes back to the network; the 10-run phantom
failure is either gone or explained.

### Step 3 — Network manners: contact User-Agent, slow-lookup notice

Do:
- `net.USER_AGENT` becomes the contact form Wikimedia's policy asks for
  (decision E) — name, contact URL, library version **D**
  ([policy](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits)).
- The network layer records, per lookup: urllib3 retries and their cause,
  `Retry-After` sleeps, requests over 10 s, pages fetched.
- When a cold lookup passes ~10 s, `report.notes` names **only causes measured
  in that lookup** — "SBN needed 7 connection retries", "Open Library took
  14.9 s to answer one request" — never a guess (decision K).

Gate — a run against a Wikimedia endpoint takes no 429 where today's agent takes
one; the slow-lookup note appears on a deliberately slowed run and is absent on
a fast one; no note names a cause that did not occur.

### Step 4 — Identify the work once

One resolver, one `Work`. The pieces are the tested ones:

- **Wikidata**: accept a candidate only when the query title matches (similarity
  ≥ 0.6, full or core title) one of its labels, sitelinks (disambiguator
  stripped) or P1476. Evidence: across 8 clusters it kept all 6 correct and
  rejected both wrong ones; on the corpus it **never accepted a wrong item** in
  91 entries and rejected all 6 wrong items today's resolver returns **M**.
- **SBN**, the guard exactly as tested: W = the highest-count
  `titolo_uniformef[]` value (adaptations excluded) for
  `{core: sbn, ANY: title, AUTHOR: author}`; **A** = title similarity between
  query and W; **B** = among the query's records whose catalogued title matches
  at ≥ 0.6, the share also present in `ANY + AUTHOR + W` (computed only when
  A < 0.6); **strong** A ≥ 0.6 or B > 0.5, **weak** B = 0.5, **rejected**
  otherwise. The author stays mandatory.
- **The second signal** (decision A): a refused or weak W is accepted when the
  Wikidata item accepted for the same entry has a label, sitelink or P1476
  matching W at ≥ 0.6.
- **Open Library**: search with the *original* title + author; the work keys, not
  the typed title. The spec's "highest edition count whose author matches" rule
  picks the author's most-printed book when the title is short (*1984* + Orwell
  → *Animal Farm*; *The Trial* + Kafka → *Metamorphosis*) **M**, so the title
  test comes first and the edition count only breaks ties.
- **The author**, through SBN's name authority: `core=autori` free text matches
  variant forms, and `item:5032:Nomi::@frase@=<id>` lists the person's records.
  One id per person for every Latin form **V/M**.
- **Romanisation and folding** (decisions B, G): non-Latin input is romanised
  before it is matched or sent; matching folds transliteration variants.

Costs to report: B cost 637 extra OPAC requests over 59 entries, max 151 **M**.
Where the free text is dropped (it never is now, under decision B), B pages the
whole author — that is what made N23 cost 151.

Gate — done when:
- every convergence set in `bench/corpus.json` resolves to its book's work at
  the strong tier or through the second signal, with the counts recorded;
- both generic titles are rejected and their header names neither *Canti* nor
  *Tutte le poesie*; *Tesi* and *Angelus Novus* get no original from SBN;
- the 7 second-signal rescues reproduce and no cross-book pair agrees;
- the gate counterexamples still fail after variant folding: *L'ordine delle
  notizie* vs *L'invenzione delle notizie*, *Quale socialismo, quale Europa*;
- no §9 case loses an edition, original or choice against the Step 1 baseline;
- the extra OPAC requests B costs are reported per case.

### Step 5 — List editions by identity

Today's record pull keeps the free-text title, so entry titles of one book get
different edition sets (*Cent'anni*: 89 via the Italian title, 13 via the
English, 143 via the original). The work removes the difference.

Do:
- For a **strong** work, list `{core: sbn, AUTHOR: author, W}` paged per
  language: read the `lingua[]` facet, then page each language, 20 rows a page.
  Every language page summed to the work total in A3 **V** — no records hide off
  the language pages.
- Take from each row: BID, catalogued title, main author, imprint (`infos[0]`),
  language (the page's code). No full record is needed to place a row.
- Open Library `editions.json?limit=1000` per work key, following `links.next`
  (N04's 1,179 editions paged correctly **M**).
- `infos[0]` is **not always the imprint** — 26 of 2,603 rows carry
  `Testo - Monografia […]`, `Fa parte di: …`, `3. ed`, `533 p` **M**. Parse
  defensively; the old note that only `infos[1]` is unreliable is wrong.
- Extend `langs._SBN`: at least **21 labels** are unmapped (`ALBANESE`,
  `RUMENO, MOLDAVO`, `TURCO MODERNO (DAL 1928)`, `UCRAINO`, and bilingual labels
  such as `ITALIANO - INGLESE` that name two languages) **M**.
- A failed language page reaches `Tally` as `SBN`; a bucket never shrinks
  silently.
- Keep `_language_contradicts_itself`: the OPAC language is the same field and
  carries the same error (`UBO4636099` is filed `jpn`).
- **The listing contains non-editions.** SBN links a York Notes study guide
  (`VIA0214939`), a Penguin Readers retelling (`TO10037839`) and the Meridiani
  collected volume (`TO02081267`) to their works **M**, and `tiporec[]` /
  `level[]` do not catch them. Do not pretend they are filtered; decide what the
  row says about them.

Gate — every convergence set shows the same work, original and language set from
each entry title; *Noise* / *Rumori* / *Bruits* + Attali each include
`RAV0708340` (fre 1977) and `LO10442107` (eng 1985); *Il nome della rosa* is no
longer starved; no 863.44 leak into *Cent'anni*; *Kafka*'s `UBO4636099` sits
under no span marked original; cold latency reported against the Step 1
baseline, with A2's 3.5 s median as the target.

### Step 6 — Recovery route beside the listing

The listing is incomplete by construction: SBN has not linked 334 same-work
records to W across the corpus, and Open Library keeps 98 editions in duplicate
work records **M**. Decision F keeps today's routes for exactly this.

Do:
- For a book **with** a strong work, run today's candidate routes (Wikidata
  title, author sweep, ISBN) beside the listing, and admit a record only when
  its brief title scores ≥ 0.6 against the **work's** titles and variants.
- The Wikidata-title route carries Step 4's rule: it brought 21 of the 44
  wrong-work leaks **M**.
- Mark recovered records in the report as reached outside the authority.
- **Drop the Open Library sibling probes**: 0 final editions from 512 candidates
  and 136 full fetches across 14 runs **M**.
- Keep the Dewey route and `_reverse_expand` for books with no work, unchanged,
  with their existing discipline (`_dewey_discriminates`, authorship agreement).

Measure before building: the yield and the leak rate of the title gate can be
computed offline on `results/stage-2/losses.json` — how many of the 334 + 98
same-work records it admits, and how many of the 44 leaks it lets through. Do
that first; it costs no network.

Gate — *Verso un'ecologia della mente* still includes `UFI0556368` (the sweep's
only unique find); the offline measurement is recorded; no case loses an
edition; the leak count against the Stage 2 judgements does not rise.

### Step 7 — Filter locally; details on expand

Do:
- Identity, original, earliest edition found and per-language counts are
  computed **unfiltered**.
- Language, year span and publisher apply to the lean list in the browser's
  hands. Changing a filter **re-filters; it does not rerun the lookup**
  (§5-4).
- Records with no parsable year stay out of a year-span filter and are counted
  in the hidden note. Open Library editions with **no language at all** (19.2%
  **M**) must not vanish from a language filter without being counted.
- The summary line says, from the unfiltered counts, how many editions in how
  many languages are hidden. Newest first, undated last. Editions stay grouped
  by language.
- Open Library details and buy links are fetched **when a row is expanded**
  (§5-3). SBN full records are not on this path — they arrive in the
  background (Step 9).

Gate — a filtered lookup shows the same original and earliest edition as the
unfiltered one; hidden counts equal unfiltered minus shown; a filter change
issues **no** new request; undated and language-less records are accounted for.

### Step 8 — The header: the original, and the earliest edition found

Do:
- Show the original (title, language, year) when a source states it, and
  **always** "earliest edition found — year, language, publisher", labelled as a
  statement about the catalogues.
- **No "first edition differs" inference** (decision D). Editions dated before
  the original's known year are left out of the earliest-edition line.
- No census. Say how many languages were found, with a fixed note that
  catalogues are incomplete (decision C).
- Uncertainty shows less, never something plausible: a refused work or a
  rejected Wikidata candidate means no original is shown.

Gate — on the 37 scored corpus books, the earliest-edition line reproduces
`results/stage-2/q4_earliest_found.json`: 22 exact, 9 right-year ties, 4 later
(original not listed), 2 partial, **0 older than the first edition**; the header
never names a wrong original; no "first edition differs" string exists in the
codebase.

### Step 9 — Edition rows: printings, background grouping, duplicate hint

Do:
- **One edition row per ISBN**, listing its printing years (decision I). SBN
  catalogues printings as separate records under one ISBN — 483 records with an
  ISBN fold into 297 rows **M**.
- **295 of 778 records have no ISBN** and stay one row per printing **M**. Do
  not group them from listing fields: that rule's precision is 0.425 **M**.
- The list shows at once; SBN full records are fetched **in the background**;
  rows fold as ISBNs arrive. The page states that grouping is in progress and
  that counts are provisional. **Nothing is streamed**, so the page carries no
  per-record progress.
- **The "possibly the same edition" hint** (decision H): a collision
  (same language, year, normalised publisher) across sources draws a red margin
  bracket between the two rows — always neighbours, since a collision shares
  language and year — with a tooltip giving the reason. Details on either row
  settles it: same ISBN → fold into one row with both sources; different ISBNs →
  the bracket goes; one side with no ISBN → the bracket stays. The language
  count includes both rows; a note under the list says how many pairs may be
  duplicates.
- **Never merge on a collision alone**: precision 0.656 **M**.

Open before building, and to be decided with the user: how the page learns that
grouping has ended when nothing is streamed — a second request, polling, or a
job id. See **UI to agree before building**.

Gate — the eight Stage 3 books reproduce `results/stage-3/q2_printings.json`'s
297 rows from 483 ISBN-bearing records; no two rows with different ISBNs are
ever merged; the bracket appears only where a collision survives with an ISBN
missing on one side; filters behave correctly on partly grouped rows (state what
was observed — this is untested today).

### Step 10 — Open Library duplicate work records

Do (decision J):
- Use the **main work** for the listing.
- **List** the duplicate work records — title and edition count on each row, so
  the reader can tell an omnibus from a duplicate — found by searching the
  original title plus each entry title (39 of 45 found; the original title alone
  finds 10) **M**.
- **Open** one by its work key: `/works/<key>/editions.json` (45 of 45 returned
  their editions; a bogus key 404s **V**). Never by re-searching its title: that
  returns the main work again 24 times of 33, and a different book 5 times **M**.
- Opening one **adds its editions to the language groups**, where they go through
  the same printing grouping and duplicate check.
- The page carries a hint of this workflow (see below).

Gate — the 45 duplicate works of the corpus are reached by key; the listed set
is reported with its precision measured by hand on at least one book (the
searches also return omnibus volumes and adaptations — untested today); opening
one changes the language counts and the note, not the page.

### Step 11 — Author mode: resolve the author first

Do:
- **Resolve the author before listing anything** (assessment §5.6): offer
  candidates pre-grouped by SBN's name authority, which gives one id per person
  for every Latin form **V/M**. Let the user select one or several, for variants
  of one person.
- VIAF is not used (decision C). Open Library's `resolve_author_keys` omits the
  main record for Murakami, Dostoevsky and Han **M**, so it does not lead.
- Rows are **works**, titled in their original language, sorted by original
  first-publication year, newest first, unknown last. Where only the earliest
  edition year is known, say so on the row.
- Sources by role: Open Library works for completeness, SBN's
  `titolo_uniformef[]` facet to group translations under their work, Wikidata for
  original titles and years.
- The SBN works facet stops at **50** items; report the truncation.
- Selecting a row runs the lookup with the original title and the author (UC3).

Evidence that variants converge once the author is pinned: author-only runs of
14 Latin variants gave the same rows — Murakami 1.0, Han 1.0,
Dostoevskij/Dostoevsky 1.0, García Márquez 0.98 **M**.

Gate — *Gregory Bateson* shows *Steps to an Ecology of Mind* once, with no
separate *Verso un'ecologia della mente* row; selecting a work yields the same
result as the title lookup of that work; truncation is visible in notes; the
candidate chooser is shown to the user before it is built.

### Step 12 — Correct the record (docs only)

Do: apply every item in **Where this plan corrects the record** to `HANDOFF.md`,
`README.md`, `CLAUDE.md` and the stale docstrings, including the benchmark's
corrections (F14, F7, F12, the non-Latin trap, the non-editions, `langs`, the
latency numbers and the Wikimedia cause). Add a line to
`docs/anatomy-of-a-lookup.html` saying it describes the machinery as of commit
`23ea2dc`. Delete `docs/Task.md` or mark it superseded — it is the benchmark
spec and no longer applies.

Gate — every listed item fixed or explicitly deferred to a named step; no code
changed.

---

## UI to agree before building

Three pieces the user asked to see first. Sketches, not markup.

### 1. "Possibly the same edition"

```
  English  ·  24 editions
  ┌─────────────────────────────────────────────────────────────────┐
 ┃│ Faber & Faber · London · 2021          [Details]        SBN     │
 ┃│                                                                 │
 ┃│ Faber and Faber · 2021                 [Details]   Open Library │
  └─────────────────────────────────────────────────────────────────┘
      ┃ possibly the same edition — same language, year and publisher;
        neither record shows an ISBN yet

  3 pairs in this list may be the same edition.
```

(The pair is a real Stage 3 false positive: Faber's two 2021 ISBNs for N06,
`9780571355884` and `…891` **M** — exactly the case the hint must survive.)

- The bracket (red, in the margin) spans exactly two neighbouring rows: a
  collision always shares language and year, so ordering puts them together.
- The tooltip gives the reason, and says which side is missing an ISBN.
- Opening Details on either row settles it, in place: same ISBN → one row, two
  source badges, bracket gone; different ISBNs → bracket gone, no note; one side
  with no ISBN → bracket stays, tooltip updates.
- Counts: the language count includes both rows. The note under the list is the
  only aggregate statement, and it says *may be*.
- Under decision I the bracket is short-lived by design. In this very sketch it
  is wrong and will go: once both full records arrive, the two Faber ISBNs
  differ. What survives is only the pair where one side has no ISBN at all —
  288 such collisions in Stage 3, precision unknown (U5).

### 2. "Grouping in progress"

```
  Editions · 143 rows · grouping printings …            (spinner, no percentage)
        counts are provisional until grouping ends
```

- No per-record progress: the server returns one JSON today and nothing is
  streamed (decision I, 2026-09-16). The line says what is happening, not how
  far along it is.
- When grouping ends the line is replaced by the settled count:
  `Editions · 97 editions · 143 printings`.
- **Open question for the user**, since nothing is streamed: how the page learns
  it ended. Three shapes, in order of how much they cost:
  a) **one extra request** when the lookup returns — the page asks once, after a
     fixed delay, and takes whatever is there;
  b) **polling** a status endpoint every second or two until it says done;
  c) **a job id**: the lookup returns an id immediately and the page fetches the
     result when the job reports finished.
  (a) is the smallest change and can be wrong if grouping takes longer than the
  delay; (c) is the honest one and changes the server's shape.

### 3. Duplicate records

```
  Open Library holds 3 more records for this work
       Doctor Zhivago            14 editions              [Add to the list]
       Doktor Živago              7 editions              [Add to the list]
       Doctor Zhivago             3 editions              [Add to the list]

  Adding one puts its editions into the language groups above.
```

(The book is E16, where Stage 2 found 3 duplicate work records holding 24
editions between them **M**; the per-row split here is illustrative.)

- Title and edition count on every row: the list is not clean — the same
  searches return omnibus volumes (*Animal Farm / Nineteen Eighty-Four*, 37
  editions) and adaptations, so the reader needs enough to judge **M**.
- The action is "add", not "open": the editions join the language groups and go
  through the same printing grouping and duplicate check (decision J).
- The hint line is the workflow explanation, one sentence, under the list.

---

## Guardrails

These hold in every step. They refine `CLAUDE.md`'s rules; they do not replace
them.

- **Identity comes first, from catalogue statements.** Inference (title match,
  ISBN, Dewey, reverse expansion) fills in where the catalogue is silent, and
  says so.
- **Uncertainty shows less, not something plausible.** A weak work, a rejected
  Wikidata candidate or an impossible year means no original is shown, rather
  than a guessed one.
- **One whitelist per SBN API.** The mobile gateway keeps `sbn.PARAMS` and
  ignores every facet filter. The OPAC API gets its own whitelist in `opac.py`:
  `core`, `page`, `item:1016:Any:@or@`, `item:1003:Autore:@and@`,
  `titolo_uniformef[]`, `lingua[]`, `tiporec[]`, `level[]`, `dataf[]`,
  `editoref[]`. Both ignore unknown keys silently. Every new key ships with a
  bogus-value control.
- **And a whitelist is not enough: the OPAC silently drops *values* it cannot
  use.** Free text in Cyrillic, Greek, Arabic, Chinese or Japanese is discarded
  and the unfiltered set comes back — `ANY` alone returns 21,806,046, and
  `ANY + AUTHOR` equals `AUTHOR` alone **V**. Send Latin script only, and prove
  a term was used with a control that must return 0.
- **The OPAC work query always carries the author.** Without it,
  `tutte le poesie` returns 84 records instead of 26.
- **A work is accepted through the guard or the second signal**, never by top
  facet count.
- **Uniform-title labels are search keys.** Displayed titles come from Open
  Library, Wikidata or SBN's catalogued title.
- **Filters never touch identity.** Original, earliest edition and counts are
  computed unfiltered.
- **A collision is never a merge.** Only a shared ISBN merges two rows.
- **An ISBN names an edition, not a printing** (in SBN, up to 31 records under
  one ISBN) **M**. A merged row lists its printing years; it does not hide them.
- **Every truncation is reported** in `report.notes`: fetch budgets, 50-item
  facet caps, page caps, unfinished background grouping.
- **Every swallowed failure reaches `Tally`**, including OPAC paging and the
  background fetches.
- **Keep `_language_contradicts_itself`.** The OPAC language field inherits the
  same error.
- The existing gate rules stand: re-check *L'ordine delle notizie* and *Quale
  socialismo, quale Europa* on any gate change — **including transliteration
  folding**; Dewey never identifies a work alone.

---

## Settled — evidence says no

Re-proposing any of these needs new evidence recorded here first.

| Idea | Evidence against |
|---|---|
| Fix cold latency in the network layer | IPv6 is not routable on this machine; forced IPv6 fails in < 1 ms. **Revised 2026-09-15**: the "Wikipedia stalls" were Wikimedia throttling, not the network layer — 101 retries on 429 over 110 runs, Wikimedia 35% of request time, 3.8% with a contact User-Agent **M**. The SBN half stands |
| Replace the author sweep with the work authority | SBN links are partial, corpus-wide: 334 same-work records not linked to W over 40 books **M**; `UFI0556368` is reachable only by the sweep |
| Drop the author from the work query | `tutte le poesie` 26 → 84 records, the extras being other poets |
| Pick the work by share of results, or top-vs-second dominance | Share: Bauman *Modernità liquida* correct at 0.48, *Angelus Novus* questionable at 0.43 |
| Loosen the work guard's B threshold to accept the classics | The known wrong works sit at B = 0.5, above every refused classic (≤ 0.375) **M**. The second signal (decision A) is the way in |
| Merge cross-source rows on a (language, year, publisher) collision | Precision 0.656; 0.664 under the strictest publisher rule, 0.636 under the loosest. All 43 false positives share a real publisher **M** |
| Group printings from listing fields instead of full records | Precision 0.425 **M** |
| Reach a duplicate Open Library work by searching its title | Returns the main work again 24 of 33, a different book 5 **M**. Fetch by work key **V** |
| VIAF as a coverage census | 20 of 37 books unusable, 13 split across clusters, results not relevance-ordered **V/M** |
| Infer "the first edition differs" from the listings | 8 false flags and 1 miss over 36 books **M** |
| Phrase or AND search via the operator suffix | `@or@`, `@and@`, `@frase@` and a bogus `@zzz@` return identical totals |
| Batch `full.json` | Every multi-BID form returns the same empty body as a bogus BID |
| Raise the OPAC page size | Six spellings ignored; 20 rows |
| Server-side year ranges | `dataf[]` accepts exact years only; three range syntaxes return 0 |
| Raise `ENRICH_BUDGET` to recover missing editions | At 400, *Il nome della rosa* gains 85 editions, but the cause is work records occupying gate slots |
| Open Library `translation_of` as a discovery route | Present on 3 of 35 Italian editions in cache (8.6%) |
| Remove `_reverse_expand` or the Dewey route | 0 of 14 runs reached them; the old corpus held almost no books SBN hasn't linked. Absence of cases is not evidence of no value |
| Loosen the gate to catch retranslations filed under a separate work | *Sul concetto di storia* is its own uniform title; no title or Dewey signal ties it to *Tesi di filosofia della storia*. A documented limit |
| Re-add Google Books | Keyless quota permanently exhausted; it contributed nothing |

---

## Verified facts

All on the OPAC API unless stated. Step 1 turns each row into a live test with
the control shown. "Re-checked" names the benchmark stage that ran it again.

| # | Fact | Numbers | Control | Re-checked |
|---|---|---|---|---|
| F1 | `titolo_uniformef[]` filters | *Cent'anni* work: 143 | bogus value → 0; bare `core=sbn` → 21,806,046 | Stage 1 **V** |
| F2 | Keeping `ANY` in the record pull returns the intersection | *Cent'anni* 89 vs 143; *Il nome della rosa* 232 = 232 | — | |
| F3 | The author term constrains generic works | `tutte le poesie` 26 with author, 84 without | — | |
| F4 | `lingua[]` filters, author kept | *Cent'anni* ita 90 / spa 22 / eng 12 | bogus → 0; `lingua[]=ita` alone → 11,197,305 | Stage 1 **V**: `lingua[]=zzqx` → 0 for all 32 works |
| F5 | Rows carry BID, `title.text`, `title.info`, `infos[]`; no ISBN, Dewey, holdings, translators | — | — | Stage 1 **M**: 98.4% of rows parse a year, 2,602/2,603 a publisher |
| F6 | A work lists without full fetches | 32 works in 469 requests, 0 failed | — | Stage 1 **M** |
| F7 | OPAC language = full-record `linguaPubblicazione` | **740 of 740 mapped records agree** | — | Stage 3 **M**. But `lookup.langs` maps **no code for 38 records under 21 labels** |
| F8 | `tiporec[]`, `level[]` filter | *Cent'anni* `a` 142 / `i` 1 | bogus → 0 | — |
| F9 | Page size is fixed at 20 | six spellings ignored | — | |
| F10 | `dataf[]` filters exact years; `editoref[]` exact values | `1996` → 8; `feltrinelli` → 21 | bogus → 0; ranges → 0 | |
| F11 | Facets cap at 50 items | `dataf[]`, `editoref[]`, `titolo_uniformef[]` for prolific authors | — | |
| F12 | A large minority of SBN full records lack an ISBN | **295 of 778 (38%)** over 8 books; E01 59/143 (41%). Open Library 252 of 1,405 (18%) | — | Stage 3 **M** |
| F13 | Mobile gateway `full.json` cannot batch | all multi-BID shapes → empty | bogus BID → skeleton body with no `codiceIdentificativo` | Stage 3 **V** |
| F14 | ~~Entry titles converge on one work~~ | **Holds for its 9 books only.** Over N01–N24 the guard withholds a correct work in **14 entries** (9 rejected, 5 weak); over the whole corpus SBN reaches the right identity for 22 of 37 books, and 23 of 91 entries reach none | — | Stage 1 **M** |
| F15 | **The OPAC silently drops non-Latin free text** | `ANY` alone → 21,806,046 (= bare `core=sbn`); `ANY + AUTHOR` = `AUTHOR` alone (Доктор Живаго 855 = 855, Ὀδύσσεια 8,818, بين القصرين 524, 活着 192, 海辺のカフカ 407). One exception: Преступление и наказание → 4 | a bogus **Latin** term → 0 | Stage 1 **V** |
| F16 | **SBN links non-editions to a work** | a York Notes study guide `VIA0214939`, a Penguin Readers retelling `TO10037839`, the Meridiani collected volume `TO02081267` — all linked to W; `tiporec[]`/`level[]` do not separate them | — | Stage 3 **M** |
| F17 | **One SBN ISBN spans printings of many years** | Adelphi `9788845906862` on 31 records, 1985–2026; Gallimard Folio `9782070360024` on 23. 361 of 499 ISBN-sharing pairs differ in year | — | Stage 3 **M** |
| F18 | **Wikimedia rate-limits by User-Agent** | today's agent: 102 × 429 of 180, exactly 10 successes then `retry-after: 14`; a contact URL: 0 of 180 | reversed order, same result | Stage 1 **M** + [policy](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits) **D** |
| F19 | **An Open Library work's editions are reachable by key** | `/works/<key>/editions.json` returned every known edition for 45 of 45 duplicate works | bogus key → 404 | Stage 3 **V** |

---

## Measured behaviour (benchmark, 2026-09-15)

These replace the 2026-09-14 instrumented figures.

| | Today's pipeline | Identity + listing |
|---|---|---|
| Cold wall per entry, median | **34.5 s** (p90 58.4, max 112.4) | **3.5 s** (p90 5.7, max 28.5) |
| Requests per entry, median | 192 | 19 |
| Slower in | — | 2 of 96 entries (N02 ita, N06 ita; causes recorded) |

- Request time by host, today's pipeline: SBN **55%**, Wikimedia **35%**, Open
  Library 10%. With the contact User-Agent, Wikimedia drops to **3.8%** **M**.
  (The 2026-09-14 figures — SBN 75.5%, Wikipedia 4.1% — were measured with other
  probes running.)
- Convergence, lowest overlap over a book's entry pairs: today median 0.658;
  identity **1.0 in 22 of 32 books**, and below 1 exactly where one entry's
  guard is not strong **M**.
- Noise floor: identical titles run cold give 1.0 on both paths, so the
  differences between entry titles are not run-to-run noise **V**.
- Full-record fetch cost (mobile gateway, one at a time, cold): 7 rows 1.5 s ·
  109 rows 25.3 s · 216 rows 102.3 s **M**.
- `CLAUDE.md` rule 10's "cold 35–50 s" understates the tail: p90 58.4 s, max
  112.4 s **M**.

---

## What is untested

Nothing in this list has been measured. It must not be written up anywhere as
though it had been.

| # | Untested | How it could be tested |
|---|---|---|
| U1 | **The slow-lookup notice** (decision K): whether the causes the network layer records are the ones that actually made a given lookup slow, and whether the ~10 s threshold fires usefully | instrument, then re-run a sample of the Stage 2 entries cold |
| U2 | **The recovery route's yield and leaks** (decision F): how many of the 334 + 98 same-work records a title gate admits, and how many of the 44 known leaks it lets through | offline on `results/stage-2/losses.json` — no network |
| U3 | **Transliteration folding** (decision G) against the gate counterexamples: *L'ordine delle notizie* vs *L'invenzione delle notizie*, *Quale socialismo, quale Europa* | offline, in the Step 1 pytest suite |
| U4 | **Background grouping** (decision I): the server has to report progress where it returns one JSON today; counts are provisional until it ends; **how the page learns grouping has ended with nothing streamed**; how filters behave on partly grouped rows; the background cost (~17 s for N10 at 6 at a time is **I**, extrapolated from 102.3 s one at a time) | build the three candidate shapes in §UI and measure one book each |
| U5 | **The duplicate hint's precision where an ISBN is missing** (decision H): 288 such collisions in Stage 3, precision **unknown**. The measured 0.656 covers only pairs where both sides have an ISBN | hand-judge a sample of the 288 against full records |
| U6 | **The duplicate-record list's precision** (decision J): the searches return omnibus volumes and adaptations beside true duplicates, and Stage 2's 98 editions are a lower bound | hand-judge the 42 extra author-matching results in `q3_duplicate_works.json` |
| U7 | The second signal's misses (N12, N17) that article stripping and romanisation might recover | offline on `results/stage-2/q1_second_signal.json` |
| U8 | Whether the 10 phantom `SBN partial` reports are cached error payloads | Step 2's instrumentation |

---

## The regression set

**`bench/corpus.json`** (40 books, version 2) plus the 16 cases in
`HANDOFF.md` §9. Structural assertions only — edition counts drift as the
catalogues are updated.

Per book the corpus carries: `original_title`, `authors`, `query_author`, the
entry titles with their language keys, and `ground_truth` — original title and
language, the original first edition (year, publisher, place, with the source
named per fact), which entries were actually published, and
`first_edition_differs`. Facts come from Wikipedia article text, national-library
records (SBN, LoC, BnF, DNB) or the publisher; **never from Wikidata**, which is
under test.

Known non-scoring items: E10 (*Opere*) and E11 (*Poesie*) are generic titles;
N23 is insights-only. They assert refusal behaviour.

Ground truth that is itself uncertain, and must not be asserted hard (from
`bench/RESULTS.md`, *Uncertain ground truth*): E16's first Russian *Živago*
(Mouton 1958 vs Feltrinelli 1957 vs the catalogues' Milano 1957), E02's first
publisher, E13's identity as a work, N04's 1867 publisher, N11's publisher,
N22's first Italian year, and the place of publication for ten books.

The convergence sets and single cases from the 2026-09-14 plan are all inside
the corpus as E01–E16; the corpus adds N01–N24. `HANDOFF.md` §9 case 1 (*Noise*
+ Attali) no longer exercises the no-Wikidata path: pick a replacement in Step 1
and say which case it is.

---

## Where this plan corrects the record

Until Step 12 lands, these override the documents named.

1. **"Facets cannot filter"** (`HANDOFF.md` §5, trap 05 in the walkthrough) is
   true of the mobile gateway only. OPAC facets filter (F1, F4, F8, F10).
2. **"No free catalogue records the link between a translation and its
   original"** is still asserted at `README.md:62`, `README.md:122`,
   `lookup/wikidata.py:4`, `lookup/openlibrary.py:5`, `lookup/pipeline.py:443`.
   It is false: SBN's uniform title records it.
3. **Cold-latency attribution** (`HANDOFF.md` §6/§8, `CLAUDE.md` rule 10):
   median 34.5 s, p90 58.4 s, max 112.4 s — not 35–50 s. SBN is 55% of request
   time, Wikimedia 35%, and the Wikimedia share is **throttling, not the network
   layer** **M**.
4. **`ENRICH_BUDGET = 150` rationale** predates the work authority.
5. **Wikidata's author check** does not stop a wrong work by the same author.
6. **Regression case 1** no longer tests the no-Wikidata path.
7. **§9 assertions can pass while a use case fails**: *Per una economia
   positiva* passes "exactly 1 Italian" with no original found.
8. **`CLAUDE.md` says fifteen regression cases**; the table holds sixteen — and
   the regression set is now `bench/corpus.json` plus those sixteen.
9. **`HANDOFF.md` §1 framing** (the Italian translation as the reason the tool
   exists) is superseded by **The aim** above. The no-verdict rule stands.
10. **`docs/anatomy-of-a-lookup.html`** describes the pipeline as of `23ea2dc`.
11. **F14 is not general** (above): entry titles converge for its 9 books, not
    for the corpus **M**.
12. **A guardrail was missing**: the OPAC drops non-Latin free-text *values*
    silently (F15) **V**. The old guardrail covered unknown keys only.
13. **`infos[0]` is not always the imprint** — 26 of 2,603 rows **M**. The old
    Step 6 warned about `infos[1]` only.
14. **`lookup.langs` is short by at least 21 SBN labels**, including bilingual
    ones **M**. The old Step 6 named `ALBANESE` alone.
15. **The listing includes non-editions** linked to W (F16) **M**.
16. **Assessment §3's VIAF census** and **§7's fallback-only inference routes**
    are both superseded — by decisions C and F.
17. **`docs/Task.md`** is the benchmark spec. The benchmark is done; it no
    longer applies.
