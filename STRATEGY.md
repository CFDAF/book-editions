# STRATEGY — authority-first lookup

The agreed plan of work for this project, derived from an audit on 2026-09-14
(tests with controls, instrumented pipeline runs, latency traces). It is the
single plan every session follows, so work stays on one line across sessions.

Read order: `CLAUDE.md` → **Session protocol** and **Status** below → the step
you are on → the sections of `HANDOFF.md` that step touches, with the
corrections in **Where this plan corrects the record** applied on top.

---

## The aim (the user's own specification — the source of truth)

Search a book and get **every edition of that book that exists**.

| Use case | Input | Result |
|---|---|---|
| UC1 | English title + author | The original first edition's title in its original language, then every later edition in every language — filterable by language, newest first, undated last |
| UC2 | Italian title + author | The same result as UC1 |
| UC3 | Original title (any language) + author | The same result as UC1 |
| UC4 | Author only | Every book by the author, as works titled in their original language, newest first. Selecting one reruns the lookup as UC3 |
| UC5 | Title only (less frequent) | Disambiguation between different *books* (not editions) sharing the title; if only one exists, a confirmation showing its first edition (author, year, publisher) |
| Filters | Year span, language, publisher on every lookup | Results arrive already filtered |

UC1–UC3 define **convergence**: the three entry titles of one book must reach
the same work, the same original, and the same edition set. Convergence is the
property most of this plan exists to deliver, and the regression suite tests it
directly.

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
| 2 | Correct the record (docs only) | todo | | |
| 3 | Stop caching error payloads | todo | | |
| 4 | Wikidata: a candidate must share a title with the query | todo | | |
| 5 | Resolve the work with the tested guard | todo | | |
| 6 | List the whole work from SBN, per language | todo | | |
| 7 | Filters apply before details | todo | | |
| 8 | Remove Open Library sibling probes | todo | | |
| 9 | Title-gate the author sweep when the work is resolved | todo | | |
| 10 | Author mode lists works | todo | | |
| 11 | Title-only disambiguation against UC5 | todo | | |

## Decision log

| Date | Decision | By |
|---|---|---|
| 2026-09-14 | Filters apply **before** per-edition details are fetched. The original, first edition and per-language counts are always computed unfiltered. Changing a filter reruns the lookup. | user |
| 2026-09-14 | Per-edition details (ISBN, holdings, translator, buy links) are fetched **upfront**, during the lookup — not on expand. | user |
| 2026-09-14 | Sessions stop after each step for review; all steps live in this document. | user |
| 2026-09-14 | The language filter **narrows** results (the aim, UC1). This supersedes the earlier "adds rather than narrows" filter, which was a build choice, not a user decision. | user (aim) |

---

## The strategy in brief

Today the lookup floods and filters: it sweeps SBN for everything the author
wrote, fetches up to 150 full records to learn their language, and throws most
of them away at a heuristic gate. The audit found that SBN already states which
work each record belongs to, and that its OPAC API can list a work's records per
language in ~20 records per request without any full-record fetch.

So the lookup becomes **authority-first**:

1. Resolve the work — SBN's uniform title, accepted only through a tested guard;
   Wikidata candidates only when they share a title with the query.
2. List the whole work from SBN per language (this is what makes UC1–UC3
   converge), then filter, then fetch details for what is shown.
3. Keep the inference routes (title match, ISBN, Dewey, reverse expansion) for
   books SBN has not linked, and cut the routes that measured zero yield.

Speed and accuracy are the same lever here: 75% of cold request time is SBN
full-record fetches, and the authority route avoids most of them.

---

## The steps

### Step 1 — Safety net: tests, baseline, API-fact checks

Every later step changes what reaches the gate. Nothing below is safe to do
without a way to see what changed.

Do:
- Offline `pytest` for the pure functions `HANDOFF.md` §9 names
  (`matching.py`, `langs.py`, `sbn.py` parsers, `_dewey_affinity`,
  `_identifies`, `_dewey_discriminates`, `_assign_groups`, `_span_is_original`,
  `_origin_phrase`), plus the gate's counterexamples as hand-built `Edition`s:
  *L'ordine delle notizie*, *Quale socialismo, quale Europa*, and the 863.44
  García Márquez set.
