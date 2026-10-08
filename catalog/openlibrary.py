"""Open Library — search, work records, and a work's editions by key.

Necessary and never sufficient:

- **It splits translations into separate works, inconsistently.** `OL2625431W`
  holds 61 editions of *Kafka on the Shore* across 16 languages and `OL274505W`
  holds 208 of *Cien años de soledad*, but *Rumori* sits in its own work,
  separate from *Bruits*. So one work key is not the whole picture: Stage 2 lost
  **98 editions** to duplicate work records over 21 books, and that is a lower
  bound (U6).
- **`translation_of` exists but is not a bridge.** It lives on *editions*, not on
  works — `/works/OL15764295W.json` has no such field because it is a work
  record, which is how the project came to believe the field did not exist at
  all. It is populated (`Kafka a la platja` carries
  `translation_of: 海辺のカフカ`), but present on 3 of 35 Italian editions in
  cache, 8.6%, so it is recorded here and relied on nowhere.
- **It has duplicate author records.** 'Jacques Attali' is `OL53916A` (160
  works), `OL4762242A` (17) and `OL12549002A` (1). Resolving to one key silently
  loses works, so every plausible key is returned and the caller keeps them all.
  It also *omits* the main record for Murakami, Dostoevsky and Han (A7).

One shape to know before searching:

- **`title=` will not match a title carrying its subtitle.** `Noise: The
  Political Economy of Music` returns zero docs; `Noise` returns the work. So a
  caller pools several spellings rather than trusting one.

`/works/<key>/editions.json` is the one thing here that is **verified rather than
measured**: it returned every known edition for 45 of 45 duplicate works, and a
bogus key answers 404 (F19). That is why a duplicate work is opened by key and
never found by searching its title, which returns the main work again 24 times
out of 33.

Fetch and parse only. Which work is this work, and which records belong to it,
are decided in `core/`.
"""

import re

from . import langs
from .http import SourceError, cached_get_json

BASE = "https://openlibrary.org"

# The fields a search doc has to carry for anything downstream to use it. Asked
# for explicitly: the default response is far larger and slower.
SEARCH_FIELDS = ("key,title,author_name,author_key,first_publish_year,language,"
                 "edition_count,publisher,isbn,cover_i,ddc,lcc,subject")

# What a candidate for the duplicate list needs and no more: a hundred docs
# with their ISBN and publisher lists is a body many times this size.
DUPLICATE_FIELDS = ("key,title,author_name,author_key,edition_count,language,"
                    "first_publish_year")

# 100, not the benchmark's 1,000: from 2026-09-27 Open Library breaks a large
# work's `editions.json` at 1,000 — the chunked body stops at byte 7,917 every
# time (N02, N06, N23) — and answers every page at 100 whole (727 of 727, 1,066
# of 1,066). `links.next` pages the rest, so nothing is lost but requests.
EDITIONS_PAGE = 100
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")

# Codes that mean "not recorded" rather than naming a language.
_NO_LANGUAGE = {"und", "zxx", "mis"}


def payload_error(data) -> str | None:
    """The reason to reject a body, or None. Given to the cache, not the caller.

    Open Library answers a bad request with a 4xx, which `raise_for_status`
    already turns into a `SourceError`, and a missing work key with a 404 (F19's
    control). What it must not do is hand back a body with no `docs` and no
    `entries` and have that cached as an empty answer, so the shape is checked:
    a dict is required, and nothing else is assumed.
    """
    if not isinstance(data, dict):
        return f"response was {type(data).__name__}, not an object"
    return None


# ---------------------------------------------------------------------------
# Searching
# ---------------------------------------------------------------------------

