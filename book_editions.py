#!/usr/bin/env python3
"""book_editions.py — find every edition of a book, in English and Italian.

Give it a title in either language. It reports which editions exist, which one
is the original, what has been translated and on what evidence, and where to get
a copy — from shops if it is in print, from Italian libraries if it is not.

    python book_editions.py "Noise" --author "Jacques Attali"
    python book_editions.py "Verso un'ecologia della mente"
    python book_editions.py "Cent'anni di solitudine" --format json -o out.json

For the web UI instead:  python server.py

Sources: Wikidata (title crosswalk, original language and year), Open Library
(editions), SBN/ICCU (Italian editions, translator evidence, library holdings).

A first lookup queries all four live and can take up to a minute — the Wikipedia
and Wikidata leg dominates it. Responses are cached under .cache/ for 24h, so
repeating a lookup, or refining its filters, returns in milliseconds.

Requirements: pip install requests
"""

import argparse
import csv
import json
import sys
import time
from dataclasses import asdict

from lookup import langs
from lookup.matching import author_display
from lookup.pipeline import lookup


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


def print_text(reports: list):
    for r in reports:
        header = (r.query_title or "?") + (f" — {r.query_author}" if r.query_author else "")
        print("\n" + "=" * len(header))
        print(header)
        print("=" * len(header))

        o = r.overview
        if not o.found:
            print("\n  No editions found.")
        else:
            print(f"\n  {o.title}")
            # Never pair a known original language with a fallback year: the
            # year would come from an Italian edition and the language from the
            # English original, making "first published 1976 in inglese" false.
            if o.original_year and o.original_language_name:
                origin = f"first published {o.original_year} in {o.original_language_name}"
            elif o.original_year:
                origin = f"first published {o.original_year}"
            elif o.original_language_name:
                origin = f"originally in {o.original_language_name}"
                if o.first_year_seen:
                    origin += f", earliest edition found {o.first_year_seen}"
            elif o.first_year_seen:
                origin = f"earliest edition found {o.first_year_seen}"
            else:
                origin = None

            byline = " · ".join(filter(None, [
                "; ".join(o.authors) or None,
                origin,
                f"{o.total_editions} editions in {len(o.spans)} language(s)",
            ]))
            print(f"  {byline}")
            if o.original_inferred:
                print(f"  (original identified by inference{': ' + o.original_basis if o.original_basis else ''})")
            print()
            for sp in o.spans:
                years = "—"
                if sp.first_year:
                    years = (f"{sp.first_year}–{sp.last_year}"
                             if sp.last_year and sp.last_year != sp.first_year
                             else str(sp.first_year))
                mark = "  (original)" if sp.is_original else ""
                print(f"    {sp.name:22} {years:>11}  {sp.editions:3} edition(s){mark}")

        if r.choices:
            print(f"\n  {len(r.choices)} different books share this title:")
            for ch in r.choices:
                span = (f"{ch['first_year']}–{ch['last_year']}"
                        if ch["first_year"] and ch["last_year"] != ch["first_year"]
                        else str(ch["last_year"] or "?"))
                print(f"    · {'; '.join(ch['authors']) or 'author not recorded'}"
                      f"  ({span}, {ch['editions']} edition(s))")
            print("    Narrow with --author to pick one.")

        if r.cluster.qid:
            print(f"\n  Wikidata: {r.cluster.url}")

        for code, editions in r.editions_by_language.items():
            print(f"\n  {langs.display(code).upper()} — {len(editions)} edition(s)")
            for e in editions:
                meta = " · ".join(filter(None, [
                    "; ".join(author_display(a) for a in e.authors) or None,
                    e.publisher, e.year,
                    f"ISBN {e.isbn}" if e.isbn else None]))
                role = f"[{e.role}] " if e.role != "reprint" else ""
                print(f"    · {role}{e.title}")
                if meta:
                    print(f"        {meta}")
                for ev in e.evidence:
                    print(f"        evidence: {ev}")
                if e.holdings:
                    cities = sorted({h.city for h in e.holdings if h.city})
                    print(f"        held by {len(e.holdings)} librar(ies): "
                          f"{', '.join(cities[:4])}{' …' if len(cities) > 4 else ''}")
                if e.url:
                    print(f"        {e.url}")

        if r.notes:
            print()
            for n in r.notes:
                print(f"  [i] {n}")
        if r.errors:
            for e in r.errors:
                print(f"  [!] {e}")
        print(f"\n  sources: " + ", ".join(f"{k} {v}" for k, v in r.sources.items()))


def write_json(reports: list, path: str | None):
    payload = [r.to_dict() for r in reports]
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written: {path}")
    else:
        print(text)


def write_csv(reports: list, path: str):
    fieldnames = ["query_title", "query_author", "language", "role", "confidence",
                  "source", "title", "publisher", "year", "isbn", "series",
                  "translators", "evidence", "holdings", "sbn_bid", "url"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in reports:
            wrote = False
            for code, editions in r.editions_by_language.items():
                for e in editions:
                    wrote = True
                    row = asdict(e)
                    row.update({
                        "query_title": r.query_title or "",
                        "query_author": r.query_author or "",
                        "language": code,
                        "translators": "; ".join(e.translators),
                        "evidence": " | ".join(e.evidence),
                        "holdings": len(e.holdings),
                    })
                    writer.writerow(row)
            if not wrote:
                writer.writerow({"query_title": r.query_title or "",
                                 "query_author": r.query_author or ""})
    print(f"Written: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Find every edition of a book, English and Italian, in either direction.")
    parser.add_argument("title", nargs="?", help="Book title in any language; omit if using --file")
    parser.add_argument("--author", help="Author name — improves matching, not required")
    parser.add_argument("--file", help="Text file, one 'Title|Author' per line")
    parser.add_argument("--year-from", help="Only editions published from this year")
    parser.add_argument("--year-to", help="Only editions published up to this year")
    parser.add_argument("--publisher", help="Only editions whose publisher contains this")
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
    parser.add_argument("-o", "--output", help="Output file path (required for csv)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between books")
    args = parser.parse_args()

    if not args.title and not args.file:
        parser.error("Provide a title, or use --file with a list of books.")
    if args.format == "csv" and not args.output:
        parser.error("--format csv requires --output <path.csv>")

    books = []
    if args.file:
        books.extend(parse_books_file(args.file))
    if args.title:
        books.append((args.title, args.author))

    reports = []
    for i, (title, author) in enumerate(books):
        if i:
            time.sleep(args.delay)
        print(f"Looking up: {title}" + (f" ({author})" if author else ""), file=sys.stderr)
        reports.append(lookup(
            title, author,
            year_from=args.year_from, year_to=args.year_to, publisher=args.publisher,
        ))

    if args.format == "text":
        print_text(reports)
    elif args.format == "json":
        write_json(reports, args.output)
    else:
        write_csv(reports, args.output)


if __name__ == "__main__":
    main()
