"""The snapshot: grouping, ordering, counts, the header, the coverage ledger.

Pure and **total**. The view is recomputed from the store from scratch after
every batch; nothing here mutates a display list incrementally (build rule 3).
That is what makes the page unable to disagree with its own store,
and it is what `snapshot` being byte-for-byte stable across 100 runs of the same
store actually tests.

Determinism is a property that has to be built, not hoped for:

- **Nothing here iterates a set or a `dict` built from one.** Every ordering is
  an explicit sort with a total key, and where two rows tie, the store's arrival
  order breaks the tie — which is the producers' order, not a hash's.
- **Every count is derived, never accumulated.** There is no running total to
  drift out of step with the rows it counts.

Two rules about what the header may say, both bought with measurements:

- **The header is a publication history, not a verdict** (`CLAUDE.md` rule 1).
  An earlier version led with "Translated into Italian." and the user rejected
  that framing.
- **The original and the earliest edition found are never compared** (decision
  D). The listing rule that flagged a differing first edition gave 8 false flags
  and 1 miss over 36 books, on bad catalogue dates — a
  Dutch translation dated 1912, CreateSpace reprints dated 1866 and 1825. So the
  header states the original where a source states it and, always, the earliest
  edition actually found, side by side, and concludes nothing from the pair.
"""

import re
from collections import Counter, defaultdict

from catalog import langs
from .fold import (collisions, fold, places_in, publisher_key, publisher_keys,
                   strip_places)
from . import dates, notes
from .identity import IDENTIFYING_TITLE_MATCH, credited_to_another
from .model import (AUTHOR_SWEEP, DUPLICATE_WORK, ISBN_MATCH, TITLE_MATCH,
                    UNIFORM_TITLE, WORK_KEY)
from .text import author_display, core_title, normalize, surname

UNKNOWN = langs.UNKNOWN


# ---------------------------------------------------------------------------
# Which book an edition belongs to. Titles are not unique.
# ---------------------------------------------------------------------------

def surname_tokens(name: str) -> set:
    return normalize(surname(name))


def same_person(a: set, b: set) -> bool:
    """One name's surname tokens being a subset of the other's.

    Catalogues disagree about compound surnames and about diacritics, and
    `surname()` can only guess where one ends: Open Library's "Gabriel García
    Márquez" has no comma, so it yields "Márquez", while SBN's "García Márquez,
    Gabriel" yields "García Márquez". Accents are already stripped by
    `normalize`, so the two reduce to {marquez} and {garcia, marquez} — the
    same man, and containment is what says so.
    """
    return bool(a) and bool(b) and (a <= b or b <= a)


def author_tokens(row, translators: list) -> set:
    """Surname tokens of everyone credited as an author, translators removed.

    SBN files a translator in the author field often enough to matter: one
    Italian printing of 'Cent'anni di solitudine' is credited to Enrico Cicogna
    alone, who is the translator named on several of its siblings.
    """
    out = set()
    for name in row.authors:
        tokens = surname_tokens(name)
        if tokens and not any(same_person(tokens, t) for t in translators):
            out |= tokens
    return out


def assign_groups(rows: list, fallback_authors: list) -> list:
    """One group key per row, in the rows' own order: which book each belongs to.

    'La matrice sociale della psichiatria' is Ruesch and Bateson in 1976 and
    Michael Shepherd in 1990 — two unrelated books — and 'Noise' is four. But
    keying on the first author's surname alone split one book four ways: the
    same man spelled two ways, his translator credited as an author, and his
    English translator credited ahead of him. So group by *any shared author*
    instead, merging until nothing else overlaps.

    A parallel list rather than a field, because a view may not mutate what it is
    derived from — and rather than a mapping, because a row's identity is its
    position here: `Record` and `Edition` both pass
    through this function and they do not agree on what a key looks like.
    """
    translators = []
    for row in rows:
        for name in row.translators or []:
            tokens = surname_tokens(name)
            if tokens and not any(same_person(tokens, t) for t in translators):
                translators.append(tokens)

    # A row with no recorded author belongs to the work it came from, so it
    # inherits rather than landing in a phantom group.
    authors = [list(row.authors) or list(fallback_authors or []) for row in rows]

    components = []                      # [[token sets], [indices]]
    for i, names in enumerate(authors):
        tokens = author_tokens(_Named(names), translators)
        if not tokens:
            continue
        hits = [c for c in components if any(same_person(tokens, t) for t in c[0])]
        if not hits:
            components.append([[tokens], [i]])
            continue
        first = hits[0]
        for other in hits[1:]:            # this row bridges two components
            first[0] += other[0]
            first[1] += other[1]
            components.remove(other)
        first[0].append(tokens)
        first[1].append(i)

    keys = [""] * len(rows)
    for names, members in components:
        key = " ".join(sorted(set().union(*names)))
        for i in members:
            keys[i] = key

    # A row whose only credited names are translators still belongs to a book —
    # the biggest one here, since a translator-only record is a filing quirk
    # rather than evidence of a second work sharing the title.
    if components:
        biggest = max(components, key=lambda c: len(c[1]))
        fallback = " ".join(sorted(set().union(*biggest[0])))
        keys = [k or fallback for k in keys]
    return keys


