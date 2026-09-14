# CLAUDE.md — book_editions

**Read `HANDOFF.md` before changing anything.** It carries the reverse-engineered
SBN API details, the traps in that data, the decisions and their reasons, the
bugs already found and fixed, and the regression cases. Most of it is expensive
to rediscover and some of it is actively counter-intuitive.

## The short version

A book-editions lookup: give it a title in any language and it shows when the
work first appeared and every edition since, grouped by language, plus where to
get a copy. An author with no title lists their whole bibliography instead.

Python stdlib + `requests`. No API keys. `python server.py` → localhost:8000, or
`python book_editions.py "<title>"`. Three sources, but **four** endpoints — SBN
is reached through two unrelated APIs. Knowing only the first is how the
project's central premise came to be recorded as verified fact and be wrong
(`HANDOFF.md` §4). Check the record *type* before concluding a field is absent.

## Rules specific to this project

1. **The header is a publication history, not a verdict.** An earlier version led
   with "Translated into Italian." — the user rejected that framing. Do not
   re-introduce a yes/no hero.
2. **Never send SBN a parameter that is not in `sbn.PARAMS`.** Unknown params are
   silently ignored and the *unfiltered* result set comes back — a silent wrong
   answer, not an error.
3. **Never call `opac.work_for` without an author.** Same failure shape on the
   other SBN API: it answers, and the answer is a different book. Bare *Rumori*
   returns Russolo; bare *The Essential Knuth* returns a book on economics.
4. **`linguaPubblicazione` is the only language signal — and it still lies.**
   `paesePubblicazione` is a country and says nothing about language. And
   `linguaPubblicazione` sometimes names the language translated *from*: SBN has
   an English Vintage printing of *Kafka on the Shore* filed as GIAPPONESE. A
   record that names a translator while claiming the work's original language is
   disbelieved rather than corrected (`_language_contradicts_itself`).
5. **A failed request must never be indistinguishable from an empty result.**
   Swallowed failures go through `net.Tally`; sources degrade to
   `partial (N failed)`. This was the single worst bug in the project.
6. **Don't loosen the identifying-signal gate** (`pipeline._identifies`,
   `IDENTIFYING_TITLE_MATCH = 0.6`) without re-checking the regression cases in
   `HANDOFF.md` §9 — particularly *L'ordine delle notizie* and
   *Quale socialismo, quale Europa*.
7. **A Dewey class does not identify a work.** It is a *subject*, and one
   author's books are mostly on one subject — García Márquez is `863.44` and so
   is every novel he wrote, exactly. A Dewey-only match must also agree on
   authorship, and must be the only title resting on that class in the candidate
   set (`_dewey_discriminates`). This means the verdict is **not** per record:
   `_identifies` returns `STRONG` or `BY_DEWEY` and the `BY_DEWEY` ones are
   judged together afterwards.
8. **Google Books was removed deliberately.** Keyless quota permanently
   exhausted; it contributed nothing. Don't re-add it as "another source".
9. **Stop the server with `pkill -f server.py`** — macOS reports the process as
   `Python server.py`, so `pkill -f "python3 server.py"` silently matches
   nothing and leaves a stale instance serving old code.
10. Cold lookups take 35–50s and cache to `.cache/` for 24h; repeats are instant.
    Delete `.cache/` to force fresh data. `ENRICH_BUDGET = 150` is deliberate —
    lowering it hides bugs rather than fixing them (`HANDOFF.md` §8).

## No automated tests

Verification is by the inline assertion patterns and regression table in
`HANDOFF.md` §9 — fifteen cases, run by hand. Adding `pytest` coverage for the
pure functions (`matching.py`, `langs.py`, `sbn.py` parsers, and in `pipeline`:
`_dewey_affinity`, `_identifies`, `_dewey_discriminates`, `_assign_groups`,
`_span_is_original`, `_origin_phrase`) is still the cheapest available
improvement. None of them touch the network.
