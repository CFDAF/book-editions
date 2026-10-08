"""Records -> editions. **Only an ISBN merges; a collision is a hint.**

This is the module the benchmark's A4 result shapes. Merging cross-source rows
on a (language, year, publisher) collision was measured and **fails**: precision
**82/125 = 0.656** where both sides carry an ISBN, 0.664 under the strictest
publisher rule and 0.636 under the loosest, so no rule over listing fields
rescues it. Every false positive pairs rows with the same language, year and
publisher but different ISBNs — one publisher's edition for another country
(Alfaguara 978-84 against 978-968), another binding or line (Faber 2021
`9780571355884` / `…891`). What separates them is page count, series and binding,
which live in the full record only: the fetch the collision rule existed to
avoid. So:

- **`fold` merges on a shared ISBN and on nothing else** (decision I). One SBN
  ISBN spans up to 31 records over 41 years (F17), and 295 of 778 full records
  carry none at all (F12, 38%), so a record with no ISBN is its own edition
  rather than being guessed into somebody else's.
- **`collisions` returns hints, never merges** (decision H). And only where a
  merge is impossible anyway: if both sides have ISBNs, they either share one —
  in which case `fold` has already merged them — or they differ, which settles
  it. So a hint survives exactly where one side has no ISBN, 288 such collisions
  in Stage 3. Hand-judged in Step 13 (U5) it was right 59 times in 77, and a
  page count both rows state, far apart, now withholds one (decision AX).

Grouping printings from listing fields instead of full records is also settled
against: precision **0.425**.
"""

import re
import unicodedata
from collections import defaultdict

from catalog import langs
from .model import Edition

# ---------------------------------------------------------------------------
# ISBN: what counts as the same one
# ---------------------------------------------------------------------------

ISBN_RE = re.compile(r"(?<![0-9X])(97[89][0-9]{10}|[0-9]{9}[0-9X])(?![0-9X])")


def _valid(code: str) -> bool:
    if len(code) == 10:
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(code)) % 11 == 0
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(code)) % 10 == 0


def to_isbn13(code: str) -> str:
    if len(code) == 13:
        return code
    body = "978" + code[:9]
    return body + str((10 - sum(int(c) * (1 if i % 2 == 0 else 3)
                                for i, c in enumerate(body)) % 10) % 10)


def isbns_in(values) -> tuple:
    """`(normalised ISBN-13s, codes with a bad check digit)` from raw strings.

    Hyphens and spaces *between digits* are dropped first
    ('978-88-502-6890-0'), and an ISBN-10 becomes its ISBN-13 so SBN's pre-2007
    printings join Open Library's modern ones.

    **A bad check digit is reported but still normalised and still merges.** Both
    catalogues copy what is printed on the book, so a typo shared by two records
    is evidence they are the same book — dropping it would lose the join and
    gain nothing.
    """
    out, invalid = set(), []
    for value in values or []:
        compact = re.sub(r"(?<=[0-9Xx])[\s\-‐–](?=[0-9Xx])", "", str(value)).upper()
        for m in ISBN_RE.finditer(compact):
            code = m.group(1)
            if not _valid(code):
                invalid.append(code)
            out.add(to_isbn13(code))
    return out, invalid


def isbn_keys(record) -> set:
    """Every ISBN this record can be joined on.

    Reads `isbns_raw` where the parser found several — one `numeri` field often
    lists the paperback and the hardback — and falls back to the single display
    `isbn`.
    """
    raw = list(getattr(record, "isbns_raw", None) or [])
    if record.isbn and record.isbn not in raw:
        raw.append(record.isbn)
    codes, _ = isbns_in(raw)
    return codes


# ---------------------------------------------------------------------------
# Records -> editions
# ---------------------------------------------------------------------------