- A live regression runner covering `HANDOFF.md` §9 plus **New regression
  cases** below. It asserts **structure only** (languages present, original
  title/language/year, number of choices, named BIDs present or absent, source
  states), never exact totals.
- Live API-fact tests: one test per row of **Verified facts**, each with its
  bogus-value control. These tell a later session the catalogue drifted
  *before* it builds on a stale fact.
- Run everything on the **unchanged** code. Commit a baseline snapshot (the
  structural fields only) under `tests/baseline/`, and list every case that
  fails today as **known-red** in this step's Status row.

Gate — done when:
- offline tests pass;
- the live runner completes every case and the baseline is committed;
- the known-red list is recorded. Expected known-reds, which must actually be
  observed rather than assumed: most convergence sets (edition sets differ by
  entry title); *Per una economia positiva* with no original (seen without the
  author; check with it); *Tesi di filosofia della storia* headed by the wrong
  work. Also observe whether *Opere* + Leopardi
  is headed by *Canti* (suspected, not yet observed).

### Step 2 — Correct the record (docs only)

Stale statements are what would push a future session into a wrong decision.

Do: apply every item in **Where this plan corrects the record** to `HANDOFF.md`,
`README.md`, `CLAUDE.md` and the stale docstrings. Add a line to
`docs/anatomy-of-a-lookup.html` saying it describes the machinery as of commit
`23ea2dc`.

Gate — done when every listed item is fixed, or explicitly marked as fixed later
by a named step; no code changed.

### Step 3 — Stop caching error payloads

`net.cached_get_json` and `cached_post_json` write any valid JSON to disk;
`sbn._request` only raises afterwards. A Solr error on a Japanese-script
Wikidata title variant was cached and replayed for 24h (observed on the
*Kafka sulla spiaggia* run). `opac._post` has the same shape for a payload with
no `data` object.

Do: make the cache refuse a payload its caller rejects — a validation hook in
`net.py`, used by `sbn._request` (an `error` key) and `opac._post` (no `data`
object). Failures still raise `SourceError` and still reach `Tally`.

Gate — done when a test with a faked error payload leaves no cache file, and a
replayed request after a transient error goes back to the network.

### Step 4 — Wikidata: a candidate must share a title with the query

`wikidata.resolve` takes the first candidate that is a written work and does not
contradict the author. Author agreement cannot separate one author's works:
*Tesi di filosofia della storia* + Walter Benjamin resolves to *Das Kunstwerk im
Zeitalter seiner technischen Reproduzierbarkeit*; *Angelus Novus* + Benjamin to
*Über den Begriff der Geschichte*. The cluster drives the header's original
title, language and year, so this is the project's core failure shape: a
confident wrong answer.

Do: accept a candidate only when the query title matches (title similarity ≥ 0.6,
full or core title) one of its labels, sitelinks (disambiguator stripped) or
P1476 original title. Otherwise try the next candidate; with none left, return
no cluster.

Evidence: across 8 clusters, the rule kept all 6 correct ones and rejected both
wrong ones. *Kafka sulla spiaggia* stays because its Italian label matches,
although P1476 is `海辺のカフカ`.

Keep: labels are fetched for `it|en|fr|es|de|pt|la`. A romanised original title
(*Umibe no Kafuka*) will find no label and lose its cluster. That degrades to
the SBN route (which resolves it, see Step 5) and is acceptable; record the
outcome rather than widening the title test.

Gate — done when both Benjamin queries carry no Wikidata cluster; the 6 correct
clusters are unchanged; no §9 case loses its original.

### Step 5 — Resolve the work with the tested guard

`opac.work_for` takes the uniform title with the most records, unguarded. For
generic titles that is a different book (*Opere* + Leopardi → `canti`;
*Poesie* + Montale → `tutte le poesie`).

Do — the guard, exactly as tested:
- W = the highest-count `titolo_uniformef[]` value (adaptations excluded) for
  `{core: sbn, ANY: title, AUTHOR: author}`.
- **A** = title similarity between the query and W (max of full and core title).
- **B** = among the query's records (all pages of `ANY + AUTHOR`) whose
  catalogued title matches the query at ≥ 0.6, the share also present in
  `ANY + AUTHOR + W`. Compute B only when A < 0.6.
