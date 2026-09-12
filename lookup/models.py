"""Data model.

The original Edition was flat and lost most of what a full SBN record carries
(translator, holdings, series, evidence). It is extended here rather than
replaced, so the CLI output shape stays recognisable.
"""

from dataclasses import dataclass, field, asdict

# Edition.role
ORIGINAL = "original"
TRANSLATION = "translation"
REPRINT = "reprint"

# Edition.confidence, and the verdict's
HIGH, MEDIUM, LOW, UNCONFIRMED = "high", "medium", "low", "unconfirmed"


@dataclass
class Holding:
    """One library that holds a copy (SBN localizzazioni)."""
    library: str = ""
    city: str = ""
    isil: str = ""


@dataclass
class BuyLink:
    store: str
    url: str
    kind: str = "new"  # new | used


@dataclass
class Edition:
    source: str
    title: str
    publisher: str | None = None
    year: str | None = None
    language: str = "unknown"
    role: str = REPRINT
    isbn: str | None = None
    url: str | None = None
    sbn_bid: str | None = None
    series: str | None = None
    physical: str | None = None
    dewey: str | None = None
    medium: str | None = None          # SBN 'tipo': print, sound recording, ...
    cover_url: str | None = None
    authors: list = field(default_factory=list)
    translators: list = field(default_factory=list)
    evidence: list = field(default_factory=list)     # translation evidence only
    match_reasons: list = field(default_factory=list)  # why we think this is the same work
    holdings: list = field(default_factory=list)
    buy_links: list = field(default_factory=list)
    confidence: str = UNCONFIRMED
    score: float = 0.0
    # Author-only searches list works rather than single editions, so a row
    # summarises several editions instead of describing one.
    work_group: str = ""               # which distinct book this belongs to
    edition_count: int | None = None
    available_languages: list = field(default_factory=list)

    def dedupe_keys(self):
        """Keys this edition may be merged on, most to least authoritative."""
        keys = []
        if self.isbn:
            keys.append(("isbn", self.isbn.replace("-", "").strip()))
        if self.sbn_bid:
            keys.append(("bid", self.sbn_bid))
        from .matching import normalize
        sig = " ".join(sorted(normalize(self.title)))
        if sig:
            keys.append(("sig", f"{sig}|{(self.publisher or '').lower()[:12]}|{self.year or ''}"))
        return keys


@dataclass
class TitleCluster:
    """What Wikidata knows about the work, across languages.

    This is the only source of original language and year, which is what makes
    an Italian-first lookup answerable at all.
    """
    qid: str | None = None
    titles_by_lang: dict = field(default_factory=dict)
    original_title: str | None = None
    original_language: str | None = None
    original_year: str | None = None
    author_names: list = field(default_factory=list)
    authors: list = field(default_factory=list)
    translators: list = field(default_factory=list)
    url: str | None = None
    # "wikidata" when the work item said so; "inferred" when the original was
    # reconstructed from a translation's authors and Dewey class, which is a
    # weaker claim and is labelled as such.
    source: str = "wikidata"
    basis: str = ""

    def variants(self):
        """Distinct title strings worth querying catalogues with."""
        seen, out = set(), []
        for t in [self.original_title, *self.titles_by_lang.values()]:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out


@dataclass
class LanguageSpan:
    """How long a work has been in print in one language."""
    code: str = ""
    name: str = ""
    editions: int = 0
    first_year: int | None = None
    last_year: int | None = None
    is_original: bool = False


@dataclass
class Overview:
    """What the editions add up to: a publication history, not a verdict.

    The tool used to lead with "is there an Italian edition?", which answers one
    narrow question and buries the rest. What the editions actually tell you is
    when the work first appeared, in which language, and when each translation
    followed — so that is what goes at the top.
    """
    title: str = ""
    authors: list = field(default_factory=list)
    original_language: str | None = None
    original_language_name: str | None = None
    original_year: int | None = None
    first_year_seen: int | None = None
    total_editions: int = 0
    spans: list = field(default_factory=list)
    found: bool = False
    original_inferred: bool = False
    original_basis: str = ""


@dataclass
class Report:
    mode: str = "work"                   # work | author
    query_title: str | None = None
    query_author: str | None = None
    asked_language: str = "unknown"      # language the user's title was in
    cluster: TitleCluster = field(default_factory=TitleCluster)
    overview: Overview = field(default_factory=Overview)
    editions_by_language: dict = field(default_factory=dict)
    choices: list = field(default_factory=list)   # distinct books sharing the title
    facets: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)   # name -> ok | skipped | error: …
    notes: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
