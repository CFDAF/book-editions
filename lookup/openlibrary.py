"""Open Library — the broadest edition source, and the recall net for Italian.

Open Library is necessary but never sufficient:

- It has no translation_of field. /works/OL15764295W.json (Rumori) carries only
  title, authors, type, revision — nothing pointing at OL685250W (Bruits). So
  translations are found by *title variant*, supplied by the Wikidata crosswalk,
  or by a language-filtered author sweep — never by following a link.

- It splits translations into separate works, so one work key is not the whole
  picture. Sibling works must be swept in as well.

- It has duplicate author records. 'Jacques Attali' is OL53916A (160 works),
  OL4762242A (17) and OL12549002A (1). Resolving to one key silently loses
  works, so every plausible key is kept and merged.

Its saving grace is that `language=ita` works, which is what found Rumori where
Wikidata has no Italian label at all.
"""

from concurrent.futures import ThreadPoolExecutor

from . import langs
from .matching import author_matches, core_title, normalize, title_similarity
from .models import Edition
from .net import SourceError, cached_get_json

BASE = "https://openlibrary.org"
SEARCH_FIELDS = ("key,title,author_name,author_key,first_publish_year,language,"
                 "edition_count,publisher,isbn,cover_i,ddc,lcc,subject")


def resolve_author_keys(author: str, limit: int = 5) -> list:
    """Every author record whose name matches — duplicates included, on purpose."""
    if not author:
        return []
    data = cached_get_json(f"{BASE}/search/authors.json", {"q": author})
    keys = []
    for doc in (data.get("docs") or [])[:limit]:
        if author_matches(author, [doc.get("name", "")]):
            keys.append(doc["key"])
    return keys


def search_works(title=None, author=None, language=None, publisher=None,
                 year_from=None, year_to=None, limit=60, q=None) -> list:
    """Ranked work docs. Year ranges go through Solr syntax in `q`."""
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
    data = cached_get_json(f"{BASE}/search.json", params)
    return data.get("docs") or []


def best_match(title: str, author: str | None, docs: list) -> tuple:
    """(work_key | None, score, ranked). Scoring kept from the original script."""
    scored = []
    for doc in docs:
        candidate = doc.get("title", "")
        score = max(title_similarity(title, candidate),
                    title_similarity(core_title(title), core_title(candidate)))
        if author and not author_matches(author, doc.get("author_name", [])):
            score *= 0.5  # heavy penalty, but author names vary too much to zero it
        scored.append((score, candidate, (doc.get("key") or "").replace("/works/", "")))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0.0, []
    best_score, _, best_key = scored[0]
    return (best_key if best_score >= 0.5 else None), best_score, scored[:5]


def work_ddc(work_key: str) -> list:
    """Dewey classes recorded for a work — the cross-language matching signal.

    Verified: the original Bruits/Noise work carries ddc ['306.484', '780.07'],
    and SBN's Italian Rumori is classified 780.07. Their titles share not one
    token, so this is what connects them.
    """
    docs = cached_get_json(f"{BASE}/search.json",
                           {"q": f"key:/works/{work_key}", "fields": "key,ddc"})
    for doc in docs.get("docs") or []:
        return doc.get("ddc") or []
    return []


def candidates(variants: list, author: str | None, publisher=None,
               year_from=None, year_to=None, limit: int = 60, tally=None) -> list:
    """Pooled, de-duplicated work docs for a set of title variants.

    Open Library's title= index will not match a title carrying its subtitle:
    searching 'Noise: The Political Economy of Music' returns zero docs while
    'Noise' returns the work. The original script handled this with several
    search strategies pooled together; that behaviour is kept here, now run over
    every known title variant rather than a single English title.
    """
    seen, pooled = set(), []
    queries = []
    for variant in variants:
        if not variant:
            continue
        core = core_title(variant)
        queries.append({"title": variant})
        if core.lower() != variant.lower():
            queries.append({"title": core})
        queries.append({"q": f"{core} {author or ''}".strip()})

    def run(q):
        try:
            return search_works(author=author, publisher=publisher, year_from=year_from,
                                year_to=year_to, limit=limit, **q)
        except SourceError as exc:
            if tally is not None:
                tally.note("Open Library", exc)
            return []

    # Open Library answers in 1-3s, and there are a dozen of these; run them
    # together or the first lookup of a book takes over a minute.
    with ThreadPoolExecutor(max_workers=6) as pool:
        for docs in pool.map(run, queries):
            for doc in docs:
                key = doc.get("key")
                if key and key not in seen:
                    seen.add(key)
                    pooled.append(doc)
    return pooled


def expand(keys: list, tally=None, authors_by_key=None) -> tuple:
    """(editions, dewey classes) for several works at once."""
    def one(key):
        try:
            return editions(key, authors=(authors_by_key or {}).get(key)), work_ddc(key)
        except SourceError as exc:
            if tally is not None:
                tally.note("Open Library", exc)
            return [], []

    found, ddc = [], []
    if not keys:
        return found, ddc
    with ThreadPoolExecutor(max_workers=4) as pool:
        for eds, classes in pool.map(one, keys):
            found += eds
            ddc += classes
    return found, list(dict.fromkeys(ddc))