- **strong** when A ≥ 0.6 or B > 0.5; **weak** when B = 0.5 exactly;
  **rejected** otherwise (`work_for` returns None).
- `work_for` returns the tier with the work. The author stays mandatory.

Evidence (13 books, 25 entry titles):

| Entry | A | B | Tier |
|---|---|---|---|
| 21 entry titles of 9 books (Italian, English, original) | 1.00 or 0.00 | 0.54–1.00 when A = 0 | strong (each book's titles converge on one work) |
| *Tesi di filosofia della storia* + Benjamin → `uber den begriff der geschichte` | 0.00 | 1/2 = 0.50 | weak |
| *Angelus Novus* + Benjamin → `schriften` | 0.00 | 9/18 = 0.50 | weak |
| *Poesie* + Montale → `tutte le poesie` | 0.50 | 0/45 | rejected |
| *Opere* + Leopardi → `canti` | 0.00 | 1/58 | rejected |

Closest calls to watch: *The Name of the Rose* (English entry, Italian original)
at B = 0.54; *Poesie* at A = 0.50.

In this step, strong and weak both keep today's record pull (the intersection
`ANY + AUTHOR + W`). Only the rejected tier changes behaviour. The pipeline's
own phase 4b (`_expand_uniform_title`) builds a cluster from **strong** works
only.

Gate — done when:
- every entry title in **Convergence sets** resolves to its book's work at the
  strong tier;
- both generic titles are rejected and their header names neither *Canti* nor
  *Tutte le poesie*;
- *Tesi* and *Angelus Novus* are weak and get no original from SBN;
- no §9 case loses an edition, original or choice compared with the baseline;
- the extra OPAC requests B costs are reported per case.

### Step 6 — List the whole work from SBN, per language

Today's record pull keeps the free-text title, so it returns only records that
match the typed title. Entry titles of one book therefore get different edition
sets (*Cent'anni*: 89 via the Italian title, 13 via the English, 143 via the
original). The whole work removes that difference.

Do:
- For a **strong** work, list `{core: sbn, AUTHOR: author, W}` paged per
  language: first read the `lingua[]` facet, then page each language with
  `lingua[]=<code>`, 20 rows a page.
- Take from each row: BID, catalogued title (`title.info`, before ` / `), main
  author (`title.text`), imprint (`infos[0]`), language (the page's
  `lingua[]` code). These records need no full-record fetch to be members or to
  be placed in a language.
- Medium: use the `tiporec[]` / `level[]` facets as filters (MARC codes: `a` =
  text, `i` = non-musical sound; `level` `m` = monograph, `a` = analytic). Do not
  parse `infos[1]`: its position is not fixed ("Fa parte di…" lines occupy it).
  Before relying on the MARC-to-`NON_BOOK_MEDIA` mapping, verify each code
  against a real record.
- Imprints carry sorting markers — `\1977!`, `\Manchester! : …`, `c1978,,
  stampa 1977` — so verify `sbn.parse_publication` on these, or extend it.
- Split the fetch budget in two: **gate** fetches (candidates still needing a
  verdict: ISBN, Wikidata-title, query-title, sweep) and **detail** fetches
  (work records already admitted, fetched upfront per the decision log). Gate
  fetches go first. Report any overflow of either in `report.notes`.
- A failed language page reaches `Tally` as `SBN`, so the source degrades to
  `partial`. A bucket never shrinks silently.
- Add `ALBANESE` and any other missing names to `langs._SBN` and display names.
- Keep `_language_contradicts_itself`. The OPAC language is the same field and
  carries the same error (`UBO4636099` is filed `jpn`). The row title keeps its
  statement of responsibility, so `TRANSLATED_FROM` still reads it.

Gate — done when:
- every convergence set shows the same work, original and language set from
  each entry title;
- *Noise* / *Rumori* / *Bruits* + Attali each include `RAV0708340` (fre 1977)
  and `LO10442107` (eng 1985), and the Italian list is still exactly *Rumori*
  `RAV0064979`;
- *Il nome della rosa* is no longer starved (report detail fetches vs admitted
  records);
- no 863.44 leak into *Cent'anni*; *Kafka*'s `UBO4636099` sits under no span
  marked original;
- cold latency is reported against the Step 1 baseline.

