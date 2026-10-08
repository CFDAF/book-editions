"""Author mode (UC4): who the person is, and which works are theirs. Pure.

An author with no title gets their bibliography as **works**, not editions,
and the person is resolved before anything is listed (decision §5-6). Every
judgement that takes is here, beside the gates in `core/identity.py` and with
the same discipline: no network, no clock, counts in and verdicts out.

Four of them, in the order a lookup reaches them (decision AJ):

1. **Who is meant.** SBN's name authority gives one id per person for every
   Latin form (A7), but a name can answer with several people — ten for *Garcia
   Marquez* — and one person can sit under several ids (four for Mahfouz, one
   of them 531 records and the others 1 or 2). So the candidates are shown, and
   the chooser is skipped only when every form asked answered with the same
   single Persona and `pick_authority` resolved it.
2. **Where SBN's works list stops.** Every facet stops at 50 (F11). A list of
   exactly 50 is split by language and then by exact year, and every leaf's
   total is summed against its parent's so what no leaf covered is a count.
3. **What a row is.** An SBN uniform title or a Wikidata work — the two sources
   that state a *work* rather than a record. Open Library files translations as
   works of their own (*Steps to an Ecology of Mind* is ~15 work records there,
   one of them titled *Verso un'ecologia della mente*), so an Open Library doc
   only ever **joins** a row, and one that joins none is listed apart.
4. **How rows sort.** By the original's year where Wikidata states one, else by
   the earliest edition found, newest first, unknown last — and the row says
   which of the two it is.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .identity import ADAPTATION, WORK_TITLE_MATCH, names_agree, pick_authority
from .view import records_year_note
from .text import (author_display, core_title, fold_variants, is_latin, normalize,
                   similarity, surname)

FACET_CAP = 50              # F11, re-run 2026-09-25: every OPAC facet stops here
YEAR_FLOOR = 1450           # where an exact-year sweep stops with no birth year

ORIGINAL = "original"       # the row's year is the work's, as Wikidata states it
EARLIEST = "earliest edition found"


# ---------------------------------------------------------------------------
# 1. Who is meant
# ---------------------------------------------------------------------------

def persons(rows) -> list:
    """The Persona rows of a `core=autori` answer. A corporate body or a
    congress (`Fondazione Umberto Eco`) is never an author to list."""
    return [r for r in rows or [] if (r.get("kind") or "").strip() == "Persona"]


def latin_forms(typed: str, aliases) -> list:
    """The name forms worth asking the OPAC: the typed one first, then every
    Latin alias, deduplicated on their tokens. The rest are dropped because the
    OPAC would discard them and answer with every name it holds (F15)."""
    seen, out = set(), []
    for form in [typed, *aliases]:
        key = frozenset(normalize(form or ""))
        if form and key and is_latin(form) and key not in seen:
            seen.add(key)
            out.append(form)
    return out


def same_name(a: str, b: str) -> bool:
    """Two spellings of one person's name: the same tokens, or surnames that
    `names_agree` reads as one (*Maḥfūẓ* and *Mahfouz*, *Dostoïevski* and
    *Dostoevsky*).

    Not `names_agree` on the whole name, which is satisfied by one shared token
    — so *Nagib Surur* agreed with *Nagib Mahfuz* and *Umberto Saba* would with
    *Umberto Eco*. A forename says nothing about who someone is.
    """
    ta, tb = normalize(author_display(a)), normalize(author_display(b))
    if ta and ta == tb:
        return True
    return names_agree(surname(author_display(a)), surname(author_display(b)))


def person_of(people: list, forms) -> dict | None:
    """The Wikidata person whose names agree with a form asked, or None.

    `names_agree` is loose on purpose (another romanisation, a Latinised
    stem), and it is safe here only because nothing the item says identifies a
    work: its aliases are *asked*, and every id they reach is shown to the
    reader rather than believed.
    """
    for person in people or []:
        if any(same_name(n, f) for n in person.get("names") or [] for f in forms
               if is_latin(n)):
            return person
    return None


@dataclass
class Candidate:
    """One SBN name-authority record the reader may pick."""
    id: str
    heading: str
    forms: list = field(default_factory=list)     # which forms reached it
    agrees: bool = False                          # its name is the one asked
    records: int | None = None                    # filled once counted
    languages: int | None = None

    @property
    def display(self) -> str:
        return author_display(self.heading)


def candidates(answers: list, typed: str) -> dict:
    """Every Persona the forms reached, the one `pick_authority` resolves, and
    whether the chooser may be skipped.

    `answers` is `[{"form", "rows", "total"}]`, the typed form first. The skip
    is decision AJ's and it is narrow: across every form, one Persona and no
    other, and the typed form resolves to it. One namesake anywhere — Peter
    Finke beside Bateson — and the reader chooses.
    """
    found: dict = {}
    for answer in answers:
        for row in persons(answer.get("rows")):
            c = found.setdefault(row["id"], Candidate(row["id"], row.get("heading") or ""))
            c.forms.append(answer["form"])
    forms = [a["form"] for a in answers]
    for c in found.values():
        c.agrees = any(same_name(c.heading, f) for f in forms)
    first = answers[0] if answers else {"rows": [], "total": 0}
    picked = pick_authority(first.get("rows"), typed, first.get("total"))
    resolved = picked.get("id") if picked.get("id") in found else None
    if resolved is None and not first.get("error"):
        # The typed form alone is ambiguous — *Garcia Marquez* is Gabriel,
        # Eligio and Vicente — but when exactly one person whose name agrees is
        # also reached by a form Wikidata's person gave, that is the one to
        # tick. Ticked, not skipped: the chooser still shows every name. Not
        # when the typed form's own request failed: nothing was answered then.
        aliased = [c for c in found.values()
                   if c.agrees and any(f != forms[0] for f in c.forms)]
        if len(aliased) == 1:
            resolved = aliased[0].id
    # One person across every answer. A form that found nobody contradicts
    # nothing — Wikidata's aliases for Han include one SBN has never heard of,
    # and counting that against him put a one-name chooser in front of him.
    skip = bool(resolved) and len(found) == 1
    return {"candidates": list(found.values()), "resolved": resolved,
            "rule": picked.get("rule"), "skip": skip}


def order(cands: list, resolved: str | None) -> list:
    """The resolved person first, then names that agree with the one asked,
    then the rest; most records first within each. Deterministic on the id."""
    return sorted(cands, key=lambda c: (c.id != resolved, not c.agrees,
                                        -(c.records or 0), c.id))


# ---------------------------------------------------------------------------
# 2. Where SBN's works list stops
# ---------------------------------------------------------------------------

def capped(items) -> bool:
    """A facet of exactly `FACET_CAP` items is a truncated facet (F11)."""
    return len(items or []) >= FACET_CAP


def _year(value) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() and len(text) == 4 else None


def extra_years(facet_years, floor: int | None, ceiling: int) -> list:
    """The exact years to ask beyond a capped `dataf[]` facet, nearest first.

    The facet holds the 50 busiest years, so the missing ones are the quiet
    ones: the gaps inside its span first, then down to `floor` (the author's
    birth, else `YEAR_FLOOR`), then up to `ceiling`. The caller stops asking as
    soon as the leaves' totals add up to the parent's.
    """
    known = {y for y in (_year(v) for v in facet_years or []) if y}
    if not known:
        return []
    lo, hi = min(known), max(known)
    floor = max(floor or YEAR_FLOOR, YEAR_FLOOR)
    inside = [y for y in range(hi, lo - 1, -1) if y not in known]
    below = list(range(lo - 1, floor - 1, -1))
    above = list(range(hi + 1, ceiling + 1))
    return [str(y) for y in inside + below + above]


def works_union(nodes) -> dict:
    """`{value: label}` over every facet read. Leaves overlap (a bilingual
    record is in two language leaves), so the union is by value, never summed."""
    out = {}
    for node in nodes:
        for item in node.get("works") or []:
            value = item.get("value")
            if value:
                out.setdefault(value, item.get("label") or value)
    return out


# ---------------------------------------------------------------------------
# 3. What a row is
# ---------------------------------------------------------------------------

_TRAILING = re.compile(r"[\s.\-:;,/]+$")


def clean_label(label: str) -> str:
    """A uniform title as a title: `'angels fear : towards … sacred. -'` loses
    its trailing ISBD punctuation, and `<film ; 1951>` its qualifier."""
    text = re.sub(r"\s*<[^>]*>", "", label or "")
    return _TRAILING.sub("", text).strip()


# Every medium SBN's uniform titles name for a work made from a book, over
# P01–P09's (2026-10-02): `film` 25, `serie tv` 5, `sceneggiato tv` and
# `sceneggiato televisivo` 5, `documentario` 2, `videoregistrazione` 1.
# Wider than `identity.ADAPTATION`, which S1's gate reads and which moves only
# with rule 6's re-check. `<versione per orchestra>`, `<interviste>` and
# `<mostra>` are not media and stay the book's.
DERIVED = re.compile(r"<\s*(film|serie tv|sceneggiato(?: tv| televisivo)?|documentario"
                     r"|video\w*|dvd|audiolibro)\b", re.I)
_QUALIFIER_YEAR = re.compile(r"<[^>]*?[;,]\s*(\d{4})")


def medium_of(label: str) -> str | None:
    """`film`, `serie tv`… when the uniform title itself says so. A label, never
    a filter (decision Z): the adaptation is the catalogue's statement."""
    m = DERIVED.search(label or "")
    return m.group(1).lower() if m else None


