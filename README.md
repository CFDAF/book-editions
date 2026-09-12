# Book editions

Find every edition of a book across English and Italian, in either direction:
give it an English title and it finds the Italian translation; give it an
Italian title and it finds what the book is a translation of.

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

For a book it reports every edition it can find grouped by language, which one
is the original, which are translations and **on what evidence**, and where to
get a copy — shops if it is in print, Italian libraries if it is not.

```
Italian translation of Steps to an Ecology of Mind (inglese, 1972).
Verso un'ecologia della mente · Adelphi, Milano · 1976 · tr. Giuseppe Longo

ITA  Verso un'ecologia della mente                     153.4  PAL0171160
 19  Adelphi, Milano · 2000 · Biblioteca scientifica ; 1 · 88-459-1535-2
       Trad. di Giuseppe Longo e Giuseppe Trautteur.
       held by 229 libraries in 167 places
```

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

## Sources

| Source | Role | Key |
|---|---|---|
| Wikidata / Wikipedia | title crosswalk, original language and year | none |
| Open Library | editions, Dewey classes | none |
| SBN / ICCU | Italian editions, translator evidence, library holdings | none |
| Google Books | extra editions and sale links | `GOOGLE_BOOKS_API_KEY` |

Google Books is optional and is skipped with a visible note when no key is set —
its keyless quota is permanently exhausted, so it cannot be used anonymously.

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
- The `IN SBN` language counts are SBN's own, across every record a search
  touched — not counts of what is listed. Only languages actually present are
  clickable filters; the rest are greyed, since filtering by them would empty
  the page.