class _Named:
    """Just the `authors` attribute, so `author_tokens` can read an inherited
    author list without a row having to be copied."""

    def __init__(self, authors):
        self.authors = authors


def choices(editions: list, group_keys: list) -> list:
    """One entry per distinct book sharing the title, newest first. [] if one.

    The overview describes all of them together until a reader picks one, which
    is a disclosure and not a failure: the title really is ambiguous.
    """
    grouped = {}
    for edition, key in zip(editions, group_keys):
        if not key:
            continue
        g = grouped.setdefault(key, {"key": key, "authors": [], "years": [],
                                     "count": 0, "titles": {}})
        g["count"] += 1
        for name in edition.authors:
            display = author_display(name)
            if display:
                _add_author(g["authors"], display)
        year = year_of(edition.year)
        if year:
            g["years"].append(year)
        g["titles"][edition.title] = g["titles"].get(edition.title, 0) + 1

    if len(grouped) < 2:
        return []
    out = []
    for key in sorted(grouped):
        g = grouped[key]
        title = max(sorted(g["titles"]), key=lambda t: g["titles"][t]) if g["titles"] else ""
        out.append({"key": key, "authors": g["authors"][:3], "title": title,
                    "first_year": min(g["years"]) if g["years"] else None,
                    "last_year": max(g["years"]) if g["years"] else None,
                    "editions": g["count"]})
    out.sort(key=lambda c: (-(c["last_year"] or 0), c["key"]))
    return out


def _add_author(names: list, display: str) -> None:
    """Append a name unless the same person is already listed.

    Catalogues differ on diacritics, so one man arrives as both "Gabriel García
    Márquez" and "Gabriel Garcia Marquez" and the chooser offered them as if
    they were a collaboration. Compared on stripped tokens they are one person;
    the spelling that kept its accents is the one worth showing.
    """
    key = normalize(display)
    for i, existing in enumerate(names):
        if normalize(existing) == key:
            if not existing.isascii() or display.isascii():
                return
            names[i] = display            # the accented spelling is the better one
            return
    names.append(display)


# ---------------------------------------------------------------------------
# Grouping by language
# ---------------------------------------------------------------------------

def group_by_language(editions: list) -> dict:
    """`{code -> [editions]}`, **newest first inside each group, undated last**.

    An edition whose language no source recorded goes under `UNKNOWN` and stays
    in the answer. It is not folded into English — the original script did that
    (`if "eng" in langs or not langs`) and quietly inflated the English list —
    and a language filter must say that those editions exist rather than drop
    them silently: Open Library records a language for 80.8% of editions.

    The order is the one the user's specification asks for (`docs/DECISIONS.md`
    §1, UC1) and it is stated here rather than in the page, so the CLI, the
    tests and the browser cannot disagree about it. Where two rows share a year
    the tie is broken by the store's arrival order — the producers' order, never
    a hash's — which is what keeps the snapshot byte-stable across runs.
    """
    grouped = {}
    for arrival, edition in enumerate(editions):
        grouped.setdefault(edition.language, []).append((arrival, edition))
    return {code: [e for _, e in sorted(rows, key=_newest_first)]
            for code, rows in grouped.items()}


def _newest_first(pair) -> tuple:
    """Sort key: dated before undated, newest first, then arrival order.

    Newest is the **latest printing** (decision AG): an ISBN reprinted from 1985
    to 2026 is in print now, and sorting it by 1985 would bury it.
    """
    arrival, edition = pair
    year = year_of(edition.latest)
    return (year is None, -(year or 0), arrival)


def year_of(value) -> int | None:
    """First four-digit year anywhere in the string.

    Open Library `publish_date` is free text — '1985', 'June 1985',
    '1972-01-01', 'December 31, 1985' — so slicing the first four characters
    dropped every month-name date, which silently removed most English editions
    whenever a year filter was set.
    """
    m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", str(value or ""))
    return int(m.group(1)) if m else None


def printing_years(edition) -> list:
    """Every year this row was printed in, as numbers, earliest first.

    What the year filter compares against and what a language span reads: a row
    printed in 1985 and 2026 *was* on sale in 2026, and a filter from 2000 that
    hid it because its first printing is older would be wrong about the row.
    """
    return sorted({y for y in (year_of(p) for p in edition.printings) if y})