def _derived(w: dict, titles: list) -> dict:
    """A film, series… made from a book, as its row draws it: the title it was
    catalogued under, its medium, the year the qualifier states (else SBN's
    earliest), and its own records — none of them the book's."""
    label = w.get("label") or w["value"]
    stated = _QUALIFIER_YEAR.search(label)
    years = [y for y in (_year(x.get("value")) for x in w.get("years") or []) if y]
    title = titles[1] if len(titles) > 1 else titles[0]
    # An episode is catalogued under its series: `{Il nome della rosa}Episodio 4`.
    series = re.match(r"\{([^}]+)\}", title)
    title = series.group(1) if series else title
    return {"title": title[:1].upper() + title[1:], "medium": medium_of(label),
            "year": int(stated.group(1)) if stated else min(years, default=None),
            "stated": bool(stated), "records": w.get("total") or 0,
            "uniform_titles": [w["value"]], "titles": list(titles)}


def _add_derived(row, entry: dict) -> None:
    """One film is one entry: SBN files Annaud's 1986 *Il nome della rosa*
    under three uniform titles, German, English and Italian. Joined only on a
    medium and a year the qualifiers both state, so a remake stays apart."""
    same = next((d for d in row.derived if entry["stated"] and d["stated"]
                 and (d["medium"], d["year"]) == (entry["medium"], entry["year"])), None)
    if same is None:
        row.derived.append(entry)
    else:
        same["records"] += entry["records"]
        same["uniform_titles"] += entry["uniform_titles"]
        same["titles"] = list(dict.fromkeys([*same["titles"], *entry["titles"]]))