Stop and ask if detail fetches for large works push cold latency past the
baseline. A budget change is the user's decision.

### Step 7 — Filters apply before details

Do:
- Resolve identity, original, first edition and per-language counts
  **unfiltered**.
- Apply language, year span and publisher to admitted records **before** detail
  fetches. For SBN work records, language comes from the page and year and
  publisher from the parsed imprint. Open Library editions are filtered locally.
- The OPAC `lingua[]` filter may narrow the SBN listing itself. Year and
  publisher stay local: there is no year-range syntax (`dataf[]` accepts exact
  years only), and publisher values are normalised and split (`feltrinelli`,
  `a. mondadori`, `oscar mondadori`, `mondadori`).
- Records with no parsable year are kept out of a year-span filter and counted
  in the hidden note.
- UI: every filter narrows and reruns the lookup. The summary line says, from
  the unfiltered counts, how many editions in how many languages are hidden.
  Newest first, undated last.

Gate — done when:
- a filtered lookup shows the same original and first edition as the unfiltered
  one;
- the hidden counts equal unfiltered minus shown;
- detail fetches drop in proportion to the filter (report *Cent'anni* with
  `language=ita`, and with a decade span).

### Step 8 — Remove Open Library sibling probes

Evidence: across 14 runs, **0** final editions from 512 candidates and 136 full
fetches. The gate can only admit a sibling hit through the Dewey set test.
Removes 1 Open Library search and up to 10 SBN searches per lookup.

Do: remove `ol.italian_siblings`, `SIBLING_PROBES`, the `"Open Library sibling"`
reason and its prescore bonus, and update the docstrings that describe them.

Gate — done when *Per una economia positiva* still has exactly 1 Italian edition
and no case loses an edition compared with the Step 7 output.

### Step 9 — Title-gate the author sweep when the work is resolved

Evidence: 2,656 sweep candidates, 662 full fetches, **2** final editions across
14 runs. Both passed on title (≥ 0.6), not Dewey: `RAV0708340` (now reached by
Step 6) and `UFI0556368` (*Steps to an Ecology of Mind*, eng 1972, **not**
linked to its work in SBN — only the sweep finds it). A retranslation filed
under a separate work (*Sul concetto di storia*) is missed today even with the
full sweep, so title-gating loses nothing observed.

Do: when Step 5 returns a **strong** work, enrich sweep candidates only if their
brief title scores ≥ 0.6 against the variants. When the work is weak or
rejected, the sweep behaves as today: it is the Dewey route's only feed for
books SBN has not linked.

Gate — done when *Verso un'ecologia della mente* still includes `UFI0556368`;
sweep full fetches are reported before and after; no case loses an edition.

### Step 10 — Author mode lists works

Today author mode keys rows by normalised title, so a translation and its
original become separate rows.

Do:
- Rows are **works**, titled in their original language, sorted by original
  first-publication year (newest first, unknown last). Where only the earliest
  edition year is known, say so on the row.
- Sources, by role:
  - Open Library works give completeness (up to `AUTHOR_WORK_LIMIT`).
  - SBN's `titolo_uniformef[]` facet over the author's records groups
    translations under their work.
  - Wikidata works (MediaWiki API search `haswbstatement:P50=<author QID>`,
    keeping only `P31` work classes and excluding edition items `Q3331189`)
    supply original titles and years where they exist.
- The SBN works facet stops at **50** items (Attali, García Márquez). Splitting
  the query by `lingua[]` recovers only part of the rest (García Márquez
  50 → 61), and the Italian subset alone hits 50. Report the truncation;
  Open Library carries the tail.
- Facet labels are search keys. Display titles come from Open Library, Wikidata
  or SBN catalogued titles.
- Selecting a row runs the lookup with the original title and the author (UC3).

Gate — done when:
- *Gregory Bateson* shows *Steps to an Ecology of Mind* once, with no separate
  *Verso un'ecologia della mente* row;
- selecting a work yields the same result as the title lookup of that work
  (convergence);
- truncation is visible in notes.

Stop and ask before building the UI: show the user the row layout, including
the non-Latin original case (`海辺のカフカ`).

### Step 11 — Title-only disambiguation against UC5

