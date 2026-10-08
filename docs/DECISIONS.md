# DECISIONS — why the lookup is the way it is

The one record of how this project was decided: the aim, the timeline, every
decision with the number that decided it, the verified facts, the traps, what
was discarded, and the thresholds. It replaces the development evidence (the
benchmark, its results, the build plan and its log), which is not part of the
release. **IDs are stable — the code cites them** (`decision AN`, `F15`,
`build rule 11`, `U2`).

Evidence tags: **V** verified with a control · **M** measured · **I** inferred.
Catalogues drift, so a count here is what was measured on its date, not a
promise. Book ids: **E01–E16, N01–N24** are the 40-book corpus (three entry
titles each where they exist: original, English, Italian); **H…** the 16 hand-written
regression cases; **P01–P09** the author-mode people. Six books
were held out of tuning (decision O).

---

## 1. The aim

Search a book and get **every edition of that book that exists** (the user's
own specification).

| Use case | Input | Result |
|---|---|---|
| UC1 | English title + author | The original first edition's title in its original language, then every later edition in every language, filterable by language, newest first, undated last |
| UC2 | Italian title + author | The same result as UC1 |
| UC3 | Original title + author, Latin script (another script is typed romanised) | The same result as UC1 |
| UC4 | Author only | Every book by the author, as works titled in their original language. The author is resolved first; picking a work reruns as UC3 |
| UC5 | Title only | Dropped 2026-09-14, restored by decision AN: adopt the one author the sources agree on, else a chooser of books and no list |
| Filters | Year span, language, publisher | Applied locally to the list in hand; no request |

UC1–UC3 define **convergence**: the three entry titles of one book must reach
the same work, original and edition set. No source hands that over (A1 below),
so it is a target, measured.

**The header is a publication history, not a verdict.** The first version led
with *"Translated into Italian."*; the user rejected it outright: it answers
one narrow question and buries what the editions say. A yes/no hero is a
regression in intent.

Completeness has no denominator (no source can say how many editions exist),
so it was made operational: **reach** every record the endpoints hold for the
work, **precision** (no wrong-work record in the default view), **disclosure**
(say what is missing and what was refused). Latency is last, and is met by
staging rather than optimisation: the list first, the expensive work behind it.

---

## 2. Timeline

| Date | What |
|---|---|
| 2026-09-12 | First version: a CLI script, then a server and page. Open Library, Wikidata, Google Books and SBN's mobile gateway; a Dewey class as the cross-language bridge. SBN's second API (the OPAC) found the same day to carry the work link the project had recorded as absent, and added as a fourth bridge |
| 2026-09-14 | **Assessment** against the aim: keep the sources, rebuild the lookup's core. Searching by the typed title is why the three entry titles of one book give different lists and why a cold lookup takes about a minute. First decisions (§5-1 to §5-7) |
| 2026-09-14/15 | **Benchmark**, three stages, 40 books, 91 scored entry runs, eight assumptions A1–A8: four pass, four fail (below) |
| 2026-09-16 | **Strategy revision** on the benchmark: decisions A–K. **Rebuild proposal**: one store, several producers, versioned snapshots; `catalog/ core/ lookup/stages.py app/` |
| 2026-09-17 | Steps 1A, 1B: fixture replay, the offline suite. Six books held out |
| 2026-09-18 | Steps 1C–4: live regression runner and baseline; the title gate measured; error payloads no longer cached; contact User-Agent and the request ledger |
| 2026-09-21/22 | Steps 5–8: the model and store; S1 identify; S2 list; the job-id transport |
| 2026-09-23/24 | Steps 9–12: S3 recovery; local filters; header, coverage ledger, loose-match band; S4 background enrich |
| 2026-09-25/26 | Steps 13–15: Open Library duplicate records; author mode; the held-out check |
| 2026-09-27/28 | Step 16 failed its gate (old path 24 red, new 85); Step 15B closed the gap; the old path deleted (one tree); Step 17 corrected the record. **Build finished 2026-09-28** |
| 2026-09-29 → 10-06 | Post-build, from the backlog: decisions AV–BD, imprint-parser fixes, Wikidata date precision |
| 2026-10-07 | Release: evidence kept privately, this log written |

**What the benchmark established** (2026-09-15, all fitted: the six were held
out later).