def catalogued_title(raw: str) -> str:
    return (raw or "").split(" / ", 1)[0].strip()


def statement_of(raw: str) -> str:
    """What a catalogued title says after ISBD's ` / `: who wrote, edited,
    prefaced or translated it, as the record words it."""
    return (raw or "").partition(" / ")[2].strip()


def item_is_work(item: dict) -> bool:
    """A Wikidata item that is a written work and not an edition of one.

    Stricter than S1's `is_written_work`, whose P50-and-P577 half is fine for
    a title already matched and wrong here: every scholarly article carries
    both. Decision AF's edition rule stands as it is.
    """
    return bool(item.get("typed")) and not item.get("edition")


@dataclass
class WorkRow:
    """One work by the person, from whichever sources state it."""
    key: str
    title: str
    titles: list = field(default_factory=list)
    uniform_titles: list = field(default_factory=list)   # SBN's, as asked
    qid: str | None = None
    original_title: str | None = None
    original_language: str | None = None
    original_year: int | None = None
    sbn_years: list = field(default_factory=list)
    sbn_years_capped: bool = False
    sbn_records: int = 0
    languages: set = field(default_factory=set)
    ol: list = field(default_factory=list)
    medium: str | None = None
    # Films, series and the rest made from this book (decision BC): drawn under
    # it, never counted as it.
    derived: list = field(default_factory=list)
    main_author: bool = False        # the person heads a record of it
    credited: list = field(default_factory=list)    # who SBN heads it with instead
    statements: list = field(default_factory=list)  # each record's statement of responsibility
    unanswered: bool = False         # SBN did not return this work's records
    item_forms: list = field(default_factory=list)  # the Wikidata work's own names

    @property
    def matched_titles(self) -> list:
        """What a record is joined on: the book's titles and its adaptations'.
        A film's catalogued title is often the book's in another language
        (Kurosawa's *Hakuchi*), and SBN files a series' episodes under no
        uniform title, so dropping them from the join would move translations
        to the band and episodes to the group filed under no work."""
        return [*self.titles, *[t for d in self.derived for t in d["titles"]]]

    @property
    def earliest_year(self) -> int | None:
        years = [y for y in self.sbn_years if y]
        years += [d["year"] for d in self.ol if d.get("year")]
        return min(years) if years else None

    @property
    def year(self) -> int | None:
        return self.original_year or self.earliest_year

    @property
    def year_kind(self) -> str | None:
        if self.original_year:
            return ORIGINAL
        return EARLIEST if self.earliest_year else None


