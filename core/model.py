"""Work, Edition, Record — the three things `models.Edition` was standing in for.

One class did all three jobs, and that conflation is the root of both the
duplicate-merge problem and the difficulty of "one row per ISBN": an `Edition`
was sometimes a catalogue row, sometimes a physical book, and sometimes the work
itself, so there was no level at which "the same thing twice" had a meaning.

|            | what it is                                            | key |
|------------|-------------------------------------------------------|-----|
| **Work**   | the identity: SBN W, QID, OL work keys, author, original | one per lookup |
| **Edition**| what a reader can buy                                  | its ISBN, else a synthetic id from its single record |
| **Record** | one catalogue row, one printing                        | `(source, id)` |

`Records -> fold by ISBN -> Editions -> group by language -> View`. Nothing in
that chain mutates anything upstream of it: an `Edition` holds its records and
derives every field from them, so there is no second copy of a value to go
stale, and the same store always derives the same view.

**Provenance is a field, not a mechanism** (build rule 4). Every
record carries where it came from, how it was reached, and what admitted it —
including that it was *refused*, with the score. The recovered badge, the leak
audit, the coverage ledger, the loose-match band and the slow-lookup
attribution are all readings of this one field, which is why it is on the record
and not in five side tables.
"""

from dataclasses import dataclass, field, replace

from catalog import langs

# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

# How a record was *reached* — which query returned it.
WORK_LISTING = "work listing"           # SBN, by uniform title
AUTHOR_SWEEP = "author sweep"           # SBN name authority, or an OL author key
TITLE_PROBE = "title probe"             # searched with a title the work is known by
ISBN_PROBE = "isbn probe"
WORK_EDITIONS = "work editions"         # Open Library /works/<key>/editions.json
DUPLICATE_WORK = "duplicate work"       # a second OL work record, opened by key
ENRICHED = "enriched"                   # the full record of a row already held

# What *admitted* it. The first is the catalogue stating the link; the rest are
# this tool inferring it, and `REFUSED` is the gate declining to.
UNIFORM_TITLE = "uniform title"         # SBN said so. Needs no corroboration.
TITLE_MATCH = "title match"             # >= IDENTIFYING_TITLE_MATCH, work's titles
ISBN_MATCH = "isbn"
WIKIDATA_TITLE = "wikidata title"
WORK_KEY = "work key"                   # Open Library's own work membership
REFUSED = "refused"                     # kept, shown in the loose-match band


@dataclass(frozen=True)
class Provenance:
    """Where a record came from, how it was reached, and what admitted it.

    `score` is the number behind `evidence` where there is one — the title
    similarity, in particular, which the loose-match band shows per row so a
    reader can see how near a refusal came. A refused record keeps its
    provenance and is stored like any other: it is filtered out of the default
    view, never dropped, because "what was refused" is a disclosure
    (decision N) and because a dropped record cannot be audited.
    """
    source: str
    route: str
    evidence: str
    score: float | None = None
    # The Open Library work a `DUPLICATE_WORK` record was opened through, so a
    # row can say which record the reader added it from. None everywhere else.
    via: str | None = None

    @property
    def refused(self) -> bool:
        return self.evidence == REFUSED


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------

@dataclass
class Holding:
    """One library that holds a copy (SBN `localizzazioni`)."""
    library: str = ""
    city: str = ""
    isil: str = ""


@dataclass
class Record:
    """One catalogue row: one printing, as one source has it.

    The field names are the ones `catalog/`'s parsers return, so a producer
    writes `Record(**parse_record(raw), provenance=p)` and no source knowledge
    reaches this layer. `language` is `langs.UNKNOWN` until something states it —
    never inferred from the country of publication, and never folded into
    English because it is blank.
    """
    source: str
    id: str | None
    provenance: Provenance
    title: str = ""
    publisher: str | None = None
    year: str | None = None
    language: str = langs.UNKNOWN
    isbn: str | None = None
    isbns_raw: list = field(default_factory=list)   # every ISBN string on the row
    url: str | None = None
    series: str | None = None
    physical: str | None = None
    dewey: str | None = None
    dewey_all: list = field(default_factory=list)
    medium: str | None = None
    cover_url: str | None = None
    authors: list = field(default_factory=list)
    translators: list = field(default_factory=list)
    evidence: list = field(default_factory=list)      # translation evidence, free text
    holdings: list = field(default_factory=list)
    # The publisher statement as its source wrote it, already split into names,
    # and the places named beside them. Splitting is the source's own convention
    # — ISBD's 'Place : Publisher ; Place : Publisher' against Open Library's
    # list — so `catalog/` does it and `core/fold.py` decides what counts as the
    # same publisher.
    publisher_names: list = field(default_factory=list)
    places: list = field(default_factory=list)
    # The date as the catalogue wrote it, from its first year on (`1386 [2007]`),
    # and the `dataf[]` values SBN's index files the record under — None until
    # asked (decision AY). `year` is the catalogue's first year; `core.dates`
    # decides which year the row means, and the view reads only that.
    date: str | None = None
    date_indexed: list | None = None
    date_check_failed: bool = False
    # Written by `core.dates.settled` on the view's copy, never by a producer:
    # why the year was not taken at face value, and every year a row whose year
    # is unsure shows instead of one.
    year_note: str | None = None
    years_shown: list = field(default_factory=list)

    @property
    def key(self) -> tuple:
        """`(source, id)`. Two rows with this key are one row seen twice."""
        return (self.source, self.id)

    def with_provenance(self, provenance: Provenance) -> "Record":
        return replace(self, provenance=provenance)


