# Handoff — book_editions

Context for picking this project up cold. `README.md` covers usage; this covers
**why it is the way it is**, what was tried and rejected, and what is still weak.

---

## 1. What the tool is for

Given a book title **in any language**, show when the work first appeared and
every edition since, grouped by language. That answers, in one view:

- when was this originally published, and in what language
- does a translation exist, and how long after the original did it arrive
- which editions exist, from whom, in what year
- where can I get a copy — in print, or from an Italian library

The second of those is the one the tool exists for, stated by the user directly:
*discover a book, then find out whether an Italian translation exists before
deciding which one to buy.* That sentence is worth keeping in view — going from
an original to its translation was quietly broken for most of the build (§4,
*The forward path*), and nothing in the output said so.

Italian is the focus of the data work, not of the framing: it is the language
with a good national catalogue (SBN) and no API, so most of the engineering went
there. It is displayed as one language among the rest.

An **author with no title** is a different question — every book they wrote,
rather than every edition of one book — and takes a separate pipeline.

### Framing history (important)

The tool originally led with a verdict: *"Translated into Italian."* The user
rejected that framing outright — it answers one narrow question and buries what
the editions actually tell you. It is now a **publication history**. If you find
yourself re-adding a yes/no hero, that is a regression in intent, not a feature.

---

## 2. Running it

```bash
pip install requests          # the only dependency
python server.py              # http://localhost:8000
python book_editions.py "Noise" --author "Jacques Attali"
python book_editions.py --author "Gregory Bateson"
```

- **No API keys.** All three sources are keyless.
- Responses cache to `.cache/` for 24h. A cold lookup takes **30–45s**; a repeat
  is ~0.03s. Delete `.cache/` to refresh.
- `pkill -f server.py` to stop it. **Not** `pkill -f "python3 server.py"` —
  macOS reports the process as `Python server.py`, so that pattern never
  matches, and a stale instance keeps serving the modules it imported at start
  while looking perfectly healthy. This wasted time twice.

---

## 3. Architecture

```
book_editions.py   CLI entry point (210 lines)
server.py          ThreadingHTTPServer: /api/* + static web/ (164)
lookup/
  net.py           thread-local pooled Session, disk cache, Tally (132)
  matching.py      normalise/score titles, author display (112)
  langs.py         one language vocabulary across 3 sources (105)
  models.py        Edition, Overview, TitleCluster, Report (165)
  wikidata.py      bidirectional title crosswalk (284)
  openlibrary.py   editions, works, Dewey (283)
  sbn.py           SBN/ICCU client + parsers (254)
  buylinks.py      deterministic retailer deep links (47)
  pipeline.py      orchestration, scoring, disambiguation (1061)
web/               index.html (50), app.js (579), style.css (695)
```

Both front ends render the same `Report`. Anything that is *phrasing* rather
than data belongs in the pipeline — `overview.origin` and `overview.ambiguous`
exist because the alternative was the CLI and the web UI wording the same
sentence separately, and being fixed separately, and drifting again (§7).

The visual rules are stated at the top of `web/style.css` and are not
decoration: two inks with fixed meanings, and no boxes or fills anywhere.
Read that header before touching the UI.

**Why there is a backend at all:** SBN sends **no `Access-Control-Allow-Origin`
header of any kind**, so a browser cannot call it from a static page. The server
is forced, not chosen. It also means one origin, so no CORS anywhere.

**Why the cache is load-bearing:** one lookup fans out over dozens of requests
(15+ SBN `full.json` calls alone). Without the cache the tool is unusable to
iterate on and impolite to the catalogues.

---

## 4. The central problem

**No free catalogue records a link between a translation and its original.**
Verified, not assumed:

- Open Library has no `translation_of` field. `/works/OL15764295W.json`
  (*Rumori*) contains only `title`, `authors`, `type`, `revision` — nothing
  pointing at `OL685250W` (*Bruits*). It also splits translations into separate
  works and has duplicate author records (three "Jacques Attali":
  `OL53916A` 160 works, `OL4762242A` 17, `OL12549002A` 1).
- SBN records carry no uniform or original title. Checked six full records. The
  only translation trace is a free-text note naming the translator.
- Wikidata's `P629`/`P747` coverage is too thin to rely on.

And **cross-language title similarity is worthless**: `title_similarity('Noise',
'Rumori')` is exactly `0.0`.

### The three bridges

| Bridge | Precision | Recall |
|---|---|---|
| **Wikidata via Wikipedia sitelinks/labels** | high | needs a Wikipedia article |
| **Dewey + full authorship agreement** | good | needs both catalogues to classify it |
| **Shared ISBN** | exact | modern books only |

Any one suffices. Dewey is the interesting one because it is **numeric, hence
language-neutral**: *Bruits/Noise* is `306.484`/`780.07` in Open Library and
SBN's *Rumori* is `780.07` — an exact match between titles sharing not one word.

> **A correction worth not repeating.** Wikidata was initially dismissed after
> testing `wbsearchentities` + SPARQL `P629` on one obscure title. That was the
> wrong probe. The **Wikipedia sitelink/label path** works in both directions and
> is a core component: `One Hundred Years of Solitude` → `Q178869` → `labels.it`
> = *Cent'anni di solitudine*, and the reverse. Prefer `labels.it` over sitelink
> titles — sitelinks carry disambiguators (`itwiki` for `Q208460` is
> `1984 (romanzo)`, the label is `1984`).

### The forward path (and why it was missing)

Wikidata is the only step that hands back an **author** for free. When it has
never heard of the work, `author` stayed `None` — and every author-keyed bridge
below it was then skipped: no SBN author sweep, no sibling titles. Open Library
had already named the author of the work it matched; the pipeline simply never
picked it up.

That is what made the tool asymmetric, and the asymmetry defeated its main use
case — find a book in its original language, ask whether it is worth buying in
Italian instead:

| Query | Before | Why |
|---|---|---|
| *L'invenzione delle notizie* | eng + ita | SBN holds that exact title, and an SBN record names its authors, which the reverse path (below) then works from |
| *The Invention of News* | **eng only** | SBN files the translation under its Italian title, so the title probe missed it — and with no author there was no sweep to catch it either |

The same book, both times. The fix is four lines: adopt Open Library's author
when Wikidata gave none. Only when the matched works **agree** on one, though —
a title as ambiguous as *Noise* resolves to several unrelated works, and taking
whichever came back first would sweep SBN for a bibliography at random.

Both directions now report eng 2014 + ita 2015 (Einaudi), matched on Dewey
`070.9`/`070.09`.

### The identifying-signal gate

An edition is reported **only if** something ties it to *this* work: a shared
ISBN, a title match ≥ 0.6 against a known variant, or Dewey agreement.
Same-author-same-era is not enough — *Quale socialismo, quale Europa* is Attali
in 1977, same as *Bruits*, and a different book. Without this gate an author
sweep drags in everything the author ever wrote.

This gate applies to **title** lookups only. An author search has no single work
to identify, so everything by the author belongs in the answer.

### The reverse path

When Wikidata knows nothing, there is no foreign title to search with. SBN gives
the **authors** and a **Dewey class**, which is enough: *La matrice sociale della
psichiatria* → Ruesch and Bateson at `616.89` → their *Communication* at ddc
`616.89` in Open Library. It returns a **synthesised cluster**, which the
pipeline adopts as if it came from Wikidata, so role assignment, the span marked
"original" and the displayed title all follow it. Flagged `inferred` in the UI,
because it is a weaker claim than a catalogued one.

Dewey at that granularity is coarse (`616.89` is all of psychiatry), so **every
credited author must match too** — that is what keeps Ruesch's unrelated
*Therapeutic communication* out. Run **per record, never pooled**: two SBN
records can share an Italian title and be different books (that exact title is
Ruesch/Bateson 1976 *and* Michael Shepherd 1990), so pooling their authors
demands a work by all three and finds nothing.

---

## 5. Reverse-engineered SBN API — the expensive knowledge

`https://opac.sbn.it/opacmobilegw` — the undocumented ICCU mobile-app gateway,
the only JSON interface SBN exposes. Works over HTTPS.