@lru_cache(maxsize=None)
def _folded(title: str) -> tuple:
    """What `core.text.similarity` computes from one title, computed once.

    The join compares every Open Library doc with every row's every title —
    4.7 million comparisons for Dostoevskij, 278 s of re-tokenising the same
    few thousand strings. The score is unchanged (`test_the_join_scores_as_the_
    gate_does` holds it to `similarity`); only the repetition goes.
    """
    core = core_title(title)
    return (frozenset(fold_variants(t) for t in normalize(title)),
            frozenset(fold_variants(t) for t in normalize(core)),
            (title or "").strip().casefold(), (core or "").strip().casefold())


def _overlap(q: frozenset, c: frozenset, a: str, b: str) -> float:
    if not q or not c:
        return 1.0 if a and a == b else 0.0
    return len(q & c) / max(len(q), len(c))


def _similar(a: str, b: str) -> float:
    """`core.text.similarity(a, b)`, from the memoised token sets."""
    fa, fb = _folded(a), _folded(b)
    return max(_overlap(fa[0], fb[0], fa[2], fb[2]), _overlap(fa[1], fb[1], fa[3], fb[3]))


def _tied(titles, candidates_titles: dict) -> list:
    """The candidates whose titles agree best with `titles`, at ≥ 0.6 — one
    key, several when they tie, none when nothing reaches the threshold."""
    scored = sorted(((max((_similar(a, b) for a in titles for b in theirs if a and b),
                          default=0.0), key)
                     for key, theirs in candidates_titles.items()), reverse=True)
    if not scored or scored[0][0] < WORK_TITLE_MATCH:
        return []
    return sorted(key for score, key in scored if score == scored[0][0])


def _best(titles, candidates_titles: dict) -> str | None:
    """The one candidate whose titles agree best with `titles` at ≥ 0.6, or
    None when none does **or two tie** — a tie is two works it could be, and
    joining either would be a guess."""
    tied = _tied(titles, candidates_titles)
    return tied[0] if len(tied) == 1 else None


def _best_work(titles, item_titles: dict, parts: dict) -> str | None:
    """`_best` for an SBN uniform title against the Wikidata works, except
    that a tie between items that are **one work** joins (decision AZ).

    Wikidata holds a work twice often enough to matter — *White Nights* as
    Q600461 and Q60714471, *Opera aperta* as Q2053926 and Q42193832 — and the
    tie it causes left SBN's title a row of its own beside both. Items are one
    work when each one's own names reach 1.0 on every other's and none is a
    part of another (P179, P361); the title then joins the one Wikidata names
    most ways, its main item. Anything less stays a guess: *Postille a Il nome
    della rosa* ties the *Postille* and *Il nome della rosa* themselves, which
    agree at 0.667, and *L'amica geniale* ties the first novel and the
    Neapolitan series it is part of, both *L'amica geniale* in Italian.
    """
    tied = _tied(titles, item_titles)
    if len(tied) > 1 and not any(set(parts.get(x) or ()) & set(tied) for x in tied) and all(
            max((_similar(a, b) for a in item_titles[x] for b in item_titles[y] if a and b),
                default=0.0) >= 1.0
            for i, x in enumerate(tied) for y in tied[i + 1:]):
        return min(tied, key=lambda k: (-len(item_titles[k]), k))
    return tied[0] if len(tied) == 1 else None


