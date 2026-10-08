"""Wikidata items and Wikipedia sitelinks: labels, P1476, P407, P577.

The bridge that works in both directions, through the plain labels and sitelinks
of the work item rather than through `P629`/`P747`, whose coverage is too thin to
rely on:

    One Hundred Years of Solitude -> Q178869 -> labels.it  Cent'anni di solitudine
    Cent'anni di solitudine       -> Q178869 -> labels.en  One Hundred Years of Solitude
                                              P1476       Cien anos de soledad (es)
                                              P407        Spanish   <- original language
                                              P577        1967      <- original year

P407 and P577 are the only place any free source states what language a work was
written in and when, which is what makes an Italian-first lookup answerable at
all. Two things bound it, and both are measured:

- **Recall is bounded by Wikipedia notability.** Attali's *Bruits* has sitelinks
  for en/es/fa/zh and no Italian label at all, so a miss is expected and must
  fall through to another route rather than fail.
- **The item's *own* original is wrong often enough to matter**: 3 of 26 accepted
  items (A5), which is why the header states the original and the earliest
  edition found side by side and infers nothing.

**Prefer `labels` over sitelink titles.** Sitelinks carry disambiguators —
`itwiki` for `Q208460` is `1984 (romanzo)` where the label is `1984` — and a
disambiguator in a search key costs a title match.

`titles` and `ids` take up to 50 values in one request; validating one item at a
time cost ~38 s per cold lookup.

Fetch and parse only. Whether an item may be believed is the title test, and it
is `core/identity.py`'s.
"""

import re

from . import langs
from .http import cached_get_json

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Wikis consulted, in order. Italian first: an Italian-first lookup is the
# direction the old script could not express, so it gets first refusal.
WIKIS = ("it", "en")
# Label languages asked for. The set the benchmark's Step 4 rule was measured on.
LABEL_LANGS = "it|en|fr|es|de|pt|la"
BATCH = 40                  # ids per wbgetentities call; the API allows 50

# An edition, translation or printing of a work. It is a written work and it is
# not the work: what it states is its own (see `is_edition`).
EDITION_CLASS = "Q3331189"

# P31 values that mark an item as a written work. Checked to avoid resolving a
# title to an unrelated article (a person, a film, a scholarly paper).
WORK_CLASSES = {
    "Q571",      # book
    "Q7725634",  # literary work
    "Q47461344", # written work
    "Q234460",   # text
    "Q8261",     # novel
    "Q49084",    # short story
    "Q1279564",  # short story collection
    "Q5185279",  # poem
    "Q35760",    # essay
    "Q17537576", # creative work
    "Q386724",   # work
    EDITION_CLASS,  # version, edition or translation
    "Q1667921",  # novel series
    "Q13136",    # reference work
    "Q2382443",  # essay collection
}


def strip_disambiguator(title: str) -> str:
    """Drop a Wikipedia disambiguator: '1984 (romanzo)' -> '1984'.

    Wikipedia's own convention for telling two articles of one name apart, so
    this lives here rather than with the text helpers: `itwiki` for `Q208460` is
    `1984 (romanzo)` where the label is `1984`, and the parenthesis costs a title
    match against a catalogue that has never heard of it.
    """
    return re.sub(r"\s*\([^)]*\)\s*$", "", title or "").strip()


def payload_error(data) -> str | None:
    """The reason to reject a body, or None. Given to the cache, not the caller.

    **Wikidata and Wikipedia fail exactly the way SBN does**: HTTP 200 with a
    top-level `error` object — `no-such-entity`, `badvalue` — verified
    2026-09-18 with a control. Being valid JSON it would be *cached for 24 h* and
    read as "no entities": no `SourceError`, no ledger entry, no note, on the
    35% of request time that goes to Wikimedia. That is `CLAUDE.md` rule 5's
    failure shape exactly.

    It was latent rather than live when found — 0 such bodies in `.cache/`
    (4,234) or the regression sweep's cache (10,044) — and Step 3 left it alone
    because its brief named two callers. This is the step that writes this module, so the
    validator arrives with it.
    """
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        if isinstance(err, dict):
            return str(err.get("info") or err.get("code") or err)
        return str(err)
    return None


def _get(url: str, params: dict):
    return cached_get_json(url, {**params, "format": "json"}, validate=payload_error)