| # | Assumption | Result |
|---|---|---|
| A1 | Every entry title + author reaches one identity | **FAIL** in every source. Books whose every entry reaches the right identity: SBN 22/37, Wikidata 14/37, Open Library 13/37. Of 91 entries SBN is right on 68, **wrong on 0**, none on 23 |
| A2 | Listing by identity loses nothing | **PASS**, no unexplained loss: it drops 334 SBN same-work records not linked to the work and 98 Open Library editions in duplicate work records. Cold median 34.5 s → **3.5 s**, requests 192 → 19 |
| A3 | Listing rows are enough to filter | **PASS**: SBN 2,561/2,603 rows with a parsable year (98.4%); Open Library 98.1% dated, language 80.8% |
| A4 | Duplicates can be found by a (language, year, publisher) collision | **FAIL**: precision 82/125 = 0.656 where both sides have an ISBN |
| A5 | Original vs first edition is detectable from listings | **FAIL**: Wikidata's original wrong in 3 of 26 accepted items; 8 false "first edition differs" flags and 1 miss over 36 books |
| A6 | VIAF can state coverage | **FAIL** for 20 of 37 books (13 census smaller than what was found, 7 no cluster) |
| A7 | Authorities group author variants | **PASS**: SBN's name authority gives one id per person for every Latin form |
| A8 | A contact User-Agent removes Wikimedia throttling | **PASS**: 102 × 429 of 180 requests → 0 of 180 |

The four failures are constraints, not a backlog: a book with no identity is
normal (A1), only an ISBN merges (A4), the header states and never infers
(A5), there is no census (A6).

**The held-out check** (Step 15, 2026-09-26, cold, 96 entries, 0 failed
requests): strong SBN work 0.765 held out against 0.811 fitting; original
stated and right 0.941 against 0.608; **original stated and wrong 0 on both**;
S3 records judged wrong-work 4 of 56 against 8 of 56; first version on the page
at 3.6 s against 3.8 s median. It says the build does not do worse on books it
was not tuned on. It cannot say more: the corpus is literary, canonical and
heavily Italian-published, the six were chosen after decisions A–K, and
refusal behaviour was never held out.

**The shipped path, cold** (2026-09-28, 128 cases, 0 failed): to the end of S4
median **4.8 s**, p90 19.1 s, max 95.3 s (the *Odyssey*, 1,255 requests). The
list is on the page after S2.

---

## 3. Decisions

One entry per ID. **Why** quotes the number that decided it. A field left out
means none. All are the user's unless marked *(session)*.

**Before the letters (2026-09-14).** §5-1: no source lists every edition; the
result says what was found. §5-3: buy links and holdings on expand (revised by
I). §5-4: enumerate the whole work, filter locally, then fetch details;
original, earliest edition and counts are computed unfiltered. §5-5: editions
stay grouped by language. §5-6: author-only resolves the author first. §5-7:
title-only dropped (superseded by AN). Also superseded that day: details
fetched upfront, and a filter change rerunning the lookup.

### From the benchmark (2026-09-15/16)

- **A — A second acceptance signal for a refused SBN work.** A refused or weak
  work is accepted when the Wikidata item accepted for the same entry has a
  label, sitelink or title matching it at ≥ 0.6. **Why:** rescues 7 of the 19
  refused-or-weak entries; 0 agreements in 2,024 cross-book pairs; 44 of 47
  strong entries agree. Re-measured 2026-10-02: 11 of 11, control still 0 of
  2,024. **Discarded:** loosening the guard's B.
- **B — Latin script only; other scripts are romanised** before matching or
  sending. **Why:** the OPAC silently drops non-Latin free text (F15) **V**;
  romanised entries reached SBN works the script form missed (N04, N16, N17).
- **C — No coverage census; VIAF is not used.** **Why:** A6. **Discarded:**
  "found N of ~M known languages". Its fixed note was later replaced by N.
- **D — No "first edition differs" inference.** The header shows the stated
  original and, always, the *earliest edition found*; editions dated before the
  original's known year are left out of it. **Why:** A5. The rule over 37
  books: right year and language 22, right year with languages tying 9, later
  than the first edition 4, other 2, **older than the first edition 0**.
- **E — The User-Agent carries a contact URL.** **Why:** A8; Wikimedia's share
  of request time 35% → 3.8%.
- **F — A recovery route beside the listing, title-gated.** Candidate routes
  (Wikidata titles, an author sweep, ISBNs) find same-work records the work
  does not link; a record is admitted only by title against the **work's**
  titles. **Why:** the listing alone drops 334 SBN records and 98 Open Library
  editions; the routes that find them also leaked 44 wrong-work records
  ungated. **Discarded:** replacing the author sweep with the work authority.
- **G — Fold transliteration variants when matching** (zh/ž/z, -eia/-ea).
  **Why:** *Doktor Zhivago* missed SBN's `doktor zivago`, *Odysseia* missed
  `odyssea`. Measured safe (U3).
