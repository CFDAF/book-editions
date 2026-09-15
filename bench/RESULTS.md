# Benchmark results — docs/assessment-2026-09-14.md §9

Evidence tags: **V** verified with a control · **M** measured · **D** documented
(link) · **I** inferred. Catalogues drift: structure, not exact totals.

## Status

| Stage | State | Date | Commit |
|---|---|---|---|
| 1 — ground truth, A1, A3, A5, A6, A7, A8 | done | 2026-09-14 | `defe095` (branch `bench/stage-1`) |
| 2 — A2, today's pipeline against listing by identity | done | 2026-09-15 | `7742793` (branch `bench/stage-2`) |
| 3 — A4, merging duplicates by collision | todo | | |

---

## Stage 1

### Verdicts

| # | Assumption | Metric (all 40 books; 37 scored: E10/E11 are generic titles, N23 insights only) | Fail criterion | Result | Evidence |
|---|---|---|---|---|---|
| A1 | Every entry title + author reaches one identity | Books whose every entry reaches the *right* identity: **SBN 22/37**, Wikidata today 20/37, **Wikidata Step 4 14/37**, **Open Library 13/37**. Entries (91): SBN 68 right · 0 wrong · 23 none; Step 4 59 right · 0 wrong · 32 none; today 68 right · 4 wrong · 19 none; OL 60 main · 8 split record · 2 wrong · 21 none | any entry title resolves differently, or disagrees with ground truth | **FAIL** in all three sources | M (OPAC facts V) |
| A3 | Listing rows are enough to filter | SBN: 2,561 / 2,603 rows with a parsable year (**98.4%**; lowest book E07 13/15), publisher 2,602, language 2,601; every language page summed to the work total (0 records on no language page); `lingua[]=zzqx` returned 0 for all 32 works. OL: 5,024 / 5,123 dated (98.1%), publisher 5,065, language **4,139 (80.8%)** | < 90% year parse on SBN rows | **PASS** | V (control) + M |
| A5 | Original vs first edition is detectable | Wikidata original (Step 4 item) right 22 · right with no year 1 (N20) · **wrong 3** (N03 year 1946, N13 all three fields, N14 title) · absent 10. Listing rule: right 27 · **false flag 8** · **missed 1** (E16) · report only 2 (N02, N23) | a wrong original; a missed or false "first edition differs" | **FAIL** | M |
| A6 | VIAF can state coverage | census ≥ languages found: 17; census < found: 13; unavailable: 7. Works split across VIAF clusters: 13 books | unavailable or smaller than found for most books | **FAIL** (20 of 37) | V (bogus index/value → 0) + M |
| A7 | Authorities group author variants | All 17 forms of 9 people reach one **VIAF** cluster (incl. 村上春樹, Фёдор Достоевский, 한병철). SBN name authority: one id per person for every Latin form; non-Latin forms dropped. Wikidata 8/9 (Han Byung-Chul finds nothing). OL `resolve_author_keys` omits the main record for Murakami, Dostoevsky, Han | variants split in every source | **PASS** | V (controls) + M |
| A8 | A contact User-Agent removes Wikimedia throttling | UA A (today's): **102 × 429 of 180**, in every phase; UA B (GitHub URL): **0 of 180**. Same in AB and BA order. Stalls > 5 s: 0 / 0. p50 of 200 responses 0.196 s vs 0.198 s | no difference | **PASS** | M |

### What each result means

**A1 — identity.**
- *SBN guard (Step 5)* never accepted a wrong work (0 strong-and-wrong in 91 entries). Its failures are refusals: of 16 entries with a W but no strong tier, **14 had the right W** (rejected 9, weak 5) and 2 had a wrong one (N17 Arabic → `hikayat haratina`, rejected; E13 → `schriften`, weak).
  - Classics with many uncatalogued records fall below B: *Crime and Punishment* eng 9/31, ita 152/476; *Der Process* 2/15, *Der Prozess* 11/47, *The Trial* 5/16; *Blindness* 3/8; *Palace Walk* 1/3.
  - Split uniform titles tie at B = 0.5: *Capital au XXIe siècle* vs `capital au 21. siecle` vs `capitale nel xxi secolo` (N22), `bain el-qasrain.` vs `bayn al-qasrayn` (N17).
  - B cost 637 extra OPAC requests over 59 entries; max 151 (N23 Greek, whose free text was dropped, so B paged all 8,818 Homer records and could not succeed).
- *New silent trap* **V**: the OPAC drops free text in Cyrillic, Greek, Arabic, Chinese and Japanese. `ANY` alone returns 21,806,046 (= bare `core=sbn`), and `ANY + AUTHOR` equals `AUTHOR` alone (Доктор Живаго 855 = 855, Ὀδύσσεια 8,818, بين القصرين 524, 活着 192, 海辺のカフカ 407). A bogus Latin term returns 0. One Cyrillic exception: Преступление и наказание alone → 4. The guard rejected all four such entries, so no wrong work got through. `probe_nonlatin_any.json`.
- *Wikidata Step 4* also never accepted a wrong item, and it rejected all 6 wrong items today's resolver returns: *Liquid Love* for *Liquid Modernity*, *L'infinito* for *Opere*, a Montale poem for *Poesie*, *The Work of Art…* for *Tesi*, *Theses* for *Angelus Novus*, *Where Mathematics Comes From* for *Metafora e vita quotidiana*.
  - It loses right items for every non-Latin-script title (`matching.normalize` reduces them to nothing, so every score is 0.0: 活着, بين القصرين, Доктор Живаго, Ὀδύσσεια), for the romanised *Umibe no Kafuka* (predicted in Step 4), and for alternate titles that are no label or sitelink (*Survival in Auschwitz*, *The Outsider*, *Vita da uomo*, *Millenovecentottantaquattro*, *Müdigkeitsgesellschaft*).
  - Today's resolver misses *Crime and Punishment* (`Q165318`) in all three languages: the author check compares "Fëdor Dostoevskij" with "Fyodor Dostoyevsky" and finds no shared token.
- *Open Library.* The spec's rule ("highest edition count whose author matches") picks the author's most-printed book when the title is short: *1984* + Orwell → *Animal Farm* (653 editions), *The Trial* + Kafka → *Metamorphosis* (955).
  - `matching.author_matches` cannot match authors filed in original script (村上春樹, نجيب محفوظ, Фёдор Михайлович Достоевский): the strict rule finds no main work for E04, N04, N17. Shown as `[keyed]` where the doc's author key from Open Library's own author search matched instead. That is a diagnostic, not a fix.
  - Original-title search finds no main work for N07 (`d'inverno`: only studies come back), N13 (`<title> Byung-Chul Han` → 0 docs for all four titles, while `The Burnout Society Han` → the work), N16 and N24. Italian entry titles reach nothing or a side record in 21 entries.

**A3 — listing.**
- Cold, every request fresh: 32 SBN works in 469 OPAC requests, 0 failed. Book wall time median 5.3 s, max 18.4 s: a single Open Library request, E08. Largest SBN work: N02, 613 rows in 49 languages, 74 requests, 13.5 s. *Cent'anni*: 143 rows / 18 languages, 25 requests, 2.5 s.
- The 42 SBN year failures:
  - 26 rows where `infos[0]` is not the imprint (`Testo - Monografia [IT\ICCU\…]`, `Fa parte di: …`, `3. ed`, `533 p`). Step 6 warned about `infos[1]`; `infos[0]` is not fixed either.
  - 14 undated records (`[19..?]`, `s. d.`, `[200?]`).
  - 2 parser misses where a second ` : ` sits in a parenthesis (`Paris, Gallimard,1964 (Paris : Paul Dupont)`).
- The markers `\1977!`, `\Milano! : …` and `c1978,, stampa 1977` all parse.
- Open Library `editions.json?limit=1000` honoured the limit and `links.next` paged N04's 1,179 editions. Two ConnectTimeouts (E16, N04) were retried once; the tables mark them.

**A5 — original vs first edition.**
- Expected positives: N01 flagged (1984 eng/fre before 1985 cze).
- E16 **missed**: SBN `UBO1185522` and Open Library `OL49953365M` both record a Russian *Doktor Zivago*, "Milano : Feltrinelli, 1957", so Russian ties with the Italian 1957. Wikipedia says the first Russian edition was Mouton, The Hague, September 1958. The catalogues' imprint date and the encyclopaedia disagree (see *Uncertain ground truth*).
- The 8 false flags come from three causes:
  - dates in the listings that are wrong: N03 SBN `IEI0481234`, a Dutch translation dated 1912; N04 and N12 CreateSpace reprints dated 1866 and 1825; E04 an audiobook dated 2001;
  - the original-language first edition absent from both listings: N13 German 2010, N16 Chinese 1993;
  - a different book in the listing (E13: Suhrkamp's German *Angelus Novus* 1966), or no language on the only edition (E15).
- N02: the rule does **not** flag *Le Petit Prince*. SBN holds both an English and a French record dated "New York : Harcourt, Brace & World, 1943", so the two languages tie.

**A6 — census.** VIAF answers keylessly and its controls pass, but it is not a one-request census.
- Queries need author + title tokens without stopwords or apostrophe words, and the SBN uniform title helps: *L'Étranger* and *Der Process* came back only that way.
- 13 books are split across clusters (E13 in 4, N08 in 4). 7 books have no cluster: E06, E14, E15, N16 (`huozhe`), N17 (transliteration), N19, N24.
- Language labels: 1,333 normalised through a bench table (none through `lookup.langs`, which knows only Italian names and codes), 22 `None`, 59 unmapped. Polish abbreviations (`(wł.)` = Italian), Swedish, Czech and Catalan names needed entries.
- Where VIAF does answer it can exceed what the catalogues list: E01 33 vs 21 found (documented 46); N13 13 vs 1 (documented > 35).

**A7 — authors.**
- VIAF search results arrive in viafID-descending order, not by relevance, and `sortKey=holdingscount` is ignored: a bogus sort key gives the identical order **V**. For "Garcia Marquez" (103 clusters) the main cluster `54147956` only appeared after paging past 50 records.
- VIAF splits people into same-name clusters: Gregory Bateson 4, Murakami 4 (one is a different Murakami Haruki b. 1937), Ferrante 4.
- SBN's `core=autori` free-text search matches variant forms ("Fyodor Dostoevsky" → *Dostoevskij, Fëdor Mihajlovič* `CFIV001049`). `item:5032:Nomi::@frase@=<id>` then lists the person's records (4,787). Both controls return 0.
- Namesakes that surname-only queries return: Bateson → Alan N., Beatrice, Catherine, Claire…; "Garcia Marquez" → Vicente, Eligio, Fausto Pedro…; "Han" → 945 authorities.

**A8 — User-Agent.**
- UA A gets exactly 10 successes, then 429s with `retry-after: 14` and `x-envoy-ratelimited: true`, the policy's 10 req/min tier.
- `net.session()` retries 429 (`status_forcelist`), and urllib3 honours `Retry-After` on 429 by default. **I**: today's "Wikipedia stalls" may be these sleeps rather than connection stalls. Not tested here.
- The Stage 1 Wikimedia parts (A1-wd, A7-wd, ground truth) were therefore sent with UA B, set in `bench/common.py`; `lookup/net.py` is unchanged.

### Uncertain ground truth

| Book | What is uncertain | Why |
|---|---|---|
| E16 *Doktor Živago* | Year and imprint of the first Russian edition | it.wikipedia (citing the Washington Post) gives Mouton, The Hague, September 1958; ru.wikipedia gives Feltrinelli's Russian edition in January 1959; SBN `UBO1185522` and OL `OL49953365M` record a Russian "Milano : Feltrinelli, 1957" |
| E02 *Steps to an Ecology of Mind* | First publisher | The same en.wikipedia article names Chandler Publishing (infobox) and Ballantine Books (lead), both 1972 |
| E13 *Angelus Novus* | What the work is | An Italian anthology (Einaudi 1962, DNB record); Benjamin's German *Angelus Novus* (1966) is a different selection |
| E10 *Opere*, E11 *Poesie* | No single work | Generic titles; left out of scoring |
| N04 *Crime and Punishment* | Publisher and place of the 1867 book edition | Only "separate edition 1867" is sourced |
| N11 *La Disparition* | Publisher | en.wikipedia infobox says Gallimard; BnF and fr.wikipedia say Denoël (recorded: Denoël) |
| N22 *Il capitale nel XXI secolo* | First Italian year | SBN's earliest record is not the first Italian edition |
| E03, E04, E05, E15, N05, N14, N16, N17, N18, N19 | Place of publication | Not stated by the sources read; left `unknown` |
| Translation counts | Documented for 7 books only | E01 46 (en.wikipedia) vs 37 (it.wikipedia); E09 > 40; N02 600 languages and dialects (2024); N06 65 (by 1989); N10 68; N13 > 35; N24 0 (user) |

§9 corrections: **N19's Italian edition is titled *Tomorrow, and tomorrow, and tomorrow*** (Nord, 2023; it.wikipedia and SBN `UBO4696991`). *Domani, e domani, e domani* returns 0 records. N5 *Vita da uomo* (Roma : Casini, 1952), N16 *Vivere!* (Roma : Donzelli, 1997) and N17 *Tra i due palazzi* (Napoli : Pironti, 1989) are confirmed by SBN.

### Contradicting the assessment or STRATEGY.md

1. **F14 holds for its 9 books, not beyond them.** On N1–N24 the guard withholds a correct work in 14 entries (A1). "Identify the work once" (assessment §7.3) through the Step 5 guard leaves *Crime and Punishment*, *The Trial* (German and English) and *Blindness* (English) with no SBN identity. **M**
2. **A guardrail is missing**: the OPAC silently drops non-Latin free text (A1). STRATEGY's guardrails cover unknown keys, not dropped values. **V**
3. **Assessment §3, VIAF as "the best one-request language census"**: 7 of 37 books have no cluster, 13 are split, and results are not relevance-ordered. **V/M**
4. **Assessment §4, "Open Library must be searched with the original title"**: necessary but not sufficient. It fails on apostrophes (N07), on a hyphenated author (N13) and on non-Latin authors under `author_matches`. The highest-edition-count rule reaches the wrong book for short titles. **M**
5. **Assessment §3, "Wikidata original-language title, year and language correct for all five"**: on 26 accepted items, 3 are wrong (N03 P577 1946; N13 `Q138528911` carries a Spanish 2024 P1476; N14 P1476 "Ensayo sobre a ceguera") and N20 has no P577. **M**
6. **STRATEGY Step 6, only `infos[1]` is unreliable**: `infos[0]` is not the imprint on 26 of 2,603 rows. **M**
7. **STRATEGY Settled, cold latency is not in the network layer**: still true for SBN. For Wikimedia, A8 shows today's User-Agent throttled to 10 requests before 429s; with urllib3 honouring `Retry-After`, that is a likely source of the observed stalls (**I**). Re-opening it is the user's call.

### Requests, failures and wall time per host

Totals over every Stage 1 script, re-runs included (cached requests are not counted). Exploratory `curl` probes (about 25) are not logged. The Wikimedia failures are A8's deliberate 429s; the VIAF failures are 68 DNS resolution errors inside one ~40 s window, after which the run was repeated with 0 failures; the Open Library failures are 1 deliberate 404 control and 2 ConnectTimeouts. A3's cold wall time per book is in the A3 table below.

| host | requests | failed | > 5 s | total s | p50 s | max s |
|---|---|---|---|---|---|---|
| opac.sbn.it/o | 1482 | 0 | 7 | 1288.9 | 0.815 | 9.99 |
| it.wikipedia.org | 397 | 34 | 2 | 128.1 | 0.252 | 17.4 |
| en.wikipedia.org | 385 | 32 | 1 | 111.4 | 0.234 | 17.46 |
| www.wikidata.org | 317 | 36 | 1 | 116.1 | 0.218 | 7.7 |
| viaf.org | 270 | 68 | 0 | 114.5 | 0.229 | 3.14 |
| openlibrary.org | 202 | 3 | 21 | 383.9 | 0.806 | 18.44 |
| lx2.loc.gov:210 | 50 | 0 | 0 | 27.2 | 0.289 | 1.67 |
| catalogue.bnf.fr | 15 | 0 | 0 | 24.2 | 1.758 | 3.09 |
| services.dnb.de | 7 | 0 | 0 | 1.7 | 0.188 | 0.59 |
| es.wikipedia.org | 1 | 0 | 0 | 0.5 | 0.501 | 0.5 |
| ja.wikipedia.org | 1 | 0 | 0 | 0.3 | 0.347 | 0.35 |
| de.wikipedia.org | 1 | 0 | 0 | 0.5 | 0.452 | 0.45 |
| fr.wikipedia.org | 1 | 0 | 0 | 0.6 | 0.641 | 0.64 |
| ru.wikipedia.org | 1 | 0 | 0 | 0.4 | 0.442 | 0.44 |
| cs.wikipedia.org | 1 | 0 | 0 | 0.3 | 0.269 | 0.27 |
| pt.wikipedia.org | 1 | 0 | 0 | 0.3 | 0.252 | 0.25 |
| zh.wikipedia.org | 1 | 0 | 0 | 0.2 | 0.242 | 0.24 |
| ar.wikipedia.org | 1 | 0 | 0 | 0.3 | 0.332 | 0.33 |
| el.wikipedia.org | 1 | 0 | 0 | 0.4 | 0.434 | 0.43 |

### Choices made where the spec was silent

- **Entry titles.** For N1–N24 the original title is an entry (UC3), and N12 carries both *Der Process* and *Der Prozess* (§9 names the spelling variant). For the 16 existing books, entries are exactly those in STRATEGY's convergence sets and single cases.
- **Author string.** `query_author` is the form the regression tables use (existing books) or §9's form. When SBN had no record for an entry, the surname alone was tried and labelled; it recovered nothing.
- **A1 Open Library.** The spec's rule is reported as *strict*. A *keyed* author match (author key among Open Library's own author-search results) is reported beside it and marked `[keyed]`. The A3 listing uses the strict main work, then keyed, then the romanised or core original title, each labelled.
- **A3.** Listings cover strong SBN works only, as specified. Each book's SBN and Open Library listings ran in parallel, with books one after another. A completeness check pages the unfiltered work only when language pages return fewer BIDs than the total; that never happened.
- **A5.** Wikidata's original is read from the item Step 4 accepts for most of a book's entries. Year granularity; a tie at the earliest year is not a flag. N02 and N23 are reported, not scored.
- **A6.** The census is the union of normalised expression languages over the author-matching, title-matching, non-adaptation work clusters, plus the work's language. "Found" is the union of SBN `lingua[]` codes and Open Library edition language codes.
- **A7.** SBN authority = an exact name-token match, else a subset match, else the sole *Persona* result. VIAF = the most sources among same-name clusters. Wikidata = the first human (P31 Q5) from `wbsearchentities` in en/it plus the script's language.
- **Hand judgements** of which QID, W and Open Library key is the right work are listed and commented at the top of `stage1_analyse.py`.

### Open questions for the user

1. **Step 5 guard on classics.** It refuses correct works whose records are thinly linked (B 0.13–0.375). Loosening B is ruled out without your decision. Should the plan look for a second acceptance signal (e.g. agreement with the Wikidata item or VIAF work), or accept "no SBN identity" for these books?
2. **Non-Latin entry titles** (Доктор Живаго, 活着, بين القصرين, Ὀδύσσεια). Neither the OPAC nor Step 4's title test can use them. Support them, e.g. by resolving through Wikidata labels first, or declare UC3 Latin-script only?
3. **Census.** VIAF fails A6. Drop "found N of ~M known languages", or show it only where a VIAF census exists and is not smaller than what was found (17 of 37 books)?
4. **"First edition differs".** The listing rule is wrong 9 times in 36, from bad catalogue dates and missing originals. Should the flag require an explicit statement (Wikidata P577 earlier than the earliest original-language edition, or a ground-truth-style source), rather than the earliest date in the listings?
5. **N19.** Keep *Domani, e domani, e domani* as a negative entry in Stage 2, or replace it with the published Italian title?
6. **User-Agent.** A8 supports switching `net.USER_AGENT` to the contact form. That is a code change for a later step; confirm it goes into the plan.
7. **Stage 2 baselines.** 4 books (N07, N13, N16, N24) have no Open Library listing and 8 (E10, E11, E12, E13, E14, E15, N04, N23) have no SBN listing. Stage 2 will classify their losses against empty listings; is that the intended reading?

### Answers (user, 2026-09-15)

| # | Answer | Effect |
|---|---|---|
| 1 | **Second signal**: a refused or weak W is accepted when the Wikidata item Step 4 accepts for the same entry has a label, sitelink or P1476 matching W at ≥ 0.6. Loosening B was ruled out: the known wrong works (*Tesi*, *Angelus Novus*) sit at B = 0.5, above every refused classic (≤ 0.375) | none on Stage 2, which compares against the Stage 1 listings as they are. Measured on Stage 1 data (`results/stage-2/q1_second_signal.json`) **M**: rescues 7 of 16 refusals (E16 eng, N14 eng, N21 eng, N22 eng + ita, N23 eng + ita); 0 agreements in 2,024 cross-book pairs (weak control: few same-author pairs); the 3 wrong-W refusals have no Step 4 item and stay refused; positive control 44 of 47 strong entries agree. Misses: N12 × 3 (`prozess` vs "Der Prozess" 0.5), N17 eng (`bain el-qasrain.` vs "Bayn al-qasrayn" 0.0), N04 and E12 (no item). Article stripping and romanisation might recover N12 and N17: **untested** |
| 2 | **Latin script only; non-Latin titles and names are normalised to Latin** | `corpus.json` v2: the five non-Latin entry titles become the corpus romanisation (`Doktor Zhivago`, `Prestuplenie i nakazanie`, `Huozhe`, `Bayn al-Qasrayn`, `Odysseia`), the script form kept as `script_title`; author variants 村上春樹, Фёдор Достоевский, 한병철 dropped (their Latin forms are already variants). Reading, to confirm: names and titles that sources file in non-Latin script (Open Library 村上春樹, نجيب محفوظ; Wikidata P1476) are romanised before matching |
| 3 | **No census**: the result states the languages found plus a fixed note that catalogues are incomplete; "of ~M known" is dropped | none on Stage 2. Revises decision 1 (assessment §5); VIAF is not used |
| 4 | **No "first edition differs" inference**: the header shows the original and, always, "earliest edition found" (year, language, publisher), a statement about the catalogues. Editions dated before the original's known year are left out of it | none on Stage 2. Revises decision 2. Checked offline on the Stage 1 listings with the Step 4 item's P577 as the original's year (`results/stage-2/q4_earliest_found.json`) **M**, 37 books: the year and language of the first edition 22; the right year with other languages dated the same year 9 (E16 shows eng, ita, rus, spa at 1957; N01 eng, fre, ger, pol at 1984); later than the first edition 4 (E12 and N16, original not listed; E13, a different book listed; **N13, Wikidata's wrong P577 2024 left out the real 2012–2023 editions**); the right year with no language (E15) or the wrong one (N04, a CreateSpace "1866", no Wikidata year to filter it) 2; a date older than the first edition 0 |
| 5 | **Use the real title** | N19 `ita` entry becomes *Tomorrow, and tomorrow, and tomorrow* (Nord, 2023), the old title kept as `stage1_title`. It differs from the `eng` entry only in case, so the pair doubles as a cold-vs-cold noise floor, as N15's three *2666* entries do |
| 6 | **Yes**: switching `net.USER_AGENT` to the contact form goes into the plan | `lookup/net.py` stays unchanged during the benchmark; Stage 2 runs today's User-Agent |
| 7 | **Keep them as "difficult" control items** | Stage 2 runs them. Records found for a book with no Stage 1 listing in that source are reported apart from losses, each judged same work or not |

