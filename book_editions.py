#!/usr/bin/env python3
"""
book_editions.py — given an English book title (and optionally its author),
find:
  1. the existing English-language editions of that book, and
  2. its Italian translation(s)/edition(s), if any exist.

Rewritten from scratch. Design choices, and why:

- Open Library is the primary source for English editions. Its "work" model
  (one work = many editions/languages) is exactly the right shape for this
  task, but *finding the right work* reliably is the hard part — a plain
  title search can either match nothing (titles with subtitles) or match
  everything (common words like "Noise"). This version fetches several
  candidate works and SCORES each one against your title+author before
  picking one, instead of blindly trusting the first hit or falling back to
  unranked free-text search. If nothing scores well, it tells you the closest
  candidates instead of silently returning nothing.

- Open Library sometimes also has the Italian edition linked under the same
  work (if a librarian merged them) — when it does, this script surfaces it
  for free. But this is NOT reliable for older or small-press translations
  (e.g. a 1978 Italian edition from a small publisher is frequently a
  separate, unlinked work in Open Library). So Open Library is necessary but
  not sufficient for the Italian side.

- For Italian editions specifically, this also queries Google Books
  restricted to Italian (langRestrict=it) by AUTHOR ONLY — not by the
  English title, since the Italian title is usually a different string.
  This is the most reliable automated signal for translations Open Library
  misses.

- SBN (Italy's national library catalog) is queried too, but ONLY via an
  author search, and results are NOT auto-matched to your book — they're
  listed for you to eyeball, because SBN's public endpoint is unofficial,
  undocumented, and free-text title matching against a translated title is
  too unreliable to trust blindly (this is what failed last time).

- VIAF is used for exactly what it's good for: showing you the canonical
  name-form(s) national libraries use for this author, so YOU can refine an
  SBN/WorldCat/BnF search by hand if the automated pass doesn't find the
  Italian edition. VIAF does not index editions/translations itself, so it
  is not used to "find" the Italian book directly.

Usage
-----
    python book_editions.py "Noise" --author "Jacques Attali"
    python book_editions.py "Steps to an Ecology of Mind" --author "Gregory Bateson" --format json --output out.json

Requirements:
    pip install requests
"""

import argparse
import csv
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests

USER_AGENT = "book-editions-lookup/2.0 (personal research script)"
TIMEOUT = 15
STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "to", "for", "is",
    "at", "by", "with", "from", "as", "essai", "sur", "la", "le", "les",
    "di", "del", "della", "il", "lo", "un", "una",
}


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------

@dataclass
class Edition:
    source: str
    title: str
    publisher: Optional[str] = None
    year: Optional[str] = None
    language: Optional[str] = None
    isbn: Optional[str] = None
    url: Optional[str] = None
    extra: str = ""


@dataclass
class Report:
    query_title: str
    query_author: Optional[str]
    matched_work: Optional[str] = None          # Open Library work key, if matched
    match_confidence: Optional[float] = None
    english_editions: list = field(default_factory=list)
    italian_editions: list = field(default_factory=list)
    other_language_editions: list = field(default_factory=list)
    viaf_matches: list = field(default_factory=list)   # informational, not editions
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)


# --------------------------------------------------------------------------
# Text matching helpers
# --------------------------------------------------------------------------

def normalize(text: str) -> set:
    """Lowercase, strip accents/punctuation, drop stopwords, return token set."""
    if not text:
        return set()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 1}


def core_title(title: str) -> str:
    """Title with any subtitle (after ':' or ' - ') stripped off."""
    for sep in (":", " - ", " — "):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title.strip()


def title_similarity(query_title: str, candidate_title: str) -> float:
    q = normalize(query_title)
    c = normalize(candidate_title)
    if not q or not c:
        return 0.0
    overlap = len(q & c)
    return overlap / max(len(q), len(c))


def author_matches(query_author: Optional[str], candidate_authors: list) -> bool:
    if not query_author:
        return True  # no author given, don't penalize
    qa = normalize(query_author)
    for cand in candidate_authors or []:
        if normalize(cand) & qa:
            return True
    return False


# --------------------------------------------------------------------------
# Open Library
# --------------------------------------------------------------------------

