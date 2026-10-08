#!/usr/bin/env python3
"""book_editions.py — every edition of a book, grouped by language.

Give it a title in any language, with the author if you have it. It prints the
work's publication history — the original where a source states it, then every
edition found, by language — and where to find a copy. An author with no title
lists their works instead.

    python book_editions.py "Noise" --author "Jacques Attali"
    python book_editions.py "Verso un'ecologia della mente"
    python book_editions.py --author "Gregory Bateson"
    python book_editions.py "Cent'anni di solitudine" --format json -o out.json

For the web page instead:  python server.py

It runs the same lookup the page does (`app.jobs.run_to_end`, stages S1 to S4)
to its end, and prints the last snapshot. The filters below are applied to the
printed rows only: the header — original, earliest edition, counts — is always
the unfiltered one (build rule 12).

Responses are cached under .cache/ for 24h, so a repeat is fast.
"""

import argparse
import csv
import json
import re
import sys
import time

from app.jobs import run_to_end
from core.view import year_of


def parse_books_file(path: str) -> list:
    books = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            title = parts[0].strip() or None
            author = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
            books.append((title, author))
    return books


# A medium is a label only where the row is not simply a printed text — the
# page's own rule (`app/web/app.js`), so the two cannot label differently.
PLAIN_TEXT = re.compile(r"testo a stampa|^testo$", re.I)


def keep(row: dict, args) -> bool:
    year = year_of(row.get("year"))
    if args.year_from and (not year or year < int(args.year_from)):
        return False
    if args.year_to and (not year or year > int(args.year_to)):
        return False
    if args.publisher and args.publisher.lower() not in (row.get("publisher") or "").lower():
        return False
    return True


def lookup(title, author, title_spellings=False, author_spellings=False) -> dict:
    job = run_to_end(title, author, title_spellings=title_spellings,
                     author_spellings=author_spellings)
    return {"query_title": title, "query_author": author,
            "state": job.state(), "snapshot": job._snapshot or {}}


def print_work(snap: dict, args):
    if "chooser" in snap:
        ch = snap["chooser"]
        print(f"\n  {ch['heading']}")
        for b in ch["books"]:
            print(f"    · {'; '.join(b['authors']) or 'author not recorded'}"
                  f"  ({b.get('first_year') or '?'}, {b['editions']} edition(s))")
        print("    Narrow with --author to pick one.")
        return
    h = snap.get("header") or {}
    if not h.get("found"):
        print("\n  No editions found.")
        return
    print(f"\n  {h['title']}")
    byline = " · ".join(filter(None, [
        "; ".join(h.get("authors") or []) or None,
        h.get("origin") or None,
        f"{h['total_editions']} edition(s) in {len(h['spans'])} language(s)"]))
    print(f"  {byline}")
    if h.get("author_adopted"):
        print(f"  ({h['author_adopted']['note']})")
    print()
    for sp in h["spans"]:
        first, last = sp.get("first_year"), sp.get("last_year")
        years = f"{first}–{last}" if first and last and last != first else str(first or "—")
        print(f"    {sp['name']:22} {years:>11}  {sp['editions']:3} edition(s)")
    for code in snap.get("language_order") or []:
        rows = [r for r in snap["editions_by_language"].get(code, []) if keep(r, args)]
        if not rows:
            continue
        print(f"\n  {rows[0]['language_name'].upper()} — {len(rows)} edition(s)")
        for r in rows:
            label = "".join(f"[{x}] " for x in filter(None, [
                None if PLAIN_TEXT.search(r.get("medium") or "testo") else r["medium"],
                r.get("credited_to") and f"credited to {r['credited_to']}",
                (r.get("year_note") or {}).get("label")]))
            print(f"    · {label}{r['title']}")
            meta = " · ".join(filter(None, [
                "; ".join(r["authors"]) or None, r["publisher"],
                r["year"] or (r.get("year_note") or {}).get("shown"),
                f"ISBN {r['isbn']}" if r["isbn"] else None]))
            if meta:
                print(f"        {meta}")
            if r["url"]:
                print(f"        {r['url']}")
    ledger = snap.get("ledger") or {}
    for line in ((ledger.get("truncations") or []) + (ledger.get("not_asked") or [])
                 + (ledger.get("spellings") or [])):
        print(f"  [i] {line}")