def _joins_any(titles, candidates_titles: dict) -> bool:
    """Whether `titles` agree with **any** candidate's at ≥ 0.6 — `_best`'s
    join without its tie refusal, for asking whether a work here has them
    rather than which one."""
    return any(_similar(a, b) >= WORK_TITLE_MATCH
               for theirs in candidates_titles.values()
               for a in titles for b in theirs if a and b)


def rows(sbn_works: list, items: list, docs: list, headings=()) -> dict:
    """The works, and the Open Library docs that joined none of them.

    `sbn_works`: `[{value, label, rows, languages, years, total}]`, one per
    uniform title. `items`: `[{qid, forms, typed, edition, original_title,
    original_language, year, part_of}]`. `docs`: Open Library docs already
    judged to be by the person, `[{key, title, year, edition_count, languages}]`.

    An SBN work joins the Wikidata work its titles agree with; several may join
    one (SBN files *sputoniku no koibito* twice). What joins nothing is a row
    of its own. Open Library docs join a row the same way, or go to the band.

    `main_author` is whether the person is **the record's own main author** on
    any SBN record of the work, or the Wikidata work names them in P50. The name
    authority files every record a person is *on* — a preface, a conference
    about them, a comic they appear in — and those are not their works.
    """
    wanted = [frozenset(normalize(h)) for h in headings if h]
    works = [i for i in items if item_is_work(i)]
    by_item = {i["qid"]: WorkRow(key=i["qid"], title="", qid=i["qid"],
                                 original_title=i.get("original_title"),
                                 original_language=i.get("original_language"),
                                 original_year=i.get("year"), main_author=True,
                                 titles=list(i.get("forms") or []),
                                 item_forms=list(i.get("forms") or []))
               for i in works}
    item_titles = {i["qid"]: list(i.get("forms") or []) for i in works}
    parts = {i["qid"]: i.get("part_of") or [] for i in works}
    out = dict(by_item)

    def titles_of(w):
        catalogued = [catalogued_title(r.get("title")) for r in w.get("rows") or []]
        return list(dict.fromkeys([clean_label(w.get("label") or w["value"]),
                                   *[t for t in catalogued if t]]))

    def join(w):
        titles = titles_of(w)
        qid = _best_work(titles, item_titles, parts)
        row = out.get(qid) if qid else None
        if row is None:
            row = out.setdefault(f"sbn:{w['value']}", WorkRow(key=f"sbn:{w['value']}",
                                                               title=""))
        row.uniform_titles.append(w["value"])
        row.titles = list(dict.fromkeys([*row.titles, *titles]))
        years = [_year(y.get("value")) for y in w.get("years") or []]
        row.sbn_years += [y for y in years if y]
        row.sbn_years_capped = row.sbn_years_capped or capped(w.get("years"))
        row.sbn_records += w.get("total") or 0
        row.languages |= {x.get("value") for x in w.get("languages") or [] if x.get("value")}
        row.medium = row.medium or medium_of(w.get("label") or w["value"])
        heads = [r.get("author") for r in w.get("rows") or [] if r.get("author")]
        # A work whose records never arrived cannot be shown to be somebody
        # else's, so it stays in the person's own list: a failure must not
        # move a work out of sight (rule 5's shape).
        row.unanswered = row.unanswered or bool(w.get("failed"))
        row.main_author = row.main_author or bool(w.get("failed")) or any(
            frozenset(normalize(h)) in wanted for h in heads)
        row.credited = list(dict.fromkeys([*row.credited, *heads]))
        said = [statement_of(r.get("title")) for r in w.get("rows") or []]
        row.statements = list(dict.fromkeys([*row.statements, *[x for x in said if x]]))

    # Books first, then what was made from them (decision BC). A film's uniform
    # title is the book's with `<film ; 1986>` after it, so it reaches the
    # book's row — the Wikidata work, or the SBN title it cleans to — and there
    # it is a derived entry, never one more of the book's titles, records,
    # languages or years. One that reaches no book is a row of its own, as before.
    made = [w for w in sbn_works if medium_of(w.get("label") or w["value"])]
    for w in sbn_works:
        if not any(w is m for m in made):
            join(w)
    for w in made:
        titles = titles_of(w)
        qid = _best_work(titles, item_titles, parts)
        book = (out.get(qid) if qid else None) or out.get(f"sbn:{clean_label(w['value'])}")
        if book is not None:
            _add_derived(book, _derived(w, titles))
        else:
            join(w)
    band = []
    row_titles = {k: r.matched_titles for k, r in out.items()}
    for doc in docs:
        key = _best([doc.get("title") or ""], row_titles)
        if key:
            out[key].ol.append(doc)
            out[key].languages |= set(doc.get("languages") or [])
        else:
            band.append(doc)
    for row in out.values():
        row.title = _display_title(row)
    return {"rows": sort_rows(list(out.values())), "band": band}


def _display_title(row: WorkRow) -> str:
    """The original's title where Wikidata states it; else the catalogued
    title closest to SBN's uniform title, which SBN writes in the original
    language; else the uniform title, cleaned. Never an Open Library title:
    those are in whatever language the record happened to be."""
    if row.original_title:
        return row.original_title
    if row.uniform_titles:
        label = clean_label(row.uniform_titles[0])
        near = max(((similarity(label, t), t) for t in row.titles if t != label),
                   default=(0.0, None))
        return near[1] if near[0] >= WORK_TITLE_MATCH else label[:1].upper() + label[1:]
    return row.titles[0] if row.titles else row.key


def lookup_title(row: WorkRow) -> str:
    """The title a click sends to the title lookup (UC3): Latin script, because
    the OPAC discards any other (F15). The original's own title when it is
    Latin; else SBN's uniform title, which is SBN's romanisation of it and is
    exactly what S1's work query matches; else any Latin form the row has."""
    for title in [row.original_title, *[clean_label(u) for u in row.uniform_titles],
                  *row.titles]:
        if title and is_latin(title):
            return title
    return row.title


def lookup_variants(row: WorkRow) -> list:
    """The other spellings the title lookup should try (Step 14): SBN's other
    uniform titles for the work — its romanisations of the original, *bain
    el-qasrain.* beside *bayn al-qasrayn* — then the Wikidata work's own Latin
    names. The lookup gates each one; this only says which to ask."""
    sent = lookup_title(row)
    out = []
    for title in [*[clean_label(u) for u in row.uniform_titles], *row.item_forms]:
        if title and is_latin(title) and title != sent and title not in out:
            out.append(title)
    return out


def sort_rows(rows_: list) -> list:
    """Newest first by the row's year, unknown last, then by title — the order
    UC4 asks for, and deterministic whatever order the sources answered in."""
    return sorted(rows_, key=lambda r: (r.year is None, -(r.year or 0),
                                        r.title.casefold(), r.key))


def doc_is_by(doc: dict, forms, keys) -> bool:
    """Is this Open Library doc by the person? By author key, or by name.

    Open Library's `author=` search matches the name anywhere in the field, so
    a co-author and a namesake both come back. Its own author resolution omits
    the main record for Murakami, Dostoevsky and Han (A7), which is why a key
    alone is not enough and the name is asked as well.
    """
    if keys and set(doc.get("author_keys") or []) & set(keys):
        return True
    return any(same_name(a, f) for a in doc.get("authors") or [] for f in forms)


def view(rows_: list, band: list, author_names: list) -> dict:
    """The rows as the page and the CLI draw them. Plain data, no prose but
    the row's own label.

    **Two lists, both whole** (decision AJ, taken mid-step on Eco: 177 of his
    305 rows are headed by somebody else). `works` are the person's own;
    `contributed` are what they wrote with others, edited, prefaced, were
    adapted in or are the subject of, each naming whom SBN credits instead, or
    nobody for an edited volume. The page draws the second closed; nothing is
    left out.

    A book written jointly has no main heading in SBN, so it lands in the
    second list, and no field tells it from a collection the person is one
    essayist of: SBN's role label gives `[Autore]` to both (D1, measured
    2026-10-03; decision BD). So each row carries its first
    record's `statement` of responsibility, and the reader sees *Umberto Eco,
    Marino Livolsi, Giovanni Panozzo* where the head alone would say nobody.
    """
    def one(r: WorkRow) -> dict:
        return {"key": r.key, "title": r.title, "year": r.year, "year_kind": r.year_kind,
                "original_year": r.original_year, "earliest_year": r.earliest_year,
                "original_language": r.original_language,
                "languages": sorted(x for x in r.languages if x),
                "sbn_records": r.sbn_records, "uniform_titles": list(r.uniform_titles),
                "qid": r.qid, "medium": r.medium,
                "derived": [{k: d[k] for k in ("title", "medium", "year", "records",
                                               "uniform_titles")}
                            for d in sorted(r.derived, key=lambda d: (d["year"] or 9999,
                                                                      d["title"]))],
                "open_library": [d["key"] for d in r.ol],
                "years_capped": r.sbn_years_capped,
                "credited_to": [author_display(h) for h in r.credited[:3]],
                "statement": r.statements[0] if r.statements else None,
                "unanswered": r.unanswered,
                "lookup": {"title": lookup_title(r),
                           "author": author_names[0] if author_names else "",
                           "variants": lookup_variants(r)}}
    return {"works": [one(r) for r in rows_ if r.main_author],
            "contributed": [one(r) for r in rows_ if not r.main_author],
            "band": [{"key": d["key"], "title": d.get("title"), "year": d.get("year"),
                      "editions": d.get("edition_count"),
                      "languages": sorted(d.get("languages") or [])} for d in band]}


def unlinked(records: list, rows_: list, linked_ids=(), headings=()) -> list:
    """The records under the person's name that no work listed here names.

    SBN's name authority files 134 records under Bateson and links 62 of them
    to a uniform title (Step 15B): *Balinese character*, the humour essays and
    the rest are his and are in no work. They are listed apart, collapsed, one
    row per catalogued title (decision AN) — the old author mode made a *work*
    of every catalogued title, *Verso un'ecologia della mente* and *Steps to
    an ecology of mind* separately, which decision AJ refused.

    A record is left out when a work's page already listed it (`linked_ids`)
    or when its title joins any work row at 0.6, the join the Open Library band
    uses — a French printing of *Steps* that the work's first page did not
    carry is that work's, not a book of its own. A tie between two rows still
    leaves it out: *Le notti bianche* is both `belye noci` and Q600461, and
    either way a listed work has it. What is left names whom SBN
    credits when it is not the person, as the contributed group does.

    A record's `year` is the one `core.dates` settled, and its settled copy,
    under `record` where the stage holds one, gives the group its year note as
    it gives an edition row's (decision AY).
    """
    wanted = [frozenset(normalize(h)) for h in headings if h]
    row_titles = {r.key: r.matched_titles for r in rows_}
    linked = set(linked_ids)
    groups: dict = {}
    for rec in records:
        if rec.get("id") in linked:
            continue
        title = catalogued_title(rec.get("title"))
        if not title or _joins_any([title], row_titles):
            continue
        key = core_title(title).casefold().strip() or title.casefold()
        g = groups.setdefault(key, {"title": title, "records": [], "years": [],
                                    "credited_to": [], "settled": []})
        g["records"].append(rec["id"])
        if rec.get("record") is not None:
            g["settled"].append(rec["record"])
        year = _year(rec.get("year"))
        if year:
            g["years"].append(year)
        head = rec.get("author")
        if head and frozenset(normalize(head)) not in wanted \
                and author_display(head) not in g["credited_to"]:
            g["credited_to"].append(author_display(head))
    out = [{"title": g["title"], "records": g["records"],
            "first_year": min(g["years"]) if g["years"] else None,
            "last_year": max(g["years"]) if g["years"] else None,
            "credited_to": g["credited_to"][:3],
            "year_note": records_year_note(g["settled"], min(g["years"], default=None))}
           for g in groups.values()]
    return sorted(out, key=lambda g: (g["first_year"] is None, -(g["first_year"] or 0),
                                      g["title"].casefold()))
