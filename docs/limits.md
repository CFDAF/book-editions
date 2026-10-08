# Limits and regression cases

What the shipped lookup still cannot do, what must not be undone, and the
sixteen cases that guard it. Decisions, facts and pitfalls cited here are in
`docs/DECISIONS.md`; the catalogue's own traps are in `docs/sbn-api.md`; what is
still open, and whose call it is, is `docs/BACKLOG.md`.

## Known limits

- **No stated original, no original.** The header states an original only where
  Wikidata or SBN's work authority states one (decision AO). Open Library's
  `first_publish_year` was measured wrong on 17 of 60 fitting entries and its
  `language` on 40 of 60, so it is not used — which is why *More Brilliant Than
  the Sun* and *Modernità liquida* (H11 and H17 below) state no original language
  (decision AQ). The *earliest edition found* is always shown.
- **The earliest edition found can be a Solar Hijri year.** SBN dates Persian
  editions in the Iranian calendar (1386 ≈ 2007), and the header drops a year
  only when it predates a *stated* original. Deferred by the user (decision AL).
- **Retranslations filed under a separate work are not joined.** *Sul concetto
  di storia* is its own uniform title; no signal ties it to *Tesi di filosofia
  della storia*. Loosening the gate to catch it is settled against.
- **A work SBN files under a name authority S1 does not pick is missed.** N17
  (*Bayn al-qaṣrayn*) loses `ara`: work mode sweeps one of Mahfouz's four SBN
  name authorities. Author mode reaches the others through Wikidata's spellings.
- **The loose-match band holds what the gate refused, not what it should have
  admitted**, and cross-language title similarity is 0.0 — a same-work record in
  a language the work has no title in is refused. S3 admits adaptations sharing
  the work's title (a screenplay, a graphic novel, a film), labelled and listed.
- **The duplicate hint is right about 3 times in 4** (0.766 on the decidable
  pairs, Step 13). It is a mark, never a merge; only an ISBN merges.
- **Open Library's main work is sometimes the wrong record** (8 fitting entries,
  Step 13), and the right one is then not on the duplicate list either.
- **Author mode reads 500 records** for the group filed under no work, and says
  so when it stops (Eco 500 of 2,575). SBN's 50-item facet cap is split by
  language and then by exact year, and whatever no leaf covers is a stated
  count (decision AJ). The contributed group's precision has not been hand-judged
  (decision AK).
- **Cold latency has a long tail**: median 4.8 s, p90 19.1 s, max 95.3 s to the
  end of S4 (N23 *Odysseia*, 1,255 requests). The list is on the page long
  before; a lookup over 10 s says what made it slow.
- **A partial source means requests failed**, and the page says editions may be
  missing. ~~Searching again fills it from cache~~ was false for an SBN error
  payload — the cache entry *was* the failure (`docs/DECISIONS.md` pitfall 8). Since
  Step 3 the cache refuses a body its caller rejects, so a repeat goes back to
  the network.
- **`catalog/langs.py` has no Italian name for every code.** Rarer ones fall
  through to the raw ISO 639-2 code. Cosmetic.
- **Buy links are search URLs**, not live stock or price. Libraccio has **no**
  buy link: its search is an ASP.NET POST form, so no GET deep link exists.

## If you pick this up next

**The gate's counterexamples are automated.** `tests/test_gate.py` holds them
against `core.identity` offline, and `python3 -m pytest` runs the whole offline
suite in about two seconds. During the build a live runner asserted every case
below beside the 40-book corpus — the regression set was the corpus plus these
sixteen; that runner is development evidence and not part of the release.

**What to read before changing anything**: `CLAUDE.md`, then
`docs/DECISIONS.md` §5 (the pitfalls) and `docs/sbn-api.md` — the traps are
counter-intuitive and each was paid for once.

## Do not regress

- Don't re-add a "translated into Italian?" hero (`docs/DECISIONS.md` §1).
- Don't re-add Google Books without a real reason (`docs/sbn-api.md`, *Other
  sources*).
- Don't loosen the identifying gate or `IDENTIFYING_TITLE_MATCH` without
  re-checking *L'ordine delle notizie* and *Quale socialismo, quale Europa*.
- Don't send unwhitelisted params to SBN (`docs/sbn-api.md`, the
  silent-failure trap).
- Don't send the OPAC non-Latin free text (`docs/sbn-api.md` trap 9), and ship
  every new key or value class with a bogus-value control that must return 0.
