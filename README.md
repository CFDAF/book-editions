# Book editions

See when a book first appeared and every edition since, in any language. Search
by title in any of those languages, or by author alone. Useful for telling when
a work was originally published, whether a translation exists and how long after
the original it arrived, and where to get a copy.

```bash
pip install requests

python server.py                                    # web UI at localhost:8000
python book_editions.py "Noise" --author "Jacques Attali"
python book_editions.py "Verso un'ecologia della mente"
python book_editions.py --author "Gregory Bateson"   # every book by one author
python book_editions.py "Cent'anni di solitudine" --format json -o out.json
```

An author with no title is a different question — every book they wrote rather
than every edition of one book — so it lists one row per work, with the edition
count, the languages it exists in, and how many have an Italian edition in SBN.

## What it answers

The header is a publication history: the original title, the author, when and in
what language it first appeared, and one row per language with its year span and
edition count — so the gap between an original and its translations is visible
rather than something you work out from a list.

```
Steps to an Ecology of Mind
Gregory Bateson · first published 1972 in inglese · 36 editions in 6 languages

  inglese   ORIGINAL  ▇▇▇▇▇▇▇▇▇�afterwards           1972–2000   15
  italiano            ░░▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇             1976–2016   17
  spagnolo                        ▪                       1993    1
```

Below that, every edition grouped by language, newest first, each with author,
title, publisher and year — expandable for the translator, the physical
description, which libraries hold it, and where to buy it.

## How the matching works

No free catalogue records a link between a translation and its original. Open
Library has no `translation_of` field, and SBN records carry no uniform title.
Two mechanisms fill the gap, and both are needed:

| Mechanism | Precision | Recall |
|---|---|---|
| **Wikidata** via Wikipedia sitelinks and labels | high | needs a Wikipedia article |
| **Dewey agreement** between Open Library and SBN | good | needs both sides classified |

Dewey is the interesting one. It is numeric, therefore language-neutral. Attali's
*Bruits/Noise* is classified `306.484` / `780.07` in Open Library and SBN's
*Rumori* is `780.07` — an exact match, while their titles share not one word.
The same test correctly declines to match *Quale socialismo, quale Europa*
(Dewey `335`), which is the same author in the same year.

An edition is only reported if something actually identifies it: a shared ISBN,
a title match against a known variant, or Dewey agreement. Same-author-same-era
is not enough, so an author sweep does not drag in everything they ever wrote.
(That gate applies to title lookups. An author search has no single work to
identify, so everything by the author belongs in the answer and it does not.)

The same pair runs in reverse when Wikidata has never heard of an Italian title,
which would otherwise leave the original undiscoverable. SBN records no original
title — only a note naming the translator — but it does record the authors and a
Dewey class, and that is enough: *La matrice sociale della psichiatria* gives
Ruesch and Bateson at `616.89`, which finds their *Communication* in Open
Library at ddc `616.89`. Dewey at that granularity is coarse (`616.89` is all of
psychiatry) so every credited author must match too, which is what keeps
Ruesch's unrelated *Therapeutic communication* out. These matches are reported as
medium confidence, being weaker than a confirmed title.

What that path finds is also used to name the work: the original's title,
language and — where the arithmetic allows — its year are taken from the matched
Open Library record, and the header says the original was identified by
inference rather than from a catalogue record. An original cannot postdate its
own translation, so a first-publication year later than the earliest translation
is dropped rather than asserted: Open Library reports 1987 for Ruesch and
Bateson's *Communication*, which is a reprint, while the Italian translation is
1976.

## Sources

| Source | Role | Key |
|---|---|---|
| Wikidata / Wikipedia | title crosswalk, original language and year | none |
| Open Library | editions, Dewey classes | none |
| SBN / ICCU | Italian editions, translator evidence, library holdings | none |


SBN is reached through the undocumented ICCU mobile gateway (`search.json`, and
`full.json?bid=`, which is the only place a record's language, Dewey, translator
and holdings appear). It sends no CORS headers, which is why this ships with a
small server instead of being a static page.

## Notes

- A first lookup queries four catalogues live and can take up to a minute; the
  Wikipedia/Wikidata leg dominates. Results are cached in `.cache/` for 24h, so
  repeats and filter changes return in milliseconds. Delete `.cache/` to refresh.
- Year and publisher filters are applied locally for SBN, which accepts neither
  as a query parameter.
- Buy links are deterministic search URLs, not live stock or prices. No scraping.
- Records SBN types as film, music, maps or graphics are excluded and counted in
  a note: a documentary *about* an author shares enough of a title to pass a
  title match, so it has to be rejected on what it is rather than what it is
  called. Sound recordings are kept — an audiobook is an edition of the text.
- A lookup fans out over dozens of requests, and a failed one is treated as "no
  results" so that one bad request cannot sink the whole answer. When that
  happens the affected source is reported as `partial (N request(s) failed)` and
  the page says editions are probably missing — a dropped request can remove an
  entire language, which would otherwise be indistinguishable from that language
  genuinely having none. Searching again fills the gaps from cache.
- The `IN SBN` language counts are SBN's own, across every record a search
  touched — not counts of what is listed. Only languages actually present are
  clickable filters; the rest are greyed, since filtering by them would empty
  the page.
