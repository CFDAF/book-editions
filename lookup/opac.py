"""SBN's OPAC API — the uniform-title bridge.

The mobile gateway in `sbn.py` is what the rest of this project is built on, and
it omits the one field that answers the cross-language question outright: SBN's
UNIMARC **uniform-title authority**, shown in the OPAC as *Titolo di opera*. Six
full records were once checked for it, found nothing, and the project concluded
that no free catalogue records the link between a translation and its original.
That conclusion was drawn from a hole in one API. SBN records the link; a
different SBN endpoint returns it.

    POST /o/opac-api/titles-search-full-post   search + facets   <- this module

`data.facets` carries `titolo_uniformef[]`, the uniform titles of everything in
the result set with counts. Searched with a title **and** an author, the top
value by count is the work's own title — the original, when the book is a
translation:

    Più brillante del sole     + Eshun    -> more brilliant than the sun
    Cent'anni di solitudine    + Marquez  -> cien anos de soledad
    Rumori                     + Attali   -> bruits : essai sur l'economie…

That is a cataloguer's explicit statement, not an inference from Dewey classes,
which makes it the most precise bridge available — and it works where the other
three are blind. `Più brillante del sole` shares no ISBN with its English
original, scores 0.0 on cross-language title similarity, and carries no Dewey
class at all, so nothing else could ever have connected the two.

Three things this module exists to contain:

1. **The author is not optional.** Bare 'Rumori' is 880 records whose top facet
   value is Russolo's 'arte dei rumori'; Attali is not in the top five. Bare
   'The Essential Knuth' confidently returns 'essential mathematics for economic
   analysis', a different book. With an author both are correct, so a call
   without one returns nothing rather than a plausible wrong answer.

2. **Facet labels are search keys, not titles.** They are lowercased and
   stripped of accents, and some carry trailing punctuation ('cien anos des
   soledad. -'). Good enough to search Open Library with; never display one.

3. **Facet values include adaptations.** Films, TV series and companion volumes
   appear alongside the work ('nome della rosa <serie tv ; 2018>'). Those are
   filtered out before the top value is taken.

A uniform title is the *work's* title, which is the original title — but for a
work that is Italian to begin with it is therefore Italian ('Il nome della rosa'
-> 'nome della rosa'). That is a correct answer meaning "not a translation", not
a failure, and callers must not assume the result is foreign.
"""

import re

from .net import SourceError, cached_post_json

SEARCH = "https://opac.sbn.it/o/opac-api/titles-search-full-post"

# The OPAC's parameter grammar is item:<code>:<Name>:<operator>=value. Only
# these are used, and the codes are not guessable: 1004 and 1005 are *not* the
# author field and answer with something that is not JSON at all.
ANY = "item:1016:Any:@or@"
AUTHOR = "item:1003:Autore:@and@"
WORK = "titolo_uniformef[]"

FACET = "titolo_uniformef[]"

# '<film ; 1986>', '<serie tv ; 2018>' — an adaptation is linked to the work but
# is not an edition of it.
ADAPTATION = re.compile(r"<\s*(film|serie tv|video|dvd|audiolibro)\b", re.I)

# Results arrive as 'ITICCUVEA1284105'; the rest of the project speaks short BIDs.
BID = re.compile(r"^(?:ITICCU)?([A-Z]{2,4}[0-9A-Z]{6,12})$")

PAGE_SIZE = 20
# SBN links 89 records to the work behind 'Cent'anni di solitudine', so three
# pages silently lost a third of the one source here that is never wrong.
MAX_PAGES = 12         # 240 records; no work in the corpus comes near it


class Work:
    """A work as SBN's authority file has it, with the records linked to it."""

    def __init__(self, title: str, records: list, count: int, total: int):
        self.title = title          # normalised uniform title (a search key)
        self.records = records      # [(short bid, title as catalogued)]
        self.count = count          # records the facet attributes to this work
        self.total = total          # records the unfiltered search matched

    def __repr__(self):
        return f"<Work {self.title!r} {self.count}/{self.total} {len(self.records)} records>"


def _post(body: dict, tally=None):
    try:
        payload = cached_post_json(SEARCH, body)
    except SourceError:
        raise
    data = (payload or {}).get("data")
    if not isinstance(data, dict):
        raise SourceError(f"{SEARCH}: no data object in the response")
    return data


def _rows(data) -> list:
    """[(short bid, catalogued title)] from a results page."""
    out = []
    for row in data.get("results") or []:
        m = BID.match(str(row.get("id") or "").strip())
        if not m:
            continue
        title = row.get("title")
        if isinstance(title, dict):
            title = title.get("info") or title.get("text") or ""
        out.append((m.group(1), str(title or "").strip()))
    return out


def work_for(title: str, author: str, tally=None) -> Work | None:
    """The work SBN files this title under, with every record linked to it.

    Two requests: one to read the facet, one to pull the records the facet
    attributes to the winning work. Returns None whenever the answer would be a
    guess — no author, no facet, nothing but adaptations.
    """
    if not (title and author):
        return None

    base = {"core": "sbn", ANY: title, AUTHOR: author, "page": "1"}
    try:
        data = _post(base, tally)
    except SourceError as exc:
        if tally is not None:
            tally.note("SBN", exc)
        return None

    total = data.get("total") or 0
    facet = next((f for f in data.get("facets") or []
                  if f.get("name") == FACET), None)
    items = [i for i in (facet or {}).get("items") or []
             if i.get("value") and not ADAPTATION.search(str(i.get("label") or ""))]
    if not items:
        return None
    top = max(items, key=lambda i: i.get("results") or 0)

    records, page = [], 1
    while page <= MAX_PAGES:
        try:
            data = _post({**base, WORK: top["value"], "page": str(page)}, tally)
        except SourceError as exc:
            if tally is not None:
                tally.note("SBN", exc)
            break
        rows = _rows(data)
        records += rows
        if len(rows) < PAGE_SIZE or len(records) >= (data.get("total") or 0):
            break
        page += 1

    if not records:
        return None
    return Work(str(top["value"]).strip(), records,
                int(top.get("results") or 0), int(total))