---

## Stage 1 per-book tables

### A1 — identity per (entry title, author)

| book | entry | title | Wikidata today | Wikidata Step 4 | SBN W · tier · A/B · B cost | Open Library |
|---|---|---|---|---|---|---|
| E01 | ita | Cent'anni di solitudine | Q178869 (right) | Q178869 (right) | cien anos de soledad · strong · A=0.0 B=0.669 [89, 133] · +11 req | /works/OL274505W (main) |
| E01 | eng | One Hundred Years of Solitude | Q178869 (right) | Q178869 (right) | cien anos de soledad · strong · A=0.0 B=0.722 [13, 18] · +1 req | /works/OL274505W (main) |
| E01 | spa | Cien años de soledad | Q178869 (right) | Q178869 (right) | cien anos de soledad · strong · A=1.0 B=None  · +0 req | /works/OL274505W (main) |
| E02 | ita | Verso un'ecologia della mente | Q1970551 (right) | Q1970551 (right) | steps to an ecology of mind · strong · A=0.0 B=0.846 [22, 26] · +3 req | None (none) |
| E02 | eng | Steps to an Ecology of Mind | Q1970551 (right) | Q1970551 (right) | steps to an ecology of mind · strong · A=1.0 B=None  · +0 req | /works/OL486424W (main) |
| E03 | ita | Rumori | None (none) | None (none) | bruits : essai sur l'economie poli · strong · A=0.0 B=1.0 [1, 1] · +1 req | /works/OL15764295W (split record) |
| E03 | eng | Noise | Q7047658 (right) | Q7047658 (right) | bruits : essai sur l'economie poli · strong · A=0.0 B=1.0 [1, 1] · +1 req | /works/OL685250W (main) |
| E03 | fre | Bruits | Q7047658 (right) | Q7047658 (right) | bruits : essai sur l'economie poli · strong · A=1.0 B=None  · +0 req | /works/OL685250W (main) |
| E04 | ita | Kafka sulla spiaggia | Q579744 (right) | Q579744 (right) | umibe no kafuka · strong · A=0.0 B=0.923 [12, 13] · +1 req | /works/OL2625431W (main [keyed]) |
| E04 | eng | Kafka on the Shore | Q579744 (right) | Q579744 (right) | umibe no kafuka · strong · A=0.0 B=0.667 [4, 6] · +1 req | /works/OL2625431W (main [keyed]) |
| E04 | jpn | Umibe no Kafuka | Q579744 (right) | None (none) | umibe no kafuka · strong · A=1.0 B=None  · +0 req | /works/OL2625431W (main [keyed]) |
| E05 | ita | L'invenzione delle notizie | None (none) | None (none) | invention of news · strong · A=0.0 B=1.0 [2, 2] · +1 req | None (none) |
| E05 | eng | The Invention of News | None (none) | None (none) | invention of news · strong · A=1.0 B=None  · +0 req | /works/OL19983430W (main) |
| E06 | ita | Più brillante del sole | None (none) | None (none) | more brilliant than the sun · strong · A=0.0 B=1.0 [1, 1] · +1 req | None (none) |
| E06 | eng | More Brilliant Than the Sun | None (none) | None (none) | more brilliant than the sun · strong · A=1.0 B=None  · +0 req | /works/OL2693265W (main) |
| E07 | ita | Modernità liquida | None (none) | None (none) | liquid modernity. · strong · A=0.0 B=0.812 [13, 16] · +2 req | /works/OL28769163W (split record) |
| E07 | eng | Liquid Modernity | Q19572648 (wrong) | None (none) | liquid modernity. · strong · A=1.0 B=None  · +0 req | /works/OL527224W (main) |
| E08 | ita | La matrice sociale della psichiatria | None (none) | None (none) | communication: the social matrix o · strong · A=0.0 B=1.0 [1, 1] · +1 req | None (none) |
| E08 | eng | Communication: The Social Matrix of Ps | None (none) | None (none) | communication: the social matrix o · strong · A=1.0 B=None  · +0 req | /works/OL12269244W (main) |
| E09 | ita | Il nome della rosa | Q172850 (right) | Q172850 (right) | nome della rosa · strong · A=1.0 B=None  · +0 req | /works/OL8996439W (main) |
| E09 | eng | The Name of the Rose | Q172850 (right) | Q172850 (right) | nome della rosa · strong · A=0.0 B=0.538 [14, 26] · +3 req | /works/OL8996439W (main) |
| E10 | ita | Opere | Q3204179 (wrong) | None (none) | canti · rejected · A=0.0 B=0.033 [2, 60] · +20 req | /works/OL15102110W (split record) |
| E11 | ita | Poesie | Q3786039 (wrong) | None (none) | tutte le poesie · rejected · A=0.5 B=0.0 [0, 45] · +15 req | /works/OL610110W (wrong) |
| E12 | ita | Tesi di filosofia della storia | Q1169425 (wrong) | None (none) | uber den begriff der geschichte · weak · A=0.0 B=0.5 [1, 2] · +1 req | None (none) |
| E13 | ita | Angelus Novus | Q330979 (wrong) | None (none) | schriften · weak · A=0.0 B=0.5 [9, 18] · +2 req | /works/OL156188W (split record) |
| E14 | ita | Per una economia positiva | None (none) | None (none) | — · no work · A=None B=None  · +0 req | None (none) |
| E15 | eng | The Essential Knuth | None (none) | None (none) | — · no work · A=None B=None  · +0 req | /works/OL36428365W (main) |
| E16 | ita | Il dottor Živago | Q206870 (right) | Q206870 (right) | doktor zivago · strong · A=0.5 B=0.618 [94, 152] · +12 req | /works/OL258301W (main) |
| E16 | eng | Doctor Zhivago | Q206870 (right) | Q206870 (right) | doktor zivago · weak · A=0.0 B=0.5 [9, 18] · +2 req | /works/OL258301W (main) |
| E16 | rus | Доктор Живаго | Q206870 (right) | None (none) | doktor zivago · rejected · A=0.0 B=None [0, 0] · +49 req | /works/OL258301W (main) |
| N01 | cze | Nesnesitelná lehkost bytí | Q917055 (right) | Q917055 (right) | nesnesitelna lehkost byti · strong · A=1.0 B=None  · +0 req | /works/OL8972751W (main) |
| N01 | eng | The Unbearable Lightness of Being | Q917055 (right) | Q917055 (right) | nesnesitelna lehkost byti · strong · A=0.0 B=1.0 [10, 10] · +1 req | /works/OL8972751W (main) |
| N01 | ita | L'insostenibile leggerezza dell'essere | Q917055 (right) | Q917055 (right) | nesnesitelna lehkost byti · strong · A=0.0 B=0.911 [72, 79] · +7 req | None (none) |
| N02 | fre | Le Petit Prince | Q25338 (right) | Q25338 (right) | petit prince · strong · A=1.0 B=None  · +0 req | /works/OL10263W (main) |
| N02 | eng | The Little Prince | Q25338 (right) | Q25338 (right) | petit prince · strong · A=0.5 B=0.526 [20, 38] · +4 req | /works/OL10263W (main) |
| N02 | ita | Il piccolo principe | Q25338 (right) | Q25338 (right) | petit prince · strong · A=0.0 B=0.612 [304, 497] · +45 req | /works/OL10263W (main) |
| N03 | ita | Se questo è un uomo | Q836036 (right) | Q836036 (right) | se questo e un uomo · strong · A=1.0 B=None  · +0 req | /works/OL860066W (main) |
| N03 | eng | If This Is a Man | Q836036 (right) | Q836036 (right) | se questo e un uomo · strong · A=0.0 B=0.875 [7, 8] · +1 req | /works/OL860066W (main) |
| N03 | eng-2 | Survival in Auschwitz | Q836036 (right) | None (none) | se questo e un uomo · strong · A=0.0 B=1.0 [4, 4] · +1 req | /works/OL860066W (main) |
| N04 | rus | Преступление и наказание | None (none) | None (none) | — · no work · A=None B=None  · +0 req | /works/OL166894W (main [keyed]) |
| N04 | eng | Crime and Punishment | None (none) | None (none) | prestuplenie i nakazanie · rejected · A=0.0 B=0.29 [9, 31] · +2 req | /works/OL166894W (main [keyed]) |
| N04 | ita | Delitto e castigo | None (none) | None (none) | prestuplenie i nakazanie · rejected · A=0.0 B=0.319 [152, 476] · +33 req | /works/OL166894W (main [keyed]) |
| N05 | eng | The Catcher in the Rye | Q183883 (right) | Q183883 (right) | catcher in the rye · strong · A=1.0 B=None  · +0 req | /works/OL3335245W (main) |
| N05 | ita | Il giovane Holden | Q183883 (right) | Q183883 (right) | catcher in the rye · strong · A=0.0 B=1.0 [42, 42] · +5 req | /works/OL3335245W (main) |
| N05 | ita-2 | Vita da uomo | Q183883 (right) | None (none) | catcher in the rye · strong · A=0.0 B=1.0 [1, 1] · +1 req | None (none) |
| N06 | eng | Nineteen Eighty-Four | Q208460 (right) | Q208460 (right) | nineteen eighty-four · strong · A=1.0 B=None  · +0 req | /works/OL1168083W (main) |
| N06 | ita | 1984 | Q208460 (right) | Q208460 (right) | nineteen eighty-four · strong · A=0.0 B=0.667 [120, 180] · +19 req | /works/OL1168007W (wrong) |
| N06 | ita-2 | Millenovecentottantaquattro | Q208460 (right) | None (none) | nineteen eighty-four · strong · A=0.0 B=0.667 [2, 3] · +5 req | None (none) |
| N07 | ita | Se una notte d'inverno un viaggiatore | Q1032190 (right) | Q1032190 (right) | se una notte d'inverno un viaggiat · strong · A=1.0 B=None  · +0 req | None (none) |
| N07 | eng | If on a Winter's Night a Traveler | Q1032190 (right) | Q1032190 (right) | se una notte d'inverno un viaggiat · strong · A=0.0 B=0.9 [9, 10] · +1 req | /works/OL15321W (main) |
| N08 | ita | L'amica geniale | Q22263533 (right) | Q22263533 (right) | amica geniale : infanzia, adolesce · strong · A=1.0 B=None  · +0 req | /works/OL16520879W (main) |
| N08 | eng | My Brilliant Friend | Q22263533 (right) | Q22263533 (right) | amica geniale : infanzia, adolesce · strong · A=0.0 B=1.0 [4, 4] · +1 req | /works/OL16520879W (main) |
| N09 | ita | Il formaggio e i vermi | Q1427187 (right) | Q1427187 (right) | formaggio e i vermi · strong · A=1.0 B=None  · +0 req | /works/OL14872792W (main) |
| N09 | eng | The Cheese and the Worms | Q1427187 (right) | Q1427187 (right) | formaggio e i vermi · strong · A=0.0 B=1.0 [2, 2] · +1 req | /works/OL14872792W (main) |
| N10 | fre | L'Étranger | Q163297 (right) | Q163297 (right) | etranger. · strong · A=1.0 B=None  · +0 req | /works/OL1230613W (main) |
| N10 | eng | The Stranger | Q163297 (right) | Q163297 (right) | etranger. · strong · A=0.0 B=1.0 [4, 4] · +1 req | /works/OL1230613W (main) |
| N10 | eng-2 | The Outsider | Q163297 (right) | None (none) | etranger. · strong · A=0.0 B=1.0 [4, 4] · +1 req | /works/OL1230613W (main) |
| N10 | ita | Lo straniero | Q163297 (right) | Q163297 (right) | etranger. · strong · A=0.0 B=0.978 [90, 92] · +10 req | /works/OL1230613W (main) |
| N11 | fre | La Disparition | Q595140 (right) | Q595140 (right) | disparition. · strong · A=1.0 B=None  · +0 req | /works/OL1715351W (main) |
| N11 | eng | A Void | Q595140 (right) | Q595140 (right) | — · no work · A=None B=None  · +0 req | /works/OL1715344W (split record) |
| N11 | ita | La scomparsa | Q595140 (right) | Q595140 (right) | disparition. · strong · A=0.0 B=0.667 [2, 3] · +1 req | None (none) |
| N12 | ger | Der Process | Q36097 (right) | Q36097 (right) | prozess · rejected · A=0.0 B=0.133 [2, 15] · +2 req | /works/OL498463W (main) |
| N12 | ger-2 | Der Prozess | Q36097 (right) | Q36097 (right) | prozess · rejected · A=0.5 B=0.234 [11, 47] · +4 req | /works/OL498463W (main) |
| N12 | eng | The Trial | Q36097 (right) | Q36097 (right) | prozess · rejected · A=0.0 B=0.312 [5, 16] · +1 req | /works/OL498556W (wrong) |
| N12 | ita | Il processo | Q36097 (right) | Q36097 (right) | prozess · strong · A=0.0 B=0.851 [172, 202] · +20 req | /works/OL498463W (main) |
| N13 | ger | Müdigkeitsgesellschaft | Q138528911 (right) | None (none) | mudigkeitsgesellschaft · strong · A=1.0 B=None  · +0 req | None (none) |
| N13 | eng | The Burnout Society | Q138528911 (right) | Q138528911 (right) | — · no work · A=None B=None  · +0 req | None (none) |
| N13 | ita | La società della stanchezza | None (none) | None (none) | mudigkeitsgesellschaft · strong · A=0.0 B=1.0 [4, 4] · +1 req | None (none) |
| N14 | por | Ensaio sobre a cegueira | Q826428 (right) | Q826428 (right) | ensaio sobre a cegueira · strong · A=1.0 B=None  · +0 req | /works/OL27420W (main) |
| N14 | eng | Blindness | Q826428 (right) | Q826428 (right) | ensaio sobre a cegueira · rejected · A=0.0 B=0.375 [3, 8] · +1 req | /works/OL27420W (main) |
| N14 | ita | Cecità | Q826428 (right) | Q826428 (right) | ensaio sobre a cegueira · strong · A=0.0 B=0.889 [32, 36] · +3 req | /works/OL26661744W (split record) |
| N15 | spa | 2666 | Q219437 (right) | Q219437 (right) | 2666. · strong · A=1.0 B=None  · +0 req | /works/OL712025W (main) |
| N15 | eng | 2666 | Q219437 (right) | Q219437 (right) | 2666. · strong · A=1.0 B=None  · +0 req | /works/OL712025W (main) |
| N15 | ita | 2666 | Q219437 (right) | Q219437 (right) | 2666. · strong · A=1.0 B=None  · +0 req | /works/OL712025W (main) |
| N16 | chi | 活着 | Q151919 (right) | None (none) | huozhe · rejected · A=0.0 B=None [0, 0] · +10 req | None (none) |
| N16 | eng | To Live | Q151919 (right) | Q151919 (right) | — · no work · A=None B=None  · +0 req | /works/OL3240289W (split record [keyed]) |
| N16 | ita | Vivere! | None (none) | None (none) | huozhe · strong · A=0.0 B=0.7 [7, 10] · +1 req | /works/OL28765493W (split record [keyed]) |
| N17 | ara | بين القصرين | Q3149381 (right) | None (none) | hikayat haratina · rejected · A=0.0 B=None [0, 0] · +27 req | /works/OL1599742W (main [keyed]) |
| N17 | eng | Palace Walk | Q3149381 (right) | Q3149381 (right) | bain el-qasrain. · rejected · A=0.0 B=0.333 [1, 3] · +1 req | /works/OL1599742W (main [keyed]) |
| N17 | ita | Tra i due palazzi | None (none) | None (none) | bain el-qasrain. · strong · A=0.0 B=0.857 [6, 7] · +1 req | /works/OL16621871W (split record [keyed]) |
| N18 | eng | Capitalist Realism | Q25519071 (right) | Q25519071 (right) | capitalist realism : is there no a · strong · A=1.0 B=None  · +0 req | /works/OL15683250W (main) |
| N18 | ita | Realismo capitalista | None (none) | None (none) | capitalist realism : is there no a · strong · A=0.0 B=0.667 [2, 3] · +1 req | /works/OL15683250W (main) |
| N19 | eng | Tomorrow, and Tomorrow, and Tomorrow | Q115818209 (right) | Q115818209 (right) | tomorrow, and tomorrow, and tomorr · strong · A=1.0 B=None  · +0 req | /works/OL26004554W (main) |
| N19 | ita | Domani, e domani, e domani | None (none) | None (none) | — · no work · A=None B=None  · +0 req | None (none) |
| N20 | eng | Metaphors We Live By | Q31067292 (right) | Q31067292 (right) | metaphors we live by. · strong · A=1.0 B=None  · +0 req | /works/OL1952983W (main) |
| N20 | ita | Metafora e vita quotidiana | Q3700692 (wrong) | None (none) | metaphors we live by. · strong · A=0.0 B=0.833 [5, 6] · +1 req | None (none) |
| N21 | spa | Veinte poemas de amor y una canción de | Q5219975 (right) | Q5219975 (right) | veinte poemas de amor y una cancio · strong · A=1.0 B=None  · +0 req | /works/OL979517W (main) |
| N21 | eng | Twenty Love Poems and a Song of Despai | Q5219975 (right) | Q5219975 (right) | veinte poemas de amor y una cancio · weak · A=0.0 B=0.5 [1, 2] · +1 req | /works/OL979517W (main) |
| N21 | ita | Venti poesie d'amore e una canzone dis | Q5219975 (right) | Q5219975 (right) | veinte poemas de amor y una cancio · strong · A=0.0 B=0.706 [12, 17] · +2 req | None (none) |
| N22 | fre | Le Capital au XXIe siècle | Q15991228 (right) | Q15991228 (right) | capital au xxie siecle · strong · A=1.0 B=None  · +0 req | /works/OL16814568W (main) |
| N22 | eng | Capital in the Twenty-First Century | Q15991228 (right) | Q15991228 (right) | capital au 21. siecle · weak · A=0.25 B=0.5 [1, 2] · +1 req | None (none) |
| N22 | ita | Il capitale nel XXI secolo | Q15991228 (right) | Q15991228 (right) | capital au xxie siecle · weak · A=0.0 B=0.5 [1, 2] · +1 req | None (none) |
| N23 | grc | Ὀδύσσεια | Q35160 (right) | None (none) | ilias · rejected · A=0.0 B=None [0, 0] · +151 req | /works/OL29477874W (wrong) |
| N23 | eng | The Odyssey | Q35160 (right) | Q35160 (right) | odyssea · rejected · A=0.0 B=0.271 [13, 48] · +12 req | /works/OL12818091W (wrong) |
| N23 | ita | Odissea | Q35160 (right) | Q35160 (right) | odyssea · rejected · A=0.0 B=0.296 [319, 1076] · +127 req | /works/OL43999507W (wrong) |
| N24 | ita | Tutto per una casa: dalla Russia alla  | None (none) | None (none) | tutto per una casa · strong · A=1.0 B=None  · +0 req | None (none) |