# ---------------------------------------------------------------------------
# Wikipedia: a title -> an item
# ---------------------------------------------------------------------------

def page_to_qid(wiki: str, title: str) -> str | None:
    """Exact page, redirects followed, to a Wikidata item."""
    data = _get(f"https://{wiki}.wikipedia.org/w/api.php",
                {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                 "redirects": "1", "titles": title})
    for page in (data.get("query", {}).get("pages") or {}).values():
        if "missing" in page:
            continue
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None


def titles_to_qids(wiki: str, titles: list) -> dict:
    """Many page titles to items in one call. `{title asked -> qid}`.

    The walk back through `normalized` and `redirects` matters: the API answers
    under the title it ended up at, and a caller that asked for `1984` and got an
    answer keyed `Nineteen Eighty-Four` would not recognise it.
    """
    if not titles:
        return {}
    data = _get(f"https://{wiki}.wikipedia.org/w/api.php",
                {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                 "redirects": "1", "titles": "|".join(titles)})
    query = data.get("query") or {}
    alias = {}
    for hop in ("normalized", "redirects"):
        for m in query.get(hop, []) or []:
            alias[m["to"]] = m["from"]
    out = {}
    for page in (query.get("pages") or {}).values():
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if not qid:
            continue
        title = page.get("title")
        while title in alias:          # back to the title originally requested
            title = alias[title]
        out[title] = qid
    return out


def search_pages(wiki: str, query: str, limit: int = 4) -> list:
    data = _get(f"https://{wiki}.wikipedia.org/w/api.php",
                {"action": "query", "list": "search", "srsearch": query,
                 "srlimit": limit})
    return [r["title"] for r in data.get("query", {}).get("search", [])]


# ---------------------------------------------------------------------------
# Wikidata: items
# ---------------------------------------------------------------------------

def entities(qids: list, props: str = "labels|sitelinks|claims",
             languages: str = LABEL_LANGS) -> dict:
    if not qids:
        return {}
    data = _get(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(qids[:BATCH]),
                               "props": props, "languages": languages})
    return data.get("entities") or {}


def labels(qids: list, order=("en", "it", "fr", "es", "de")) -> dict:
    """QID -> one readable label, batched into one request.

    Used for author and translator names, where any spelling will do for
    matching; the display spelling comes from wherever kept its accents.
    """
    out = {}
    for qid, ent in entities(qids, "labels", "|".join(order)).items():
        got = ent.get("labels") or {}
        for lang in order:
            if lang in got:
                out[qid] = got[lang]["value"]
                break
    return out


def names(qids: list, languages: str = LABEL_LANGS) -> dict:
    """QID -> every label it carries in `languages`, in that order, one request.

    What an author check reads. One label is not enough: Q991's English label is
    *Fyodor Dostoyevsky* and its Italian one *Fëdor Dostoevskij*, which is the
    name an Italian reader types and the only one of the two it shares a token
    with (Step 15B, N04).
    """
    order = languages.split("|")
    out = {}
    for qid, ent in entities(qids, "labels", languages).items():
        got = ent.get("labels") or {}
        out[qid] = list(dict.fromkeys(got[lang]["value"] for lang in order if lang in got))
    return out


# ---------------------------------------------------------------------------
# A person, and the works that name them (Step 14)
# ---------------------------------------------------------------------------

HUMAN = "Q5"
SEARCH_PAGE = 500           # `srlimit`'s maximum for an anonymous client


def people(name: str, limit: int = 5) -> list:
    """Items named `name` that are people: `[{qid, names, born}]`, in the
    search's own order.

    `names` is every label and alias the item carries, in any script — the
    caller decides which of them may be sent anywhere. Which item *is* the
    person asked for is a judgement, and it is not made here.
    """
    if not name:
        return []
    hits = _get(WIKIDATA_API, {"action": "wbsearchentities", "search": name,
                               "language": "en", "type": "item", "limit": limit})
    qids = [h["id"] for h in hits.get("search") or [] if h.get("id")]
    ents = entities(qids, "labels|aliases|claims") if qids else {}
    out = []
    for qid in qids:
        ent = ents.get(qid) or {}
        claims = ent.get("claims") or {}
        if HUMAN not in claim_ids(claims, "P31"):
            continue
        names = [v["value"] for _, v in sorted((ent.get("labels") or {}).items())]
        for _, values in sorted((ent.get("aliases") or {}).items()):
            names += [v["value"] for v in values]
        born = claim_first(claims, "P569")
        year = str(born.get("time") or "").lstrip("+").split("-", 1)[0] \
            if isinstance(born, dict) else ""
        out.append({"qid": qid, "names": list(dict.fromkeys(names)),
                    "born": int(year) if year.isdigit() else None})
    return out