def search(q: str | None = None, title: str | None = None, author: str | None = None,
           language: str | None = None, publisher: str | None = None,
           year_from=None, year_to=None, limit: int = 60) -> list:
    """Ranked work docs. Year ranges go through Solr syntax in `q`.

    Returns `[]` rather than everything when given nothing to search on: an
    unfiltered search is never what a caller meant.
    """
    params = {"limit": limit, "fields": SEARCH_FIELDS}
    if title:
        params["title"] = title
    if author:
        params["author"] = author
    if language:
        params["language"] = language
    if publisher:
        params["publisher"] = publisher
    clauses = [q] if q else []
    if year_from or year_to:
        clauses.append(f"first_publish_year:[{year_from or '*'} TO {year_to or '*'}]")
    if clauses:
        params["q"] = " AND ".join(clauses)
    if not any(k in params for k in ("title", "author", "language", "publisher", "q")):
        return []
    data = cached_get_json(f"{BASE}/search.json", params, validate=payload_error)
    return data.get("docs") or []


def search_counted(q: str, limit: int = 100) -> dict:
    """`{"docs", "total"}` for one free-text query.

    `total` is Open Library's own `numFound`, so a caller that read only the
    first `limit` docs can say so: *1984 George Orwell* finds 278 and the page
    holds 100 (rule 10 — every truncation is on the page).
    """
    if not q:
        return {"docs": [], "total": 0}
    data = cached_get_json(f"{BASE}/search.json",
                           {"q": q, "fields": DUPLICATE_FIELDS, "limit": limit},
                           validate=payload_error)
    return {"docs": data.get("docs") or [], "total": data.get("numFound")}


AUTHOR_WORKS_PAGE = 1000        # search.json's own maximum `limit`
AUTHOR_WORKS_MAX_PAGES = 5


def works_by_author(author: str, max_pages: int = AUTHOR_WORKS_MAX_PAGES) -> dict:
    """`{"docs", "total"}`: every work doc Open Library's `author=` search holds.

    Paged to `max_pages` of `AUTHOR_WORKS_PAGE`; `total` is `numFound`, so the
    caller can say when it read fewer (Dostoevsky: 2,835). Which docs are by
    the person, and which work each belongs to, is not decided here.
    """
    if not author:
        return {"docs": [], "total": 0}
    docs, total = [], 0
    for page in range(1, max_pages + 1):
        data = cached_get_json(f"{BASE}/search.json",
                               {"author": author, "fields": DUPLICATE_FIELDS,
                                "limit": AUTHOR_WORKS_PAGE, "page": page},
                               validate=payload_error)
        total = data.get("numFound") or 0
        got = data.get("docs") or []
        docs += got
        if len(got) < AUTHOR_WORKS_PAGE or len(docs) >= total:
            break
    return {"docs": docs, "total": total}


def author_keys(author: str, limit: int = 10) -> list:
    """`[{"key", "name"}]` from Open Library's own author search.

    Every match, unfiltered and in its own ranking: which of them is the person
    is a judgement, and the duplicates are the point — dropping them loses works.
    """
    if not author:
        return []
    data = cached_get_json(f"{BASE}/search/authors.json", {"q": author, "limit": limit},
                           validate=payload_error)
    return [{"key": d.get("key"), "name": d.get("name") or ""}
            for d in (data.get("docs") or [])[:limit] if d.get("key")]


# ---------------------------------------------------------------------------
# A work's editions, by key
# ---------------------------------------------------------------------------

def editions(work_key: str, limit: int = EDITIONS_PAGE) -> dict:
    """Every edition of one work, following `links.next`.

    `{"rows", "size", "failed"}`. `size` is Open Library's own count, so a caller
    can say when the paging stopped short.

    **By key, never by title.** Verified for 45 of 45 duplicate works (F19); the
    title search returns the main work again 24 of 33 times, a different book 5,
    and the duplicate itself 3.
    """
    key = work_key.replace("/works/", "").strip("/")
    url, params = f"{BASE}/works/{key}/editions.json", {"limit": limit}
    entries, failed, size = [], [], None
    while url:
        try:
            data = cached_get_json(url, params, validate=payload_error)
        except SourceError as exc:
            failed.append(str(exc)[:200])
            break
        size = data.get("size", size)
        entries += data.get("entries") or []
        nxt = (data.get("links") or {}).get("next")
        url, params = (f"{BASE}{nxt}", None) if nxt else (None, None)
    return {"rows": [parse_edition(e) for e in entries], "size": size, "failed": failed}