def openlibrary_candidates(title: str, author: Optional[str], limit: int = 10) -> list:
    """Run a couple of search strategies and return a pooled list of candidate docs."""
    seen_keys = set()
    pooled = []

    queries = [
        {"title": title, "limit": limit},
        {"title": core_title(title), "limit": limit},
        {"q": f"{core_title(title)} {author or ''}".strip(), "limit": limit},
    ]
    if author:
        queries[0]["author"] = author
        queries[1]["author"] = author

    for params in queries:
        try:
            r = requests.get(
                "https://openlibrary.org/search.json",
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            for doc in r.json().get("docs", []):
                key = doc.get("key")
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    pooled.append(doc)
        except requests.RequestException:
            continue  # try the next strategy; caller handles a totally empty pool

    return pooled


def openlibrary_best_match(title: str, author: Optional[str]) -> tuple:
    """
    Returns (work_key_or_None, score, ranked_candidates) where ranked_candidates
    is a list of (score, title, work_key) for the top few, for transparency.
    """
    candidates = openlibrary_candidates(title, author)
    scored = []
    for doc in candidates:
        t = doc.get("title", "")
        score = title_similarity(title, t)
        if author and not author_matches(author, doc.get("author_name", [])):
            score *= 0.5  # heavy penalty, but don't zero it out — author names vary
        scored.append((score, t, doc.get("key", "").replace("/works/", "")))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0.0, []

    best_score, best_title, best_key = scored[0]
    return (best_key if best_score >= 0.5 else None), best_score, scored[:5]


def openlibrary_get_editions(work_key: str, max_editions: int = 300) -> list:
    editions = []
    r = requests.get(
        f"https://openlibrary.org/works/{work_key}/editions.json",
        params={"limit": max_editions},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    for e in r.json().get("entries", []):
        isbn = None
        if e.get("isbn_13"):
            isbn = e["isbn_13"][0]
        elif e.get("isbn_10"):
            isbn = e["isbn_10"][0]
        lang_codes = [l.get("key", "").replace("/languages/", "") for l in e.get("languages", [])]
        editions.append(
            Edition(
                source="Open Library",
                title=e.get("title", ""),
                publisher=", ".join(e.get("publishers", [])) or None,
                year=e.get("publish_date"),
                language=", ".join(lang_codes) if lang_codes else None,
                isbn=isbn,
                url=f"https://openlibrary.org{e.get('key', '')}" if e.get("key") else None,
            )
        )
    return editions


# --------------------------------------------------------------------------
# Google Books
# --------------------------------------------------------------------------

def google_books_search(
    query: str,
    lang_restrict: Optional[str] = None,
    max_results: int = 40,
    api_key: Optional[str] = None,
    max_retries: int = 3,
) -> list:
    params = {"q": query, "maxResults": min(max_results, 40)}
    if lang_restrict:
        params["langRestrict"] = lang_restrict
    if api_key:
        params["key"] = api_key

    data = None
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.get(
                "https://www.googleapis.com/books/v1/volumes",
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
            )
            if r.status_code == 429:
                last_exc = requests.HTTPError("429 Too Many Requests")
                time.sleep(2 ** attempt * 2)
                continue
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2 ** attempt * 2)

    if data is None:
        raise RuntimeError(
            f"Google Books error after {max_retries} attempts "
            f"(pass --google-api-key for a higher quota): {last_exc}"
        )

    editions = []
    for item in data.get("items", []):
        info = item.get("volumeInfo", {})
        isbn = None
        for ident in info.get("industryIdentifiers", []):
            if ident.get("type") in ("ISBN_13", "ISBN_10"):
                isbn = ident.get("identifier")
                if ident.get("type") == "ISBN_13":
                    break
        editions.append(
            Edition(
                source="Google Books",
                title=info.get("title", ""),
                publisher=info.get("publisher"),
                year=info.get("publishedDate"),
                language=info.get("language"),
                isbn=isbn,
                url=info.get("infoLink"),
            )
        )
    return editions


# --------------------------------------------------------------------------
# SBN (Italy) — unofficial, author-only, NOT auto-matched
# --------------------------------------------------------------------------

def sbn_by_author(author: str, max_results: int = 25) -> list:
    """
    Lists works by this author found in SBN (Italy's national catalog), for
    manual review — it does NOT try to guess which one is the translation of
    your target book, since matching a translated title automatically is too
    unreliable. Uses the unofficial ICCU mobile-app endpoint; may break.
    """
    r = requests.get(
        "http://opac.sbn.it/opacmobilegw/search.json",
        params={"any": author, "type": 0, "start": 0, "rows": max_results},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    records = data if isinstance(data, list) else data.get("records", data.get("results", []))
    if isinstance(records, dict):
        records = records.get("docs", [])

    editions = []
    for rec in records or []:
        editions.append(
            Edition(
                source="SBN (Italy, unofficial API — unverified match)",
                title=rec.get("titolo", ""),
                publisher=rec.get("pubblicazione"),
                language="ITALIANO",
                extra=f"BID: {rec.get('codiceIdentificativo', '')}",
            )
        )
    return editions


# --------------------------------------------------------------------------
# VIAF — author name-form lookup only (not an editions source)
# --------------------------------------------------------------------------

def viaf_autosuggest(author: str) -> list:
    r = requests.get(
        "https://viaf.org/viaf/AutoSuggest",
        params={"query": author},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json() or {}
    results = []
    for item in (data.get("result") or [])[:5]:
        results.append({
            "term": item.get("term"),
            "viafid": item.get("viafid"),
            "nametype": item.get("nametype"),
            "url": f"https://viaf.org/viaf/{item.get('viafid')}/" if item.get("viafid") else None,
        })
    return results


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def lookup_book(
    title: str,
    author: Optional[str],
    do_openlibrary: bool = True,
    do_google: bool = True,
    do_sbn: bool = True,
    do_viaf: bool = True,
    google_api_key: Optional[str] = None,
) -> Report:
    report = Report(query_title=title, query_author=author)

    # --- Open Library: primary source, English + whatever else is linked ---
    if do_openlibrary:
        try:
            work_key, score, ranked = openlibrary_best_match(title, author)
            report.match_confidence = round(score, 2)
            if not work_key:
                near = "; ".join(f'"{t}" ({s:.2f})' for s, t, _ in ranked[:3])
                report.notes.append(
                    f"Open Library: no confident match (best guesses: {near or 'none found'})"
                )
            else:
                report.matched_work = work_key
                editions = openlibrary_get_editions(work_key)
                for e in editions:
                    langs = (e.language or "").lower()
                    if "eng" in langs or not langs:
                        report.english_editions.append(e)
                    elif "ita" in langs:
                        report.italian_editions.append(e)
                    else:
                        report.other_language_editions.append(e)
                if not any([e.language and "ita" in e.language.lower() for e in editions]):
                    report.notes.append(
                        "Open Library: no Italian edition linked to this work "
                        "(common for older/small-press translations — check Google Books/SBN results below)"
                    )
        except requests.RequestException as exc:
            report.errors.append(f"Open Library error: {exc}")

    # --- Google Books: cross-check English, and the main automated route to Italian ---
    if do_google:
        try:
            en_query = f'intitle:"{core_title(title)}"' + (f' inauthor:"{author}"' if author else "")
            en_hits = google_books_search(en_query, lang_restrict="en", api_key=google_api_key)
            report.english_editions.extend(en_hits)
        except RuntimeError as exc:
            report.errors.append(str(exc))

        if author:
            try:
                it_query = f'inauthor:"{author}"'
                it_hits = google_books_search(it_query, lang_restrict="it", api_key=google_api_key)
                report.italian_editions.extend(it_hits)
                if not it_hits:
                    report.notes.append("Google Books: no Italian-language results for this author")
            except RuntimeError as exc:
                report.errors.append(str(exc))
        else:
            report.notes.append("Google Books: skipped Italian search (no author given — pass --author)")

    # --- SBN: author-only, unverified, for manual review ---
    if do_sbn:
        if not author:
            report.notes.append("SBN: skipped (no author given — pass --author)")
        else:
            try:
                hits = sbn_by_author(author)
                if hits:
                    report.notes.append(
                        f"SBN: {len(hits)} work(s) by this author found — titles are NOT "
                        f"auto-matched to your book, review manually"
                    )
                    # keep these separate from the "confirmed" italian_editions list
                    report.other_language_editions.extend(hits)
                else:
                    report.notes.append("SBN: no results for this author (endpoint may be down/renamed)")
            except (requests.RequestException, ValueError) as exc:
                report.errors.append(f"SBN error (unofficial endpoint, may be unstable): {exc}")

    # --- VIAF: informational only ---
    if do_viaf and author:
        try:
            report.viaf_matches = viaf_autosuggest(author)
            if not report.viaf_matches:
                report.notes.append("VIAF: no author record found")
        except requests.RequestException as exc:
            report.errors.append(f"VIAF error: {exc}")

    return report


def parse_books_file(path: str) -> list:
    books = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            title = parts[0].strip()
            author = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
            books.append((title, author))
    return books


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _print_edition_list(editions: list):
    if not editions:
        print("    (none)")
        return
    by_source = {}
    for e in editions:
        by_source.setdefault(e.source, []).append(e)
    for source, items in by_source.items():
        print(f"    -- {source} --")
        for e in items:
            meta = [m for m in [e.language, e.publisher, str(e.year) if e.year else None,
                                 f"ISBN {e.isbn}" if e.isbn else None] if m]
            line = f"    · {e.title}"
            if meta:
                line += "  [" + " · ".join(meta) + "]"
            print(line)
            if e.url:
                print(f"        {e.url}")
            if e.extra:
                print(f"        {e.extra}")


def print_text(reports: list):
    for r in reports:
        header = r.query_title + (f" — {r.query_author}" if r.query_author else "")
        print("\n" + "=" * len(header))
        print(header)
        print("=" * len(header))
        if r.matched_work:
            print(f"  Open Library work: {r.matched_work} (match confidence {r.match_confidence})")

        if r.errors:
            for e in r.errors:
                print(f"  [!] {e}")
        if r.notes:
            for n in r.notes:
                print(f"  [i] {n}")

        print("\n  English editions:")
        _print_edition_list(r.english_editions)

        print("\n  Italian editions:")
        _print_edition_list(r.italian_editions)

        if r.other_language_editions:
            print("\n  Other / unverified (incl. SBN author search, other languages):")
            _print_edition_list(r.other_language_editions)

        if r.viaf_matches:
            print("\n  VIAF author record(s) (for cross-referencing national catalogs by hand):")
            for m in r.viaf_matches:
                print(f"    · {m['term']}  {m['url'] or ''}")


def write_json(reports: list, path: str):
    payload = []
    for r in reports:
        d = asdict(r)
        payload.append(d)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Written: {path}")


def write_csv(reports: list, path: str):
    fieldnames = ["query_title", "query_author", "category", "source", "title",
                  "publisher", "year", "language", "isbn", "url", "extra"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in reports:
            groups = [("english", r.english_editions), ("italian", r.italian_editions),
                      ("other/unverified", r.other_language_editions)]
            wrote_any = False
            for category, editions in groups:
                for e in editions:
                    wrote_any = True
                    row = {"query_title": r.query_title, "query_author": r.query_author or "",
                           "category": category}
                    row.update(asdict(e))
                    writer.writerow(row)
            if not wrote_any:
                writer.writerow({"query_title": r.query_title, "query_author": r.query_author or ""})
    print(f"Written: {path}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Find English editions and Italian translations of a book."
    )
    parser.add_argument("title", nargs="?", help="Book title (English), omit if using --file")
    parser.add_argument("--author", help="Author name — strongly recommended, enables Italian lookup")
    parser.add_argument("--file", help="Text file, one 'Title|Author' per line")
    parser.add_argument("--skip-openlibrary", action="store_true")
    parser.add_argument("--skip-google", action="store_true")
    parser.add_argument("--skip-sbn", action="store_true")
    parser.add_argument("--skip-viaf", action="store_true")
    parser.add_argument("--google-api-key", default=None,
                         help="Free key from console.cloud.google.com (Books API) — avoids 429s")
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
    parser.add_argument("--output", help="Output file path (required for csv)")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between books")
    args = parser.parse_args()

    if not args.title and not args.file:
        parser.error("Provide a title, or use --file with a list of books.")

    books = []
    if args.file:
        books.extend(parse_books_file(args.file))
    if args.title:
        books.append((args.title, args.author))

    reports = []
    for i, (title, author) in enumerate(books):
        if i > 0:
            time.sleep(args.delay)
        print(f"Looking up: {title}" + (f" ({author})" if author else " (no author given)"), file=sys.stderr)
        reports.append(lookup_book(
            title, author,
            do_openlibrary=not args.skip_openlibrary,
            do_google=not args.skip_google,
            do_sbn=not args.skip_sbn,
            do_viaf=not args.skip_viaf,
            google_api_key=args.google_api_key,
        ))

    if args.format == "text":
        print_text(reports)
    elif args.format == "json":
        if args.output:
            write_json(reports, args.output)
        else:
            print(json.dumps([asdict(r) for r in reports], ensure_ascii=False, indent=2))
    elif args.format == "csv":
        if not args.output:
            parser.error("--format csv requires --output <path.csv>")
        write_csv(reports, args.output)


if __name__ == "__main__":
    main()