# ---------------------------------------------------------------------------
# Edition
# ---------------------------------------------------------------------------

@dataclass
class Edition:
    """What a reader can buy: every record that shares one ISBN.

    Keyed on the ISBN; a record with none is its own edition, keyed on the
    record, because 295 of 778 SBN full records (38%) carry no ISBN and guessing
    would merge a third of them wrongly.

    **An ISBN names an edition, not a printing.** One SBN ISBN spans up to 31
    records over 41 years — Adelphi's *L'insostenibile leggerezza dell'essere*
    `9788845906862`, 1985-2026. So `printings` lists the years and the row does
    not hide them.

    Every field is derived from `records`, in a fixed order, so two identical
    stores derive identical editions.
    """
    id: str
    isbn: str | None
    records: list

    # -- identity of the row ------------------------------------------------

    @property
    def sources(self) -> list:
        return sorted({r.source for r in self.records})

    @property
    def refused(self) -> bool:
        """True only when *every* record behind the row was refused.

        One admitted record is enough to admit the edition: the others are the
        same book, and the ISBN said so.
        """
        return bool(self.records) and all(r.provenance.refused for r in self.records)

    # -- the fields a row shows --------------------------------------------

    @property
    def language(self) -> str:
        """The first stated language, records in order; UNKNOWN when none is.

        A language filter must not silently drop an edition whose language is
        simply not recorded — Open Library records it for 80.8% of editions.
        """
        for r in self.records:
            if r.language != langs.UNKNOWN:
                return r.language
        return langs.UNKNOWN

    @property
    def printings(self) -> list:
        """Every distinct year on the records behind this row, earliest first."""
        return sorted({r.year for r in self.records if r.year})

    @property
    def year(self) -> str | None:
        """The earliest printing. The others are on `printings`, not lost."""
        years = self.printings
        return years[0] if years else None

    @property
    def latest(self) -> str | None:
        """The most recent printing — what a newest-first list sorts on.

        Adelphi's `9788845906862` was first printed in 1985 and again in 2026;
        sorted on its first printing it would sit at the bottom of a list that
        promises the newest first (decision AG).
        """
        years = self.printings
        return years[-1] if years else None

    @property
    def title(self) -> str:
        # A string field, so it is "" and not None when no record carried one:
        # every text helper downstream takes a str, and a catalogue row with no
        # title at all is rare but real.
        return self._first("title") or ""

    @property
    def publisher(self) -> str | None:
        return self._first("publisher")

    @property
    def series(self) -> str | None:
        return self._first("series")

    @property
    def medium(self) -> str | None:
        """What kind of thing this is — 'testo', 'registrazione sonora…'.

        SBN's own record-type statement, carried by every listing row, not an
        inference. An audiobook is still an edition of the text, so this labels
        the row rather than filtering it.
        """
        return self._first("medium")

    @property
    def physical(self) -> str | None:
        return self._first("physical")

    @property
    def url(self) -> str | None:
        return self._first("url")

    @property
    def cover_url(self) -> str | None:
        return self._first("cover_url")

    @property
    def authors(self) -> list:
        return self._union("authors")

    @property
    def translators(self) -> list:
        return self._union("translators")

    @property
    def evidence(self) -> list:
        return self._union("evidence")

    @property
    def holdings(self) -> list:
        out, seen = [], set()
        for r in self.records:
            for h in r.holdings:
                key = (h.library, h.city, h.isil)
                if key not in seen:
                    seen.add(key)
                    out.append(h)
        return out

    def _first(self, name: str):
        """The first record that has this field. Order is the store's order, so
        the answer does not depend on set iteration."""
        for r in self.records:
            value = getattr(r, name)
            if value:
                return value
        return None

    def _union(self, name: str) -> list:
        out, seen = [], set()
        for r in self.records:
            for value in getattr(r, name) or []:
                if value not in seen:
                    seen.add(value)
                    out.append(value)
        return out


