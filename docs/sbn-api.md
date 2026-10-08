# The SBN API, reverse-engineered — the expensive knowledge

Facts F1–F20 and the decisions cited below are in `docs/DECISIONS.md`; what the
lookup still cannot do is in `docs/limits.md`.

`https://opac.sbn.it/opacmobilegw` — the undocumented ICCU mobile-app gateway.
Everything below is built on it. It is **not** the only JSON SBN exposes: the
OPAC website has its own API, which carries more (see *The OPAC API* below).

| Fact | Detail |
|---|---|
| `search.json` params (`catalog/sbn_mobile.PARAMS`) | `any`, `title`, `author`, `subject`, `isbn`, `type`, `start`, `rows`. Multi-word = AND. |
| Rejected params | `titolo`, `autore` → validation error. |
| **Silent-failure trap** | Unknown params are **silently ignored** and the unfiltered set is returned. Only ever send whitelisted names (`sbn.PARAMS`). |
| `rows` | Honoured to at least 500. ~60ms, no rate limiting observed. |
| **`full.json?bid=<SHORTBID>`** | Undocumented detail endpoint. **Only `bid` works** — `id`, `cid`, `codiceIdentificativo` all rejected. |
| Only the full record has | `linguaPubblicazione`, `classificazioneDewey`, `nomi`, `note`, `numeri`, `collezione`, `descrizioneFisica`, `localizzazioni` (holdings). The brief record has **no language**, which is why candidates must be enriched. |
| Facets returned | `level`, `tiporec`, `nomef`, `soggettof`, `luogof`, `lingua`, `paese`, with counts. |
| **Facets cannot filter — on this gateway** | `lingua=ita`, `fq=`, `facet=`, `refine=`, `facetName/facetValue`, `paese=it` — every form ignored. **The OPAC API's facets do filter** (F1, F4, F8, F10, below); only this gateway ignores them. |
| **No CORS** | No `Access-Control-Allow-Origin` at all. |
| Permalink | `https://opac.sbn.it/bid/MIL0871878`. Short BID = `codiceIdentificativo` minus `IT\ICCU\`, segments joined. |

### The OPAC API — a second, richer interface

`https://opac.sbn.it/o/opac-api/…` — what the OPAC website itself calls. Same
host as the mobile gateway, different application, **and it carries the uniform
title the mobile gateway omits.** No key, no auth, no `X-Requested-With` needed.

| Endpoint | Shape |
|---|---|
| `GET /o/opac-api/title?id=<SHORTBID>&core=sbn&page=1` | One record. Carries a *Titolo di opera* row: the work's title, its author, and a work id. ~0.5–2s; `max-age=600`. One id only — a comma list returns nothing. |
| `POST /o/opac-api/titles-search-post` | Search results, lean rows, **no facets**. |
| `POST /o/opac-api/titles-search-full-post` | Search results **with facets**. ~0.3s. This is the one that matters. |
| `GET /o/opac-api/title?id=<WORK ID>&core=opere&page=1` | **The work authority record** (F20): the work's *Lingua* and *Forme varianti*, never a year. Bogus id → `data: null`. It can be wrong — Mahfouz's *Bayn al-qaṣrayn* is filed `ITALIANO` — so `stages._sbn_work_language` believes it only unless SBN holds records in that language none of which is titled like the work (decision AN) |

Search parameters are form-encoded and shaped `item:<code>:<Name>:<op>=value`:

| Parameter | Meaning |
|---|---|
| `core=sbn` | required |
| `item:1016:Any:@or@=<text>` | free-text search |
| `item:1003:Autore:@and@=<name>` | author. `1004`/`1005` are **not** author and return non-JSON |
| `item:8006:Titolo_uniforme:@frase@=<work id>` | every record linked to that work |
| `item:5032:Nomi::@frase@=<authority id>` | records by that authority-controlled name |
| `page=<n>` | 1-based. Page size is fixed at 20 (F9) |
| `titolo_uniformef[]`, `lingua[]`, `tiporec[]`, `level[]`, `dataf[]`, `editoref[]` | **facet filters that work** (F1, F4, F8, F10) — exact values only; `dataf[]` takes exact years, never a range; every facet caps at 50 items (F11) |

