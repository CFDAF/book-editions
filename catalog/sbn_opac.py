"""SBN's OPAC API — the uniform-title authority, language pages, name authority.

    POST /o/opac-api/titles-search-post        results, no facets
    POST /o/opac-api/titles-search-full-post   results + facets  <- this module
    GET  /o/opac-api/title?id=<SHORTBID>       one record, with *Titolo di opera*

A **different application** from `catalog/sbn_mobile.py`, on the same host, with
near-identical names for unrelated things. What it has and the mobile gateway
does not is SBN's UNIMARC **uniform-title authority** — the catalogue's own
statement that two records are the same work, which is the strongest bridge
there is and the only one that reaches a book with no Wikipedia article, no
shared ISBN and no Dewey class. Six mobile-gateway full records were once
checked for it, found nothing, and the project concluded no free catalogue
records the link. That was a hole in one API (`docs/DECISIONS.md` pitfall 1).

The facet is the prize and the detail endpoint is not: of the first 45
*Cent'anni* records only 5 carried the *Titolo di opera* row, the first at #41,
yet the facet reports 89. **Ask the facet, never hunt for a linked record.** The
facet is also the safer read — it keys on `name == "titolo_uniformef[]"`, an
internal identifier, where the detail endpoint nests the field under the Italian
display string `"Titolo di opera"`, which a relabel breaks silently.

This module fetches, pages and parses. It does **not** choose the work, exclude
adaptations, or decide which authority record is the person: those are judgements
and they live in `core/identity.py`. Two of them are load-bearing enough to
repeat here as warnings to any caller:

- **The author is not optional** (`CLAUDE.md` rule 3). Bare *Rumori* is 880
  records whose top facet value is Russolo's `arte dei rumori`; bare *The
  Essential Knuth* confidently returns `essential mathematics for economic
  analysis`. With an author both are correct. Nothing here supplies one, so
  nothing here may be called without one.
- **Only `PARAMS` is ever sent** (`CLAUDE.md` rule 2, and the value half of it).
  Unknown keys are ignored silently and the unfiltered set comes back, and so
  are *values* the OPAC cannot use: non-Latin free text is discarded and `ANY +
  AUTHOR` then equals `AUTHOR` alone (F15). Every new key and every new value
  class ships with a bogus-value control that must return 0.
"""

import re

from . import langs
from .http import Pool, SourceError, cached_get_json, cached_post_json
from .sbn_mobile import (PERMALINK, RESPONSIBILITY_RE, TRANSLATION_RE,
                         clean_text, date_statement, is_extent,
                         parse_publication, publisher_names, title_of)

SEARCH = "https://opac.sbn.it/o/opac-api/titles-search-full-post"
TITLE = "https://opac.sbn.it/o/opac-api/title"

# The OPAC's parameter grammar is item:<code>:<Name>:<operator>=value. The codes
# are not guessable: 1004 and 1005 are *not* the author field and answer with
# something that is not JSON at all. The operator suffix does nothing — `@or@`,
# `@and@`, `@frase@` and a bogus `@zzz@` return identical totals.
ANY = "item:1016:Any:@or@"               # free text
AUTHOR = "item:1003:Autore:@and@"        # author
WORK = "titolo_uniformef[]"              # every record linked to that work
NAMES = "item:5032:Nomi::@frase@"        # records under one authority-controlled name
LANGUAGE = "lingua[]"                    # F4: filters, author kept
RECORD_TYPE = "tiporec[]"                # F8
LEVEL = "level[]"                        # F8
YEAR = "dataf[]"                         # F10: exact years only; ranges return 0
PUBLISHER = "editoref[]"                 # F10: exact values

# The whitelist, one per API (build rule 5). `core` and `page` are
# plain keys; the rest are the grammar above.
PARAMS = {"core", "page", ANY, AUTHOR, WORK, NAMES, LANGUAGE, RECORD_TYPE,
          LEVEL, YEAR, PUBLISHER}

