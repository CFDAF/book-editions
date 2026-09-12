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
`python book_editions.py "<title>"`.

## Rules specific to this project

1. **The header is a publication history, not a verdict.** An earlier version led
   with "Translated into Italian." — the user rejected that framing. Do not
   re-introduce a yes/no hero.
2. **Never send SBN a parameter that is not in `sbn.PARAMS`.** Unknown params are
   silently ignored and the *unfiltered* result set comes back — a silent wrong
   answer, not an error.
3. **`linguaPubblicazione` is the only language signal.** `paesePubblicazione` is
   a country and says nothing about language.
4. **A failed request must never be indistinguishable from an empty result.**
   Swallowed failures go through `net.Tally`; sources degrade to
   `partial (N failed)`. This was the single worst bug in the project.
5. **Don't loosen the identifying-signal gate** (`pipeline._identifies`,
   `IDENTIFYING_TITLE_MATCH = 0.6`) without re-checking the regression cases in
   `HANDOFF.md` §9 — particularly *L'ordine delle notizie* and
   *Quale socialismo, quale Europa*.
6. **Google Books was removed deliberately.** Keyless quota permanently
   exhausted; it contributed nothing. Don't re-add it as "another source".
7. **Stop the server with `pkill -f server.py`** — macOS reports the process as
   `Python server.py`, so `pkill -f "python3 server.py"` silently matches
   nothing and leaves a stale instance serving old code.
8. Cold lookups take 30–45s and cache to `.cache/` for 24h; repeats are instant.
   Delete `.cache/` to force fresh data.

## No automated tests

Verification is by the inline assertion patterns and regression table in
`HANDOFF.md` §9. Adding `pytest` coverage for the pure functions
(`matching.py`, `langs.py`, `sbn.py` parsers, `pipeline._dewey_affinity`,
`pipeline._identifies`) is the cheapest available improvement.