Do: check title-only lookups against UC5 — choices are distinct works, and a
single work gets a confirmation carrying its first edition (author, year,
publisher). *Noise* (4 books) is the existing multi-work case. Close the gaps
found; where a gap needs a UX decision, stop and ask.

Gate — done when *Noise* offers its works and picking one reruns the lookup as
title + author, converging with UC1; a single-work title shows the confirmation.

---

## Guardrails

These hold in every step. They refine `CLAUDE.md`'s rules; they do not replace
them.

- **Identity comes first, from catalogue statements.** Inference (title match,
  ISBN, Dewey, reverse expansion) fills in where the catalogue is silent.
- **Uncertainty shows less, not something plausible.** A weak work, a rejected
  Wikidata candidate or an impossible year means no original is shown, rather
  than a guessed one.
- **One whitelist per SBN API.** The mobile gateway (`opacmobilegw`) keeps
  `sbn.PARAMS` and **ignores every facet filter**. The OPAC API
  (`/o/opac-api/titles-search-full-post`) gets its own whitelist in `opac.py`:
  `core`, `page`, `item:1016:Any:@or@`, `item:1003:Autore:@and@`,
  `titolo_uniformef[]`, `lingua[]`, `tiporec[]`, `level[]`, `dataf[]`,
  `editoref[]`. Both APIs silently ignore unknown keys; the OPAC ignored six
  page-size spellings. Every new key ships with a bogus-value control test.
- **The OPAC work query always carries the author.** Without it,
  `tutte le poesie` returns 84 records instead of 26: other poets' books.
- **A work is accepted through the Step 5 guard**, never by top facet count.
- **Uniform-title labels are search keys.** Displayed titles come from Open
  Library, Wikidata or SBN's catalogued title.
- **Filters never touch identity.** Original, first edition and counts are
  computed unfiltered.
- **Every truncation is reported** in `report.notes`: fetch budgets, 50-item
  facet caps, page caps.
- **Every swallowed failure reaches `Tally`**, including OPAC paging.
- **Keep `_language_contradicts_itself`.** The OPAC language field inherits the
  same error.
- The existing gate rules stand: re-check *L'ordine delle notizie* and *Quale
  socialismo, quale Europa* on any gate change; Dewey never identifies a work
  alone.

## Settled — evidence says no

Re-proposing any of these needs new evidence recorded here first.

| Idea | Evidence against |
|---|---|
| Fix cold latency in the network layer (force IPv4, Happy Eyeballs) | IPv6 is not routable on this machine (link-local only); forced IPv6 fails in < 1 ms. The Wikipedia stall appeared in 1 of 4 cold runs. SBN is 75.5% of request time. |
| Replace the author sweep with the work authority | SBN links are partial: *Steps to an Ecology of Mind* has 31 title matches but 26 work-linked records; `UFI0556368` is reachable only by the sweep. |
| Drop the author from the work query | `tutte le poesie` 26 → 84 records, the extras being other poets. |
| Pick the work by share of results, or top-vs-second dominance | Share: Bauman *Modernità liquida* is correct at 0.48, *Angelus Novus* questionable at 0.43. Dominance: *Angelus* 9.0 > Bauman 4.3. |
| Phrase or AND search via the operator suffix | `@or@`, `@and@`, `@frase@` and a bogus `@zzz@` return identical totals. |
| Batch `full.json` | Every multi-BID form returns the same empty body as a bogus BID; `bids` is ignored. |
| Raise the OPAC page size | Six spellings (`rows`, `size`, `pageSize`, `limit`, `perPage`, `page_size`) all ignored; 20 rows. |
| Raise `ENRICH_BUDGET` to recover missing editions | At 400, *Il nome della rosa* gains 85 editions, but the cause is work records occupying gate slots; Step 6 splits the budget instead. |
| Open Library `translation_of` as a discovery route | Present on 3 of 35 Italian editions in cache (8.6%). Useful at most as a verification signal. |
| Remove `_reverse_expand` or the Dewey route | 0 of 14 runs reached them, because the corpus holds almost no books SBN hasn't linked. Absence of cases is not evidence of no value. |
| Loosen the gate to catch retranslations filed under a separate work | *Sul concetto di storia* is its own uniform title; no title or Dewey signal ties it to *Tesi di filosofia della storia*. It is a documented limit. |
| Server-side year ranges | `dataf[]` accepts exact years only; three range syntaxes return 0. |

