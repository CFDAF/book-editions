# Book editions

See when a book first appeared and every edition since, in any language. Search
by title in any of those languages, with or without the author, or by author
alone.

Mainly for one thing: you have come across a book, and you want to know whether
an Italian translation exists — and if so, from whom and when — before deciding
which one to buy. It works from either end, the original title or the Italian
one, and tells you where to get a copy of whichever you pick.

```bash
pip install requests

python3 server.py                                    # web page at localhost:8000
python3 book_editions.py "Noise" --author "Jacques Attali"
python3 book_editions.py "Verso un'ecologia della mente" --author "Gregory Bateson"
python3 book_editions.py "Verso un'ecologia della mente"   # no author: see below
python3 book_editions.py --author "Gregory Bateson"   # every book by one author
python3 book_editions.py "Cent'anni di solitudine" --format json -o out.json
```

`PORT=8001 python3 server.py` picks another port. No API keys: every source is
keyless.

**A title with no author** takes the author the sources agree on, and says in
the byline that none was typed. When they name several people — four books are
called *Noise* — it shows a chooser of books and no list, and picking one runs
the lookup again as title + author.

**An author with no title** is a different question — every book they wrote
rather than every edition of one book. The person is resolved first (a chooser
appears only when the name answers to more than one), then it lists one row per
work, titled in its original language, with its editions' count and languages.
What the person only edited, prefaced or is the subject of is a separate group,
closed by default. Clicking a work runs a title lookup for it.

## What it answers

The header is a publication history: the original title, the author, when and in
what language it first appeared — **where a source states it** — and one row per
language with its year span and edition count.

```
Steps to an Ecology of Mind
Gregory Bateson · first published 1972 in inglese · 32 edition(s) in 4 language(s)

  inglese                  1972–2000   12 edition(s)
  italiano                 1976–2024   15 edition(s)
  francese                 1977–1980    3 edition(s)
  tedesco                  1983–1996    2 edition(s)
```

It also states the **earliest edition found** — a statement about the
catalogues, not about history — and never infers from the two whether "the
first edition differs": that inference was measured and was wrong 9 times in 36.
Where no source states an original, none is shown rather than a guess.

Below that, every edition grouped by language, newest first, each led by its
year and publisher — the two fields that tell editions of one book apart. A
row opens for the translator, the physical description, which libraries hold a
copy, and where to buy one.

Filters sit between the header and the list: **language**, **publisher** and a
**year span**. They re-filter the list already in hand and send no request, and
they never move the header — the original, the earliest edition and the counts
are always computed over everything found.

The list arrives in a few seconds and keeps improving behind you: records the
catalogue did not link are recovered and title-checked, then every SBN record is
read in full so that printings of one ISBN fold into one row. Until that ends the
page says the counts are provisional.

## How the matching works

**SBN records the link between a translation and its original.** It files
editions against a uniform-title authority — *Titolo di opera* in its catalogue
— so it already knows that *Più brillante del sole* and *More Brilliant Than the
Sun* are one work. That link is absent from SBN's mobile gateway, which is why
this project once concluded that no free catalogue records it; the OPAC's own
API carries it. It is the strongest bridge there is and the only one that
reaches a book with no Wikipedia article and no shared ISBN.

A lookup runs in stages:

1. **Identify the work once.** Wikidata (accepted only when the title matches
   one of the item's own names), SBN's uniform-title authority (read through a
   guard, and **always with an author** — bare *Rumori* returns Russolo's *L'arte
   dei rumori*), and Open Library's work, searched with the *original* title.
2. **List its editions by that identity**: SBN's records filed under the work,
   and Open Library's editions of the work. Nothing after step 1 uses the title
   you typed.
3. **Recover what the listing misses**: SBN holds many same-work records it
   never linked. Three routes find candidates, and each one is admitted **only**
   if its title matches one of the *work's* titles. The refused ones are not
   dropped: they sit in a collapsed band, each labelled with how it was reached
   and the score it was refused at.
4. **Read every SBN record in full**, behind the page, for holdings,
   translators and printings.

Two rows merge only when they share an ISBN. Two rows that merely agree on
language, year and publisher are marked as *possibly the same edition* and left
apart: that rule is right only about two times in three. Open Library's other
work records for the same book are listed, closed, and each can be added to the
list; they never change the header.

A Dewey class is not used anywhere: it is a subject, and one author's books are
mostly on one subject — García Márquez is `863.44`, and so is every novel he
wrote.

The precision claims above are measurements on the books they were tuned on,
except the held-out check, which is the one figure measured on books nothing
was tuned against.

## Sources

| Source | Role | Key |
|---|---|---|
| Wikidata / Wikipedia | title crosswalk, the only stated original language and year | none |
| Open Library | editions, ISBNs, duplicate work records | none |
| SBN / ICCU — OPAC API | the uniform-title authority, work listings by language, name authorities | none |
| SBN / ICCU — mobile gateway | full records: language, translator, physical description, holdings | none |

SBN is reached through two undocumented, unrelated APIs on one host. It sends no
CORS headers, which is why this ships with a small server instead of being a
static page.

## Notes

- A cold lookup shows its list in a few seconds; the background reading of full
  records can take a minute or more on a large work (the 128-case sweep of
  2026-09-28: median 4.8 s, p90 19.1 s, max 95 s to the end of everything).
  Responses are cached in `.cache/` for 24 h, so a repeat is fast. Delete
  `.cache/` to refresh.
- Every cap is on the page when it binds, and a failed request is never shown as
  an empty result: a source that lost requests is reported as `partial (N
  failed)` and the page says editions may be missing. A lookup slower than 10 s
  says what made it slow.
- **Nothing is excluded for what it is.** SBN links study guides, graded
  readers, omnibus volumes, operas, films and graphic novels to a work. They stay
  in the list and the counts, labelled with the catalogue's own medium, and with
  *credited to X* where SBN heads the record under somebody else. A film the
  title check admits (*The Unbearable Lightness of Being*) is labelled the same
  way.
- A record whose language no source recorded is a language filter of its own
  (*unknown*), hidden and counted like any other.
- Buy links are deterministic search URLs, not live stock or prices. No scraping.
- Among the known limits: an edition dated only in another calendar (Solar
  Hijri 1386 ≈ 2007) whose year SBN's index does not confirm is shown with no
  year, so it cannot be the *earliest edition found* even when it is.

## Tests

```bash
python3 -m pytest                # the offline suite: about two seconds
python3 tools/core_coverage.py   # core/ at 100% of executable lines, stdlib only
```

The suite never reaches a catalogue: `tests/conftest.py` blocks sockets, the
stages are tested with the catalogues stubbed, and the recorded catalogue bodies
it reads are in `tests/data/`. Green is not "the server runs" — that takes a
real port and a cold lookup.

## Why it is shaped this way

[`docs/project.html`](docs/project.html) is the project on one page: the
sources, one lookup walked through, the decisions and the traps.