### A3 — listing by identity (cold)

| book | SBN rows/total · langs | SBN year | SBN publisher | SBN requests · wall · bogus lingua | OL rows · langs | OL year | OL publisher | OL language | OL requests · wall | book wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| E01 | 143/143 · 18 lang | 99% | 100% | 25 req · 2.5 s · ctl 0 | 208 · 15 lang | 98% | 97% | 78% | 1 req · 3.7 s | 3.7 |
| E02 | 26/26 · 4 lang | 96% | 100% | 7 req · 1.1 s · ctl 0 | 14 · 2 lang | 100% | 100% | 86% | 1 req · 9.1 s | 9.1 |
| E03 | 3/3 · 3 lang | 100% | 100% | 5 req · 0.8 s · ctl 0 | 7 · 2 lang | 100% | 100% | 86% | 1 req · 4.3 s | 4.3 |
| E04 | 20/20 · 7 lang | 100% | 100% | 9 req · 0.7 s · ctl 0 | 61 · 15 lang | 98% | 98% | 70% | 1 req · 5.1 s | 5.1 |
| E05 | 2/2 · 1 lang | 100% | 100% | 3 req · 0.9 s · ctl 0 | 3 · 1 lang | 100% | 100% | 100% | 1 req · 3.1 s | 3.1 |
| E06 | 1/1 · 1 lang | 100% | 100% | 3 req · 0.4 s · ctl 0 | 3 · 1 lang | 67% | 100% | 100% | 1 req · 7.7 s | 7.7 |
| E07 | 15/15 · 2 lang | 87% | 100% | 4 req · 0.5 s · ctl 0 | 6 · 1 lang | 100% | 100% | 67% | 1 req · 3.6 s | 3.6 |
| E08 | 1/1 · 1 lang | 100% | 100% | 3 req · 0.4 s · ctl 0 | 5 · 1 lang | 100% | 100% | 80% | 1 req · 18.4 s | 18.4 |
| E09 | 232/232 · 23 lang | 99% | 100% | 33 req · 6.7 s · ctl 0 | 151 · 12 lang | 100% | 99% | 83% | 1 req · 4.2 s | 6.7 |
| E10 | no strong work | — | — | — | 12 · 2 lang | 100% | 100% | 100% | 1 req · 6.4 s | 6.4 |
| E11 | no strong work | — | — | — | 19 · 2 lang | 100% | 100% | 100% | 1 req · 3.2 s | 3.2 |
| E12 | no strong work | — | — | — | 1 · 1 lang | 100% | 100% | 100% | 1 req · 2.8 s | 2.8 |
| E13 | no strong work | — | — | — | 2 · 1 lang | 100% | 100% | 100% | 1 req · 2.6 s | 2.6 |
| E14 | no strong work | — | — | — | 1 · 1 lang | 100% | 100% | 100% | 1 req · 5.5 s | 5.5 |
| E15 | no strong work | — | — | — | 1 · 0 lang | 100% | 100% | 0% | 1 req · 2.6 s | 2.6 |
| E16 | 126/126 · 9 lang | 98% | 99% | 15 req · 2.5 s · ctl 0 | 176 · 14 lang | 98% | 99% | 88% | 2 req · 5.1 s (2nd attempt) | 12.6 |
| N01 | 109/109 · 15 lang | 99% | 100% | 20 req · 4.9 s · ctl 0 | 81 · 14 lang | 96% | 96% | 84% | 1 req · 12.3 s | 12.3 |
| N02 | 613/613 · 49 lang | 97% | 100% | 74 req · 13.5 s · ctl 0 | 689 · 37 lang | 95% | 99% | 71% | 1 req · 5.9 s | 13.5 |
| N03 | 264/264 · 37 lang | 99% | 100% | 47 req · 9.0 s · ctl 0 | 112 · 13 lang | 97% | 97% | 76% | 1 req · 9.1 s | 9.1 |
| N04 | no strong work | — | — | — | 1179 · 22 lang | 99% | 100% | 89% | 3 req · 3.2 s (2nd attempt) | 13.8 |
| N05 | 92/92 · 13 lang | 100% | 100% | 18 req · 5.9 s · ctl 0 | 204 · 16 lang | 98% | 97% | 80% | 1 req · 6.0 s | 6.0 |
| N06 | 172/172 · 15 lang | 98% | 100% | 23 req · 9.5 s · ctl 0 | 537 · 22 lang | 98% | 99% | 70% | 1 req · 4.7 s | 9.5 |
| N07 | 141/141 · 32 lang | 100% | 100% | 36 req · 16.0 s · ctl 0 | no main work | — | — | — | — | 16.0 |
| N08 | 57/57 · 30 lang | 98% | 100% | 32 req · 13.4 s · ctl 0 | 40 · 5 lang | 100% | 98% | 52% | 1 req · 5.7 s | 13.4 |
| N09 | 27/27 · 5 lang | 100% | 100% | 8 req · 3.6 s · ctl 0 | 23 · 6 lang | 100% | 100% | 78% | 1 req · 2.0 s | 3.6 |
| N10 | 216/216 · 10 lang | 99% | 100% | 21 req · 9.0 s · ctl 0 | 468 · 20 lang | 99% | 98% | 88% | 1 req · 3.0 s | 9.0 |
| N11 | 4/4 · 2 lang | 100% | 100% | 4 req · 2.4 s · ctl 0 | 10 · 2 lang | 100% | 90% | 90% | 1 req · 3.3 s | 3.3 |
| N12 | 213/213 · 10 lang | 100% | 100% | 20 req · 8.2 s · ctl 0 | 783 · 19 lang | 98% | 99% | 82% | 1 req · 4.2 s | 8.2 |
| N13 | 4/4 · 1 lang | 100% | 100% | 3 req · 2.4 s · ctl 0 | no main work | — | — | — | — | 2.4 |
| N14 | 48/48 · 9 lang | 100% | 100% | 12 req · 4.8 s · ctl 0 | 40 · 7 lang | 100% | 100% | 85% | 1 req · 4.1 s | 4.8 |
| N15 | 11/11 · 4 lang | 100% | 100% | 6 req · 3.5 s · ctl 0 | 62 · 33 lang | 100% | 100% | 100% | 1 req · 5.5 s | 5.5 |
| N16 | 10/10 · 3 lang | 100% | 100% | 5 req · 3.3 s · ctl 0 | no main work | — | — | — | — | 3.3 |
| N17 | 8/8 · 3 lang | 100% | 100% | 5 req · 3.6 s · ctl 0 | 37 · 6 lang | 95% | 92% | 89% | 1 req · 15.2 s | 15.2 |
| N18 | 2/2 · 1 lang | 100% | 100% | 3 req · 4.2 s · ctl 0 | 8 · 4 lang | 100% | 100% | 88% | 1 req · 3.5 s | 4.2 |
| N19 | 7/7 · 2 lang | 100% | 100% | 4 req · 3.4 s · ctl 0 | 17 · 4 lang | 100% | 100% | 76% | 1 req · 3.3 s | 3.4 |
| N20 | 12/12 · 6 lang | 100% | 100% | 8 req · 4.3 s · ctl 0 | 7 · 3 lang | 100% | 100% | 100% | 1 req · 3.4 s | 4.3 |
| N21 | 21/21 · 4 lang | 100% | 100% | 6 req · 4.5 s · ctl 0 | 135 · 5 lang | 99% | 100% | 70% | 1 req · 5.5 s | 5.5 |
| N22 | 2/2 · 2 lang | 100% | 100% | 4 req · 3.0 s · ctl 0 | 20 · 4 lang | 100% | 100% | 60% | 1 req · 2.6 s | 3.0 |
| N23 | no strong work | — | — | — | 1 · 1 lang | 100% | 100% | 100% | 1 req · 3.9 s | 3.9 |
| N24 | 1/1 · 1 lang | 100% | 100% | 3 req · 4.2 s · ctl 0 | no main work | — | — | — | — | 4.2 |