def span_is_original(work, code: str, years: list) -> bool:
    """Is this language row the work's original, on the evidence shown in it?

    Marking it on the language alone let the header contradict itself: a
    giapponese row reading 1972-2005 carried the ORIGINAL tag directly under
    'first published 2002 in giapponese'. The tag names a language, but it is
    read as naming the row, so the row has to be able to support it.

    With no original year known there is nothing to check against and the
    language is the best evidence available, so the tag stands.
    """
    if not (work and work.original_language == code):
        return False
    year = work.original_year
    if not (year and str(year).isdigit() and years):
        return True
    return min(years) <= int(year) <= max(years)


def spans(work, grouped: dict, shown: dict | None = None) -> list:
    """One row per language: how long the work has been in print in it.

    Earliest first, so the original leads and the translations follow in the
    order they appeared, which is the shape of a publication history. Undated
    languages come after the dated ones and an unrecorded language last of all.

    `grouped` is what the years and the counts are read from. `shown`, when
    given, is every row the page draws, the reader's additions included: a
    language only they reach still gets a span, with `editions` 0 and no years,
    and every span says in `added` how many rows beyond `editions` it holds
    (decision AI).
    """
    out = []
    shown = grouped if shown is None else shown
    for code in sorted(set(grouped) | set(shown)):
        editions = grouped.get(code, [])
        years = [y for e in editions for y in printing_years(e)]
        out.append({
            "code": code,
            "name": langs.display(code),
            "editions": len(editions),
            "added": len(shown.get(code, [])) - len(editions),
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "is_original": span_is_original(work, code, years),
        })
    out.sort(key=lambda s: (s["code"] == UNKNOWN, s["first_year"] is None,
                            s["first_year"] or 0, -s["editions"], s["code"]))
    return out


# ---------------------------------------------------------------------------
# The header
# ---------------------------------------------------------------------------

def origin_phrase(original_year, language_name, first_year_seen) -> str:
    """How a work's beginning is stated. One implementation, every client.

    Never pair a known original language with a fallback year: "first published
    1976 in inglese" would take the year from an Italian edition and the
    language from the English original, and is simply false.
    """
    if original_year and language_name:
        return f"first published {original_year} in {language_name}"
    if original_year:
        return f"first published {original_year}"
    if language_name:
        return (f"originally in {language_name}"
                + (f", earliest edition found {first_year_seen}" if first_year_seen else ""))
    if first_year_seen:
        return f"earliest edition found {first_year_seen}"
    return ""


def stated_when(work) -> str | None:
    """The stated date, as precise as its source was and no more.

    `1838`, `in the 1300s`, `in the 19th century`, `39 BCE`: *Le livre des
    rois* is dated `+1838` at century precision, and "first published 1838"
    stated a year Wikidata never gave. Anything coarser than a century is
    not stated at all.
    """
    if not work:
        return None
    if not work.original_date:
        return str(work.original_year) if work.original_year else None
    year, precision = work.original_date
    era = " BCE" if year < 0 else ""
    year = abs(year)
    if precision >= 9:
        return f"{year}{era}"
    if precision == 8:
        return f"in the {year // 10 * 10}s{era}"
    if precision == 7:
        century = (year - 1) // 100 + 1
        suffix = "th" if century % 100 in (11, 12, 13) else \
            {1: "st", 2: "nd", 3: "rd"}.get(century % 10, "th")
        return f"in the {century}{suffix} century{era}"
    return None


def original_is_stated(work) -> bool:
    """Did a source state this original? Rule 8: uncertainty shows less, so the
    header states an original a source stated and otherwise states none. Since
    decision AH nothing in the tree infers one, so `stated_by` is always a
    source's name where it is set."""
    return bool(work and work.stated_by)