FACET = WORK                             # the uniform-title facet's own name
LANGUAGE_FACET = LANGUAGE

# Results arrive as 'ITICCUVEA1284105'; the rest of the project speaks short BIDs.
BID = re.compile(r"^(?:ITICCU)?([A-Z]{2,4}[0-9A-Z]{6,12})$")

PAGE_SIZE = 20                           # F9: fixed; six spellings of a larger
                                         # page were all ignored
# SBN links 89 records to the work behind 'Cent'anni di solitudine', so three
# pages silently lost a third of the one source here that is never wrong.
MAX_PAGES = 12                           # 240 records, the guard's default
# **The listing needs more than 12 pages and the old comment said otherwise.**
# "No corpus work comes near 240" was true of the works Stage 1 listed; it is
# false of *Le Petit Prince* (613 records) and the *Odysseia* (858), whose
# Italian and Greek buckets both run past it. Truncating there did not lose the
# rows — the completeness pass recovered 408 of them — but it recovered them
# from the *unfiltered* work, where they carry no language at all. The cap is
# what decides whether a row keeps its language, so the listing gets its own.
LISTING_MAX_PAGES = 100                  # 2,000 records in one language
# The completeness pass only runs when the language pages came back short, so
# capping *it* would truncate the very rows it exists to recover. It reads the
# whole work, and `truncated` still says so if a work ever exceeds this.
COMPLETENESS_MAX_PAGES = 100
PAGE_WORKERS = 4                         # the politeness the benchmark measured at


def no_data(payload) -> str | None:
    """The reason to reject a body, or None. Given to the cache, not the caller.

    The OPAC's own failures are not JSON at all (a bogus `core` answers 200 with
    an empty body, verified 2026-09-18) and never reach here — the decode raises
    first. This is the shape that would: a valid JSON body with no `data`
    object, which is unusable and must not be cached, since a cached one is
    replayed for 24 h. Defensive: not provoked from the live API.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return "no data object in the response"
    return None


def post(body: dict) -> dict:
    """One search. `data`, unwrapped. Raises SourceError, never returns a guess.

    Every key is checked against `PARAMS` before it is sent, because an unknown
    one is not an error here — it is the unfiltered result set, which is a
    silent wrong answer.
    """
    unknown = sorted(set(body) - PARAMS)
    if unknown:
        raise ValueError(f"not in the OPAC whitelist: {unknown}. Sending it would "
                         "return the unfiltered result set, not an error.")
    return cached_post_json(SEARCH, body, validate=no_data)["data"]


def record(bid: str) -> dict:
    """One record from the detail endpoint. One id only — a comma list returns
    nothing. Presentation JSON: the uniform title is nested under `contents` ->
    `table` -> rows keyed on the Italian string "Titolo di opera", so prefer the
    facet wherever a facet can answer."""
    return cached_get_json(TITLE, {"id": bid, "core": "sbn", "page": "1"})


def work_authority(work_id: str) -> dict:
    """SBN's work authority record: `{"language", "variants"}`, labels as stated.

    `GET title?core=opere` — the same endpoint as `record`, another `core`
    (Step 15B; a bogus id answers `data: null`, and the work id asked as
    `core=sbn` answers nothing). It states the work's language on most works
    and a year on none measured. Presentation JSON keyed on the Italian row
    titles *Lingua* and *Forme varianti*, so a relabel reads as "not stated".
    """
    data = cached_get_json(TITLE, {"id": work_id, "core": "opere", "page": "1"}).get("data")
    rows = _table_rows(data)
    language = rows.get("Lingua", {})
    return {"language": (language.get("value") or "").strip() or None,
            "variants": [c.get("value") for c in rows.get("Forme varianti", {})
                         .get("contents") or [] if c.get("value")]}


_WORK_LINK = re.compile(r"Titolo_uniforme:@frase@=([A-Z0-9]+)$")


def work_links(payload: dict) -> list:
    """`[{"id", "label"}]`: the works a `record` body's *Titolo di opera* row
    links to — the only place a work's id is given."""
    out = []
    for row in _table_rows_all(payload.get("data")):
        if row[0] != "Titolo di opera":
            continue
        stack = [row[1]]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack += node
            elif isinstance(node, dict):
                for v in node.get("values") or []:
                    m = _WORK_LINK.search(v.get("href") or "")
                    if m:
                        out.append({"id": m.group(1), "label": v.get("value") or ""})
                stack += node.get("contents") or []
    return out