def print_author(snap: dict):
    if not snap.get("works"):
        print("\n  " + ("Several people answer to this name:" if snap.get("people")
                        else "Nobody answers to this name."))
        for p in snap.get("people") or []:
            print(f"    · {p['name']}  ({p['records']} record(s))")
        return
    for group, rows in (("works", snap["works"]), ("contributed to", snap["contributed"])):
        if rows:
            print(f"\n  {group.upper()} — {len(rows)}")
            for w in rows:
                langs_ = ", ".join(w["languages"])
                print(f"    · {w['title']}  ({w.get('year') or '?'}{'; ' + langs_ if langs_ else ''})")
                if group != "works" and w.get("statement"):
                    print(f"        {w['statement']}")
                for d in w.get("derived") or []:
                    print(f"        ↳ {d['title']}  ({d['medium']}{' ' + str(d['year']) if d['year'] else ''};"
                          f" {d['records']} record(s))")
    for line in snap.get("truncations") or []:
        print(f"  [i] {line}")


def print_text(results: list, args):
    for r in results:
        head = (r["query_title"] or "") + (f" — {r['query_author']}" if r["query_author"] else "")
        print("\n" + "=" * len(head) + "\n" + head + "\n" + "=" * len(head))
        snap, state = r["snapshot"], r["state"]
        if state["error"]:
            print(f"  [!] {state['error']}")
        elif snap.get("mode") == "author":
            print_author(snap)
        else:
            print_work(snap, args)
        for note in filter(None, [state.get("incomplete"), state.get("slow")]):
            print(f"  [!] {note}")
        print("\n  sources: " + ", ".join(f"{k} {v}" for k, v in state["sources"].items()))


def write_json(results: list, path: str | None):
    text = json.dumps(results, ensure_ascii=False, indent=2)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written: {path}")
    else:
        print(text)


def write_csv(results: list, path: str, args):
    fields = ["query_title", "query_author", "language", "title", "authors", "publisher",
              "year", "year_note", "isbn", "medium", "credited_to", "sources", "url"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            q = {"query_title": r["query_title"] or "", "query_author": r["query_author"] or ""}
            rows = [row for rows in (r["snapshot"].get("editions_by_language") or {}).values()
                    for row in rows if keep(row, args)]
            for row in rows:
                note = row.get("year_note") or {}
                writer.writerow({**row, **q, "authors": "; ".join(row["authors"]),
                                 "year_note": " — ".join(filter(None, [
                                     note.get("label"), note.get("shown")])),
                                 "sources": ", ".join(row["sources"])})
            if not rows:
                writer.writerow(q)
    print(f"Written: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Every edition of a book, grouped by language, from its first appearance on.")
    parser.add_argument("title", nargs="?", help="Book title in any language; omit for an author's works")
    parser.add_argument("--author", help="Author name; alone, lists the author's works")
    parser.add_argument("--file", help="Text file, one 'Title|Author' per line")
    parser.add_argument("--year-from", help="Print only editions published from this year")
    parser.add_argument("--year-to", help="Print only editions published up to this year")
    parser.add_argument("--publisher", help="Print only editions whose publisher contains this")
    parser.add_argument("--format", choices=["text", "json", "csv"], default="text")
    parser.add_argument("-o", "--output", help="Output file path (required for csv)")
    parser.add_argument("--title-spellings", action="store_true",
                        help="Also ask SBN under the work's other titles (slower)")
    parser.add_argument("--author-spellings", action="store_true",
                        help="Also sweep SBN under the author's other spellings (slower)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between books")
    args = parser.parse_args()

    if not args.title and not args.author and not args.file:
        parser.error("Provide a title, an author, or --file with a list of books.")
    if args.format == "csv" and not args.output:
        parser.error("--format csv requires --output <path.csv>")

    books = parse_books_file(args.file) if args.file else []
    if args.title or args.author:
        books.append((args.title, args.author))

    results = []
    for i, (title, author) in enumerate(books):
        if i:
            time.sleep(args.delay)
        print(f"Looking up: {title or ''}" + (f" ({author})" if author else ""), file=sys.stderr)
        results.append(lookup(title, author, args.title_spellings, args.author_spellings))

    if args.format == "text":
        print_text(results, args)
    elif args.format == "json":
        write_json(results, args.output)
    else:
        write_csv(results, args.output, args)


if __name__ == "__main__":
    main()