def earliest_edition(work, editions: list) -> dict | None:
    """The earliest edition **found**, and what the catalogues say it is.

    Always shown, beside the original and never compared with it: A5 measured
    the comparison as 8 false flags and 1 miss over 36 books, so no such
    inference exists anywhere in this codebase (decision D).

    **Editions dated before a known original year are left out**, which is the
    other half of the same measurement: a Dutch translation catalogued 1912, a
    CreateSpace reprint dated 1866, an audiobook dated 2001 under a 2002 work.
    The rule keeps nothing out when no original year is known, because then
    there is nothing to be earlier than. Scored over the corpus
    (decision D) — 22 right, 9 right with other
    languages tying, 4 later, 2 right-year, and **0 older than the first
    edition** — which `tests/test_core_earliest.py` reproduces.

    The row that gives the line its language and publisher is the original's own
    where one of the rows at that year is in the original language, and
    otherwise the first the store wrote: a tie is real (9 books of 37) and
    `languages` carries all of it rather than the pick pretending there was one.
    """
    original_year = None
    if work and work.original_year and str(work.original_year).isdigit():
        original_year = int(work.original_year)
    dated = [(y, e) for y, e in ((year_of(e.year), e) for e in editions) if y]
    kept = [(y, e) for y, e in dated if original_year is None or y >= original_year]
    if not kept:
        return None
    year = min(y for y, _ in kept)
    at = [e for y, e in kept if y == year]
    lead = next((e for e in at
                 if work and e.language == work.original_language), at[0])
    return {
        "year": year,
        "language": lead.language,
        "language_name": langs.display(lead.language),
        "publisher": lead.publisher,
        "languages": sorted({e.language for e in at}),
        "language_names": [langs.display(code)
                           for code in sorted({e.language for e in at})],
        "editions": len(at),
        # What the rule kept out, counted rather than described: the reader is
        # owed the fact that something older was found and not believed.
        "older_dropped": len(dated) - len(kept),
    }


def display_title(editions: list, work) -> str:
    """The work's name, preferring the original title then the earliest edition's.

    With no stated original, the earliest edition carries the original title,
    which is more meaningful than whichever spelling happens to recur most:
    counting occurrences picked the Italian title for 'The Invention of News',
    because the two English records differ in article and casing and so tie at
    one each.
    """
    if work and work.original_title:
        return work.original_title
    if work and work.original_language:
        known = work.titles_by_lang.get(work.original_language)
        if known:
            return known
    dated = [(year_of(e.year), e) for e in editions]
    dated = [(y, e) for y, e in dated if y]
    if dated:
        return core_title(min(dated, key=lambda pair: (pair[0], pair[1].id))[1].title)
    counts = {}
    for edition in editions:
        base = core_title(edition.title)
        if base:
            counts[base] = counts.get(base, 0) + 1
    if counts:
        return max(sorted(counts), key=lambda t: counts[t])
    return ""


def header(work, grouped: dict, language_spans: list, ordered: list = ()) -> dict:
    """The publication history, stated. Never a verdict, never an inference.

    Two statements side by side and **no comparison between them**: the original
    where a source stated one (`original_stated`, false when this tool worked it
    out), and the earliest edition the catalogues actually hold, always. No
    inference is drawn from the pair anywhere in this codebase, and the rule
    that would draw one was measured wrong (A5: 8 false flags, 1 miss, 36
    books).

    `ordered` is the store's own order, which `earliest` uses to break a tie
    between rows sharing the earliest year. `grouped` is sorted newest-first
    inside each language, so deriving it from there would make the tie-break a
    reading of the sort instead of a reading of the store.
    """
    editions = [e for code in sorted(grouped) for e in grouped[code]]
    years = [y for y in (year_of(e.year) for e in editions) if y]
    original_year = None
    if work and work.original_year and str(work.original_year).isdigit():
        original_year = int(work.original_year)
    stated = original_is_stated(work)
    language_name = (langs.display(work.original_language)
                     if work and work.original_language else None)
    first_year_seen = min(years) if years else None
    return {
        "title": display_title(editions, work),
        "authors": _header_authors(work, editions),
        "original_title": (work.original_title if work else None),
        "original_language": work.original_language if work else None,
        "original_language_name": language_name,
        "original_year": original_year,
        "original_stated": stated,
        "original_stated_by": (work.stated_by if work else ""),
        "original_basis": (work.basis if work else ""),
        "first_year_seen": first_year_seen,
        "earliest": earliest_edition(work, list(ordered) or editions),
        "total_editions": len(editions),
        "spans": language_spans,
        # The stated original only. The earliest edition found has a line of its
        # own now, so the phrase never borrows a year from an edition to stand
        # in for one no source gave.
        "origin": origin_phrase(stated_when(work), language_name, None) if stated else "",
        "found": bool(editions),
    }


def _header_authors(work, editions: list) -> list:
    """The work's authors if it has any, else the first edition's that has some.

    One source, not a pool: mixing them lists a translator beside an author and
    reads as a collaboration.
    """
    names = []
    for source in ([work.authors] if work and work.authors else []) + \
                  [e.authors for e in editions]:
        for name in source:
            display = author_display(name)
            if display and display not in names:
                names.append(display)
        if names:
            break
    return names[:3]


# ---------------------------------------------------------------------------
# The publisher facet
# ---------------------------------------------------------------------------