def fold(records) -> list:
    """One `Edition` per ISBN, transitively; one per record with no ISBN.

    Transitive because a record can list two ISBNs: if A lists {x} and B lists
    {x, y} and C lists {y}, all three are printings of one edition and SBN says
    so twice. Union-find rather than a single pass, so the answer does not depend
    on the order the records arrive in — except where it must, which is the
    order of the records *inside* each edition, and that is the store's.

    Determinism: editions come back in the order their first record was written,
    and each edition's `records` in store order. Nothing here iterates a set.
    """
    records = list(records)
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys = [isbn_keys(r) for r in records]
    by_isbn = defaultdict(list)
    for i, codes in enumerate(keys):
        parent[i] = i
        for code in sorted(codes):
            by_isbn[code].append(i)
    for code in sorted(by_isbn):
        members = by_isbn[code]
        for other in members[1:]:
            parent[find(other)] = find(members[0])

    grouped, order = defaultdict(list), []
    for i, codes in enumerate(keys):
        root = ("isbn", find(i)) if codes else ("record", i)
        if root not in grouped:
            order.append(root)
        grouped[root].append(i)

    out = []
    for root in order:
        members = grouped[root]
        codes = sorted({code for i in members for code in keys[i]})
        rows = [records[i] for i in members]
        out.append(Edition(id=_edition_id(rows, codes),
                           isbn=codes[0] if codes else None, records=rows))
    return out


def _edition_id(records, codes) -> str:
    """The ISBN, or a synthetic id from the row's single record.

    Synthetic ids are `(source, id)` so they are stable across runs and across
    snapshots: a row that gains an ISBN in the background becomes a *different*
    edition, which is correct — it has just been shown to be the same book as
    another row, and the page replaces snapshots rather than patching them.
    """
    if codes:
        return codes[0]
    first = records[0]
    return f"{first.source}:{first.id}"


# ---------------------------------------------------------------------------
# Publisher: what counts as the same one
# ---------------------------------------------------------------------------

# Words that name a kind of company rather than which company. 'Einaudi' and
# 'Giulio Einaudi editore' are one publisher; 'press' and 'verlag' say nothing.
GENERIC = {
    # Italian
    "editore", "editori", "editrice", "edizioni", "edizione", "ed", "edit",
    "casa", "editoriale", "gruppo", "spa", "srl", "sas",
    # English
    "press", "publishing", "publishers", "publisher", "publications",
    "publication", "pubns", "pub", "publ", "books", "book", "inc",
    "incorporated", "ltd", "limited", "co", "company", "corp", "corporation",
    "group", "llc", "plc",
    # French, Spanish, Portuguese
    "editions", "edition", "editeur", "editeurs", "sarl", "editorial",
    "ediciones", "editora", "editores", "grupo", "lda", "ltda",
    # German
    "verlag", "gmbh", "kg", "ag",
    # connectors and the article that fronts English company names
    "and", "et", "und", "the",
}
# SBN imprint noise the publication parser leaves in the publisher
# ('Gallimard, dep. leg.').
NOISE = {"dep", "leg", "stampa", "impr"}