The whitelist is `catalog/sbn_opac.PARAMS`, and `post()` **refuses** a key outside it rather than filtering it: an unknown key is silently ignored by the OPAC and the unfiltered set comes back (`CLAUDE.md` rule 2).

**The `titolo_uniformef[]` facet is the prize.** `titles-search-full-post`
returns `data.facets`, one of which is `{"name": "titolo_uniformef[]", "label":
"Titolo dell'opera", "items": [{label, results, value}, …]}` — the uniform
titles of the works in the result set, with counts. Searched with a title *and*
an author, the top item by count is the work's own title, i.e. the original:

| Query | Top facet value | Share |
|---|---|---|
| *Più brillante del sole* + Eshun | `more brilliant than the sun` | 1/1 |
| *Verso un'ecologia della mente* + Bateson | `steps to an ecology of mind` | 22/28 |
| *Cent'anni di solitudine* + Garcia Marquez | `cien anos de soledad` | 89/138 |
| *Rumori* + Attali | `bruits : essai sur l'economie politique de la musique` | 1/1 |
| *L'invenzione delle notizie* | `invention of news` | 2/9 |
| *La matrice sociale della psichiatria* + Ruesch | `communication: the social matrix of psychiatry.` | 1/1 |
| *Il nome della rosa* + Eco | `nome della rosa` | 232/297 |
| *The Essential Knuth* + Knuth | *(0 records, no facet)* | — |

One request answers what the three bridges approximate. It even splits the
*matrice sociale* case correctly — Ruesch's *Communication* and Shepherd's
*Psychosocial Matrix* are separate facet values, per record, which is exactly
the discipline the reverse path has to enforce by hand.

**Do not use it unguarded:**

- **The author is not optional.** Bare *Rumori* is 880 records and the top facet
  value is `arte dei rumori` (Russolo) — Attali is not in the top five. Bare
  *The Essential Knuth* confidently returns `essential mathematics for economic
  analysis`, a different book entirely. With the author both are correct.
- **Labels are normalised** — lowercased, accents stripped, sometimes with
  trailing punctuation (`cien anos des soledad. -`). A search key, not a
  display title.
- **A uniform title is the *work's* title, not necessarily a foreign one.**
  *Il nome della rosa* returns `nome della rosa`, correctly — the work is
  Italian. That is a useful "not a translation" signal, not a failure.
- Facet values include films, TV adaptations and related works
  (`nome della rosa <serie tv ; 2018>`, `postille a il nome della rosa`).
- **Per-record coverage is partial and unintuitive.** Probing detail records one
  by one is the wrong approach: of the first 45 *Cent'anni* records only 5
  carried the row, the first at #41 — yet the facet reports 89. Ask the facet,
  never hunt for a linked record.
- It is **presentation JSON**. The detail endpoint nests the field under
  `contents` → `table` → `table-title` rows keyed on the Italian string
  `"Titolo di opera"`, which a relabel breaks silently. The facet is safer: it
  keys on `name == "titolo_uniformef[]"`, an internal identifier.

**How it is wired** (since Step 16):

- **S1** (`stages.identify`) asks the facet with the title and the author, and
  reads the answer through the **A/B work guard** (`core.identity`), never by top
  facet count; a weak or refused work is accepted only by the **second signal**
  (decision A) — the Wikidata item accepted for the same entry names the same
  work. Loosening B is settled against: the known wrong works sit at B = 0.5,
  above every refused classic.
- **S2** (`stages.list_editions`) lists every record filed under the accepted
  work, a `lingua[]` page at a time, **always with the author**
  (`sbn_opac.work_facet` and `work_records` raise without one). It calls no
  title gate: a record there is the catalogue's statement.
- **S3** (`stages.recover`) finds the same-work records the work does not link —
  334 over 40 books in the benchmark — and admits them by title against the
  work's titles only.