def work(work_key: str) -> dict:
    """One work record. Carries title and authors; no `translation_of` — that is
    an edition field, and believing otherwise is `docs/DECISIONS.md` pitfall 1."""
    key = work_key.replace("/works/", "").strip("/")
    return cached_get_json(f"{BASE}/works/{key}.json", validate=payload_error)


# ---------------------------------------------------------------------------
# One edition, in full — what a reader opens a row to see
# ---------------------------------------------------------------------------

COVER = "https://covers.openlibrary.org/b/id/{id}-M.jpg"
ARCHIVE = "https://archive.org/details/{ocaid}"


def book(edition_key: str) -> dict:
    """One edition record, by its Open Library key.

    The listing row is `editions.json`'s **projection** of this same document —
    `parse_edition` keeps what a `Record` has and drops the rest — so this is
    the richer half, asked for only when a reader expands the row (Step 10) and
    never for a list. Control: a bogus key answers **404**, which
    `raise_for_status` turns into a `SourceError`
    (`OL7353617M` 200 / `OL0000000000M` 404, 2026-09-23 **V**).
    """
    key = edition_key.replace("/books/", "").strip("/")
    return cached_get_json(f"{BASE}/books/{key}.json", validate=payload_error)


def _text(value) -> str:
    """Open Library writes free text either bare or as `{type, value}`."""
    if isinstance(value, dict):
        return str(value.get("value") or "").strip()
    return str(value or "").strip()


def parse_book(entry: dict) -> dict:
    """One edition record as the display fields a row shows when it is opened.

    Fetch and parse only: nothing here decides whether the record belongs to the
    work — it was already admitted as a `Record`, and this is the same row seen
    in full.

    `covers` carries **-1** where a cover slot is empty, which is a real value
    in real records (`OL7353617M`: `[15152634, 8739161, -1]`), so a cover id is
    taken only where it is positive.
    """
    covers = [c for c in (entry.get("covers") or []) if isinstance(c, int) and c > 0]
    ocaid = str(entry.get("ocaid") or "").strip()
    pages = entry.get("number_of_pages")
    return {
        "title": entry.get("title") or "",
        "subtitle": entry.get("subtitle") or "",
        "edition_name": entry.get("edition_name") or "",
        "by_statement": entry.get("by_statement") or "",
        "physical_format": entry.get("physical_format") or "",
        "pages": int(pages) if isinstance(pages, int) else None,
        "pagination": entry.get("pagination") or "",
        "places": [p for p in (entry.get("publish_places") or []) if p],
        "publish_date": entry.get("publish_date") or "",
        "publishers": [p for p in (entry.get("publishers") or []) if p],
        "series": [s for s in (entry.get("series") or []) if s],
        "contributions": [c for c in (entry.get("contributions") or []) if c],
        "isbns": list(entry.get("isbn_13") or []) + list(entry.get("isbn_10") or []),
        "cover_url": COVER.format(id=covers[0]) if covers else None,
        # A scan anybody can read, where Open Library records one. For an
        # out-of-print book this is the only honest answer to "where do I get a
        # copy", and it is a catalogue statement rather than a shop's guess.
        "archive_url": ARCHIVE.format(ocaid=ocaid) if ocaid else None,
        "description": _text(entry.get("description")),
        "notes": _text(entry.get("notes")),
        "first_sentence": _text(entry.get("first_sentence")),
        # Recorded and relied on nowhere as a discovery route (8.6% of the
        # Italian editions in cache), but on an opened row it is the catalogue
        # saying what this edition was translated from, which is the question
        # the whole tool is about.
        "translation_of": entry.get("translation_of") or "",
        "translated_from": [langs.from_openlibrary(l.get("key"))
                            for l in entry.get("translated_from") or []],
        "url": f"{BASE}/books/{entry.get('key', '').replace('/books/', '').strip('/')}"
               if entry.get("key") else None,
    }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def publisher_names(publishers) -> list:
    """The publisher statements split into publishers.

    Open Library keeps a list, but a single entry can still carry ISBD
    punctuation copied from a record, so the same separators apply.
    """
    out = []
    for value in publishers or []:
        for piece in str(value).split(";"):
            for part in re.split(r"\s+:\s+", piece):
                out += [n.strip() for n in
                        re.split(r"\bin association with\b", part, flags=re.I) if n.strip()]
    return out