- Don't put SBN's own `lingua` facet counts back in front of the reader
  (`docs/DECISIONS.md` pitfall 12). They count the author's catalogue, not the
  work.
- Don't key work grouping on the first author alone. Compound surnames,
  diacritics, author order and translators-as-authors all break it.
- Don't phrase the same sentence separately in the CLI and the page:
  `core/notes.py` and `core/view.py` word it once.
- Don't re-conclude that SBN records no original title (`docs/DECISIONS.md`
  pitfall 1). They do; the mobile gateway just doesn't return it.
- Don't ask the OPAC for a work without an author (`docs/sbn-api.md`):
  `sbn_opac.work_facet`
  and `work_records` raise rather than query. It would answer, and the answer
  would be a different book.
- Don't re-add a Dewey route (`CLAUDE.md` rule 7): one was measured and
  deleted (decision AH). Don't lower a per-stage cap to go faster — it hides
  records rather than fixing anything.

## Regression cases

| Case | Expected |
|---|---|
| `Noise` + `Jacques Attali` | exactly 1 Italian: *Rumori*, Mazzotta 1978, Dewey 780.07, tr. Sergio Mancini, 74 holdings, BID `RAV0064979` |
| `Verso un'ecologia della mente` | title *Steps to an Ecology of Mind*, original eng 1972, both Italian and English present (~16 / ~15) |
| `Cent'anni di solitudine` | original **spa** 1967, English title present — proves it is not English-centric; **no** disambiguation chooser, and the author named once, accented |
| `The Invention of News` / `L'invenzione delle notizie` | both languages **both ways** — the Dewey `070.09`/`070.9` case. The English direction depends on adopting Open Library's author |
| `La matrice sociale della psichiatria` | 2 choices (Ruesch/Bateson, Shepherd 1990); original *Communication* **1951**, from the authority, not inferred; no *Therapeutic communication*. Before the fourth bridge this had no original year at all — Open Library's Dewey-matched work reported 1987, a reprint, which was dropped as impossible against a 1976 translation |
| `Per una economia positiva` + author | exactly 1 Italian, no sibling leakage |
| `The Essential Knuth` | no Italian edition, all sources `ok` |
| `Noise` (no author) | ≥3 disambiguation choices (Kahneman, Patterson, Wild, Nihei) |
| `--author "Gregory Bateson"` | author mode, ~75 works, ~20 with an Italian edition |
| `book_editions.py "Noise"` | byline names **no** author — four books share the title |
| `More Brilliant Than the Sun` / `Più brillante del sole` | both languages **both ways**; original eng 1998. Nothing but the uniform-title authority can join these two — no shared ISBN, 0.0 title similarity, no Dewey on the SBN side |
| `Rumori` + `Jacques Attali` | resolves to *Bruits*, fre 1977, with Italian and English present |
| `Kafka sulla spiaggia` + `Murakami Haruki` | original **jpn 2002** in the byline, and **no** span marked original — SBN holds no Japanese edition. `UBO4636099` must appear under *inglese*, not *giapponese* |
| `Cent'anni di solitudine` (Dewey leak) | **no** *L'autunno del patriarca*, *Il generale nel suo labirinto* or *L'amore ai tempi del colera* in the Italian list |
| SBN `CFI1172094` | classified **English** despite `paesePubblicazione: ITALIA` |
| SBN `CFI1183309` | translation detected from `note` alone |

Edition **counts drift** as the catalogues are updated — assert on structure
(both languages present, exactly one Italian, N choices, correct language
classification), not on exact totals.

**Case 1 (`Noise` + Attali) no longer exercises the no-Wikidata path**; H17
(*Modernità liquida* + Bauman, SBN's authority alone giving the original) took
that role in Step 1C. And a case can pass while its use case fails: *Per una
economia positiva* passes "exactly 1 Italian" with no original found.

**Not every case passes on the shipped path, by decision.** On 2026-09-28
(Step 16): H05 wants 2 choices and an original, and a bare title with two
authors shows a chooser and no list (decision AN); H09's *≥ 10 works with an
Italian edition* is 6 over work rows (decisions AQ, AR); H11a/b and H17 want
original `eng`, which only Open Library states (decisions AO, AQ); H13 is red on
both paths. That is decision AS's accepted set — a new red outside it is a
regression.