- **H — A cross-source duplicate is a "possibly the same edition" hint, never
  a merge.** A bracket joins the two rows; a shared ISBN folds them, different
  ISBNs remove it. **Why:** A4. Hint precision 0.766 on 100 hand-judged hints
  (59 same, 18 different, 23 undetermined); tightened by AX.
- **I — One edition row per ISBN, listing its printing years, grouped in the
  background.** Every SBN full record is fetched behind the list. **Why:** 483
  records with an ISBN become 297 edition rows; 295 of 778 records have no ISBN
  and stay one row each. **Discarded:** grouping from listing fields, precision
  0.425. **Supersedes** details-on-expand for SBN.
- **J — Open Library's main work only; its duplicate work records are listed
  and their editions fetched by work key** into the language groups. **Why:**
  by key, every known edition for 45 of 45 duplicates (F19); by title, the
  search returns the main work again 24 times and a different book 5.
- **K — A lookup slow for a known reason says so**, naming only causes
  measured in that lookup, above ~10 s cold (identity p90 was 5.7 s).

### During the build (2026-09-17 → 09-28)

- **L — The new tree is built beside the old code from Step 5**; parsers and
  the guard are ported by reading, and the old path runs until the new one
  matches it.
- **M — Job id + polling.** `POST /lookup` returns an id; the page polls
  `GET /lookup/<id>?v=N` for a new versioned snapshot or `{unchanged: true}`.
  **Discarded:** streaming; one blocking JSON.
- **N — Two disclosures: the coverage ledger and the loose-match band.** The
  ledger gives measured per-lookup numbers; the band shows what the title gate
  refused, collapsed, each row labelled with how it was reached.
  **Supersedes** C's fixed note; C's *no census* half stands.
- **O — Six books are held out**: N01, N05, N09, N11, N21, N22. Checked at
  gates only.
- **P** *(session)* **— An identity-keyed snapshot cache is deferred**: its
  win is bounded by repeat lookups of one work, which nothing measured.
- **Q** *(session)* **— The reverse path and the Dewey route are ported, then
  measured, then decided**, not deleted unmeasured. Settled by AC, then AH.
- **R — A fixture miss is loud.** An offline run that cannot answer a request
  stops; it never degrades to "no results" and never reaches the network.
- **S — The fixture bundle is not widened to the old path** (1,171 more bodies
  for code due to be deleted).
- **T — Nothing is pushed during the build**: the bundle is ~15 MB of
  third-party catalogue bodies into a 1.4 MB public repository. Ended by the
  release (private evidence repository).
- **U — F3 is amended with new numbers and a dated note** when SBN re-filed
  its example, rather than kept with the drift noted beside it.
- **V — The Step 1C known-red list is frozen as a file of its own**; the
  runner overwrote it on every run.
- **W** *(session)* **— `partial (N failed)` counts every failed request**,
  not only those a source reported. Measured cost on the sweep: none.
- **X — Always-read documents are split from append-only ones.** A session's
  mandatory read was ~156 KB and growing ~6 KB per step; ~66 KB after.
- **Y — N04's wrong header on the old path is accepted and filed**, not
  reverted: reverting romanisation cost 14 languages on E04 and 30 works in
  author mode. S1's own answer was unaffected.
- **Z — A non-edition is labelled, never filtered.** SBN links study guides,
  retellings, omnibus volumes and films to a work (F16). A row carries what the
  catalogue says: its medium, and *credited to X* where SBN's main heading is
  another person. **Discarded:** free-text markers (`retold by`), which leak on
  annotated editions. The label is incomplete and the list says so once.
- **AA — The first snapshot is S2's complete list.** **Discarded:** a
  header-only version at ~2 s: a header reading `0 editions` that then changes,
  for ~1.5 s.
- **AB — S3's title gate is 0.6, the number already in the code.**
  **Discarded:** 0.7, which blocks 7 more leaks for 1 lost record, but every
  record it moves scores exactly 0.667 (two of three tokens), an artefact, and
  all 7 are 3 books. The held-out six were not used to choose.
- **AC — The Dewey routes stay until re-measured on full records.** In Step 9
  the Dewey branch fired 0 times in 96 entries, but a brief row carries no
  Dewey class, so that was no verdict. Closed by AH.