def _fold_case(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def plain(text: str) -> str:
    return " ".join(re.findall(r"\w+", _fold_case(text or "")))


def publisher_key(name: str) -> frozenset:
    """The words that identify a publisher, as a set.

    A set and not a string because the two catalogues order and abbreviate
    differently, and because containment is the comparison that works:
    'mondadori' and 'oscar mondadori' are the same house.
    """
    s = _fold_case(name or "").replace("&", " and ")
    s = re.sub(r"\b(\w)\s*/\s*(\w)\b", r"\1\2", s)     # 'E/O' -> 'eo', not two initials
    return frozenset(t for t in re.findall(r"\w+", s)
                     if len(t) > 1 and not t.isdigit()
                     and t not in GENERIC and t not in NOISE)


def strip_places(name: str, places: set) -> str:
    """'Milano, Mondadori' / 'London : Penguin' -> the publisher.

    Only a place set off by a comma or colon is removed, so 'Cambridge
    University Press' keeps its Cambridge. `places` is every place the records
    of *this* lookup name, which is why it is passed in rather than being a
    fixed list: a gazetteer would strip a publisher named after a town.
    """
    parts = [p.strip() for p in re.split(r"\s*[,:]\s+", name or "") if p.strip()]
    kept = [p for p in parts if plain(p) not in places]
    return ", ".join(kept) if kept else ""


def publisher_keys(record, places: set) -> set:
    """Every publisher key on a record. Empty when it names none we can read."""
    names = list(getattr(record, "publisher_names", None) or [])
    if not names and record.publisher:
        names = [record.publisher]
    return {k for k in (publisher_key(strip_places(n, places)) for n in names) if k}


def places_in(records) -> set:
    """The place names these records use, for `strip_places` to remove."""
    out = set()
    for r in records:
        for name in getattr(r, "places", None) or []:
            if plain(name):
                out.add(plain(name))
    return out


def publisher_agrees(a: set, b: set) -> bool:
    """One publisher name's words all inside the other's. The primary rule.

    Measured against the exact-equality variant (precision 0.664 against 0.656)
    and the loosest (0.636). All three fail, and the spread is the evidence that
    the publisher rule is not what is wrong: the rows really do share a
    publisher.
    """
    return any(x <= y or y <= x for x in a for y in b)


# ---------------------------------------------------------------------------
# Collisions: the hint that is never a merge
# ---------------------------------------------------------------------------

def collisions(editions, places: set | None = None) -> list:
    """Pairs of editions from *different* sources that may be the same book.

    `[{"a", "b", "why"}]`, a and b being edition ids. The rule is the one A4
    measured: the same language, the same year, and one publisher key contained
    in the other.

    **A pair where both sides have an ISBN is not returned.** They either share
    one, and `fold` has merged them already, or they differ, and they are
    different editions — a bracket there would contradict a fact the page holds.
    **Nor is a pair whose page counts disagree** (`pages_disagree`), for the
    same reason. What survives is the unverifiable case, where at least one side
    has no ISBN, and it is still a guess: a caller that shows these says how
    many there are and does not imply they are right.
    """
    rows = list(editions)
    if places is None:
        places = places_in([r for e in rows for r in e.records])
    keys = {e.id: _collision_key(e, places) for e in rows}
    # A pair shares a language and a year or it is not a pair, so only rows in
    # one (language, year) bucket are compared. The pairwise scan over the whole
    # list was 87% of N23's snapshot (1,133 of 1,294 ms), and S4 derives one
    # more. Buckets keep the rows' own order, so the pairs come back in the
    # order the full scan produced them.
    buckets = defaultdict(list)
    for i, e in enumerate(rows):
        k = keys[e.id]
        if k["year"] and k["language"] != langs.UNKNOWN:
            buckets[(k["language"], k["year"])].append(i)
    position = {}
    for members in buckets.values():
        for n, i in enumerate(members):
            position[i] = members[n + 1:]
    out = []
    for i, a in enumerate(rows):
        for j in position.get(i, ()):
            b = rows[j]
            if set(a.sources) & set(b.sources):
                continue                       # one source's own rows: not a duplicate
            if a.isbn and b.isbn:
                continue                       # settled either way; see the docstring
            ka, kb = keys[a.id], keys[b.id]
            if not publisher_agrees(ka["publisher"], kb["publisher"]):
                continue
            if pages_disagree(a, b):
                continue
            out.append({"a": a.id, "b": b.id,
                        "why": f"both {ka['language']}, {ka['year']}, same publisher"})
    return out


# Two page counts further apart than this are two editions: Bompiani's 503- and
# 442-page *Il nome della rosa* of 1983. Over Step 13's 100 hand-judged hints it
# withholds 9 of the 18 judged different and 1 of the 59 judged the same, an Open
# Library `number_of_pages` of 23 that is the book's 23 cm (decision AX).
# 10% is Step 13's own pre-sort threshold, kept so
# the rule was not tuned on the pairs that scored it.
PAGES_APART = 0.10
PAGES_APART_MIN = 10
_PAGES = re.compile(r"(\d+)\s*p\b")


def page_counts(edition) -> list:
    """The page count each record states — the largest run, so `XV, 312 p.`
    is 312. Open Library's arrives as `<number_of_pages> p.`."""
    out = []
    for r in edition.records:
        runs = [int(n) for n in _PAGES.findall(r.physical or "")]
        if runs:
            out.append(max(runs))
    return out


def pages_disagree(a, b) -> bool:
    """True when both editions state a page count and no two of them are
    within `PAGES_APART` (at least `PAGES_APART_MIN` pages) of each other."""
    pa, pb = page_counts(a), page_counts(b)
    return bool(pa and pb) and all(
        abs(x - y) > max(PAGES_APART_MIN, PAGES_APART * max(x, y)) for x in pa for y in pb)


def _collision_key(edition, places: set) -> dict:
    return {
        "year": edition.year,
        "language": edition.language,
        "publisher": publisher_keys(edition.records[0], places) if edition.records else set(),
    }