---

## Verified facts

All on the OPAC API unless stated. Step 1 turns each row into a live test with
the control shown.

| # | Fact | Numbers | Control |
|---|---|---|---|
| F1 | `titolo_uniformef[]` filters | *Cent'anni* work: 143 | bogus value → 0; bare `core=sbn` → 21,806,046 |
| F2 | Keeping `ANY` in the record pull returns the intersection | *Cent'anni* 89 vs 143 (0 lost); *Rumori* 1 vs 3; *Il nome della rosa* 232 = 232 | — |
| F3 | The author term constrains generic works | `tutte le poesie` 26 with author, 84 without | — |
| F4 | `lingua[]` filters, author kept | *Cent'anni* ita 90 / spa 22 / eng 12 | bogus → 0; `lingua[]=ita` alone → 11,197,305 |
| F5 | Rows carry BID, `title.text` (main author), `title.info` (title / responsibility), `infos[]` (imprint first); no ISBN, Dewey, holdings, translators | — | — |
| F6 | A work lists without full fetches | *Cent'anni* 143 records, 18 languages, 24 requests; *Noise* 3 records, 4 requests | — |
| F7 | OPAC language = full-record `linguaPubblicazione` | 130 / 131 agree (the one: `ALBANESE` unmapped in `langs.py`); `UBO4636099` filed `jpn` in both | — |
| F8 | `tiporec[]`, `level[]` filter | *Cent'anni* `a` 142 / `i` 1; `m` 142 / `a` 1 | bogus → 0 |
| F9 | Page size is fixed at 20 | six spellings ignored | — |
| F10 | `dataf[]` filters exact years; `editoref[]` exact values | `1996` → 8; `feltrinelli` → 21 | bogus → 0; ranges → 0 |
| F11 | Facets cap at 50 items | `dataf[]`, `editoref[]`, and `titolo_uniformef[]` for prolific authors | — |
| F12 | 43% of SBN full records lack an ISBN | 56 / 131 (*Cent'anni*) | — |
| F13 | Mobile gateway `full.json` cannot batch | all multi-BID shapes → empty | bogus BID → same empty body |
| F14 | Entry titles converge on one work | 21 entry titles, 9 books | — |

## Measured pipeline behaviour (current code, 2026-09-14)

Instrumented runs over 14 regression queries, warm cache:

| Route | Candidates | Full fetches | Final editions |
|---|---|---|---|
| SBN work authority | 592 | 509 | 148 |
| Wikidata title | 290 | 106 | 56 |
| ISBN match | 39 | 13 | 9 (2 reachable by no other route) |
| Query title | 67 | 63 | 7 |
| Open Library sibling | 512 | 136 | **0** |
| Author sweep | 2,656 | 662 | **2** |
| Same Open Library work | — | — | 350 |

- 5 of 14 runs exceed the 150-fetch budget; in *Il nome della rosa* all 150
  slots went to work-authority records.
- `_expand_uniform_title` ran 7/14 (a cluster found in 6); `_reverse_expand` 0/14.
- Cold latency, 4 runs with a fresh cache: 45 s, 70 s, 99 s, 111 s. Request
  time by host: `opac.sbn.it` 75.5% (644 requests, ~1.5 s each), Open Library
  20.2%, Wikipedia 4.1%, Wikidata 0.2%. Other probes were running concurrently,
  so absolute numbers lean pessimistic; the ranking holds.

---

## New regression cases

Add to `HANDOFF.md` §9 in Step 1. Structural assertions only.

### Convergence sets (UC1–UC3)

Each row's entry titles must reach the same SBN work, original and language set.

| Book | Author | Entry titles | SBN work |
|---|---|---|---|
| Cent'anni | García Márquez | *Cent'anni di solitudine* · *One Hundred Years of Solitude* · *Cien años de soledad* | `cien anos de soledad` |
| Ecology of Mind | Bateson | *Verso un'ecologia della mente* · *Steps to an Ecology of Mind* | `steps to an ecology of mind` |
| Noise | Attali | *Rumori* · *Noise* · *Bruits* | `bruits : essai sur l'economie politique de la musique` |
| Kafka | Murakami | *Kafka sulla spiaggia* · *Kafka on the Shore* · *Umibe no Kafuka* | `umibe no kafuka` |
| Invention of News | Pettegree | *L'invenzione delle notizie* · *The Invention of News* | `invention of news` |
| Brilliant | Eshun | *Più brillante del sole* · *More Brilliant Than the Sun* | `more brilliant than the sun` |
| Liquid Modernity | Bauman | *Modernità liquida* · *Liquid Modernity* | `liquid modernity.` |
| Matrice | Ruesch | *La matrice sociale della psichiatria* · *Communication: The Social Matrix of Psychiatry* | `communication: the social matrix of psychiatry.` |
| Name of the Rose | Eco | *Il nome della rosa* · *The Name of the Rose* | `nome della rosa` |

### Single cases

| Case | Expected | Why it exists |
|---|---|---|
| *Opere* + Leopardi | work rejected; header does not name *Canti* | generic title |
| *Poesie* + Montale | work rejected; header does not name *Tutte le poesie* | generic title |
| *Tesi di filosofia della storia* + Walter Benjamin | weak work; no Wikidata cluster; header names no wrong work | Wikidata same-author mis-pick; B tie |
| *Angelus Novus* + Walter Benjamin | weak work (`schriften`); no expansion; no Wikidata cluster | anthology vs collected works; B tie |
| *Verso un'ecologia della mente* | `UFI0556368` (eng 1972) present | the sweep's only unique find |
| *Per una economia positiva* + Jacques Attali | observed **without** the author: no original, 1 Italian, "earliest edition found 2014". Observe with the author in Step 1. Target: the French original, if Open Library holds it — verify first | a translation SBN has not linked; the only case for the fallback routes |
| *Modernità liquida* + Zygmunt Bauman | resolves to `liquid modernity.` | kills share thresholds (0.48) |
| *The Name of the Rose* + Eco | strong work at B ≈ 0.54 | closest strong call |
| *Umibe no Kafuka* + Murakami | same result as *Kafka sulla spiaggia*, through SBN if Wikidata finds no label | Step 4 caveat |
| *Kafka sulla spiaggia* + Murakami, cache poisoning | a Solr error payload is not cached | Step 3 |
| *Tesi di filosofia della storia* + Benjamin, retranslation | BIDs `TO01637306`, `CAG1888071`, `UFE1075470`, `TO00566017` (*Sul concetto di storia*) absent | documents a known limit; must stay honest, not be "fixed" by loosening |

`HANDOFF.md` §9 case 1 (*Noise* + Attali) no longer exercises the no-Wikidata
path: Wikidata now resolves it (`Q7047658`). Pick a replacement for that path
in Step 1, and say which case it is.

---

## Where this plan corrects the record

Until Step 2 lands, these override the documents named.

1. **"Facets cannot filter"** (`HANDOFF.md` §5, trap 05 in the walkthrough) is
   true of the mobile gateway only. OPAC facets filter (F1, F4, F8, F10).
2. **"No free catalogue records the link between a translation and its
   original"** is still asserted at `README.md:62`, `README.md:122`,
   `lookup/wikidata.py:4`, `lookup/openlibrary.py:5`, `lookup/pipeline.py:443`.
   It is false: SBN's uniform title records it; Open Library editions carry
   `translation_of` on a minority of records.
3. **Cold-latency attribution** (`HANDOFF.md` §6/§8, `CLAUDE.md` rule 10):
   dominated by SBN full fetches, not a Wikipedia stall; measured 45–111 s
   cold, not 35–50 s.
4. **`ENRICH_BUDGET = 150` rationale** predates the work authority: at 150,
   work-linked records crowd out every other route on large works.
5. **Wikidata's author check** does not stop a wrong work by the same author.
6. **Regression case 1** no longer tests the no-Wikidata path.
7. **§9 assertions can pass while a use case fails**: *Per una economia
   positiva* passes "exactly 1 Italian" with no original found.
8. **`CLAUDE.md` says fifteen regression cases**; the table holds sixteen.
9. **`HANDOFF.md` §1 framing** (the Italian translation as the reason the tool
   exists) is superseded by **The aim** above. The no-verdict rule stands.
10. **`docs/anatomy-of-a-lookup.html`** describes the pipeline as of `23ea2dc`.