def works_by(qid: str, max_pages: int = 20) -> dict:
    """Every item whose P50 is `qid`, through wikidata.org's own search.

    `{"qids", "total"}` — `haswbstatement:` on the API this module already
    calls, not a new endpoint, paged by `sroffset`. `total` is the search's own
    `totalhits`, so a read that stopped short is a number the caller can state.
    The items are unvalidated: editions, articles and adaptations carry P50 too.
    """
    qids, total, offset = [], 0, 0
    for _ in range(max_pages):
        data = _get(WIKIDATA_API, {"action": "query", "list": "search",
                                   "srsearch": f"haswbstatement:P50={qid}",
                                   "srlimit": SEARCH_PAGE, "sroffset": offset})
        query = data.get("query") or {}
        total = (query.get("searchinfo") or {}).get("totalhits") or 0
        qids += [h["title"] for h in query.get("search") or []]
        offset = (data.get("continue") or {}).get("sroffset")
        if not offset:
            break
    return {"qids": qids, "total": total}


def work_classes(claims: dict) -> list:
    """The item's P31 values, as the caller needs them to judge it."""
    return claim_ids(claims, "P31")


# ---------------------------------------------------------------------------
# Reading claims
# ---------------------------------------------------------------------------

def claim_ids(claims: dict, prop: str) -> list:
    out = []
    for c in claims.get(prop, []):
        val = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(val, dict) and val.get("id"):
            out.append(val["id"])
    return out


def claim_first(claims: dict, prop: str):
    for c in claims.get(prop, []):
        val = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if val is not None:
            return val
    return None


def is_edition(claims: dict) -> bool:
    """Is this item an *edition* of a work rather than the work itself?

    `Q3331189` is in `WORK_CLASSES` because an edition is a written work — but
    what it states is the edition's. `Q138528911` carries the English label
    *The Burnout Society*, `P1476` "La sociedad del cansancio" (es), `P407`
    Spanish and `P577` 2024: the 2024 Spanish translation of a book first
    published in German in 2010, and no `P629` back to the work to say so.
    Believed as a work it makes the header state a wrong original, which is the
    one thing the header may never do.

    Measured over the corpus before the rule was added: **1 accepted item of
    the 63 entries that accept one**, and that one is the only stated original
    in 94 entries that disagrees with hand-checked ground truth **M**. It can
    only refuse, never admit.
    """
    return EDITION_CLASS in set(claim_ids(claims, "P31"))


def is_written_work(claims: dict) -> bool:
    """P31 says so, or it has both an author and a publication date.

    The second half is not a loosening: an item with an unmodelled P31 that
    carries P50 *and* P577 is a work, and an article or a person will not have
    both.
    """
    if set(claim_ids(claims, "P31")) & WORK_CLASSES:
        return True
    return bool(claim_ids(claims, "P50")) and claim_first(claims, "P577")


# ---------------------------------------------------------------------------
# Parsing one item
# ---------------------------------------------------------------------------

# Sitelink keys that end in `wiki` and are not a Wikipedia. Every other
# project's key ends in its own name (`enwikisource`, `cswikiquote`).
NOT_WIKIPEDIA = frozenset({"abstractwiki", "commonswiki", "foundationwiki", "incubatorwiki",
                           "mediawikiwiki", "metawiki", "outreachwiki", "sourceswiki",
                           "specieswiki", "wikidatawiki", "wikifunctionswiki",
                           "wikimaniawiki"})
# A page in a namespace: `Category:The Idiot (Dostoyevsky)`, `Dílo:Idiot`. No
# space after the colon, which a subtitle has.
_NAMESPACED = re.compile(r"^[^\s:]+:\S")