def publisher_ids(edition, places: set) -> list:
    """Every publisher this row names, as stable ids. Sorted, so it is total.

    An id is `core.fold.publisher_key`'s word set joined — the fold's own rule
    for "the same house", so 'Mondadori, Milano' and 'A. Mondadori, Milano' are
    one publisher and 'Einaudi' finds 'Giulio Einaudi editore'. It is computed
    here and carried on the row because the browser filters on it: deriving it
    again in JavaScript would be a second implementation of a rule that was
    measured once (A4, the collision's precision).

    A list rather than one value, because a row can genuinely name two —
    'Penguin ; in association with Martin Secker & Warburg' is both — and
    hiding it from one of its own publishers would be wrong. Read off the
    **records**, because the publisher statement and its split into names are a
    record's, and two sources folded into one row name it differently.
    """
    keys = set()
    for record in edition.records:
        keys |= publisher_keys(record, places)
    return sorted(" ".join(sorted(key)) for key in keys if key)


def publisher_names_on(record) -> list:
    """The publisher statements on one record, already split by its own source."""
    names = list(getattr(record, "publisher_names", None) or [])
    if not names and record.publisher:
        names = [record.publisher]
    return names


def publisher_facets(editions: list, places: set, ids: dict | None = None) -> list:
    """`[{"id", "label", "editions"}]`, most editions first. Unfiltered, always.

    Every publisher in hand, with no cap: the page collapses the list, which is
    a display choice, rather than truncating it, which would be a claim about
    the data and would owe rule 10 a note. N06 names 390 of them.

    The label is the commonest spelling of the name, ties going to the shortest
    and then to the alphabet, so one publisher is offered under one name and the
    choice does not move between runs.

    `ids` is `snapshot`'s already-computed `{edition id: publisher ids}`, so the
    facet and the rows read one derivation rather than two that could drift.
    """
    counts, spellings = Counter(), defaultdict(Counter)
    for edition in editions:
        for pid in (ids[edition.id] if ids is not None else publisher_ids(edition, places)):
            counts[pid] += 1
        for record in edition.records:
            for name in publisher_names_on(record):
                spelling = strip_places(name, places).strip()
                key = publisher_key(spelling)
                if key:
                    spellings[" ".join(sorted(key))][spelling] += 1
    out = []
    for pid in sorted(counts):
        forms = spellings.get(pid) or Counter()
        label = min(sorted(forms), key=lambda s: (-forms[s], len(s), s)) if forms else pid
        out.append({"id": pid, "label": label, "editions": counts[pid]})
    out.sort(key=lambda p: (-p["editions"], p["label"], p["id"]))
    return out


# ---------------------------------------------------------------------------
# The coverage ledger
# ---------------------------------------------------------------------------

# One line per way a record was admitted, in the order the ledger reads them.
# A key is a tuple because the reader is owed the *distinction that matters* —
# SBN said so, or this tool worked it out — not the six internal names of the
# evidence that worked it out.
LEDGER_LINES = (
    ((UNIFORM_TITLE,), "linked to this work in SBN"),
    ((TITLE_MATCH, ISBN_MATCH),
     "found by other routes — SBN holds them but has not linked them"),
    ((WORK_KEY,), "in Open Library's record for this work"),
    ((DUPLICATE_WORK,), "in Open Library's other records for the same work"),
)


def coverage_ledger(coverage: dict, evidence: dict, editions: int) -> dict:
    """What this answer is made of: counts, and what was read only in part.

    It **counts what was found and never states what exists** — decision C's
    *no census* half stands, VIAF was measured as unusable for one (A6: 20 of 37
    books), and decision N reversed only the other half. So every line here is a
    number this lookup can prove, and the truncations say how much of a query
    was read rather than how much SBN holds.

    Every admitted record lands on exactly one line: the lines are keyed on the
    evidence that admitted it, and whatever the four named keys do not cover is
    counted on a line of its own rather than quietly lost. That is what "the
    ledger's numbers reconcile with the store" means, and
    `records == admitted + refused` is the other half of it.
    """
    by_evidence = coverage["by_evidence"]
    lines, counted = [], 0
    for keys, text in LEDGER_LINES:
        n = sum(by_evidence.get(name, 0) for name in keys)
        counted += n
        if n:
            lines.append({"count": n, "text": text})
    rest = coverage["admitted"] - counted
    if rest:
        lines.append({"count": rest, "text": "admitted on other evidence"})
    disbelieved = _disbelieved(evidence)
    return {
        "records": coverage["records"],
        "admitted": coverage["admitted"],
        "refused": coverage["refused"],
        "editions": editions,
        "lines": lines,
        "truncations": notes.truncations(evidence),
        "not_asked": notes.not_asked(evidence),
        "spellings": notes.spellings(evidence.get("identity") or {},
                                     evidence.get("recovery") or {}),
        "disbelieved": disbelieved,
        "multi_language": len(_multi_language(evidence)),
    }