- **AD — Filters are chips: multi-select, collapsed and never capped; a row
  with no language is a chip like any other** (18.3% of N06's rows).
  **Discarded:** a free-text publisher box; pinning unknown-language rows.
- **AE — The band shows every refused record, lean, in two groups by route;
  the ledger is one line with its warnings outside the fold.** 8,833 refusals,
  median 82 per entry; 6,799 of the author sweep's 6,987 score exactly 0.0.
  **Discarded:** a floor at score > 0, which hides the 400 title-probe rows at
  0.0, where the gate is most likely wrong. A lean row is 242 B.
- **AF — A Wikidata item that is an edition is not the work.** `Q138528911`,
  a 2024 Spanish translation, made the header say a 2010 German book first
  appeared in 2024 in Spanish. A tightening: 1 accepted item of 63, and the
  only stated original in 94 entries that disagreed with ground truth.
- **AG — S4 reads every admitted SBN row, capped at 1,500, and publishes
  once; a row sorts by its latest printing.** No corpus entry reaches the cap
  (max 1,078). **Discarded:** a cap of 300 (p90 is 292); a version every 5 s.
- **AH — The Dewey routes are deleted and the inferred original dropped; the
  reverse path's typed-title half stays.** **Why:** on full records the Dewey
  branch fires on 323 refused records and would admit 1 (an omnibus); with
  SBN's own Dewey 3 of the 4 it admits are other books; the reverse half saves
  0 of 3. The typed-title half alone answers E12 and E14. **Supersedes** AC, Q.
- **AI — Open Library's other records are listed by the work's author and
  title tests (≥ 0.6), searched beside S4, added one at a time or all at once,
  and left out of the header.** **Discarded:** author only, about 3× the rows
  (1,843 against 663) for one more known duplicate; searching on demand. By
  hand, 33 of 44 listed records are the same work (0.75).
- **AJ — Author mode.** The chooser is skipped only when one person answers;
  Wikidata's other spellings are asked too; SBN's 50-work cap is split by
  language, then by exact year, and what no leaf covers is a stated count;
  Open Library records joining no work, and records the person is on but does
  not head, go in collapsed groups. **Why:** Eco's Italian works 50 → 231; 177
  of Eco's 305 rows are headed by someone else. **Discarded:** raising the cap
  (it is SBN's own, F11; no whitelisted key moves it).
- **AK — A work row's click tries every spelling of its title**; nothing is
  loosened and a typed lookup carries none. N17: 8 records → 11.
- **AL — A film S3 admits stays in the list, labelled** (Z applied to S3).
  The Persian-calendar dates were deferred (closed by AY).
- **AM — No path is deleted while it reaches a correct edition or original
  the other does not.** On one day's catalogue the old path was 24 red, the
  new 85. Step 15B closed the gap first.
- **AN — Title only: adopt the one author Wikidata, Open Library and SBN's
  catalogued titles agree on, and say so in the byline; if they name several
  people, a chooser of books and no list.** SBN's work authority states the
  work's language (F20) and is believed unless SBN holds records in that
  language none of which is titled like the work. **Discarded:** the old
  chooser over one combined list. **Supersedes** §5-7.
- **AO — No original year where no source states one.** Open Library's
  `first_publish_year` was wrong on 17 of 60 fitting entries, its `language`
  on 40 of 60. **Discarded:** using it narrowly (4 right, 1 wrong).
- **AP — S3 runs for any identified work with titles to gate on**, not only
  beside an accepted SBN work. N04 reached no SBN record without it, 115 on the
  old path. **Discarded:** requiring SBN's main heading to be the author.
- **AQ — Regression clauses no stated source can meet stay red, as written**
  (H11, H17 original `eng`; H05; H09 ≥ 10 works). **Discarded:** restating
  them to fit.
- **AR — Author mode is scored on what the page reaches, the collapsed band
  included** (83 of 84 Bateson titles).
- **AS — Step 15B's third gate is accepted, and its remaining failures are
  the accepted set.** Wrong originals: new path 0, old 7; right 66 = 66. A new
  red outside the set is a regression.
- **AT — AS covers the old baseline clause**: 59 fitting cases red after the
  deletion, none outside the accepted set.
- **AU — One plan, a backlog, and an archive.** `docs/BACKLOG.md` is the home
  of anything deferred.

### After the build (2026-09-29 → 10-03)

- **AV — Other spellings are the reader's two switches, off by default.**
  *Title*: the SBN guard is asked again under the Wikidata item's other names.
  *Author*: `core=autori` under each Latin name, an id kept only where it
  resolves. No gate moved. **Why:** 128 cases, 0 failed; switches off, the red
  set is unchanged; on, no case loses a record, 14 gain 62 records (about 50
  right, 12 not: 11 are other volumes of Ferrante's quartet, whose uniform
  title names the series). Extra requests median 0, p90 12, max 74.
  **Discarded:** always on; one switch.
- **AW — A Retry-After over 60 s is a failure, not a wait.** The longest wait
  any host asked for and then honoured is 36 s. **Discarded:** urllib3's own
  cap, which sleeps 60 s and asks again before the server said it would answer.
- **AX — A duplicate hint is withheld when both rows state page counts more
  than max(10 pages, 10%) apart.** On the 100 judged hints it withholds 9 of
  the 18 different and 1 of the 59 same; precision 0.766 → 0.866. Corpus hints
  1,167 → 1,054. **Discarded:** a series rule (2 same withheld for 2
  different); a minimum page count fitted to the one wrong call.
- **AY — A year written in another calendar, or twice, is settled by two
  readings or not at all, and the row says which.** 2,190 live SBN records in
  32 languages: 65 of 156 Persian records showed their Iranian year. The
  bracketed year and SBN's `dataf[]` index were each wrong once, so neither is
  trusted alone: a plain Gregorian year is taken as written (95%); any other is
  checked against the index and labelled *year inferred*, *year unsure*, *year
  unchecked*, *other calendar* or *no year*. Replayed: 96 inferred, 6 unsure, 3
  other calendar, 0 labels on 504 Western controls. Plain years are reconciled
  against the listing's own counts (capped at 60 values per lookup); a stated
  printing is *printed 1997*. **Discarded:** converting by rule (one Persian
  book is dated in the lunar calendar); trusting either reading alone.
- **AZ — In author mode a tie between Wikidata works that are one work
  joins; another project's namespaced page is not a work's name.** Of 14 ties
  7 join and 7 stay refused, each right (a part is not its whole).
  **Discarded:** merging rows at 0.6 (of 64 pairs, 14 are different works).
- **BA — Author mode reads 500 records under a name, and the reader can read
  the rest** (`POST /lookup/<id>/more`, no ceiling, cost stated first). Eco,
  live: 14 s, 136 requests, 133 → 535 titles; the works list does not move.
  **Discarded:** a higher cap for every lookup; a 5,000-record ceiling.
- **BB — A work under the name is read whole before the group filed under no
  work is drawn.** Ferrante's group 65 → 23 titles; Dostoevskij +62 requests,
  wall time within noise. **Discarded:** reading whole only on BA's click.
- **BC — In author mode a work is a book; what was made from it is drawn
  under it.** A uniform title whose qualifier names a medium (`film`,
  `serie tv`…) had joined the book's row and labelled it (Eco's *Il nome della
  rosa* read as a TV series, 254 records for 233). Over P01–P09: 13 book rows
  labelled a medium → 0; 16 books carry derived entries. S1's `ADAPTATION` is
  not widened (rule 6).
- **BD — A co-written book is the person's; the contributed group shows each
  row's statement of responsibility rather than deciding it.** About 7% of 250
  judged rows are the person's own, 14 co-written. No field separates a joint
  work from a collection: SBN's `[Autore]` label finds 5 of 16 and takes 12
  others. So no row moves.

---

## 4. Verified facts

On SBN's OPAC API unless stated. Each was verified with the control shown; a
fact resting on one facet value has a shelf life (see F3), so re-run it.

| # | Fact | How verified |
|---|---|---|
| F1 | `titolo_uniformef[]` filters (*Cent'anni di solitudine*: 143) | bogus value → 0; bare `core=sbn` → 21,806,046 |
| F2 | Keeping free text in the record pull returns the intersection (89 against 143) | measured |
| F3 | The author term constrains a generic query: `tutte le poesie` + Leopardi 41, without 1,265; as a work query, 0 with the author, 84 (other poets) without | re-measured 2026-09-18, after SBN re-filed Leopardi under `canti` (was 26) |
| F4 | `lingua[]` filters with the author kept (ita 90 / spa 22 / eng 12) | bogus → 0 for all 32 works |
| F5 | Rows carry id, title, `infos[]`; no ISBN, Dewey, holdings or translators | 98.4% of rows parse a year |
| F6 | A work lists without full fetches | 32 works, 469 requests, 0 failed |
| F7 | The OPAC row's language equals the full record's `linguaPubblicazione` | 740 of 740 mapped records |
| F8 | `tiporec[]` and `level[]` filter | bogus → 0 |
| F9 | Page size is fixed at 20 | six spellings ignored |
| F10 | `dataf[]` filters exact years, `editoref[]` exact values | bogus → 0; three range syntaxes → 0 |
| F11 | Every facet caps at 50 items | prolific authors; re-run 2026-09-25 |
| F12 | A large minority of SBN full records have no ISBN: 295 of 778 (38%); Open Library 252 of 1,405 (18%) | measured over 8 books |
| F13 | The mobile gateway's `full.json` cannot batch | every multi-id form → the bogus-id body |
| F14 | Entry titles converge on one work **for the 9 books it was checked on only**; the guard withholds a correct work in 14 entries of N01–N24 | measured; the general claim was wrong |
| F15 | **The OPAC silently drops non-Latin free text**: alone it returns all 21,806,046; with an author it equals the author alone (Доктор Живаго 855 = 855) | a bogus **Latin** term → 0 |
| F16 | SBN links non-editions to a work (a York Notes guide, a Penguin Readers retelling, a collected volume); `tiporec[]`/`level[]` do not separate them | measured |
| F17 | One SBN ISBN spans printings of many years: `9788845906862` on 31 records, 1985–2026 | 361 of 499 ISBN-sharing pairs differ in year |
| F18 | Wikimedia rate-limits by User-Agent: 102 × 429 of 180 without a contact URL, 0 of 180 with | both orders; re-run 2026-09-18, Retry-After 36 s |
| F19 | An Open Library work's editions are reachable by key (45 of 45) | bogus key → 404 |
| F20 | SBN's work authority (`core=opere`) states the work's language (10 of 14 sampled), never a year, and can be wrong (Mahfouz filed ITALIANO) | bogus id → `data: null` |

---

## 5. Pitfalls

Each was paid for once. The API detail is in `docs/sbn-api.md`.

1. **SBN is two APIs, and the project's premise came from knowing one.** *"No
   free catalogue records the link between a translation and its original"*
   was recorded as verified and was false. SBN records it as a uniform title;
   the mobile gateway's JSON simply omits it, so six full records showed no
   trace. *Symptom:* a Dewey class used as the bridge, and an original unable to
   find its own translation. Check the record **type**
   before concluding a field is absent (Open Library's `translation_of` lives
   on editions, not works, the same mistake).
2. **Both SBN APIs answer an unknown parameter with the unfiltered set.**
   *Symptom:* a confident wrong answer, no error. One whitelist per API; the
   OPAC's refuses a key outside it.
3. **The OPAC drops non-Latin values the same way** (F15). *Symptom:* a
   Cyrillic title "found" the author's whole catalogue. Send Latin script and
   prove each term was used with a control that must return 0.
4. **An OPAC work query without an author answers with a different book.**
   Bare *Rumori* → Russolo's `arte dei rumori`; bare *The Essential Knuth* →
   `essential mathematics for economic analysis`. The functions raise instead.
5. **`linguaPubblicazione` sometimes names the language translated from.**
   `UBO4636099`, Vintage's English *Kafka on the Shore*, is filed GIAPPONESE.
   *Symptom:* an English translation under Japanese, marked the original.
   A record naming a translator while claiming the original language is
   disbelieved, not corrected. `paesePubblicazione` is a country, never a
   language signal.
6. **A failed request indistinguishable from an empty result** — the worst
   bug in the project. Every helper returned "no results" on failure.
   *Symptom:* editions silently missing, sources reading `ok`. One ledger per
   lookup now records every call; `partial (N failed)` is a reading of it.
7. **A plain thread pool drops the ledger.** Context does not reach executor
   threads, so their failures reach no reading. Every pool is `Pool`; a test
   scans for the other by text.
8. **A 200 that is not an answer.** A single `/` in an SBN free-text value
   returns HTTP 200 and a Solr error object (U8). Being valid JSON it was
   cached and replayed for 24 h. *Symptom:* `SBN partial` on every repeat. The
   cache now refuses what its caller rejects.
9. **627 green tests and a dead sweep** (Step 9). `catalog/` returns plain
   dicts; a record whose holdings were dicts raised only where the view read
   one, which no tested row did. Green is not "the pipeline runs".
10. **Wikimedia throttles an agent with no contact** (F18). *Symptom:* recorded
    as "connect stalls to one Wikipedia host"; it was 429s, 35% of request
    time.
11. **A uniform-title label is a search key, not a title**: lowercased,
    accents stripped (`cien anos de soledad`). Never displayed. Its share of
    results does not pick the work either: *Modernità liquida* is right at
    0.48, *Angelus Novus* questionable at 0.43.
12. **SBN's `lingua` facet counts the author's catalogue, not the work**
    (`francese 124` beside one Italian edition). Language chips are counted
    from the rows on the page.
13. **Cross-language title similarity is exactly 0.0** (*Noise* / *Rumori*).
    Of 608 same-work rows, 580 score exactly 0.0 or 1.0: the title gate tests
    whether the work has a title in the record's language, so its threshold is
    not the lever (U2).
14. **Data-shape traps in SBN records**: non-sorting articles wrapped in
    `\x88…\x89`; several Dewey codes run together with no separator; in
    holdings the library name is in `shelfmark` and the city in `invNum`;
    `infos[0]` is not the imprint on 26 of 2,603 rows; language codes are read
    off the `lingua[]` facet, never guessed (`SLOVACCO` is `slo`).
15. **A record count is never asserted.** *Nineteen Eighty-Four* returned 733
    records, then 899 on the same 35 requests hours later.

---

## 6. Discarded alternatives

Re-proposing any of these needs new evidence first.

| Idea | Evidence against |
|---|---|
| A yes/no "translated into Italian" hero | The user's rejection (section 1) |
| Google Books as a source | Keyless quota permanently exhausted (429 on every call); it contributed nothing |
| A Dewey class identifying a work | A class is a subject, and one author's books are mostly one subject (García Márquez's novels are all `863.44`). Measured: 3 of 4 admissions other books, 0 of 3 saves (AH) |
| VIAF as a coverage census, or at all | 20 of 37 books unusable, 13 split across clusters, results not relevance-ordered (C) |
| Inferring "the first edition differs" | 8 false flags and 1 miss over 36 books: a Dutch translation dated 1912, reprints dated 1866 (D) |
| The old pipeline (`lookup/pipeline.py`) | Median 34.5 s and 192 requests against 3.5 s and 19; 7 wrong originals against 0. Deleted only once the new path reached what it reached (AM, AS) |
| Title-only lookups dropped | Reinstated by AN: completeness comes first, and an agreed author makes it safe |
| Fetching details upfront | It was the 34.5 s. The list first, full records behind it (I, AG) |
| Fixing cold latency in the network layer | The "stalls" were Wikimedia throttling (F18) |
| Replacing the author sweep with the work authority | SBN's links are partial: 334 same-work records not linked, over 40 books |
| Dropping the author from the work query | F3: 84 records by other poets |
| Picking the work by share of results or dominance | Pitfall 11 |
| Loosening the work guard's B to accept the classics | The known wrong works sit at B = 0.5, above every refused classic (≤ 0.375). The second signal is the way in (A) |
| Merging on a (language, year, publisher) collision | Precision 0.656; 0.664 under the strictest publisher rule. All 43 false positives share a real publisher: another country's edition, another binding |
| Grouping printings from listing fields | Precision 0.425 |
| Reaching a duplicate Open Library work by its title | Returns the main work again 24 of 33 (J) |
| Phrase or AND search through the operator suffix | `@or@`, `@and@`, `@frase@` and a bogus `@zzz@` return identical totals |
| Batching full records; a larger OPAC page; server-side year ranges | F13, F9, F10 |
| Raising the enrichment budget to recover editions | The cause was work records occupying gate slots, not the budget |
| Open Library's `translation_of` as a discovery route | Present on 3 of 35 Italian editions (8.6%) |
| Open Library's first-publish year or language as the original | Wrong on 17 and 40 of 60 (AO) |
| Loosening the gate to catch retranslations under a separate work | *Sul concetto di storia* is its own uniform title; nothing ties it to *Tesi di filosofia della storia*. A documented limit |
| Re-asking the guard with a record's own title | 1 right record gained, 26 wrong admitted (2026-09-29) |
| A title gate at 0.7; a second threshold for S3 | AB |
| Filtering non-editions and films out | Z, AL: label, never filter |
| Converting calendars by rule | AY |

---

## 7. Thresholds

| Constant | Value | What pins it |
|---|---|---|
| `core.identity.IDENTIFYING_TITLE_MATCH` | 0.6 | A record is reported only if tied to the work: the work authority, a shared ISBN, or a title match at this score against one of the **work's** titles. It was 0.45, where one shared word passed. *L'ordine delle notizie* scores 0.5 against the titles of *The Invention of News* and must stay out; *Quale socialismo, quale Europa* (Attali, 1977, like *Bruits*) scores 0.0: same author and era is not enough. Chosen over 0.7 by AB |
| `core.identity.WORK_TITLE_MATCH` | 0.6 | The same number, for a title against a work; also the second signal (A) and author mode's joins |
| The SBN work guard | A ≥ 0.6, or B > 0.5: strong. B = 0.5: weak. Else refused | **A** is the typed title against the uniform title. **B** is, of the query's records really carrying that title, the share SBN files under the work. Wrong works at B = 0.5 (*Tesi di filosofia della storia*, *Angelus Novus*); refused classics at ≤ 0.375 (*Crime and Punishment* 9/31, *Der Process* 2/15, *Blindness* 3/8), thinly linked rather than misjudged. Over 91 entries the guard accepted no wrong work |
| `stages.ENRICH_CAP` | 1,500 | Full records S4 reads; corpus max 1,078 (AG) |
| OPAC page / facet | 20 / 50 | SBN's own (F9, F11) |
| `sbn_opac.LISTING_MAX_PAGES` | 100 | 2,000 records in one language |
| `stages.UNLINKED_MAX_PAGES` | 25 | 500 records under a name; the reader can read the rest (BA) |
| `stages.MAX_VARIANTS` | 6 | Other spellings asked per switch (AV) |
| `stages.RECONCILE_CAP` | 60 | Year values reconciled per lookup (AY) |
| `core.fold.PAGES_APART` | 10%, min 10 pages | AX |
| `http.RETRY_AFTER_CAP_S` | 60 s | AW |
| `http.SLOW_LOOKUP_S` | 10 s | K |
| `http.TIMEOUT` | (4, 15) s | Connect and read apart, so a stalled connection fails fast |
| Cache | 24 h | A cold lookup is dozens to hundreds of requests |

**Every cap is reported on the page when it binds.** Lowering one to go faster
hides records. **A threshold is not the only way to move a gate**: the
romanisation, the fold and `STOPWORDS` in `core/text.py` change what scores
0.6 without touching a number, so they carry the same re-check (`STRONG` is a
verdict about a record, `WORK_STRONG` about a work; they are different).

---

## 8. Build rules

Cited in the code as *build rule N*. They held in every step and hold in any
change.

1. **A source module never decides.** `catalog/` fetches, parses, returns.
   Every gate is pure and lives in `core/`.
2. **Producers never decide and never format.** They write records with
   provenance.
3. **Derivation is pure and total.** The view is recomputed from the store
   after every batch; no display list is mutated.
4. **Provenance is a field, not a mechanism.** Each record carries source,
   route and the evidence that admitted it; the band, the ledger and the
   slow-lookup note are readings of it.
5. **One whitelist per API, one control per key and per value class.**
6. **A failed request is never an empty result.** One ledger, several
   readings.
7. **The cache refuses what its caller rejects.**
8. **Uncertainty shows less.** No original where none is stated; no inference
   in the header. The loose-match band is the one exception, collapsed.
9. **A collision is a hint; only an ISBN merges.**
10. **Every truncation is on the page**: facet caps, page caps, budgets,
    unfinished grouping.
11. **Identity is computed once and never re-derived from the typed title.**
    After S1 only S3 uses it, to find candidates it gates on the work's
    titles; and the reverse path, where there is no identity at all.
12. **Filters never touch identity** and issue no request.
13. **Nothing is tuned against the held-out six.**

---

## 9. Measurements the code cites

| # | Question | Answer |
|---|---|---|
| U1 | Does the slow-lookup note name the real causes? | One book, four runs, 2026-09-18: every clause agreed with an independent log. Whether ~10 s fires usefully across the corpus is unmeasured |
| U2 | The title gate's yield and leaks (decision F) | 2026-09-18, 758 rows, held-out excluded: *not linked to the work* 266 of 288 admitted (0.924); *separate Open Library record* 72 of 92 (0.783). Leaks: 16 of 42 pass, all adaptations, sequels and companion essays sharing the work's title (Pinter's screenplay of *The Trial*, *Postille a Il nome della rosa*), which no threshold separates. Thresholds from 0.05 to 0.65 admit within 2% of the same set |
| U3 | Is transliteration folding safe? (G) | 2026-09-17: 0 of 5,152 cross-book title pairs pushed across 0.6; 1 same-book pair recovered (*Odysseia* ~ *Odissea*); both gate counterexamples unchanged. Re-run on any change to the fold |
| U4 | How does the page learn grouping ended? | Decisions M and AG |
| U5 | The duplicate hint's precision | 0.766 (H), then 0.866 (AX) |
| U6 | The duplicate-record list's precision | 33 of 44 (AI) |
| U7 | The second signal's misses | Recovered by romanisation and the fold: 11 of 11 (A) |
| U8 | Were the phantom `SBN partial` reports cached error payloads? | Yes: pitfall 8. 3 such bodies of 4,234 in the cache, one per book |

Still open, and whose call each item is: `docs/BACKLOG.md`.