### A5 — original vs first edition

| book | Wikidata original (Step 4 item) | vs ground truth | ground truth | earliest overall / in original language (listings) | earliest rows | flag | expected | outcome |
|---|---|---|---|---|---|---|---|---|
| E01 | Q178869: Cien años de soledad · spa · 1967 | ✓ | spa 1967 | 1967 / 1967 (tie with another language) | SBN BVE0917706 spa Buenos Aires : Editorial sudamericana, 1; OL /books/OL48124364M ? ['Penguin'] 1967 | False | False | right |
| E02 | Q1970551: Steps to an Ecology of Mind · eng · 1972 | ✓ | eng 1972 | 1972 / 1972 | SBN UTO1471790 eng San Francisco [etc.] : Chandler, c1972; OL /books/OL18229195M eng ['Ballantine Books'] 1972 | False | False | right |
| E03 | Q7047658: Bruits: essai sur l'economie politique de la musique · fre · 1977 | ✓ | fre 1977 | 1977 / 1977 | SBN RAV0708340 fre Vendôme : Presses universitaires de Fran; OL /books/OL4625368M fre ['Presses universitaires de France'] 197 | False | False | right |
| E04 | Q579744: 海辺のカフカ · jpn · 2002 | ✓ | jpn 2002 | 2001 / 2002 | OL /books/OL8904254M eng ['Audiofy/Naxos'] 2001 | True | False | false flag |
| E05 | no item accepted | — | eng 2014 | 2014 / 2014 | OL /books/OL29232448M eng ['Yale University Press'] 2014; OL /books/OL29225404M eng ['Yale University Press'] 2014 | False | False | right |
| E06 | no item accepted | — | eng 1998 | 1998 / 1998 | OL /books/OL450084M eng ['Quartet Books'] 1998 | False | False | right |
| E07 | no item accepted | — | eng 2000 | 2000 / 2000 (tie with another language) | SBN MIL0479747 eng Cambridge : Polity ; Oxford ; Malden : B; OL /books/OL50559844M ? ['Polity Press'] 2000 | False | False | right |
| E08 | no item accepted | — | eng 1951 | 1951 / 1951 | OL /books/OL17880054M eng ['Norton'] 1951 | False | False | right |
| E09 | Q172850: Il nome della rosa · ita · 1980 | ✓ | ita 1980 | 1980 / 1980 | SBN PAL0220225 ita Milano : CDE, 1980; SBN RAV0047653 ita Milano : Bompiani, 1980 | False | False | right |
| E12 | no item accepted | — | ger 1942 | 2010 / 2010 | OL /books/OL25049991M ger ['Suhrkamp'] 2010 | False | False | right |
| E13 | no item accepted | — | ita 1962 | 1966 / None | OL /books/OL16404576M ger ['Suhrkamp'] 1966; OL /books/OL20304391M ger ['Suhrkamp'] 1966 | True | False | false flag |
| E14 | no item accepted | — | fre 2013 | 2013 / 2013 | OL /books/OL31149107M fre ['Fayard'] 2013 | False | False | right |
| E15 | no item accepted | — | eng 2013 | 2013 / None | OL /books/OL49221860M ? ['Lonely Scholar'] August 1, 2013 | True | False | false flag |
| E16 | Q206870: Доктор Живаго · rus · 1957 | ✓ | rus 1958 / first ita 1957 | 1957 / 1957 (tie with another language) | SBN RAV0064624 ita Milano : Feltrinelli, 1957; SBN UM10038453 ita Milano : Feltrinelli, 1957 | False | True | missed |
| N01 | Q917055: Nesnesitelná lehkost bytí · cze · 1984 | ✓ | cze 1985 / first fre 1984 | 1984 / 1985 | SBN RLZ0100986 eng London ; Boston : Faber and Faber, 1984; SBN UBO2232068 eng London ; Boston : Faber and Faber, 1984 | True | True | right |
| N02 | Q25338: Le Petit Prince · fre · 1943 | ✓ | fre 1943 / first eng 1943 | 1943 / 1943 (tie with another language) | SBN PUV1602239 eng New York : Harcourt Brace & World, 1943; SBN PUV1602240 fre New York : Harcourt, Brace & World, 1943 | False | True | report only |
| N03 | Q836036: Se questo è un uomo · ita · 1946 | ✗ year | ita 1947 | 1912 / 1947 | SBN IEI0481234 dut Amsterdam : Meulenhoff, 1912 | True | False | false flag |
| N04 | no item accepted | — | rus 1867 | 1866 / 1917 | OL /books/OL56178734M eng ['CreateSpace Independent Publishing Pla; OL /books/OL56260359M eng ['CreateSpace Independent Publishing Pla | True | False | false flag |
| N05 | Q183883: The Catcher in the Rye · eng · 1951 | ✓ | eng 1951 | 1945 / 1945 | OL /books/OL16677355M eng ['Little, Brown and Co.'] 1945 | False | False | right |
| N06 | Q208460: Nineteen Eighty-Four · eng · 1949 | ✓ | eng 1949 | 1949 / 1949 (tie with another language) | SBN GRO0000910 eng London : Penguin Books, 1949; OL /books/OL60620826M ? ['Books & Coffee'] 1949 | False | False | right |
| N07 | Q1032190: Se una notte d'inverno un viaggiatore · ita · 1979 | ✓ | ita 1979 | 1979 / 1979 | SBN FER0136648 ita Torino : Einaudi, c1979; SBN RAV0002500 ita Torino : Einaudi, [1979] | False | False | right |
| N08 | Q22263533: L'amica geniale · ita · 2011 | ✓ | ita 2011 | 2011 / 2011 | SBN SBS0000682 ita Roma : E/O, 2011; OL /books/OL62515388M ita ['Edizioni e/o'] October 1, 2011 | False | False | right |
| N09 | Q1427187: Il formaggio e i vermi · ita · 1976 | ✓ | ita 1976 | 1976 / 1976 | SBN RAV0120901 ita Torino : Einaudi, [1976]; SBN ANA0179197 ita Torino : Einaudi, c1976 | False | False | right |
| N10 | Q163297: L'Étranger · fre · 1942 | ✓ | fre 1942 | 1942 / 1942 | SBN RMS1931647 fre Paris : Gallimard, 1942, stampa 1993; SBN LO10779691 fre [Paris! : Gallimard, c1942 | False | False | right |
| N11 | Q595140: La Disparition · fre · 1969 | ✓ | fre 1969 | 1969 / 1969 | OL /books/OL19589815M fre ['Denoël'] 1969; OL /books/OL12452067M fre ['Denoel'] 1969 | False | False | right |
| N12 | Q36097: Der Prozeß · ger · 1925 | ✓ | ger 1925 | 1825 / 1925 | OL /books/OL51067170M eng ['CreateSpace Independent Publishing Pla | True | False | false flag |
| N13 | Q138528911: La sociedad del cansancio · spa · 2024 | ✗ title,lang,year | ger 2010 | 2012 / None | SBN RAV1957566 ita Roma : Nottetempo, 2012 | True | False | false flag |
| N14 | Q826428: Ensayo sobre a ceguera · por · 1995 | ✗ title | por 1995 | 1995 / 1995 (tie with another language) | SBN RAV2097773 ger München : Random House, 1995; SBN MIL0288581 por Lisboa : Caminho, 1995 | False | False | right |
| N15 | Q219437: 2666 · spa · 2004 | ✓ | spa 2004 | 2004 / 2004 | SBN TO01362318 spa Barcelona : Anagrama, [2004]; OL /books/OL61536868M spa ['Círculo de Lectores'] 2004 | False | False | right |
| N16 | Q151919: 活着 · chi · 1993 | ✓ | chi 1993 | 1994 / 2010 | SBN TSA1644885 fre [Paris : Caractères, 1994] | True | False | false flag |
| N17 | Q3149381: بين القصرين (Bayn al-qasrayn) · ara · 1956 | ✓ | ara 1956 | 1956 / 1956 | SBN USM2040668 ara al-Qāhira : Maktabat Miṣr, [tra il 1956  | False | False | right |
| N18 | Q25519071: Capitalist Realism · eng · 2009 | ✓ | eng 2009 | 2009 / 2009 (tie with another language) | OL /books/OL36800373M eng ['Hunt Publishing Limited, John'] 2009; OL /books/OL30920499M por ['Autonomia Literária'] 2009, 2020 | False | False | right |
| N19 | Q115818209: Tomorrow, and Tomorrow, and Tomorrow · eng · 2022 | ✓ | eng 2022 | 2022 / 2022 (tie with another language) | SBN PCM0037140 eng Dublin : Vintage, 2022; SBN MOD1754482 eng London : Chatto & Windus, 2022 | False | False | right |
| N20 | Q31067292: Metaphors We Live By · eng · None | ✓ (no year) | eng 1980 | 1980 / 1980 | SBN MIL0182712 eng Chicago and London : The University of C; OL /books/OL20680018M eng ['University of Chicago Press'] 1980 | False | False | right |
| N21 | Q5219975: Veinte poemas de amor y una canción desesperada · spa · 1924 | ✓ | spa 1924 | 1924 / 1924 | OL /books/OL6735230M spa ['Chile, Nascimento'] 1924 | False | False | right |
| N22 | Q15991228: Le Capital au XXIe siècle · fre · 2013 | ✓ | fre 2013 | 2013 / 2013 (tie with another language) | OL /books/OL27180385M fre ['Éditions du Seuil'] 2013; OL /books/OL25619817M eng ['Éditions du Seuil, Harvard University  | False | False | right |
| N23 | Q35160: Ὀδύσσεια · grc · None | ✓ (no year) | grc None | 1488 / None | OL /books/OL40578004M eng ['Independently Published'] 1488 | True | None | report only |
| N24 | no item accepted | — | ita 2009 | 2009 / 2009 | SBN VIA0219276 ita Silea : Piazza, 2009 | False | False | right |

### A6 — VIAF census

| book | work clusters | census langs | langs found (SBN ∪ OL) | found not in census | census not found | documented | state |
|---|---|---|---|---|---|---|---|
| E01 | 1 | 33 | 21 | 3 | 15 | 46 | census ≥ found |
| E02 | 2 | 7 | 4 | 0 | 3 | — | census ≥ found |
| E03 | 1 | 1 | 3 | 2 | 0 | — | census < found |
| E04 | 1 | 6 | 17 | 12 | 1 | — | census < found |
| E05 | 2 | 2 | 2 | 1 | 1 | — | census ≥ found |
| E06 | 0 | 0 | 2 | 2 | 0 | — | unavailable |
| E07 | 1 | 8 | 2 | 0 | 6 | — | census ≥ found |
| E08 | 2 | 3 | 2 | 1 | 2 | — | census ≥ found |
| E09 | 2 | 21 | 23 | 8 | 6 | 40 | census < found |
| E10 | 1 | 0 | 2 | 2 | 0 | — | not scored |
| E11 | 0 | 0 | 2 | 2 | 0 | — | not scored |
| E12 | 2 | 6 | 1 | 0 | 5 | — | census ≥ found |
| E13 | 4 | 3 | 1 | 0 | 2 | — | census ≥ found |
| E14 | 0 | 0 | 1 | 1 | 0 | — | unavailable |
| E15 | 0 | 0 | 0 | 0 | 0 | — | unavailable |
| E16 | 2 | 14 | 18 | 9 | 5 | — | census < found |
| N01 | 1 | 26 | 17 | 4 | 13 | — | census ≥ found |
| N02 | 2 | 54 | 60 | 25 | 19 | 600 | census < found |
| N03 | 2 | 10 | 38 | 28 | 0 | — | census < found |
| N04 | 1 | 28 | 22 | 6 | 12 | — | census ≥ found |
| N05 | 1 | 30 | 21 | 3 | 12 | — | census ≥ found |
| N06 | 3 | 22 | 26 | 11 | 7 | 65 | census < found |
| N07 | 1 | 17 | 32 | 18 | 3 | — | census < found |
| N08 | 4 | 15 | 30 | 18 | 3 | — | census < found |
| N09 | 2 | 5 | 9 | 5 | 1 | — | census < found |
| N10 | 1 | 34 | 23 | 6 | 17 | 68 | census ≥ found |
| N11 | 1 | 10 | 3 | 1 | 8 | — | census ≥ found |
| N12 | 1 | 29 | 23 | 5 | 11 | — | census ≥ found |
| N13 | 1 | 13 | 1 | 0 | 12 | 35 | census ≥ found |
| N14 | 1 | 8 | 11 | 5 | 2 | — | census < found |
| N15 | 1 | 8 | 33 | 25 | 0 | — | census < found |
| N16 | 0 | 0 | 3 | 3 | 0 | — | unavailable |
| N17 | 0 | 0 | 7 | 7 | 0 | — | unavailable |
| N18 | 1 | 9 | 4 | 3 | 8 | — | census ≥ found |
| N19 | 0 | 0 | 4 | 4 | 0 | — | unavailable |
| N20 | 2 | 8 | 6 | 0 | 2 | — | census ≥ found |
| N21 | 2 | 3 | 6 | 3 | 0 | — | census < found |
| N22 | 1 | 13 | 5 | 1 | 9 | — | census ≥ found |
| N23 | 1 | 37 | 1 | 0 | 36 | — | not scored |
| N24 | 0 | 0 | 1 | 1 | 0 | 0 | unavailable |

### A7 — author identity

| person | variants | SBN name authority | VIAF | Open Library | Wikidata | SBN surname probe (first persons) |
|---|---|---|---|---|---|---|
| Gregory Bateson | 1 | one (CFIV034892); Latin forms one | one (56605567); same-name clusters ≤4 | top OL30388A (41 works): raw search all, resolve_author_keys all | one (Q314252) | Bateson , Alan N.; Bateson , Beatrice; Bateson , Catherine; Bateson , Claire |
| Haruki Murakami | 3 | split (LO1V086706); Latin forms one | one (108238901); same-name clusters ≤4 | top OL382524A (534 works): raw search all, resolve_author_keys not all | one (Q134798) | Kresin-Murakami , Jutta; Masashi , Murakami; Murakami , Akira; Murakami , Ana Maria Brandão |
| Fyodor Dostoevsky | 4 | split (CFIV001049); Latin forms one | one (104023256); same-name clusters ≤0 | top OL22242A (2822 works): raw search all, resolve_author_keys not all | one (Q991) | Ašimbaeva , Natal'ja Tujmebaevna; Coldefy-Faucard , Anne; Dostoevskaja , Anna Grigorʹevna; Dostoevskaja , Ljubov' Fedorovna |
| Elena Ferrante | 1 | one (RAVV076631); Latin forms one | one (32103009); same-name clusters ≤4 | top OL3105889A (40 works): raw search all, resolve_author_keys all | one (Q368127) | Adessoscrivo; Agnelli Soardi , Ferrante   <ballerino>; Albergotti , Ferrante  <fl. 1621>; Ambivere , Ferrante : d' |
| Jacques Attali | 1 | one (CFIV023341); Latin forms one | one (101721040); same-name clusters ≤1 | top OL53916A (158 works): raw search all, resolve_author_keys all | one (Q364315) | Araujo-Attali , Luisa; Attali , Arlette; Attali , Bernard; Attali , Erieta |
| Umberto Eco | 1 | one (CFIV006213); Latin forms one | one (108299403); same-name clusters ≤2 | top OL20735A (511 works): raw search all, resolve_author_keys all | one (Q12807) | Alfonzo , Antonio; Arbore , Giuseppe  <1945- >; Attinà , Rocco; Barbacci , Dante |
| Kodwo Eshun | 1 | one (UM1V031295); Latin forms one | one (79471390); same-name clusters ≤4 | top OL276117A (15 works): raw search all, resolve_author_keys all | one (Q113174) | Eshun , Ekow; Eshun , I. T.; Eshun , Kodwo; Hamaguchi , Eshun |
| Byung-Chul Han | 3 | split (RAVV673297); Latin forms one | one (37059891); same-name clusters ≤1 | top OL295822A (56 works): raw search not all, resolve_author_keys not all | split (Q495875) | 'Abd al-Mu'id Han , Muhammad; Abu Talib Han; Abu Talib Han ibn Muhammad Istahani; Abulghazi Behadir Han , Khan av Khorezm |
| Gabriel García Márquez | 2 | one (CFIV002730); Latin forms one | one (54147956); same-name clusters ≤2 | top OL27363A (441 works): raw search all, resolve_author_keys all | one (Q5878) | Garcia Marquez , Vicente; Garcia-Escudero Marquez , Piedad; García de Castro Márquez , Carmelo; García de Castro Márquez , Emilio |

### A8 — Wikimedia User-Agent

| phase | UA | requests | 429 | stalls > 5 s | p50 s | p95 s |
|---|---|---|---|---|---|---|
| alternating | A | 60 | 27 | 0 | 0.152 | 0.296 |
| alternating | B | 60 | 0 | 0 | 0.194 | 0.343 |
| block-AB-A | A | 60 | 40 | 0 | 0.118 | 0.344 |
| block-AB-B | B | 60 | 0 | 0 | 0.21 | 0.407 |
| block-BA-B | B | 60 | 0 | 0 | 0.196 | 0.371 |
| block-BA-A | A | 60 | 35 | 0 | 0.12 | 0.319 |

---

## Stage 2

### Verdict

| # | Assumption | Metric (96 entry runs; 91 scored, E10/E11 generic titles and N23 insights excluded) | Fail criterion | Result | Evidence |
|---|---|---|---|---|---|
| A2 | Listing by identity loses nothing today's tool finds | Distinct records today's run shows outside the book's Stage 1 listing: SBN **not linked to W 334** (301 no uniform title, 33 another uniform title) · Open Library **separate work record 98** · **wrong-work leak in today's tool 44** (SBN 27, OL 17) · other 10 (9 volumes with other works, 1 excerpt) · **unexplained 0**. Books with no Stage 1 listing: SBN 243 (199 same work, 42 leaks, 2 other), OL 29 (same work). Cold wall per entry: today median **34.5 s** (p90 58.4, max 112.4), identity **3.5 s** (p90 5.7, max 28.5); identity slower in **2 of 96** (N02 ita 28.5 vs 15.8 s, N06 ita 17.6 vs 16.5 s). Requests per entry, median: 192 vs 19 | an unexplained loss, or listing by identity slower cold than today | **PASS**, latency read overall (answer 1). Per entry it would fail: 2 slower entries. No unexplained loss | M; record classes V (OPAC record detail, control: bogus BID → `data: null`) + 161 hand judgements (`judgements.STAGE2`) |

### What each result means

**Losses: listing by identity does drop records today's tool shows.**
- **334 SBN records of the same book are not linked to W**, against 2,575 listed SBN rows for the same books. Largest: E16 56, N12 55, E01 47, N06 42, N02 39, N21 30.
  - Today's routes that found them (a record may carry several): Wikidata title 207, author sweep 119, translation evidence 83, ISBN 25. Leaving aside 'same Open Library work' and 'translation evidence', one route alone found 276: Wikidata title 167, author sweep 99, ISBN 10.
  - Languages: ita 86, eng 77, spa 60, ger 38, fre 35, rus 23.
  - The 33 under another uniform title are split authorities: N08 `L'amica geniale` vs W `amica geniale : infanzia, adolescenza`; N17 a third transliteration, `Bayan al-Qasrayn`; N01 a Chinese translation under the French `L'insoutenable légèreté de l’être`; N14 `Ensaio sobre Cegueira.`.
- **98 Open Library editions sit in duplicate work records** with the same title: E16 3 works / 24 editions, N04 7 / 21, N12 3 / 14, N02 2 / 8.
- **44 records are wrong-work leaks in today's tool**, and the listing correctly lacks them:
  - 21 through the wrong Wikidata item today's resolver picks (E07 *Liquid Love*, E12 *Das Kunstwerk…*, N20 *Where Mathematics Comes From*);
  - 4 through Open Library sibling + Dewey (E01 *Crónica de una muerte anunciada*, N03 *Così fu Auschwitz*);
  - 1 through an ISBN match (N14: Veltroni's *Buonvino e il caso del bambino scomparso*);
  - 18 neighbouring books, adaptations and studies with similar titles: E09 *Postille a Il nome della rosa*, N14 *Ensaio sobre a lucidez*, N08 volume 2 and two graphic-novel adaptations, N12 the Gide–Barrault play and Pinter's screenplay, N02 two retellings, N05 a critical commentary, E16 a film booklet, E02 *A Sacred Unity*, N22 *Peut-on sauver l'Europe?*.
- Evidence: OPAC record detail for 1,005 BIDs (1,011 requests, 4 connect timeouts retried); the works of all 164 lost Open Library editions came from the runs' own cached `editions.json`, work titles from 54 requests. Same-work judgement is title similarity ≥ 0.6 to the book's known titles or uniform titles, overridden by hand; the linked-to-W test is full-title similarity ≥ 0.9 between the record's uniform title and W.
- Reverse direction, not an A2 metric: listing records a run lacks sum to SBN 5,087 and OL 11,985 over the 91 scored runs. The OL figure is an upper bound: today merges an Open Library edition into an SBN record by ISBN and keeps only the SBN link.

**Books with no Stage 1 listing (answer 7).** Today's fallback routes carry them, with leaks: E12 SBN 39 (36 *Das Kunstwerk* leaks through Wikidata, 3 same work); E13 SBN 15 (12 same, 3 leaks); E14 SBN 1 same; N04 SBN 188 (183 same work, 2 volumes with other works, 3 leaks); N07 OL 17, N13 OL 9, N16 OL 3, all same work.

**Latency.**
- The two slower entries: N02 ita spent 19.3 s on identity, where the guard's B paged 497 records (54 requests) and the OPAC needed 7 connect-timeout retries; N06 ita waited 14.9 s on one Open Library `editions.json` (537 editions). Neither is the SBN listing.
- Today's runs that met no Wikimedia 429 (33): today median 15.8 s (p90 27.0), identity 3.7 s (p90 8.3) on the same entries.
- The comparison leans against identity on politeness (gated: OPAC 4 at a time, Open Library 1 request a second; today ungated) and toward it on the User-Agent (contact form; today's own).

**User-Agent control (A8 inside the pipeline, 16 entries).**
- Today's agent met 1–2 Wikimedia 429s in 9 of 16 runs; the contact agent none. Medians: 41.1 s → 11.5 s on those 9, 15.9 s → 15.0 s on the other 7.
- Over all 110 today runs: 101 Wikimedia retries on 429 (it 41, en 42, wikidata 18); Wikimedia took 3,054 s of 8,802 s request time (35%). Contact-agent runs: 40 s of 1,056 s (3.8%). The Stage 1 inference that "Wikipedia stalls" are `Retry-After` sleeps is now **M**.
- Records do not depend on it: overlap 1.0 in 13 of 15 pairs (E01 ita 0.959, N08 eng 0.872; N13 eng empty both times).

**Convergence** (assessment §2's metric; lowest Jaccard over a book's entry pairs, 32 books with ≥ 2 entries).
- Today: median lowest overlap 0.658 on all records (30 books, N15 and N19 left out), 0.634 on SBN records; 0.0 for N04 SBN, N13 and N17, N02 SBN 0.024, N12 SBN 0.132. E01 reproduces §2: 0.662 / 0.375 (§2: 0.668 / 0.380).
- Identity: 1.0 in 22 of 32 books. Below 1 exactly where one entry's guard is not strong: E16 0.583, N14 0.455, N11 0.714, N12 0.786, N17 0.804, N04 0.856, N21 0.865, N22 0.909, N13 0.0, N16 0.0.
- Noise floor: identical titles run cold (N15 × 3, N19 eng/ita) give 1.0 on both paths, so today's differences between entry titles are not run-to-run noise.

**Romanised entries (answer 2)**, identity path, against the script titles of Stage 1:

| entry | SBN Stage 1 (script) | SBN Stage 2 (romanised) | Wikidata Step 4 | today records |
|---|---|---|---|---|
| E16 rus *Doktor Zhivago* | `doktor zivago` rejected | `doktor zivago` rejected (A 0.5, B 0.4) | Q206870 | 126 |
| N04 rus *Prestuplenie i nakazanie* | no work | **`prestuplenie i nakazanie` strong** (A 1.0) | none | 133 |
| N16 chi *Huozhe* | `huozhe` rejected | **`huozhe` strong** (A 1.0) | none | 13 |
| N17 ara *Bayn al-Qasrayn* | `hikayat haratina` rejected (wrong) | **`bayn al-qasrayn` strong** (A 1.0) | Q3149381 | 6 |
| N23 grc *Odysseia* | `ilias` rejected (wrong) | `odyssea` rejected (A 0.0, B 0.222) | Q35160 | 42 |

The romanisation decides: SBN writes `zivago` (ISO 9) and `odyssea` (Latin); the corpus's `Zhivago` and `Odysseia` miss them.

**Author-only runs (14 Latin variants).** Variants of one person give the same rows: Murakami 1.0, Dostoevskij / Dostoevsky 1.0 (0.872 against Dostoïevski), Han 1.0, García Márquez 0.98. 17 (Eshun) to 307 (Eco) rows, 2.3–30.3 s, 6–152 requests; `SBN partial (3 request(s) failed)` once (P09 1). Rows are titles, not works (assessment §2); not scored.

**Source states.** No request failed at the HTTP level in either path after urllib3's retries (today: mobile gateway ConnectTimeout 5, NameResolution 6, Protocol 13; identity: OPAC ConnectTimeout 7). The pipeline's own `Tally` still reported `SBN partial (1 request(s) failed)` in 10 runs, every entry of E04, N03 and N12: one failure per book that is not a failed HTTP request, likely an error payload (STRATEGY Step 3) **I**.

### Contradicting the assessment or STRATEGY.md

1. **Assessment §7, steps 4 and 6**: listing by identity plus a fallback "only when no strong identity exists" loses 334 same-work SBN records and 98 Open Library editions that today's tool shows for books *with* a strong identity. STRATEGY's Settled row ("SBN links are partial", one book) holds corpus-wide. **M/V**
2. **STRATEGY "Measured pipeline behaviour"** (SBN 75.5% of request time, Wikipedia 4.1%, Wikidata 0.2%; cold 45–111 s): SBN 55%, Wikimedia 35%, Open Library 10%; cold median 34.5 s, max 112.4 s, 7 of 96 entry runs over 60 s. With the contact User-Agent, Wikimedia is 3.8%. The Wikimedia share is throttling, not the network layer. **M**
3. **HANDOFF §2 / CLAUDE.md rule 10** ("cold 35–50 s"): median 34.5 s, p90 58.4 s, max 112.4 s over 96 entries. **M**
4. **Assessment §4** ("17 s instead of 52 s" for *Cent'anni*): identity plus listing 3.5–4.1 s; today 13.6–39.1 s. **M**

### Choices made where the spec was silent

- **Runs.** `stage2_today.py` runs one process per entry, calling `book_editions.main()` with docs/Task.md's argv. Its session logs without the politeness gates and keeps today's User-Agent, so the pipeline's latency is its own. Each run starts with a fresh cache.
- **Listing by identity was re-measured per entry** (`stage2_newpath.py`): the SBN guard, Wikidata Step 4 (contact agent, answer 6), Open Library author keys and original-title search, then the SBN listing of a strong W and the Open Library editions. It runs gated, with the bogus-language control. The original title comes from the corpus. The two paths ran back to back, their order alternating. Losses are still judged against the Stage 1 listings, as specified.
- **User-Agent control**: 16 entries fixed before the runs, one per book, mixed sizes, in rotating order.
- **Full reports** (57 MB + 10 MB) live in `bench/raw/stage-2/runs*`, gitignored. Committed: `meta*/`, `newpath/`, `losses.json`, `loss_evidence.json`, `summary.json`, `tables.md`, and `bench/baseline/` (structural fields; STRATEGY Step 1 names `tests/baseline/`).
- **Hand judgements**: 161, in `bench/judgements.py`, which now also holds Stage 1's. E10, E11 and N23 are left partly unjudged and unscored.
- **Author-only runs**: the 14 Latin-script variants; no loss classification, since no per-author listing exists.
- **Interruption**: the first orchestrator was killed by the machine's memory pressure after 178 of 222 runs (later runs peaked at ≤ 73 MB). The interrupted run (N18 ita, today) was redone about 45 minutes after its pair.

### Open questions for the user

1. **A2 latency verdict.** Identity was slower in 2 of 96 entries (causes above) and 8.8× faster at the median. Read the criterion per entry (FAIL) or overall (PASS)?
2. **Records SBN has not linked to W.** 334 same-work records would drop out of the planned listing. Add a recovery route beside it, today's Wikidata-title and sweep candidates admitted only by title ≥ 0.6 against the work's titles (STRATEGY Step 9's shape), or accept the loss? The Wikidata-title route is also the largest source of leaks (21 of 44), so it would need Step 4's rule.
3. **Open Library duplicate works.** 98 editions sit in 2–7 duplicate work records per classic. List every work whose title and author match (one more `editions.json` per duplicate), or the main work only?
4. **Romanisation.** `Doktor Zhivago` and `Odysseia` miss SBN's `zivago` and `odyssea`. Fold transliteration variants when matching (zh/ž/z, -eia/-ea), or accept a miss when the typed form differs from the catalogue's?

---

### Answers (user, 2026-09-15)

| # | Answer | Effect |
|---|---|---|
| 1 | **Latency is judged overall: A2 passes.** A lookup that is slow for a known reason must say so | Proposal for the plan, **untested**: the network layer records, per lookup, what made it slow (urllib3 retries and their cause, `Retry-After` sleeps, requests over 10 s, pages fetched); when a cold lookup exceeds about 10 s (identity p90 5.7 s), `report.notes` names only causes measured in that lookup, e.g. "Slow: SBN needed 7 connection retries" or "Slow: Open Library took 14.9 s to answer one request". A live status line in the web UI would need the server to stream progress |
| 2 | **Add a recovery route.** The project's first need is to reach every edition of a book, or as close as possible | The plan keeps today's candidate routes beside the listing for books with a strong work, admitting a record only by title against the work's titles (STRATEGY Step 9's shape). The Wikidata-title route needs Step 4's rule: it brought 21 of the 44 leaks. **Untested**: how many of the 334 + 98 same-work records and of the 44 leaks a title gate admits can be measured offline on `results/stage-2/losses.json` |
| 3 | Open: the user asked for the cons of listing every Open Library work whose title and author match | none yet |
| 4 | **Fold spelling variants** (zh/ž/z, -eia/-ea and the like) to reach more editions | Plan item, **untested**: matching folds transliteration variants, so *Doktor Zhivago* can meet `doktor zivago` and *Odysseia* `odyssea`. It also raises match scores between different titles, so the gate counterexamples (*L'ordine delle notizie*, *Quale socialismo, quale Europa*) are re-checked |

---

## Stage 2 tables

### Losses by class

Records are counted once per run; distinct counts each (book, source, id) once. Books marked * (E10, E11 generic titles; N23 insights) are excluded.

| source · class | records | distinct |
|---|---|---|
| OL · no OL listing | 51 | 29 |
| OL · other | 2 | 1 |
| OL · separate OL work record | 246 | 98 |
| OL · wrong-work leak | 18 | 17 |
| SBN · no SBN listing | 333 | 243 |
| SBN · not linked to W | 689 | 334 |
| SBN · other | 22 | 9 |
| SBN · wrong-work leak | 43 | 27 |

### Per book

Entry values are in corpus order. Listing = Stage 1 listing size (— = none). Losses are distinct records. Overlap = lowest Jaccard over entry pairs. Requests = today·identity.

| book | entries | today records | listing records today lacks (SBN·OL) | SBN listing | OL listing | losses (distinct) | overlap today all | overlap today SBN | overlap identity | today s | identity s | requests | source states |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E01 | 3 | 241 / 241 / 243 | 81·52 / 96·66 / 69·56 | 143 | 208 | OL separate OL work record 4; SBN not linked to W 47; SBN wrong-work leak 3 | 0.662 | 0.375 | 1.0 | 17.3 / 13.6 / 39.1 | 4.1 / 3.7 / 3.5 | 207·48 / 203·38 / 210·37 | ok |
| E02 | 2 | 36 / 37 | 10·6 / 9·6 | 26 | 14 | OL separate OL work record 4; SBN not linked to W 7; SBN wrong-work leak 1 | 0.973 | 0.96 | 1.0 | 57.5 / 30.2 | 3.0 / 3.1 | 195·21 / 196·19 | ok |
| E03 | 3 | 10 / 10 / 10 | 1·1 / 0·1 / 0·1 | 3 | 7 | OL separate OL work record 2 | 0.818 | 0.667 | 1.0 | 12.7 / 22.2 / 53.5 | 3.8 / 4.0 / 4.2 | 177·18 / 190·19 / 190·18 | ok |
| E04 | 3 | 13 / 13 / 16 | 8·61 / 8·61 / 5·61 | 20 | 61 | SBN not linked to W 1 | 0.812 | 0.812 | 1.0 | 43.3 / 10.5 / 35.1 | 4.5 / 4.1 / 3.1 | 185·22 / 185·22 / 185·21 | SBN partial (1 request(s) failed) |
| E05 | 2 | 4 / 4 | 0·2 / 0·2 | 2 | 3 | SBN not linked to W 1 | 1.0 | 1.0 | 1.0 | 53.7 / 7.2 | 2.7 / 3.0 | 71·14 / 74·13 | ok |
| E06 | 2 | 4 / 4 | 0·1 / 0·1 | 1 | 3 | SBN not linked to W 1 | 1.0 | 1.0 | 1.0 | 36.8 / 48.0 | 2.7 / 2.9 | 30·12 / 36·14 | ok |
| E07 | 2 | 8 / 13 | 8·5 / 8·5 | 15 | 6 | OL wrong-work leak 2; SBN wrong-work leak 3 | 0.615 | 0.7 | 1.0 | 14.9 / 27.3 | 2.9 / 3.2 | 180·16 / 195·16 | ok |
| E08 | 2 | 11 / 12 | 0·0 / 0·0 | 1 | 5 | OL separate OL work record 3; SBN not linked to W 3 | 0.917 | 1.0 | 1.0 | 57.0 / 11.7 | 2.7 / 3.2 | 178·14 / 191·14 | ok |
| E09 | 2 | 169 / 174 | 180·34 / 174·46 | 232 | 151 | SBN not linked to W 6; SBN wrong-work leak 5 | 0.581 | 0.21 | 1.0 | 41.1 / 19.2 | 4.5 / 4.1 | 212·45 / 200·48 | ok |
| E10 * | 1 | 83 | —·4 | — | 12 | OL separate OL work record 1; OL wrong-work leak 2; SBN no SBN listing 72 | — | — | — | 58.4 | 3.3 | 189·32 | ok |
| E11 * | 1 | 33 | —·19 | — | 19 | OL separate OL work record 4; SBN no SBN listing 29 | — | — | — | 11.8 | 3.5 | 186·27 | ok |
| E12 | 1 | 50 | —·1 | — | 1 | OL wrong-work leak 11; SBN no SBN listing 39 | — | — | — | 34.5 | 3.2 | 203·13 | ok |
| E13 | 1 | 15 | —·2 | — | 2 | SBN no SBN listing 15 | — | — | — | 54.2 | 3.2 | 187·14 | ok |
| E14 | 1 | 1 | —·1 | — | 1 | SBN no SBN listing 1 | — | — | — | 26.0 | 3.4 | 167·10 | ok |
| E15 | 1 | 1 | —·0 | — | 1 | 0 | — | — | — | 10.6 | 3.2 | 170·11 | ok |
| E16 | 3 | 103 / 126 / 126 | 72·176 / 81·176 / 81·176 | 126 | 176 | OL separate OL work record 24; SBN not linked to W 56; SBN other 2; SBN wrong-work leak 1 | 0.547 | 0.46 | 0.583 | 41.8 / 32.4 / 58.8 | 3.8 / 3.5 / 3.4 | 201·39 / 197·14 / 198·13 | ok |
| N01 | 3 | 107 / 92 / 98 | 54·30 / 73·29 / 66·28 | 109 | 81 | SBN not linked to W 4 | 0.739 | 0.59 | 1.0 | 112.4 / 22.0 / 19.2 | 3.5 / 3.4 / 3.7 | 207·32 / 201·33 / 203·38 | ok |
| N02 | 3 | 472 / 484 / 457 | 504·334 / 526·341 / 528·325 | 613 | 689 | OL separate OL work record 8; SBN not linked to W 39; SBN wrong-work leak 2 | 0.622 | 0.024 | 1.0 | 60.6 / 37.6 / 15.8 | 6.1 / 5.5 / 28.5 | 213·86 / 200·90 / 213·131 | ok |
| N03 | 3 | 176 / 159 / 163 | 170·30 / 182·39 / 178·40 | 264 | 112 | OL separate OL work record 1; SBN not linked to W 1; SBN other 2; SBN wrong-work leak 1 | 0.654 | 0.517 | 1.0 | 41.3 / 29.8 / 27.0 | 14.5 / 8.9 / 8.3 | 214·59 / 203·60 / 203·60 | SBN partial (1 request(s) failed) |
| N04 | 3 | 133 / 52 / 120 | —·1179 / —·1179 / —·1179 | — | 1179 | OL separate OL work record 21; SBN no SBN listing 188 | 0.018 | 0.0 | 0.856 | 93.9 / 38.9 / 16.3 | 11.8 / 7.9 / 5.2 | 194·35 / 199·15 / 196·45 | ok |
| N05 | 3 | 208 / 195 / 196 | 30·59 / 46·56 / 45·56 | 92 | 204 | SBN wrong-work leak 1 | 0.91 | 0.746 | 1.0 | 24.6 / 72.2 / 27.7 | 4.2 / 5.7 / 4.8 | 194·30 / 192·35 / 190·32 | ok |
| N06 | 3 | 465 / 473 / 460 | 50·202 / 65·194 / 89·207 | 172 | 537 | OL separate OL work record 5; SBN not linked to W 42 | 0.781 | 0.445 | 1.0 | 19.4 / 16.5 / 34.4 | 3.9 / 17.6 / 3.6 | 204·35 / 203·54 / 199·39 | ok |
| N07 | 2 | 107 / 49 | 50·— / 111·— | 141 | — | OL no OL listing 17; SBN not linked to W 3 | 0.405 | 0.351 | 1.0 | 44.4 / 54.2 | 6.1 / 4.4 | 210·47 / 201·48 | ok |
| N08 | 2 | 73 / 44 | 9·23 / 41·20 | 57 | 40 | OL other 1; OL wrong-work leak 1; SBN not linked to W 4; SBN wrong-work leak 2 | 0.519 | 0.382 | 1.0 | 18.3 / 39.4 | 4.0 / 4.5 | 205·44 / 202·45 | ok |
| N09 | 2 | 35 / 31 | 10·5 / 14·5 | 27 | 23 | 0 | 0.886 | 0.765 | 1.0 | 14.9 / 54.7 | 3.2 / 3.1 | 199·20 / 198·21 | ok |
| N10 | 4 | 94 / 41 / 46 / 93 | 122·468 / 175·468 / 170·468 / 125·468 | 216 | 468 | OL separate OL work record 2 | 0.324 | 0.33 | 1.0 | 51.4 / 49.4 / 11.9 / 13.2 | 4.2 / 4.0 / 4.1 / 4.4 | 191·33 / 181·34 / 183·34 / 190·43 | ok |
| N11 | 3 | 20 / 20 / 20 | 0·4 / 0·4 / 0·4 | 4 | 10 | OL separate OL work record 4; SBN not linked to W 6 | 1.0 | 1.0 | 0.714 | 56.7 / 51.8 / 47.7 | 3.0 / 2.8 / 3.6 | 192·16 / 191·12 / 192·17 | ok |
| N12 | 4 | 96 / 121 / 96 / 120 | 174·783 / 161·783 / 174·783 / 107·783 | 213 | 783 | OL separate OL work record 14; SBN not linked to W 55; SBN other 1; SBN wrong-work leak 2 | 0.181 | 0.132 | 0.786 | 15.6 / 35.0 / 52.4 / 70.5 | 4.4 / 4.8 / 4.1 / 4.8 | 193·14 / 195·16 / 193·13 / 202·52 | SBN partial (1 request(s) failed) |
| N13 | 3 | 10 / 0 / 11 | 2·— / 4·— / 2·— | 4 | — | OL no OL listing 9; SBN not linked to W 1 | 0.0 | 0.0 | 0.0 | 25.8 / 15.9 / 23.5 | 3.5 / 2.3 / 3.0 | 122·13 / 107·10 / 111·14 | ok |
| N14 | 3 | 70 / 35 / 37 | 17·11 / 24·40 / 22·40 | 48 | 40 | OL separate OL work record 3; SBN not linked to W 6; SBN wrong-work leak 3 | 0.458 | 0.8 | 0.455 | 59.2 / 32.5 / 16.2 | 3.1 / 3.3 / 3.3 | 206·24 / 196·13 / 196·26 | ok |
| N15 | 3 | 54 / 54 / 54 | 4·20 / 4·20 / 4·20 | 11 | 62 | SBN not linked to W 5 | 1.0 | 1.0 | 1.0 | 57.4 / 31.2 / 59.4 | 4.3 / 3.5 / 3.3 | 181·18 / 181·18 / 181·18 | ok |
| N16 | 3 | 13 / 12 / 6 | 1·— / 2·— / 4·— | 10 | — | OL no OL listing 3; SBN not linked to W 1 | 0.462 | 0.6 | 0.0 | 18.3 / 30.1 / 42.6 | 3.2 / 3.3 / 3.1 | 188·17 / 187·12 / 168·17 | ok |
| N17 | 3 | 6 / 6 / 6 | 7·37 / 7·37 / 3·37 | 8 | 37 | OL separate OL work record 1; SBN not linked to W 5 | 0.0 | 0.0 | 0.804 | 60.2 / 12.3 / 34.2 | 3.3 / 3.7 / 3.3 | 185·15 / 184·12 / 178·16 | ok |
| N18 | 2 | 7 / 6 | 1·5 / 1·6 | 2 | 8 | SBN not linked to W 3 | 0.857 | 1.0 | 1.0 | 49.6 / 11.4 | 3.5 / 3.0 | 184·16 / 172·15 | ok |
| N19 | 2 | 19 / 19 | 1·5 / 1·5 | 7 | 17 | SBN not linked to W 1 | 1.0 | 1.0 | 1.0 | 7.3 / 54.0 | 3.9 / 3.0 | 76·16 / 76·16 | ok |
| N20 | 2 | 14 / 12 | 0·5 / 5·7 | 12 | 7 | OL wrong-work leak 3; SBN wrong-work leak 2 | 0.368 | 0.5 | 1.0 | 46.2 / 58.2 | 3.1 / 3.0 | 86·20 / 87·20 | ok |
| N21 | 3 | 151 / 149 / 149 | 9·32 / 11·32 / 11·32 | 21 | 135 | OL separate OL work record 2; SBN not linked to W 30; SBN other 4 | 0.987 | 0.957 | 0.865 | 20.1 / 31.9 / 44.4 | 3.7 / 3.7 / 3.6 | 204·18 / 202·13 / 202·19 | ok |
| N22 | 3 | 23 / 23 / 23 | 0·6 / 0·6 / 0·6 | 2 | 20 | SBN not linked to W 6; SBN wrong-work leak 1 | 1.0 | 1.0 | 0.909 | 54.8 / 9.3 / 35.4 | 3.1 / 3.4 / 3.2 | 130·16 / 130·13 / 129·12 | ok |
| N23 * | 3 | 42 / 145 / 153 | —·1 / —·1 / —·1 | — | 1 | OL separate OL work record 12; SBN no SBN listing 292 | 0.0 | 0.0 | 1.0 | 51.5 / 63.1 / 25.8 | 3.3 / 3.6 / 18.2 | 184·24 / 198·25 / 205·139 | ok |
| N24 | 1 | 1 | 0·— | 1 | — | 0 | — | — | — | 3.5 | 2.5 | 16·11 | ok |

### Cold latency

| path | n | median s | p90 s | max s | total s |
|---|---|---|---|---|---|
| today's pipeline | 96 | 34.5 | 58.4 | 112.4 | 3456.8 |
| listing by identity | 96 | 3.5 | 5.7 | 28.5 | 437.4 |
| today's pipeline, runs with no Wikimedia 429 | 33 | 15.8 | 27.0 | 41.3 | 570.6 |
| listing by identity, same entries | 33 | 3.7 | 8.3 | 28.5 | 181.2 |

Identity slower than today in 2 entries ([('N02__ita', 15.8, 28.5), ('N06__ita', 16.5, 17.6)]); median ratio today / identity 8.8.

### User-Agent control (today's pipeline, same entry)

| run | today s | contact UA s | identity s | Wikimedia 429 today | Wikimedia 429 contact UA | overlap all | overlap SBN |
|---|---|---|---|---|---|---|---|
| E01__ita | 17.3 | 15.0 | 4.1 | 0 | 0 | 0.959 | 0.94 |
| E02__ita | 57.5 | 11.5 | 3.0 | 1 | 0 | 1.0 | 1.0 |
| E03__eng | 22.2 | 11.5 | 4.0 | 2 | 0 | 1.0 | 1.0 |
| E06__eng | 48.0 | 7.6 | 2.9 | 1 | 0 | 1.0 | 1.0 |
| E09__ita | 41.1 | 18.7 | 4.5 | 2 | 0 | 1.0 | 1.0 |
| E14__ita | 26.0 | 9.6 | 3.4 | 1 | 0 | 1.0 | 1.0 |
| E16__ita | 41.8 | 11.7 | 3.8 | 2 | 0 | 1.0 | 1.0 |
| N02__ita | 15.8 | 15.9 | 28.5 | 0 | 0 | 1.0 | 1.0 |
| N03__ita | 41.3 | 48.0 | 14.5 | 0 | 0 | 1.0 | 1.0 |
| N06__ita | 16.5 | 17.3 | 17.6 | 0 | 0 | 1.0 | 1.0 |
| N08__eng | 39.4 | 19.6 | 4.5 | 2 | 0 | 0.872 | 0.84 |
| N10__ita | 13.2 | 10.8 | 4.4 | 2 | 0 | 1.0 | 1.0 |
| N12__ita | 70.5 | 49.5 | 4.8 | 2 | 0 | 1.0 | 1.0 |
| N13__eng | 15.9 | 14.0 | 2.3 | 0 | 0 | — | — |
| N18__ita | 11.4 | 11.6 | 3.0 | 0 | 0 | 1.0 | 1.0 |
| N24__ita | 3.5 | 4.9 | 2.5 | 0 | 0 | 1.0 | 1.0 |

### Author-only runs

| run | variant | rows | wall s | requests | sources |
|---|---|---|---|---|---|
| P01__1 | Gregory Bateson | 84 | 8.3 | 57 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P02__1 | Murakami Haruki | 230 | 30.3 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P02__2 | Haruki Murakami | 230 | 21.2 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P03__1 | Fëdor Dostoevskij | 247 | 28.6 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P03__2 | Fyodor Dostoevsky | 247 | 19.8 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P03__3 | Dostoïevski | 249 | 13.2 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P04__1 | Elena Ferrante | 174 | 12.0 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P05__1 | Jacques Attali | 268 | 8.5 | 149 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P06__1 | Umberto Eco | 307 | 21.8 | 152 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P07__1 | Kodwo Eshun | 17 | 2.3 | 6 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P08__1 | Byung-Chul Han | 103 | 6.4 | 65 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P08__2 | Han Byung-Chul | 103 | 8.5 | 65 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |
| P09__1 | Gabriel García Márquez | 249 | 27.6 | 129 | Open Library ok; SBN partial (3 request(s) failed); Wikidata skipped (not needed for an author search) |
| P09__2 | Garcia Marquez | 252 | 9.6 | 129 | Open Library ok; SBN ok; Wikidata skipped (not needed for an author search) |

Overlap of work-row titles between variants of one person: P02__1~P02__2 1.0; P03__1~P03__2 1.0; P03__1~P03__3 0.872; P03__2~P03__3 0.872; P08__1~P08__2 1.0; P09__1~P09__2 0.98

### Requests per host — today's pipeline

Retries are urllib3's, inside one logged request.

| host | requests | failed | total s | retries |
|---|---|---|---|---|
| opac.sbn.it/opacmobilegw | 14774 | 0 | 4748.3 | ConnectTimeoutError×5, NameResolutionError×6, ProtocolError×13 |
| openlibrary.org | 1132 | 0 | 882.9 | 0 |
| opac.sbn.it/o | 349 | 0 | 116.5 | ProtocolError×1 |
| it.wikipedia.org | 284 | 0 | 1150.9 | 429×41 |
| en.wikipedia.org | 271 | 0 | 1173.1 | 429×42 |
| www.wikidata.org | 176 | 0 | 730.1 | 429×18 |

### Requests per host — today's pipeline, contact UA

Retries are urllib3's, inside one logged request.

| host | requests | failed | total s | retries |
|---|---|---|---|---|
| opac.sbn.it/opacmobilegw | 2332 | 0 | 838.1 | ProtocolError×4 |
| openlibrary.org | 186 | 0 | 144.5 | 0 |
| opac.sbn.it/o | 92 | 0 | 33.3 | 0 |
| it.wikipedia.org | 47 | 0 | 12.7 | 0 |
| en.wikipedia.org | 44 | 0 | 12.8 | 0 |
| www.wikidata.org | 27 | 0 | 14.5 | 0 |

### Requests per host — listing by identity

Retries are urllib3's, inside one logged request.

| host | requests | failed | total s | retries |
|---|---|---|---|---|
| opac.sbn.it/o | 1695 | 0 | 598.5 | ConnectTimeoutError×7, ProtocolError×1 |
| openlibrary.org | 289 | 0 | 226.6 | 0 |
| it.wikipedia.org | 284 | 0 | 75.3 | 0 |
| en.wikipedia.org | 271 | 0 | 78.3 | 0 |
| www.wikidata.org | 177 | 0 | 90.5 | 0 |

### Requests per host — author-only runs

Retries are urllib3's, inside one logged request.

| host | requests | failed | total s | retries |
|---|---|---|---|---|
| opac.sbn.it/opacmobilegw | 1650 | 3 | 836.3 | ConnectTimeoutError×23, ProtocolError×2 |
| openlibrary.org | 14 | 0 | 18.1 | 0 |