def _disbelieved(evidence: dict) -> int:
    """Records whose stated language this tool refused to believe (rule 4).

    `linguaPubblicazione` is the only language signal there is and it sometimes
    names the language translated *from*, so a record that contradicts itself
    stops being evidence of a language. That is this tool acting on a catalogue's
    statement, so it is disclosed rather than done quietly.
    """
    return len(disbelieved_notes(evidence))


# Where inside a stage's evidence a producer files its rule 4 notes: at the top,
# under S3's gate, and under decision Q's reverse path, which Step 12 found this
# reading was missing.
_DISBELIEF_PARTS = ("gate", "reverse")


def disbelieved_notes(evidence: dict) -> list:
    """Every rule 4 note any stage wrote, in stage order. One reading for the
    ledger's count and for S4's *already reported* list, so they cannot drift."""
    out = []
    for stage in evidence.values():
        if not isinstance(stage, dict):
            continue
        out += stage.get("language_disbelieved") or []
        for part in _DISBELIEF_PARTS:
            inner = stage.get(part)
            if isinstance(inner, dict):
                out += inner.get("language_disbelieved") or []
    return out


def _multi_language(evidence: dict) -> dict:
    """`{record id: [codes]}` for rows SBN returned on two language pages.

    A parallel Russian/Italian text, a Greek/Latin *Odyssea*: 326 rows over the
    corpus **M**. `Record.language` holds one of them, so the row is counted
    once — which is right — and the other code would be lost if the row did not
    carry it. It is a label and it filters nothing (decision Z's shape).
    """
    listing = evidence.get("listing") or {}
    return ((listing.get("sbn") or {}).get("multi_language")) or {}


# ---------------------------------------------------------------------------
# The loose-match band
# ---------------------------------------------------------------------------

# The band's two groups, by the route that reached the record. The split is the
# honest one: a title probe offered the record **as this work's title** and the
# gate said no, while the author sweep only ever said "the same person is on
# it". Calling 6,799 of the latter "matched loosely" would be false.
BAND_GROUPS = (
    ("matched", "matched against this work's titles and refused"),
    ("swept", "filed under this author's name in SBN — no title of this work "
              "identifies them"),
)


def band_group(route: str) -> str:
    return "swept" if route == AUTHOR_SWEEP else "matched"


def loose_matches(records: list) -> dict:
    """Every record the gate refused, lean, in two groups, best score first.

    **Records, not editions**, and every one of them: the band's contents are
    the store's gate-rejected records and nothing else, which is a clause of
    Step 11's gate and stops being checkable the moment a floor is applied.
    8,833 refusals over 79 entries — median 82, max 337 — of which 6,987 are the
    author sweep's and 7,199 score exactly 0.0 **M**.

    The rows are **lean** because that is what makes showing all of them
    affordable: a band row is what a reader needs to judge a refusal — its
    title, its imprint, how it was reached and how near it came — and not the
    twenty fields an edition row carries for filtering, folding and expanding.
    None of those apply here: a refused record is in no language group, no
    filter, no count and no duplicate hint.
    """
    rows = [_band_row(r) for r in records]
    groups = []
    for name, label in BAND_GROUPS:
        members = [r for r in rows if r["group"] == name]
        if members:
            members.sort(key=lambda r: (-(r["score"] or 0.0), _by_year(r), r["id"] or ""))
            groups.append({"group": name, "label": label, "count": len(members),
                           "rows": members})
    return {"total": len(rows), "threshold": IDENTIFYING_TITLE_MATCH,
            "groups": groups}


def _by_year(row: dict) -> tuple:
    year = year_of(row["year"])
    return (year is None, -(year or 0))


def _band_row(record) -> dict:
    """One refused record as the band draws it. Nine fields, and no more."""
    p = record.provenance
    return {
        "id": record.id,
        "source": record.source,
        "title": record.title or "",
        "year": record.year or " / ".join(record.years_shown) or None,
        "publisher": record.publisher,
        "url": record.url,
        "route": p.route,
        "score": p.score,
        "group": band_group(p.route),
    }


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------

def snapshot(store, work=None, version: int = 1, evidence: dict | None = None,
             this_year: int | None = None) -> dict:
    """The whole view, derived from the store from scratch. Deterministic.

    Everything the page shows and nothing it does not: the header, the language
    groups, the ambiguity choices, the coverage ledger, the loose-match band's
    rows and the duplicate hints. A caller replaces one of these with the next;
    it never patches one in place (decision M).

    **Filters never touch identity** (rule 12): the header, the spans and the
    counts here are computed over the whole store, unfiltered, so changing a
    filter re-filters the rows and issues no request and moves no number in the
    header.
    """
    evidence = evidence or {}
    # Every reading below — the header, the spans, the rows, the filters — takes
    # the year `core.dates` settled, never the catalogue's first year as written
    # (decision AY). The store keeps what the catalogue said.
    records = [dates.settled(r, this_year) for r in store.records()]
    editions = fold(records)
    grouped = group_by_language(editions)
    # The reader's own additions (decision AI) join the groups, the counts, the
    # filters and the duplicate check, and **not the header**: it states what
    # the catalogues tie to this work, and an omnibus the reader added from 1949
    # must not become the earliest edition found. So the header and the language
    # spans are derived over the rest, and each span counts what was added apart.
    added = {e.id for e in editions if is_added(e)}
    identified = [e for e in editions if e.id not in added]
    language_spans = spans(work, group_by_language(identified), grouped)
    group_keys = assign_groups(editions, work.authors if work else [])
    groups = dict(zip([e.id for e in editions], group_keys))
    places = places_in(records)

    # One derivation of "which publishers does this row name", read by the row
    # and by the facet: two would be two things that can drift apart.
    pub_ids = {e.id: publisher_ids(e, places) for e in editions}

    # With an author S1 identified one work, and a row credited to somebody
    # else already says so (decision Z), so there is nothing to choose between
    # (decision AN). Only a lookup that had no author to ask with groups rows
    # into books: the chooser a bare title gets is `title_chooser`'s, earlier.
    asked = ((evidence.get("identity") or {}).get("question") or {}).get("author")
    ambiguity = [] if asked else choices(editions, group_keys)
    routes = store.routes
    forms = author_forms(work)
    multi = _multi_language(evidence)
    return {
        "version": version,
        "header": {**header(work, group_by_language(identified), language_spans,
                            identified),
                   "added": len(added),
                   # No author was typed and the sources agreed on one (decision
                   # AN): the byline says so rather than passing it off as asked.
                   "author_adopted": evidence.get("author_adopted")},
        "editions_by_language": {code: [_row(e, groups, routes, forms, pub_ids, multi)
                                        for e in grouped[code]]
                                 for code in sorted(grouped)},
        "language_order": [s["code"] for s in language_spans],
        # The three filters' own vocabularies, counted over the whole store.
        # A filter is a choice among what is already in hand, so these move
        # only when a new version arrives (rule 12).
        "publishers": publisher_facets(editions, places, pub_ids),
        "choices": ambiguity,
        "ambiguous": len(ambiguity) > 1,
        "coverage": store.coverage(),
        "ledger": coverage_ledger(store.coverage(), evidence, len(editions)),
        "duplicate_hints": collisions(editions, places),
        # Collapsed by default, opened deliberately: the one sanctioned place
        # the project shows a record it could not tie to the work (decision N).
        "loose_matches": loose_matches([dates.settled(r, this_year)
                                        for r in store.refused()]),
        "duplicate_works": duplicate_works(evidence.get("duplicates") or {}),
    }


def is_added(edition) -> bool:
    """Is every record behind this row one the reader added (decision AI)?

    One record reached any other way — the main work's own listing, an ISBN
    it shares with an SBN row — makes the row the catalogues', and it stays in
    the header like any other.
    """
    return bool(edition.records) and all(
        r.provenance.evidence == DUPLICATE_WORK for r in edition.records)


def duplicate_works(evidence: dict) -> dict:
    """Open Library's other records for this work, as the page lists them.

    Every row the stage listed, never capped: a cap would be a claim about which
    ones matter, and the reader is the one who judges an omnibus from a
    duplicate (decision J). `added` and `failed` are per row, so an *Add* that
    did not arrive is never drawn as one that brought nothing (`CLAUDE.md`
    rule 5).
    """
    if not evidence:
        return {"asked": False, "rows": [], "editions": 0, "why_not": None}
    added, failed = set(evidence.get("added") or []), evidence.get("failed") or {}
    rows = [{**r, "added": r["key"] in added, "failed": failed.get(r["key"])}
            for r in evidence.get("rows") or []]
    return {"asked": bool(evidence.get("asked")),
            "why_not": evidence.get("why_not"),
            "rows": rows,
            "editions": sum(r["editions"] for r in rows),
            "added": sum(1 for r in rows if r["added"])}


def author_forms(work) -> list:
    """Every name form the work's author is known by, for matching only.

    The typed and Wikidata names plus SBN's authority headings. A row is only
    said to be credited to somebody else when it matches none of them, and
    `Maḥfūẓ, Naǧīb` against `Naguib Mahfouz` is exactly why the headings are
    here (`core.identity.credited_to_another`).
    """
    if not work:
        return []
    return list(work.authors) + list(work.author_headings)


def also_filed_as(edition, multi: dict) -> list:
    """The other language codes SBN returned this row under. Usually none.

    326 rows over the corpus come back on two language pages — a parallel
    Russian/Italian text, a Greek/Latin *Odyssea* — and `Record.language` holds
    one of them, so the row is counted once, in one group. The other code is a
    **label and filters nothing** (decision Z's shape applied to the same kind
    of fact): the catalogue said it, this tool did not work it out, and a reader
    filtering for russo is owed the knowledge that the row exists.
    """
    codes = []
    for record in edition.records:
        for code in multi.get(record.id) or ():
            if code != edition.language and code not in codes:
                codes.append(code)
    return codes


def _row(edition, groups: dict, routes, author_forms: list, ids: dict,
         multi: dict) -> dict:
    """One edition as the page reads it, with every route that reached it.

    `routes` is `RecordStore.routes`: a record found by the work listing and
    again by the author sweep carries both, in arrival order, because "which
    route found this" is what the recovered badge and the leak audit read.

    `year_num` and `publisher_ids` are what the browser's three filters compare
    on, and they are here rather than in the page for the same reason: the
    header's earliest year and a year filter must read a catalogue's free-text
    date the *same* way, or a filtered list could disagree with the header above
    it. `year_of` is that one reading.

    `ids` is `snapshot`'s `{edition id: publisher ids}` and is required: one
    derivation feeds the row and the facet, and a fallback here would be a
    second one, reachable only when they had already diverged.
    """
    return {
        "id": edition.id,
        "isbn": edition.isbn,
        "title": edition.title,
        "publisher": edition.publisher,
        "year": edition.year,
        "year_note": year_note(edition),
        "year_num": year_of(edition.year),
        "years_num": printing_years(edition),
        "latest": edition.latest,
        "publisher_ids": ids[edition.id],
        "printings": edition.printings,
        "language": edition.language,
        "language_name": langs.display(edition.language),
        "sources": edition.sources,
        "series": edition.series,
        "physical": edition.physical,
        # What the catalogue says this row is, where that is not simply an
        # edition of the work. Both are labels and neither filters: SBN links
        # non-editions to a work (F16) and hiding them would be a claim the
        # list is clean, which it is not.
        "medium": edition.medium,
        "credited_to": credited_to_another(edition, author_forms),
        "also_in": [{"code": code, "name": langs.display(code)}
                    for code in also_filed_as(edition, multi or {})],
        "url": edition.url,
        "authors": [author_display(a) for a in edition.authors],
        "translators": [author_display(t) for t in edition.translators],
        "evidence": edition.evidence,
        # Holdings are not here: one full record lists up to 851 libraries
        # (85 KB), so they are read off the store when a row is opened
        # (`lookup.stages.details`), with no request.
        "work_group": groups.get(edition.id, ""),
        "provenance": [{"source": p.source, "route": p.route,
                        "evidence": p.evidence, "score": p.score, "record": r.id,
                        **({"via": p.via} if p.via else {})}
                       for r in edition.records for p in routes(r)],
        "added_from": sorted({r.provenance.via for r in edition.records
                              if r.provenance.evidence == DUPLICATE_WORK
                              and r.provenance.via}),
    }


def year_note(edition) -> dict | None:
    """Why this row's year is not simply the one the catalogue wrote, or None."""
    return records_year_note(edition.records, edition.year)


def records_year_note(records: list, year) -> dict | None:
    """The note for one row over its settled records, `year` the row's own.

    `shown` is every year a row with no settled year shows instead of one;
    `detail` is what the catalogue wrote and what SBN's index said, for the
    label's tooltip (decision AY).
    """
    note, shown, statements = dates.row_note(records)
    if not note:
        return None
    indexed = sorted({str(v) for r in records if r.year_note
                      for v in r.date_indexed or []})
    printing = note == dates.PRINTED
    return {"note": note, "label": notes.year_label(note, shown if printing else ()),
            "shown": " / ".join(shown) if not (year or printing) and shown
            else None,
            "detail": notes.year_detail(note, statements, indexed,
                                        asked=any(r.date_indexed is not None
                                                  for r in records))}


def title_chooser(title: str, books: list, version: int = 1) -> dict:
    """A bare title naming several books: the chooser, and nothing else.

    No edition list and no header (decision AN). Without an author SBN's work
    authority cannot be asked (`CLAUDE.md` rule 3), so any list here would be
    Open Library's alone and would describe several books at once. A pick
    reruns the lookup as title + author.
    """
    return {"version": version,
            "chooser": {"title": title, "books": books,
                        "heading": notes.books_share_title(len(books), title)}}