| Fact | Detail |
|---|---|
| `search.json` params | `any`, `title`, `author`, `subject`, `isbn`, `type`, `start`, `rows`. Multi-word = AND. |
| Rejected params | `titolo`, `autore` → validation error. |
| **Silent-failure trap** | Unknown params are **silently ignored** and the unfiltered set is returned. Only ever send whitelisted names (`sbn.PARAMS`). |
| `rows` | Honoured to at least 500. ~60ms, no rate limiting observed. |
| **`full.json?bid=<SHORTBID>`** | Undocumented detail endpoint. **Only `bid` works** — `id`, `cid`, `codiceIdentificativo` all rejected. |
| Only the full record has | `linguaPubblicazione`, `classificazioneDewey`, `nomi`, `note`, `numeri`, `collezione`, `descrizioneFisica`, `localizzazioni` (holdings). The brief record has **no language**, which is why candidates must be enriched. |
| Facets returned | `level`, `tiporec`, `nomef`, `soggettof`, `luogof`, `lingua`, `paese`, with counts. |
| **Facets cannot filter** | `lingua=ita`, `fq=`, `facet=`, `refine=`, `facetName/facetValue`, `paese=it` — every form ignored. Filtering is local. |
| **No CORS** | No `Access-Control-Allow-Origin` at all. |
| Permalink | `https://opac.sbn.it/bid/MIL0871878`. Short BID = `codiceIdentificativo` minus `IT\ICCU\`, segments joined. |

### SBN data traps

1. **`paesePubblicazione` is not a language.** `CFI1172094` is an English
   *Nineteen Eighty-Four* published in Pesaro: `linguaPubblicazione: INGLESE`,
   `paesePubblicazione: ITALIA`. Only `linguaPubblicazione` is trustworthy.
2. **Translator evidence is often only in free text.** `CFI1183309` has no
   `[Traduttore]` in `nomi`; the only trace is
   *"…traduzione italiana a cura di Boris Yousef."* in `note`.
3. **Invisible control characters.** Non-sorting articles are wrapped in `\x88`
   … `\x89` (`'\x88Il \x89disoriente'`). Strip C0/C1 controls from every text
   field.
4. **Multiple Dewey codes run together** with no separator:
   `'616.89 (18.) PSICHIATRIA616.85 (19.) MALATTIE…'`. A letter-to-digit
   transition is **not** a `\b`, so a word-boundary regex reads `616.85` as `85`.
5. **Field names lie about content.** In `localizzazioni`, the library name is in
   `shelfmark` and the city is in `invNum`.
6. **`tipo` distinguishes media.** Used to exclude films/maps. See §7.

### Other sources

- **Open Library** — `Access-Control-Allow-Origin: *`. `language=ita` works.
  `publisher=` works. Year ranges via Solr `q=first_publish_year:[1975 TO 1980]`.
  **`title=` will not match a title carrying its subtitle** — searching
  `Noise: The Political Economy of Music` returns zero docs while `Noise`
  returns the work, so several search strategies are pooled per variant.
  `ddc:` is **not** queryable; Dewey must be compared locally.
- **Wikidata/Wikipedia** — keyless, CORS-enabled. `action=query&prop=pageprops`
  for exact titles, `list=search` for fuzzy, then `wbgetentities` (**up to 50
  ids in one request** — validating one at a time cost ~38s per cold lookup).
  Claims used: `P1476` title, `P407` language of work, `P577` date, `P50`
  author, `P655` translator.
- **Google Books — removed.** Needs a key nobody has by default, its keyless
  quota is permanently exhausted (`429 Quota exceeded … Queries per day`), and
  the matching rests entirely on the other three. Do not re-add it without a
  reason beyond "more sources".

---

## 6. Decisions and why

| Decision | Reason |
|---|---|
| Python stdlib + `requests`, no framework | Single dependency; SBN forces a backend anyway |
| Disk cache, 24h TTL | Cold lookup is 30–45s; without it the tool cannot be iterated on |
| Dewey as the cross-language bridge | Numeric, so language-neutral — the only signal that survives translation |
| Identifying-signal gate | Otherwise an author sweep returns the author's whole bibliography |
| Reject, don't just fail to confirm | Dewey known on both sides and disagreeing is positive evidence of a different work |
| Deterministic retailer deep links | No Italian retailer has a free stock/price API; scraping breaks and violates terms |
| Library holdings as the real availability answer | For an out-of-print book, SBN `localizzazioni` is what actually helps |
| Group by language, not by work | Matches the question being asked |
| Unknown language stays `unknown` | The original script folded blanks into English, inflating it |
| Publication-history header, no verdict | Explicit user direction; see §1 |
| One vocabulary for every filter | The year/publisher toggle, the book chooser and the language filter are the same gesture, so they share one look: blue ink, a doubled rule, no ticks. They render through `filterRow` for the same reason |
| Two inks — red and blue, the bicolour school pencil | Blue = the catalogue (links, focus, what is selected). Red = the hand in the margin (the original, an inference, a degraded source). A third accent was removed so the reading stays unambiguous; the rule is stated at the top of `style.css` |
| Year first in the imprint line | Within one work every row repeats the same title and author, so the year and publisher are the only fields that tell two editions apart — and the list is already sorted by year |
| Language filters counted from the results, not from SBN's facets | SBN's `lingua` facet counts come from the *author sweep*, so they count the author's whole catalogue, not the work — see below |

**The `lingua` facet is not a language filter.** `report.facets` is whatever
SBN returned for the broadest probe, which is almost always the *author sweep*
(`_collect_sbn_candidates` prefers it explicitly). For `Per una economia
positiva` + Attali the facet says `francese 124` next to a result of exactly one
Italian edition: SBN holds 124 French records **by Attali**, none of them this
book. The UI used to print that row under the label "In SBN", greyed out the
languages with no editions, and made the rest clickable — so the counts never
agreed with the list below them, and the greyed entries advertised editions that
did not exist. The row is now built from `editions_by_language` after the chosen
work is applied, so every count equals the list under it and every entry filters
to something. `report.facets` is still collected (it rides along on responses the
pipeline already makes) but nothing renders it.

**Latency:** cold is 30–45s, dominated by an intermittent connect stall to one
Wikipedia host in this environment (curl is consistently 0.3s; one Python
process saw 37s and another 0.28s for the identical request). Parallelising
around it does not help — it *is* the critical path. Connect and read timeouts
are separate (`TIMEOUT = (4, 15)`) so a stall fails fast and retries.

---

## 7. Bugs found (all fixed)

### In the original script

- **`sbn_by_author()` was dead code.** It read
  `data.get("records", data.get("results", []))`; the endpoint returns
  `briefRecords`. It always returned `[]` — which is why SBN "never worked".
- **Google Books contributed nothing** — 429 on every call, while the docstring
  called it "the most reliable automated signal for translations".
- **Blank language counted as English** (`if "eng" in langs or not langs`).
- **One-directional by construction** — `english_editions` / `italian_editions`
  as separate destinations made an Italian-first lookup inexpressible.

### Introduced during the build, then fixed

- **Silent partial results.** Every helper treated a failed request as "no
  results" and still reported the source `ok`. Failing a third of Open Library
  requests dropped English from 13 editions to 4 with no warning — this was the
  actual cause of "I only get Italian editions". Now counted via `Tally`,
  reported as `partial (N failed)`, with a retry that fills gaps from cache.
- **`Tally.__len__` made an empty tally falsy**, so `if tally:` never recorded
  the first failure and could never become true. Added `__bool__`; guards use
  `is not None`.
- **Year filter dropped most English editions.** It read `date[:4]`, but Open
  Library writes `June 1985` and `December 31, 1985`. Those failed the numeric
  test and were discarded while SBN's clean years survived.
- **Collapsed filters kept applying invisibly.**
- **Dewey zero-padding.** Open Library has *The Invention of News* at `070.09`,
  SBN's Einaudi edition at `070.9` — same class, different padding, sharing only
  `070.` and so scoring 0.00. Now compared with fraction zeros stripped, which
  keeps `306.4`/`306.484` and `616.89`/`616.85` apart.
- **`delle` missing from `STOPWORDS`** while `della` was present, so it scored as
  a content word: *L'ordine delle notizie* scored **0.67** against
  *L'invenzione delle notizie* while the correct record scored **0.43**.
- **Identifying title threshold too low** at 0.45 — one shared word passed. Now
  `IDENTIFYING_TITLE_MATCH = 0.6`.
- **A documentary listed as an edition.** *"An ecology of mind: a daughter's
  portrait of Gregory Bateson"* scored 0.67 against *Steps to an Ecology of
  Mind*. Rejected on SBN `tipo` (`Documento da proiettare o video`) — on what it
  *is*, not what it is called. Sound recordings are kept: an audiobook is an
  edition of the text.
- **Match provenance written into `evidence`**, which `has_translation_evidence`
  reads — so every matched edition looked like a translation and the French
  original was labelled one. Separate `match_reasons` field now.
- **Open Library sibling leakage.** Italian works by the same author were
  appended as results rather than used as probe candidates, so a lookup for
  *Per una economia positiva* returned *Rumori* and *Karl Marx ovvero lo spirito
  del mondo*.
- **`best_works` locked onto one work**, picking a stub `Noise` (1 edition, no
  Dewey) over the real `Bruits` (7 editions, ddc 780.07). Now scores against all
  variants, breaks near-ties by `edition_count`, expands the top few.
- **Inferred original never reached the header.** The reverse path found the work
  and the overview ignored it, because every "original" field read only from the
  Wikidata cluster.
- **Impossible original year.** Open Library reports `first_publish_year: 1987`
  for *Communication* (a reprint) against a 1976 Italian translation. An original
  cannot postdate its translation, so the year is dropped rather than asserted.
- **Byline could pair a known original language with a fallback year**, printing
  *"first published 1976 in inglese"* from an Italian edition's date. Fixed in
  the web UI, then found **identical in the CLI** — see §9.
- **An original could not find its own translation.** See §4, *The forward
  path*. Every author-keyed bridge was skipped whenever Wikidata missed, so
  looking up an English title with no Wikipedia article returned its English
  editions and stopped. The Italian title of the same book returned both.
- **The CLI byline had drifted from the web UI's**, and carried the
  aggregate-author bug on its own: `book_editions.py "Noise"` printed
  *"Tsutomu Nihei"* over 25 editions of four different books. The origin phrase
  is now built once, in `_origin_phrase`, and reaches both clients as
  `overview.origin`; `overview.ambiguous` tells both when not to name an author.
- **One book offered as four.** `_group_key` keyed an edition on its *first*
  author's surname, and `surname()` cannot tell where a compound surname ends:
  Open Library's comma-less "Gabriel García Márquez" reduced to `marquez`,
  SBN's "García Márquez, Gabriel" to `garcia marquez`. Add Enrico Cicogna
  (the Italian translator) credited as sole author on one record, and Gregory
  Rabassa (the English translator) credited ahead of the author on two, and
  *Cent'anni di solitudine* came back as four different books. Grouping is now
  by *any* shared author, merged transitively, with known translators removed
  from the author list first and translator-only records attached to the
  largest group. The chooser for that title now correctly does not appear.
- **The same person listed twice in one choice.** "Gabriel García Márquez;
  Gabriel Garcia Marquez" — two catalogues disagreeing about diacritics, read
  as a collaboration. `_add_author` compares on stripped tokens and keeps the
  accented spelling.
- **Byline did not follow the chooser.** The spans under it did (`spansFor`),
  but the author and the first-publication claim kept describing the work the
  *pipeline* resolved. Pick Kahneman's *Noise* and the header still read
  "Tsutomu Nihei · earliest edition found 2003". Now `isResolvedWork` asks
  whether the chosen book's authors are in `cluster.author_names`; if not, the
  origin degrades to the honest *"earliest edition found &lt;the choice's own
  first year&gt;"*, and the `original` marker is withheld from its spans. With
  several books sharing a title and none chosen, the byline names **no** author
  at all — the aggregate is not any one of them, and the chooser below lists
  them all.

---

## 8. Known limits

- **No bridge, no original.** If Wikidata has no article *and* one catalogue
  lacks a Dewey class or authors, you get one language only. A genuine data
  limit, not a code fix.
- **Cold lookup 30–45s**, environment-dependent (see §6).
- **Disambiguation groups on any shared author.** Two editions are the same
  book if one of their authors is the same person, merged transitively. Still
  biased toward over-offering rather than silently merging two books, but it no
  longer splits on spelling, author order, or a translator in the author field.
  It *would* still split a book credited to disjoint author sets across
  catalogues (an editor-led volume naming different editors).
- **Inferred originals can name a reprint**, since Open Library's
  `first_publish_year` is per work record, not the true first edition.
- **Enrichment budget** is `ENRICH_BUDGET = 45` full records per lookup. A work
  with more SBN records than that shows a ranked subset, stated in a note.
- **`langs.py` has no Italian name for every code.** Rarer ones fall through to
  the raw ISO 639-2 code, so *Cent'anni di solitudine* lists `kor` and `guj`
  beside *giapponese* and *turco*. Cosmetic, and a one-line fix per language.
- **Buy links are search URLs**, not live stock or price.
- Libraccio has **no** buy link: its search is an ASP.NET POST form, so no GET
  deep link exists. Verified-200 stores only: IBS, Amazon.it, Feltrinelli,
  Mondadori, AbeBooks.it, Maremagnum.

---

## 9. If you pick this up next

**Highest-value next:** there are still **no automated tests**, and the pure
functions are exactly the ones with known-tricky inputs — `matching.py`,
`langs.py`, the `sbn.py` parsers, `pipeline._dewey_affinity`,
`pipeline._identifies`, `pipeline._assign_groups` and `pipeline._origin_phrase`.
All are deterministic and need no network. Every regression case below is
currently an assertion someone has to run by hand and read.

`pipeline.py` is past a thousand lines and is now the only file doing real work.
The seam is already marked: `lookup()` is written as numbered steps (1, 2, 4,
4b, 5 — step 3 was Google Books, §6), and lifting the SBN candidate collection
and scoring out of it would disturb nothing else.

**Recently closed:** the byline/origin formatting used to be duplicated between
`web/app.js` and `book_editions.py`, and was fixed in one while left broken in
the other — twice. It now lives in `_origin_phrase` and reaches both front ends
as `overview.origin`. Only the web UI's *chosen-work* case is still phrased
client-side, because the choice exists only in the browser.

**Do not regress:**

- Don't re-add a "translated into Italian?" hero (§1).
- Don't re-add Google Books without a real reason (§5).
- Don't loosen the identifying gate or `IDENTIFYING_TITLE_MATCH` without
  re-checking *L'ordine delle notizie* and *Quale socialismo, quale Europa*.
- Don't send unwhitelisted params to SBN (§5, trap 1).
- Don't put SBN's own `lingua` facet counts back in front of the reader (§6).
  They count the author's catalogue, not the work.
- Don't key work grouping on the first author alone (§7). Compound surnames,
  diacritics, author order and translators-as-authors all break it.
- Don't phrase the same sentence separately in the CLI and the web UI (§3).

### Regression cases (all currently pass)

| Case | Expected |
|---|---|
| `Noise` + `Jacques Attali` | exactly 1 Italian: *Rumori*, Mazzotta 1978, Dewey 780.07, tr. Sergio Mancini, 74 holdings, BID `RAV0064979` |
| `Verso un'ecologia della mente` | title *Steps to an Ecology of Mind*, original eng 1972, both Italian and English present (~16 / ~15) |
| `Cent'anni di solitudine` | original **spa** 1967, English title present — proves it is not English-centric; **no** disambiguation chooser, and the author named once, accented |
| `The Invention of News` / `L'invenzione delle notizie` | both languages **both ways** — the Dewey `070.09`/`070.9` case. The English direction depends on adopting Open Library's author (§4) |
| `La matrice sociale della psichiatria` | 2 choices (Ruesch/Bateson 1976, Shepherd 1990); inferred original *Communication*; **no** original year; no *Therapeutic communication* |
| `Per una economia positiva` + author | exactly 1 Italian, no sibling leakage |
| `The Essential Knuth` | no Italian edition, all sources `ok` |
| `Noise` (no author) | ≥3 disambiguation choices (Kahneman, Patterson, Wild, Nihei) |
| `--author "Gregory Bateson"` | author mode, ~75 works, ~20 with an Italian edition |
| `book_editions.py "Noise"` | byline names **no** author — four books share the title |
| SBN `CFI1172094` | classified **English** despite `paesePubblicazione: ITALIA` |
| SBN `CFI1183309` | translation detected from `note` alone |

Edition **counts drift** as the catalogues are updated — assert on structure
(both languages present, exactly one Italian, N choices, correct language
classification), not on exact totals.

Every check above is an inline assertion pattern, not a test suite — **there are
no automated tests.** Adding `pytest` coverage for `lookup/matching.py`,
`lookup/langs.py`, `lookup/sbn.py` parsers and `pipeline._dewey_affinity` /
`_identifies` would be cheap and high-value, since those are pure functions with
known-tricky inputs.