- The normalised uniform title is **never displayed.** It is a search key; the
  displayed title is a catalogued one.
- Every request goes on the lookup's `Ledger` (`catalog/http.py`), so a dropped
  request degrades the source to `partial (N failed)` rather than silently
  returning a shorter list.

### SBN data traps

1. **`paesePubblicazione` is not a language.** `CFI1172094` is an English
   *Nineteen Eighty-Four* published in Pesaro: `linguaPubblicazione: INGLESE`,
   `paesePubblicazione: ITALIA`. Only `linguaPubblicazione` is trustworthy —
   with the exception below.
1b. **`linguaPubblicazione` sometimes names the language translated *from*.**
   `UBO4636099` is *"Kafka on the shore / Haruki Murakami ; translated from the
   Japanese by Philip Gabriel"*, `London : Vintage, 2005`, ISBN `9780099494096`
   — and records `linguaPubblicazione: GIAPPONESE`, `paesePubblicazione:
   GIAPPONE`. It is the English translation. There is no better signal to
   switch to, so `_language_contradicts_itself` only *disbelieves* it: a record
   naming a translator while claiming the work's original language cannot be
   both, and its language becomes unrecorded rather than trusted.
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
6. **`tipo` distinguishes media — and a medium is a label, never a filter.**
   The old tree excluded films and maps by it; the new one keeps every record
   SBN links to the work and labels it with this field (decision Z), including
   a film the title gate admits (decision AL). Bare `testo` appears beside
   `testo a stampa` on view rows (`docs/BACKLOG.md`).
7. **SBN links non-editions to a work** (F16): a York Notes study guide
   `VIA0214939`, a Penguin Readers retelling `TO10037839`, the Meridiani collected
   volume `TO02081267`. `tiporec[]`/`level[]` do not separate them, so they are
   listed, labelled with the medium and *credited to X* where SBN's main heading
   is another person — and the label is incomplete, which the list says once.
8. **A single `/` in any SBN free-text value is an error that looks like an
   answer** — HTTP 200, `{"error": {"code": 0, "msg": "…SolrServerException…"}}`
   and no records (2026-09-18, Step 3) **V**. Solr reads the `/` as the start of
   a regex literal; `alpha / beta / gamma`, a closed one, does not error. It
   sits beside the silent-failure trap: both are 200s that are not answers. It
   is counted as a failure only because the parser reads the body, and since
   Step 3 the cache refuses to store it.
9. **The OPAC silently drops non-Latin free-text *values*** (F15) **V**. `ANY`
   in Cyrillic, Greek, Arabic, Chinese or Japanese returns the unfiltered
   21,806,046; `ANY + AUTHOR` equals `AUTHOR` alone. A whitelist of keys is not
   enough: send Latin script only (romanised at S0) and prove a term was used
   with a control that must return 0.
10. **`infos[0]` of an OPAC row is not always the imprint** — 26 of 2,603 rows
    carry the record type there instead (`sbn_opac.imprint_of`).
11. **`linguaPubblicazione` labels are not all mapped by guessing.** Every row of
    `catalog/langs.py`'s SBN map is read off the `lingua[]` facet, which prints
    the code beside the label: `SLOVACCO` is `slo`, `ISLANDESE` is `ice`.
    Stage 3 found 21 labels unmapped; Step 7 mapped them from that evidence.
12. **An imprint's first year may be in another calendar.** `Tihran : Aryaban,
    1386 [2007!` — Solar Hijri, with the Gregorian year in SBN's brackets; also
    Lunar Hijri (`1308 AH [1891]`), Bengali (`1364 [1957!`), Bikram Sambat
    (`2012 [1955!`, a year that looks Gregorian) and Ethiopian (`1975, 1982/83`,
    no brackets). SBN's own date is the `dataf[]` facet value the record is
    filed under (2007 here) — no field of the full record or the OPAC detail
    record carries it — and it is wrong too, once in the probe. Neither reading
    is trusted alone (decision AY).

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