# ---------------------------------------------------------------------------
# Work
# ---------------------------------------------------------------------------

@dataclass
class Work:
    """The identity, resolved once per lookup and never re-derived.

    **Nothing after identity uses what the user typed** (build rule 11), so
    the typed title is deliberately *not* a field here: `titles()` is
    what the gates match against, and it holds only titles a catalogue stated.
    The one exception in the whole design is the recovery route, which uses the
    typed title to find candidates and then gates them on these titles.

    **No original where none is stated** (rule 8). `original_title`,
    `original_language` and `original_year` stay None unless a source said so,
    and `stated_by` names which one. A refused Wikidata candidate, a weak W or an
    impossible year means no original — not a guess.
    """
    # SBN: the uniform title (a normalised search key — never displayed) and how
    # far the guard would go in believing it.
    sbn_work: str | None = None
    sbn_work_tier: str | None = None
    sbn_work_via_second_signal: bool = False
    # Further uniform titles SBN files the same work under, each accepted by
    # the guard on its own spelling (Step 14: *bain el-qasrain.* and *bayn
    # al-qasrayn* are one Mahfouz novel). Listed in S2 beside W; empty unless
    # the lookup was handed spellings to try.
    sbn_other_works: list = field(default_factory=list)
    # SBN's name authority id: one per person for every Latin form (A7), and
    # the heading forms it is filed under. The headings are for **matching
    # only and are never displayed**: SBN writes `Maḥfūẓ, Naǧīb` where the
    # reader typed `Naguib Mahfouz`, and without that form on hand every one of
    # the ten Mahfouz rows looks credited to somebody else.
    author_id: str | None = None
    author_headings: list = field(default_factory=list)
    # Further name authorities the same person is filed under in other
    # spellings, each resolved by `pick_authority` for its own spelling. Swept
    # in S3 beside `author_id`; empty unless the reader ticked the author
    # switch (decision AV). Four for Mahfouz, one of them 531 records.
    author_other_ids: list = field(default_factory=list)

    qid: str | None = None
    ol_keys: list = field(default_factory=list)
    ol_duplicate_keys: list = field(default_factory=list)
    # Open Library's own title for the main work. A catalogue's statement of
    # what the work is called, in the spelling the uniform title cannot carry,
    # and one of the three title sets U2 scored the gate against — so it is
    # kept rather than left in the evidence where the gate could not reach it.
    ol_title: str | None = None

    titles_by_lang: dict = field(default_factory=dict)
    original_title: str | None = None
    original_language: str | None = None
    original_year: str | None = None
    # What the source stated, however coarse: `(year, precision)`, the year
    # negative BCE. `original_year` is set from it only when it is a year.
    original_date: tuple | None = None
    authors: list = field(default_factory=list)

    stated_by: str = ""        # which source stated the original
    basis: str = ""            # and on what evidence, for the UI to show

    def titles(self) -> list:
        """Every distinct title the work is known by, for the gates to match on.

        Deduplicated case-insensitively, first spelling kept, in a fixed order:
        the original, then the language titles by language code, then Open
        Library's title for the work. The uniform title is **not** here — it is normalised, accent-stripped and sometimes
        punctuated (`cien anos des soledad. -`), a search key and not a title.

        Step 2 measured what this list costs when it is thin: the gate admits
        266 of 288 same-work records not linked to W at 0.6, and the lever is
        how many languages this list covers, not the threshold.
        """
        seen, out = set(), []
        ordered = [self.original_title]
        ordered += [self.titles_by_lang[code] for code in sorted(self.titles_by_lang)]
        ordered.append(self.ol_title)
        for title in ordered:
            if title and title.lower() not in seen:
                seen.add(title.lower())
                out.append(title)
        return out

    @property
    def identified(self) -> bool:
        """Did anything at all identify this work?

        A book with no identity is **normal, not an error state** (A1: no source
        reaches one identity for every entry title — SBN 22 of 37 books,
        Wikidata 14, Open Library 13). The lookup still has to answer.
        """
        return bool(self.sbn_work or self.qid or self.ol_keys)
