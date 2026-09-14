# Book editions

See when a book first appeared and every edition since, in any language. Search
by title in any of those languages, or by author alone.

Mainly for one thing: you have come across a book, and you want to know whether
an Italian translation exists — and if so, from whom and when — before deciding
which one to buy. It works from either end, the original title or the Italian
one, and tells you where to get a copy of whichever you pick.

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
edition count.

```
Steps to an Ecology of Mind
Gregory Bateson · first published 1972 in inglese · 36 editions in 6 languages

  inglese  ORIGINAL   ━━━━━━━━━━━━━━──────────────   1972–2000   15
  italiano            ────━━━━━━━━━━━━━━━━━━━━━━━   1976–2016   16
  spagnolo            ────────────━───────────────        1993    1
```

Each language is a bar on one shared time axis, so the gap between an original
and its translations is something you see rather than work out.

Below that, every edition grouped by language, newest first, each led by its
year and publisher — the two fields that tell editions of one book apart — and
expandable for the translator, the physical description, which libraries hold a
copy, and where to buy one.

Two filters sit between the header and the list, and work the same way as each
other: pick one or more **languages**, and — when several different books share
the title you searched — pick **which book** you meant. Whatever is on is blue,
with a line underneath saying in words what is showing and what that hides.

The page uses two inks and only two, borrowed from the red-and-blue bicolour
pencil. Blue is the catalogue: links, and whatever you have selected. Red is a
mark in the margin: which language is the original, which editions are first
printings, a claim resting on inference rather than on a catalogue record, a
source that came back incomplete. If something is red, it is being pointed at.

## How the matching works

No free catalogue records a link between a translation and its original. Open
Library has no `translation_of` field, and SBN records carry no uniform title.
Four mechanisms fill the gap, and any one of them suffices:

| Mechanism | Precision | Recall |
|---|---|---|
| **SBN's uniform-title authority** | exact — the catalogue's own statement | needs SBN to hold and link the record |
| **Wikidata** via Wikipedia sitelinks and labels | high | needs a Wikipedia article |
| **Dewey agreement** between Open Library and SBN | good | needs both sides classified |
| **Shared ISBN** | exact | modern books only |

The first is the strongest and the least obvious. SBN files editions against a
work record — *Titolo di opera* in its catalogue — so it already knows that
*Più brillante del sole* and *More Brilliant Than the Sun* are one book. The
other three have to work that out; this one just asks. It is also the only one
that reaches a book with no Wikipedia article, no shared ISBN and no Dewey
class, which is exactly that book.

Dewey is the interesting one. It is numeric, therefore language-neutral. Attali's
*Bruits/Noise* is classified `306.484` / `780.07` in Open Library and SBN's
*Rumori* is `780.07` — an exact match, while their titles share not one word.
The same test correctly declines to match *Quale socialismo, quale Europa*
(Dewey `335`), which is the same author in the same year.

An edition is only reported if something actually identifies it: the work
authority, a shared ISBN, or a title match against a known variant.
Same-author-same-era is not enough, so an author sweep does not drag in
everything they ever wrote.

Dewey agreement *corroborates* but no longer identifies on its own, because a
Dewey class is a subject and an author who writes one kind of book has every
title in it. García Márquez is `863.44`, and so are *L'autunno del patriarca*
and *L'amore ai tempi del colera* — each an exact match with *Cent'anni di
solitudine*. A Dewey-only match now has to agree on authorship too, and has to
be the only title resting on that class; otherwise the class is describing a
shelf rather than a book.
(That gate applies to title lookups. An author search has no single work to
identify, so everything by the author belongs in the answer and it does not.)

Going the other way — from a book you have just discovered to whether it is
worth buying in Italian — takes one more step, because SBN files a translation
under its *Italian* title and searching SBN for the original title cannot find
it. What crosses that gap is a sweep of every record SBN holds by the author,
sifted by the same Dewey test. That needs an author, and Wikidata is the only
source that hands one back for free, so a book with no Wikipedia article used to
have none and the sweep never ran. Open Library has normally matched the work by
that point and named its author, so that is where the author now comes from —
but only when the matched works agree on one, since a title as ambiguous as
*Noise* resolves to four unrelated works. *The Invention of News* finds the 2015
Einaudi translation this way, on Dewey `070.9` against `070.09`.

Titles are not unique, so editions are grouped into works by shared authorship:
two editions are the same book if any one of their authors is the same person,
merged onwards from there. Catalogues disagree about diacritics, about where a
compound surname ends and about author order, and SBN sometimes files a
translator in the author field — so the comparison is on surname tokens with
known translators removed first. When more than one book is left, the page says
so and offers the choice rather than blending them into one answer.

The Wikidata-and-Dewey pair also runs in reverse, when Wikidata has never heard
of an Italian title and the original would otherwise be undiscoverable. SBN
records no original title — only a note naming the translator — but it does
record the authors and a Dewey class, and that is enough: *La matrice sociale
della psichiatria* gives Ruesch and Bateson at `616.89`, which finds their
*Communication* in Open Library at ddc `616.89`. Dewey at that granularity is
coarse (`616.89` is all of psychiatry) so every credited author must match too,
which is what keeps Ruesch's unrelated *Therapeutic communication* out. These
matches are reported as medium confidence, being weaker than a confirmed title.

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

- A first lookup queries three catalogues live and can take up to a minute; the
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
- The language counts beside the filters count the editions listed below them
  and nothing else, and follow the chosen book. SBN returns counts of its own,
  but they come from the sweep of the *author's* whole catalogue, so they answer
  a question nobody asked — 124 French records by Attali above a result of one
  Italian edition — and are not shown.
- Two codes sit beside each edition, both explained on hover: the Dewey class it
  is shelved under, and its SBN record number, the permanent id for that record
  in the Italian national union catalogue.