def _table_rows_all(data) -> list:
    """`[(title, cell)]` over every `table-title` row of a detail body."""
    out = []
    for res in (data or {}).get("results") or []:
        for block in res.get("contents") or []:
            for row in block.get("body") or []:
                if len(row) >= 2 and isinstance(row[0], dict) \
                        and row[0].get("type") == "table-title":
                    out.append((row[0].get("value"), row[1]))
    return out


def _table_rows(data) -> dict:
    return {title: cell for title, cell in _table_rows_all(data)}


# ---------------------------------------------------------------------------
# Reading a response
# ---------------------------------------------------------------------------

def facet_items(data: dict, name: str) -> list:
    """[{label, results, value}] for one facet, or [] when it is absent.

    Facets cap at 50 items for a prolific author (F11), so a truncated list is
    normal and the caller reports it rather than assuming completeness.
    """
    f = next((f for f in data.get("facets") or [] if f.get("name") == name), None)
    return (f or {}).get("items") or []


def total(data: dict) -> int:
    return data.get("total") or 0


def page_count(data: dict, cap: int = MAX_PAGES) -> int:
    """How many pages this result set has, capped. `page_count(d) < pages(d)`
    is the caller's signal that it is about to truncate."""
    return min((total(data) + PAGE_SIZE - 1) // PAGE_SIZE, cap)


# The `infos` element that states what kind of record this is, not where it was
# published: '<medium> - <level> [IT\ICCU\UBO\4636099]'. Every row carries one
# and it is normally `infos[1]`, but a row with no imprint at all makes it
# `infos[0]` — which is how `infos[0]` stops being the imprint.
_RECORD_TYPE = re.compile(r"^(?P<medium>[^\[]+?)\s+-\s+(?P<level>[^\[]+?)\s*\[IT.ICCU")
# 'Fa parte di: Romanzi e saggi' — the host record of a volume in a set.
_PART_OF = re.compile(r"^Fa parte di\s*:", re.I)
_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
# '{Delitto e castigo : romanzo}2' — a volume of a set, the set's own title in
# braces and the volume's designation after them, where ISBD would write
# 'Delitto e castigo : romanzo. 2'. Left as it is, the header takes an 1889
# volume's title as the work's and cuts it at the colon: '{Delitto e castigo'.
_VOLUME = re.compile(r"^\{(?P<set>[^}]*)\}\s*")


def volume_title(title: str) -> str:
    """A volume's title written the ISBD way; any other title unchanged."""
    m = _VOLUME.match(title)
    if not m:
        return title
    rest = title[m.end():]
    return f"{m['set'].strip()}. {rest}" if rest else m["set"].strip()


def imprint_of(infos) -> str | None:
    """The publication statement, or None — never `infos[0]` taken on trust.

    `infos[0]` is the imprint on 2,577 of 2,603 rows and something else on the
    other 26 (`docs/sbn-api.md` trap 10): `12. rist`, `533 p`, `3. ed`, a
    `Fa parte di:` host record, or the record-type element when the row carries
    no imprint at all. Taking it on trust publishes `Testo - Monografia` as a
    publisher.

    So an imprint has to look like one: ISBD writes `Place : Publisher, Year`,
    and an element with neither a ` : ` nor a year is an extent or an edition
    statement, not a place of publication. Nor is one with a colon when it
    opens with a count: `121 p. : ill. ; 24 cm`.
    """
    for info in infos or []:
        text = clean_text(info)
        if not text or _RECORD_TYPE.match(text) or _PART_OF.match(text):
            continue
        if (":" in text or _YEAR.search(text)) and not is_extent(text):
            return text
    return None


def record_type_of(infos) -> tuple:
    """`(medium, level)` from the record-type element — 'Testo', 'Monografia'.

    The medium is the same vocabulary the mobile gateway's full record puts in
    `tipo`, so a listing row can be told apart from a DVD or a score without a
    second request. It does **not** separate a study guide from an edition:
    every one of F16's three non-editions is `Testo - Monografia`.
    """
    for info in infos or []:
        m = _RECORD_TYPE.match(clean_text(info) or "")
        if m:
            return m.group("medium").strip(), m.group("level").strip()
    return None, None


def parse_rows(data: dict, language: str | None = None) -> list:
    """The result rows as plain fields.

    `title.info` is the catalogued title with its statement of responsibility
    (`'Kafka on the shore / Haruki Murakami ; translated from the Japanese by
    Philip Gabriel'`) and **`title.text` is the record's main author heading**
    (`'Murakami, Haruki'`) — not the statement of responsibility, which this
    docstring said until Step 7 read a hundred of them.

    `infos` is kept whole beside the two fields read out of it, because a caller
    that needs certainty about either reads the full record.
    """
    out = []
    for row in data.get("results") or []:
        m = BID.match(str(row.get("id") or "").strip())
        if not m:
            continue
        title = row.get("title") or {}
        if not isinstance(title, dict):
            title = {"info": title}
        infos = row.get("infos") or []
        medium, level = record_type_of(infos)
        out.append({
            "id": m.group(1),
            "title": str(title.get("info") or "").strip(),
            "author": clean_text(title.get("text")),
            "imprint": imprint_of(infos),
            "infos": list(infos),
            "medium": medium,
            "level": level,
            "type": row.get("type"),
            "language": language,
        })
    return out


def listing_record(row: dict) -> dict:
    """One listing row as plain fields, named the way a `core.model.Record` is.

    A dict rather than a `Record` because `catalog/` may not import `core/`.
    Everything here is on the row: **no full record is needed to place it**
    (A3 — 98.4% of rows parse a year, 2,602 of 2,603 a publisher), which is
    what makes listing by identity 3.5 s against today's 34.5 s.

    What a row cannot carry is on `Record`'s defaults and stays there until S4
    enriches it: no ISBN, no Dewey, no holdings, no named translator (F5). The
    one piece of translation evidence a row *does* hold is in the title's own
    statement of responsibility — `'... ; translated from the Japanese by Philip
    Gabriel'` — which is the only trace `UBO4636099` has of being a translation,
    and the reason `core.identity.language_contradicts_itself` can fire here.
    """
    publisher, year, place = parse_publication(row.get("imprint"))
    raw_title = volume_title(clean_text(row.get("title")) or "")
    _, _, responsibility = raw_title.partition(" / ")
    evidence = []
    if responsibility and (RESPONSIBILITY_RE.search(responsibility)
                           or TRANSLATION_RE.search(responsibility)):
        evidence.append(responsibility.strip())
    bid = row["id"]
    return {
        "source": "SBN",
        "id": bid,
        "title": title_of(raw_title),
        "publisher": ", ".join(filter(None, [publisher, place])) or None,
        "year": year,
        "date": date_statement(row.get("imprint")),
        "language": langs.from_sbn_code(row.get("language")),
        "url": PERMALINK.format(bid),
        "medium": (row.get("medium") or "").lower() or None,
        "authors": [row["author"]] if row.get("author") else [],
        "evidence": evidence,
        "publisher_names": publisher_names(publisher) if publisher else [],
        "places": [place] if place else [],
    }


def parse_authorities(data: dict) -> list:
    """`core=autori` rows: the authority id, its heading and what kind it is.

    `kind` is `infos[0]` and is "Persona" for a person. Which of these *is* the
    person asked for is a judgement and is not made here — SBN gives one id per
    person for every Latin form and drops the non-Latin ones (A7), so the
    choosing rule matters and belongs with the other gates.
    """
    out = []
    for row in data.get("results") or []:
        m = BID.match(str(row.get("id") or "").strip())
        title = row.get("title") or {}
        if not isinstance(title, dict):
            title = {"text": title}
        infos = row.get("infos") or []
        out.append({
            "id": m.group(1) if m else str(row.get("id") or "").strip(),
            "heading": str(title.get("text") or "").strip(),
            "kind": infos[0] if infos else None,
        })
    return out


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------

def all_rows(body: dict, first: dict | None = None, language: str | None = None,
             cap: int = MAX_PAGES) -> dict:
    """Every row of one query, pages 2..n fetched `PAGE_WORKERS` at a time.

    `{"rows", "total", "pages", "truncated", "failed", "years"}` — `pages` being what
    this query actually cost, which is how the caller reports the guard's B
    requests without counting them a second way. A page that fails is named in
    `failed` and the rest are still returned — a partial answer the caller can
    disclose beats an exception that loses the 200 rows that did arrive. Every
    failure is on the ledger regardless (`catalog/http.py`), so it is counted
    whether or not the caller mentions it.
    """
    first = first if first is not None else post({**body, "page": "1"})
    n = page_count(first, cap)
    rows, failed = parse_rows(first, language), []

    def page(p):
        return parse_rows(post({**body, "page": str(p)}), language)

    if n > 1:
        with Pool(PAGE_WORKERS) as pool:
            futures = {p: pool.submit(page, p) for p in range(2, n + 1)}
        for p, future in futures.items():
            try:
                rows += future.result()
            except SourceError as exc:
                failed.append({"page": p, "error": str(exc)[:200]})
    return {"rows": rows, "total": total(first), "pages": n, "failed": failed,
            "truncated": (total(first) + PAGE_SIZE - 1) // PAGE_SIZE > cap,
            # SBN's own dates for the whole answer, with counts, off page 1: what
            # a listing's plain years are reconciled against (decision AY).
            "years": facet_items(first, YEAR)}


# ---------------------------------------------------------------------------
# The three queries the build makes
# ---------------------------------------------------------------------------

def work_facet(title: str, author: str) -> dict:
    """`{core, ANY, AUTHOR}` page 1: the `titolo_uniformef[]` facet and the total.

    The caller picks W from `items` (`core.identity.pick_work`) — this only
    reads. **`author` is mandatory** and empty is a programming error, not a
    query: without it the top facet value belongs to a different book.
    """
    if not (title and author):
        raise ValueError("the OPAC work query always carries the author "
                         "(CLAUDE.md rule 3): bare Rumori returns Russolo.")
    data = post({"core": "sbn", ANY: title, AUTHOR: author, "page": "1"})
    return {"items": facet_items(data, FACET), "total": total(data), "first": data}


def work_records(work: str, author: str, language: str | None = None) -> dict:
    """Every record SBN files under uniform title `work`, optionally one language.

    With `language`, this is the listing query: `lingua[]` filters and the author
    is kept (F4). Without it, the unfiltered work — which is how a caller finds
    the records no language page returned.

    **`ANY` is not in this body and must never be added.** The guard's second
    query *is* `ANY + AUTHOR + W` and its answer is the intersection (F2: 89 of
    the work's 143 records for *Cent'anni*), which is a different question: it
    asks what share of the query's records SBN files under W. Asking it here
    would list a third of the work.
    """
    if not (work and author):
        raise ValueError("the OPAC work query always carries the author "
                         "(CLAUDE.md rule 3).")
    body = {"core": "sbn", AUTHOR: author, WORK: work}
    if language:
        body[LANGUAGE] = language
    return all_rows(body, language=language, cap=LISTING_MAX_PAGES)


def work_languages(work: str, author: str) -> dict:
    """Page 1 of the work listing: the `lingua[]` facet, the total, the body.

    `{"items", "total", "first"}` — `first` handed back so the caller can page
    the unfiltered work without paying for page 1 twice. The caller decides
    what the facet means; this only reads it.
    """
    if not (work and author):
        raise ValueError("the OPAC work query always carries the author "
                         "(CLAUDE.md rule 3).")
    data = post({"core": "sbn", AUTHOR: author, WORK: work, "page": "1"})
    return {"items": facet_items(data, LANGUAGE_FACET), "total": total(data),
            "first": data}


def authorities(text: str, pages: int = 2) -> dict:
    """`core=autori`: name-authority records matching a free-text name form.

    `{"rows", "total"}`. The total is the caller's control as much as its
    paging: a term the OPAC **dropped** comes back as the bare `core=autori`
    total rather than as an error (F15's shape on this core), and only the
    number says so.

    SBN gives one id per person for every Latin form and silently drops
    non-Latin ones (A7, F15) — so send romanised text, and prove the term was
    used with a control that must return 0.
    """
    if not text:
        return {"rows": [], "total": 0}
    first = post({"core": "autori", ANY: text, "page": "1"})
    rows = parse_authorities(first)
    for p in range(2, min(page_count(first), pages) + 1):
        rows += parse_authorities(post({"core": "autori", ANY: text, "page": str(p)}))
    return {"rows": rows, "total": total(first)}


FACET_CAP = 50                           # F11: every facet stops here


def authority_facets(authority_id: str, language: str | None = None,
                     year: str | None = None) -> dict:
    """Page 1 of the records under one name, as facets: the person's works.

    `{"works", "languages", "years", "total"}` — the `titolo_uniformef[]`,
    `lingua[]` and `dataf[]` facets, each `[{value, label, results}]`. Each one
    stops at `FACET_CAP` (F11), so a list of exactly 50 is a truncated list,
    and `language` and `year` exist to split it: both keys are whitelisted and
    controlled (F4, F10), and `dataf[]` takes an exact year only.

    The authority id is the author term here, so rule 3 holds by construction.
    """
    if not authority_id:
        raise ValueError("a works facet needs an authority id")
    body = {"core": "sbn", NAMES: authority_id, "page": "1"}
    if language:
        body[LANGUAGE] = language
    if year:
        body[YEAR] = str(year)
    data = post(body)
    return {"works": facet_items(data, FACET),
            "languages": facet_items(data, LANGUAGE_FACET),
            "years": facet_items(data, YEAR), "total": total(data)}


def authority_work(authority_id: str, work: str) -> dict:
    """Page 1 of one work's records under one name: how it is catalogued.

    `{"rows", "languages", "years", "total"}`. The rows are the catalogued
    titles the work goes by in each language — which is what lets an Open
    Library record titled *Mente e natura* join `mind and nature`, where the
    uniform title alone scores 0.0 — and the two facets say in how many
    languages SBN holds it and its earliest year.
    """
    if not (authority_id and work):
        raise ValueError("a work's records need the authority id and the work")
    data = post({"core": "sbn", NAMES: authority_id, WORK: work, "page": "1"})
    return {"rows": parse_rows(data), "languages": facet_items(data, LANGUAGE_FACET),
            "years": facet_items(data, YEAR), "total": total(data)}


def authority_work_records(authority_id: str, work: str, cap: int) -> dict:
    """Every record of one work under one name, `authority_work`'s query paged
    to `cap`. Page 1 is the same body `authority_work` sent, so the cache has it.
    """
    if not (authority_id and work):
        raise ValueError("a work's records need the authority id and the work")
    return all_rows({"core": "sbn", NAMES: authority_id, WORK: work}, cap=cap)


def records_by_authority(authority_id: str, cap: int = MAX_PAGES) -> dict:
    """Every record filed under one authority-controlled name.

    This is the author sweep's backbone, and it is not replaceable by the work
    authority: SBN's work links are partial, 334 same-work records over 40 books
    are not linked to W, and `UFI0556368` is reachable only this way.
    """
    if not authority_id:
        return {"rows": [], "total": 0, "failed": [], "truncated": False}
    return all_rows({"core": "sbn", NAMES: authority_id}, cap=cap)