def parse_edition(entry: dict, authors=None) -> dict:
    """One `editions.json` entry as plain fields, named the way a `Record` is.

    `authors` is passed down from the work, because `editions.json` rarely
    carries them. A language that is not recorded stays unknown: Open Library
    records one for 80.8% of editions, and the original script counted the blanks
    as English, which inflated the English list.
    """
    codes = [langs.from_openlibrary(l.get("key")) for l in entry.get("languages") or []]
    known = [c for c in codes if c != langs.UNKNOWN]
    isbns_raw = list(entry.get("isbn_13") or []) + list(entry.get("isbn_10") or [])
    publishers = entry.get("publishers") or []
    series = entry.get("series") or []
    date = entry.get("publish_date")
    year = _YEAR_RE.search(date or "")
    key = entry.get("key") or ""
    return {
        "source": "Open Library",
        "id": key.rsplit("/", 1)[-1] or None,
        "title": entry.get("title") or "",
        "publisher": ", ".join(publishers) or None,
        "year": year.group(1) if year else None,
        "date": (date or "").strip() or None,
        "language": known[0] if known else langs.UNKNOWN,
        "isbn": isbns_raw[0] if isbns_raw else None,
        "isbns_raw": isbns_raw,
        "url": f"{BASE}{key}" if key else None,
        "series": series[0] if series else None,
        "physical": f"{entry['number_of_pages']} p." if entry.get("number_of_pages") else None,
        "dewey": None,                  # not on an edition; the work carries it
        "dewey_all": [],
        "medium": None,
        "cover_url": None,
        "authors": list(authors or []),
        "translators": [],
        "evidence": [],
        "holdings": [],
        "publisher_names": publisher_names(publishers),
        "places": list(entry.get("publish_places") or []),
        # Recorded, relied on nowhere: present on 8.6% of the Italian editions in
        # cache, which is too thin and too biased to be a discovery route.
        "translation_of": entry.get("translation_of"),
        "works": [w.get("key") for w in entry.get("works") or [] if w.get("key")],
    }


def parse_doc(doc: dict) -> dict:
    """A search doc as plain fields. Coarser than an edition — one row standing
    for a work, which is what a duplicate work record is listed as until it is
    opened by key (decision J)."""
    codes = [langs.from_openlibrary(c) for c in doc.get("language") or []]
    known = [c for c in codes if c != langs.UNKNOWN]
    publishers = doc.get("publisher") or []
    isbns_raw = list(doc.get("isbn") or [])
    key = (doc.get("key") or "").replace("/works/", "").strip("/")
    ddc = list(doc.get("ddc") or [])
    return {
        "source": "Open Library",
        "id": key or None,
        "title": doc.get("title") or "",
        "publisher": publishers[0] if publishers else None,
        "year": str(doc["first_publish_year"]) if doc.get("first_publish_year") else None,
        "language": known[0] if known else langs.UNKNOWN,
        "languages": sorted(set(known)),
        "isbn": isbns_raw[0] if isbns_raw else None,
        "isbns_raw": isbns_raw,
        "url": f"{BASE}/works/{key}" if key else None,
        "series": None,
        "physical": None,
        "dewey": ddc[0] if ddc else None,
        "dewey_all": ddc,
        "medium": None,
        "cover_url": None,
        "authors": list(doc.get("author_name") or []),
        "translators": [],
        "evidence": [],
        "holdings": [],
        "publisher_names": publisher_names(publishers),
        "places": [],
        "edition_count": doc.get("edition_count"),
        "author_keys": [k if str(k).startswith("/") else f"/authors/{k}"
                        for k in doc.get("author_key") or []],
    }


def language_codes(rows) -> list:
    """The languages a set of parsed rows actually records, `und`/`zxx`/`mis` out."""
    return sorted({r["language"] for r in rows
                   if r["language"] not in _NO_LANGUAGE and r["language"] != langs.UNKNOWN})