def item_forms(entity: dict, names_only: bool = False) -> list:
    """Every name this item goes by, for the title test to match against.

    Labels, then sitelink titles with the disambiguator stripped, then P1476.
    In that order and deduplicated, so the same string is not weighed twice.

    This is the list the Step 4 rule was measured on: it **never accepted a wrong
    item** in 91 entries and rejected all 6 wrong items today's resolver returns.

    `names_only` leaves out another project's page in a namespace — Commons'
    `Category:The Idiot (Dostoyevsky)`, cs.wikiquote's `Dílo:Idiot` — which is
    a page about the work, not its name: `core_title` cuts it at the colon, so
    every one is the same title (decision AZ). A Wikipedia title is kept
    whatever it holds (`スパイダーマン:フレンドリー・ネイバーフッド` is a
    title), and so is another project's plain one (ru.wikisource's `Идиот
    (Достоевский)`). Author mode asks for it; the title test keeps the list it
    was measured on.
    """
    seen, out = set(), []
    for value in _label_values(entity):
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    for title in _sitelink_titles(entity, names_only):
        stripped = strip_disambiguator(title)
        if stripped and stripped not in seen:
            seen.add(stripped)
            out.append(stripped)
    p1476 = claim_first(entity.get("claims") or {}, "P1476") or {}
    text = p1476.get("text") if isinstance(p1476, dict) else None
    if text and text not in seen:
        out.append(text)
    return out


def _label_values(entity: dict) -> list:
    return [v["value"] for _, v in sorted((entity.get("labels") or {}).items())]


def _sitelink_titles(entity: dict, names_only: bool = False) -> list:
    return [v["title"] for site, v in sorted((entity.get("sitelinks") or {}).items())
            if not (names_only and _NAMESPACED.match(v["title"])
                    and (not site.endswith("wiki") or site in NOT_WIKIPEDIA))]


def titles_by_language(entity: dict, wikis=("it", "en", "fr", "es", "de")) -> dict:
    """`{iso 639-2/B code -> title}` from labels, falling back to sitelinks."""
    label_map = {k: v["value"] for k, v in (entity.get("labels") or {}).items()}
    sitelinks = {k: v["title"] for k, v in (entity.get("sitelinks") or {}).items()}
    out = {}
    for two in wikis:
        code = langs.from_two_letter(two)
        if two in label_map:
            out[code] = label_map[two]
        elif f"{two}wiki" in sitelinks:
            out[code] = strip_disambiguator(sitelinks[f"{two}wiki"])
    return out


def original_language(entity: dict) -> str:
    """P407, falling back to the language P1476 is stated in. UNKNOWN otherwise."""
    claims = entity.get("claims") or {}
    code = langs.from_wikidata((claim_ids(claims, "P407") or [None])[0])
    if code != langs.UNKNOWN:
        return code
    p1476 = claim_first(claims, "P1476") or {}
    if isinstance(p1476, dict) and p1476.get("language"):
        return langs.from_two_letter(p1476["language"])
    return langs.UNKNOWN


def original_date(entity: dict) -> tuple | None:
    """P577 as `(year, precision)`: the earliest year stated. None when none is.

    Wikidata's own date is wrong often enough that nothing may be inferred from
    it — a Dutch translation dated 1912, CreateSpace reprints dated 1866 and
    1825 (A5). It is reported as stated, beside the earliest edition actually
    found, and never used to conclude that one differs from the other.

    A BCE year is negative. `precision` is Wikidata's: 9 a year, 8 a decade, 7
    a century, and `+1838` at 7 means the 19th century, not 1838 (*Le livre
    des rois*). Several values are several printings or parts — *Don Quixote*
    1605 and 1615 — so the earliest is the one that says when it first
    appeared; the first listed was not, once in 461 works (decision AY's year probe).
    """
    dates = []
    for c in (entity.get("claims") or {}).get("P577", []):
        value = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if c.get("rank") == "deprecated" or not isinstance(value, dict):
            continue
        m = re.match(r"([+-])(\d+)-", str(value.get("time") or ""))
        if m and int(m.group(2)):
            year = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
            dates.append((year, int(value.get("precision") or 9)))
    return min(dates, key=lambda d: (d[0], -d[1])) if dates else None


def original_year(entity: dict) -> str | None:
    """P577's year, as a string, when Wikidata states one to the year.

    None for a decade, a century or a BCE date: every reader of this treats it
    as a year a printing can be compared with, and `+1838` at century
    precision is not one. `original_date` keeps what those state.
    """
    date = original_date(entity)
    if date and date[1] >= 9 and date[0] > 0:
        return str(date[0])
    return None