def authors_by_work(docs: list) -> dict:
    """work key -> author names, so expand() can attach them to editions."""
    out = {}
    for doc in docs:
        key = (doc.get("key") or "").replace("/works/", "")
        if key and doc.get("author_name"):
            out[key] = list(doc["author_name"])
    return out


def best_works(variants: list, author: str | None, docs: list, limit: int = 3) -> tuple:
    """(work keys worth expanding, ranked debug list).

    Scored against EVERY known title variant, not just the query string. Open
    Library holds this work under two keys — a stub 'Noise' (OL19402867W, 1
    edition, no Dewey) and the real 'Bruits' (OL685250W, 7 editions, ddc 780.07).
    Scoring 'Noise' against the string 'Bruits' gives 0.0 and loses the useful
    record entirely; scoring against the variant 'Bruits: essai sur l'economie
    politique de la musique' matches it on the core title.

    Near-ties are then broken by edition_count, and the top few keys expanded
    together, because a translation is often a separate work.
    """
    scored = []
    for doc in docs:
        candidate = doc.get("title", "")
        score = 0.0
        for variant in variants:
            if not variant:
                continue
            score = max(score,
                        title_similarity(variant, candidate),
                        title_similarity(core_title(variant), core_title(candidate)))
        if author and not author_matches(author, doc.get("author_name", [])):
            score *= 0.5
        key = (doc.get("key") or "").replace("/works/", "")
        if key:
            scored.append((score, doc.get("edition_count") or 0, candidate, key))
    # Highest score first; among comparable scores prefer the fuller record.
    scored.sort(key=lambda x: (round(x[0], 2), x[1]), reverse=True)

    keys, seen = [], set()
    best = scored[0][0] if scored else 0.0
    for score, _, _, key in scored:
        if score >= 0.5 and score >= best - 0.15 and key not in seen:
            seen.add(key)
            keys.append(key)
        if len(keys) >= limit:
            break
    return keys, [(s, t, k) for s, _, t, k in scored[:5]]


def _isbn_of(entry: dict) -> str | None:
    for field in ("isbn_13", "isbn_10"):
        values = entry.get(field)
        if values:
            return values[0]
    return None


def editions(work_key: str, limit: int = 500, authors=None) -> list:
    """Every edition of one work, as Editions.

    Authors come from the work, not the edition record — editions.json rarely
    carries them — so they are passed down from the search doc.
    """
    data = cached_get_json(f"{BASE}/works/{work_key}/editions.json", {"limit": limit})
    out = []
    for entry in data.get("entries") or []:
        codes = [langs.from_openlibrary(l.get("key")) for l in entry.get("languages") or []]
        known = [c for c in codes if c != langs.UNKNOWN]
        publishers = entry.get("publishers") or []
        series = entry.get("series") or []
        out.append(Edition(
            source="Open Library",
            title=entry.get("title") or "",
            publisher=", ".join(publishers) or None,
            year=entry.get("publish_date"),
            # No language recorded stays unknown. The original script counted
            # blank as English, which inflated the English list.
            language=known[0] if known else langs.UNKNOWN,
            isbn=_isbn_of(entry),
            url=f"{BASE}{entry['key']}" if entry.get("key") else None,
            series=series[0] if series else None,
            physical=f"{entry['number_of_pages']} p." if entry.get("number_of_pages") else None,
            authors=list(authors or []),
        ))
    return out


def work_doc_to_edition(doc: dict) -> Edition:
    """A search doc as a coarse Edition, for sibling works we don't expand."""
    codes = [langs.from_openlibrary(c) for c in doc.get("language") or []]
    known = [c for c in codes if c != langs.UNKNOWN]
    publishers = doc.get("publisher") or []
    isbns = doc.get("isbn") or []
    key = (doc.get("key") or "").replace("/works/", "")
    return Edition(
        source="Open Library",
        title=doc.get("title") or "",
        authors=list(doc.get("author_name") or []),
        publisher=publishers[0] if publishers else None,
        year=str(doc["first_publish_year"]) if doc.get("first_publish_year") else None,
        language=known[0] if known else langs.UNKNOWN,
        isbn=isbns[0] if isbns else None,
        url=f"{BASE}/works/{key}" if key else None,
    )


def italian_siblings(author: str, cluster_titles: list, limit: int = 60) -> list:
    """Italian-language works by this author, ranked against known title variants.

    This is the recall net that catches translations Open Library never linked to
    the original work — the path that found Rumori.
    """
    docs = search_works(author=author, language="ita", limit=limit)
    ranked = []
    for doc in docs:
        title = doc.get("title", "")
        score = max((title_similarity(v, title) for v in cluster_titles), default=0.0)
        ranked.append((score, doc))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked
