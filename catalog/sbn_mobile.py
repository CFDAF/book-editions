"""SBN's undocumented mobile-app gateway: full records, ISBNs, holdings.

    search.json                brief records + facets
    full.json?bid=<SHORTBID>   the full record — `bid` is the only accepted
                               parameter name; `id`, `cid`,
                               `codiceIdentificativo` are all rejected

**This is not the SBN API that answers the cross-language question.** That one
is `catalog/sbn_opac.py`, a different application on the same host, and the two
have near-identical names for unrelated things. Believing there was only this
one is how "no free catalogue records the link between a translation and its
original" became a recorded fact and was wrong (`docs/DECISIONS.md` pitfall 1). What this
gateway has and the OPAC does not is the *full record*: `linguaPubblicazione`,
`classificazioneDewey`, `nomi`, `note`, `numeri`, `collezione`,
`descrizioneFisica` and `localizzazioni`. The brief record carries **no
language**, which is why a candidate costs a second request before anything can
be said about it.

Four traps this module exists to contain (`docs/sbn-api.md`):

1. **Unknown parameters are silently ignored** and the *unfiltered* result set
   comes back — a wrong answer, not an error. Only `PARAMS` is ever sent.
2. **A slash in a free-text value fails with HTTP 200.** Solr reads it as the
   opening of a regex literal and an unterminated one is a parse error, so the
   body is `{"error": {...}}` and valid JSON. `payload_error` is what the cache
   is given so it refuses to store one (Step 3, U8). A bogus BID is *not* this
   shape: `full.json` answers it with a skeleton record (F13), a real body.
3. **Facets come back with counts but cannot be sent back as filters.** Every
   syntax was probed and ignored. Filtering here is the caller's job — the
   OPAC's facets *do* filter, which is a fact about the other API.
4. **`paesePubblicazione` is not a language.** `CFI1172094` is an English
   *Nineteen Eighty-Four* published in Pesaro: `linguaPubblicazione: INGLESE`,
   `paesePubblicazione: ITALIA`. Only `linguaPubblicazione` is read — and even
   it lies sometimes, which `core/identity.py` disbelieves rather than fixes.

Everything here fetches or parses. Whether a record is an edition of *this*
work, whether its language can be believed, whether it is a book at all — all
of that is pure and lives in `core/`.
"""

import re

from . import langs
from .http import cached_get_json

BASE = "https://opac.sbn.it/opacmobilegw"
PERMALINK = "https://opac.sbn.it/bid/{}"

# The only parameters the endpoint actually honours. Verified by probing:
# anything else is silently dropped rather than rejected.
PARAMS = {"any", "title", "author", "subject", "isbn", "type", "start", "rows"}

# Translation evidence in free text. 'traduzione ... a cura di' is caught by the
# trad- stem; bare 'a cura di' is deliberately NOT matched, since it means
# 'edited by' and would make every edited volume look like a translation.
TRANSLATION_RE = re.compile(r"\btrad(?:\.|uzion\w*|ott\w*|\. it\w*)|\bversione (?:italiana|di)\b", re.I)

# The same evidence, in the one place nothing looked: the title's own statement
# of responsibility, which `title_of` cuts away before anyone sees it.
# UBO4636099 is 'Kafka on the shore / Haruki Murakami ; translated from the
# Japanese by Philip Gabriel' and carries no [Traduttore] and no note — its only
# trace of being a translation is in that half of the title. Records catalogued
# in English say 'translated from', not 'traduzione di', so TRANSLATION_RE never
# saw them either.
RESPONSIBILITY_RE = re.compile(
    r"\b(translated (?:from|by)|tradotto dal|tradotta dal|traduit (?:du|par)"
    r"|traducido del|ubersetzt|übersetzt)\b", re.I)

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
# The year inside an imprint, where a calendar's letter can sit on the digits:
# `1373H`, `1304 h` (year_probe, 2026-09-29). `\b` refused the first and so
# dated the record not at all. Digits either side still end a match.
_IMPRINT_YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")
# A bracket between two numbers is a separator, not noise: `1371[1992]` lost
# both years once the brackets went and `13711992` was left.
_BRACKET_BETWEEN_DIGITS_RE = re.compile(r"(?<=\d)[\\!\[\]](?=\d)")
# A number that opens the publisher's name and is followed by a word: `Ankara :
# 1001 Çiçek kitaplar, 2015` is 2015, not 1001.
_NAME_NUMBER_RE = re.compile(r"\s+[^\W\d]")
# '780.07 (19.) MUSICA. RAPPORTO CON LA SOCIETA' -> '780.07'. Dewey is numeric
# and so language-neutral: it is the one signal that can tie an Italian title to
# an English original when their words have nothing in common.
_DEWEY_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)")
# SBN marks supplied/uncertain data with \...! and [...] and © — noise for us.
_CRUFT_RE = re.compile(r"[\\!\[\]©]|\b(?:c|d\.l\.|stampa|impr\.|copyr\.)\s*(?=\d)", re.I)
_SINE_DATA_RE = re.compile(r"[\s,]*\bs\.\s?d\.?\s*$", re.I)
# The words a cataloguer puts before a supplied year: `[tra il 1970 e il 1990]`,
# `[dopo il 1920]`, `[non prima del 1832]`, `[ca. 1878]`. They open the date, so
# they are not the end of the publisher's name. Every form here was seen in the
# 16,143 imprints on this machine (2026-09-29), and only these. `<` is SBN's
# other date bracket (`<dopo il 1880>`, `<1993>`), which `_CRUFT_RE` keeps.
_DATE_QUALIFIER_RE = re.compile(
    r"(?:^|(?<=[\s,;(<]))(?:non\s+prima\s+del|prima\s+del|dopo(?:\s+il)?"
    r"|tra(?:\s+il)?|dal|circa|ca\.?|post\.?)\s*$", re.I)
# A year in a calendar `_IMPRINT_YEAR_RE`'s range does not reach, written before
# the Gregorian one: `c5760 [i.e. 1999/00]` (Hebrew), `[5]718-[5]719 [1959]`,
# `2559 [2016]` (Thai), `11353 h. 1935 m`. After the name's last comma and made
# of numbers alone, it is the date; a number beside a word is a name (`1001
# Çiçek kitaplar`, `N° 132. Strand`, `Grafica 080`). Every form was seen in the
# 26,012 imprints on this machine (2026-09-30).
_OTHER_CALENDAR_RE = re.compile(r",\s*[\d(][\d\s()\-]*(?:\s*(?:i\.\s?e|h)\.?)?\s*$", re.I)
# A date known only to the decade or century, which the year search cannot
# take: `[19..]`, `195.`, `[198.?]`, `[18--?]`, `<196.>`, and a printer's
# statement after it (`[198.] (Milano : ColorBlack)`); a decade clipped to its
# digits after a comma (`Insel-Verlag, 192`, `[182`); or a century, `inizio 20.
# sec.`, `2. metà 17. sec.`. Every form was seen in the 26,011 imprints on this
# machine (2026-09-30). At least two digits, so `Aldo Manuzio <1.>` is a name.
_PARTIAL_DATE_RE = re.compile(
    r"(?:[,\s]\s*[?°¢<]?[12]\d{1,2}[.\-?][.\-?\s>}]*?(?:\(.*\))?"
    r"|,\s*[12]\d\d"
    r"|,[^,;]*\b(?:1?\d|2[01])\.?\s*sec\b[^,;]*)(?=\s*;|\s*$)", re.I)
# An extent or a carrier, not an imprint: `157 p. ; 21 cm`, `xxxv, 191 p.`,
# `[2]c.`, `v. 2`, `5 volumi`, `1 DVD-video`, `P. 133-141`. SBN's mobile gateway
# puts some in `pubblicazione` itself, and the OPAC's `infos` holds them where
# the imprint would be. Every form was seen in the 26,012 imprints on this
# machine (2026-09-30). A count must lead, so `DVD Storm` stays a publisher.
_EXTENT_RE = re.compile(
    r"^(?:\[?(?:\d{1,3}|[xivlc]+)\]?\s*,\s*)*\[?\d+\]?\s*(?:p|c|v|voll?|volumi|cd|dvd"
    r"|compact\s+disc|audiocassett\w*)\b|^v\.?\s*(?:\d|;|$)|^p\.\s*\d", re.I)
# An extent after the imprint, which ends it: `Oriental Institute. - 2 voll. ;
# 25 cm.`, `Principato, [195..] - VIII, 597 p. : ill.`, `feltrinelli, 20 cm`,
# `Seidosha, 1984. 380 p. : 19 cm`, whose own ` : ` was taken for ISBD's.
_TRAILING_EXTENT_RE = re.compile(
    r"(?:[.,]\s*[-–]\s*\.?\s*|\s[-–]\s*\.?\s*|\.\s+|,\s+)(?:\[?(?:\d{1,3}|[xivlc]+)\]?\s*,\s*)*[\[\]\d]+\s*"
    r"(?:p|c|v|voll?)\b.*$|[.,]?\s*[-–]\s+volumi\b.*$|,\s*\d+\s*cm\.?$", re.I)
# An edition or reprint statement before the imprint: `18. ed. Milano : …`,
# `2. ed. riv. e accresciuta - Milano : …`, `Rist. anast.- Oxford : …`, `, 154.
# ed. ; Paris : …`, and alone: `4 ed`, `12. rist`, `Diciottesima edizione`, `Ed.
# accresciuta, …`. Led by a number, an ordinal word, or the word itself before a
# lowercase one, so `Edizione Club` and `Ed. Paoline` stay publishers.
_EDITION_WORD = r"(?:ed|edizione|edition|editio|rist|ristampa|tirage|auflage)\b\.?"
_EDITION_RE = re.compile(
    r"^[\s,]*(?:\d+\s*(?:[.°]|st|nd|rd|th)?\s*(?:[\w.]+\s+){0,2}" + _EDITION_WORD
    + r"|(?:nuova|nova|new|rev|revised|prima|seconda|terza|quarta|\w+esima)\.?\s+"
    + _EDITION_WORD + r"|" + _EDITION_WORD + r"(?=\s*[a-zàèéìòù]|[^:]*?(?:\s[-–_]|\.[-–])))",
    re.I)
# What ends an edition statement before the place: ISBD's `. - ` in any of the
# spacings SBN has (`ed.- Madrid`, `ed. -Bombay`, `ed. _ Milano`), else ` ; `.
# The dash first: `6 edizione, con saggi … ; con 99 illustrazioni … - Firenze`.
_EDITION_ENDS = (re.compile(r"^\s*[-–_]\s*|\s[-–_]\s*|\.[-–]\s*"), re.compile(r"\s;\s"))
# A reprint named after the publisher: `A. Mondadori, 2. rist. 1990`, `Edizioni
# e/o, ristampa 2016`, `SEI, terza edizione ristampa 1948`.
_REPRINT_RE = re.compile(r",[^,]*\b(?:rist|ristampa)\b\.?\s*$", re.I)
_LABELLED_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
# SBN wraps non-sorting articles in C1 control characters (\x88 ... \x89), e.g.
# '\x88Il \x89disoriente'. They are invisible markup, not content.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean_text(value):
    """Strip SBN's invisible sort markers and collapse whitespace."""
    if not value:
        return None
    text = _CONTROL_RE.sub("", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def short_bid(codice: str | None) -> str | None:
    r"""'IT\ICCU\MIL\0871878' -> 'MIL0871878', the permalink form."""
    if not codice:
        return None
    parts = [p for p in codice.replace("/", "\\").split("\\") if p]
    if parts[:2] == ["IT", "ICCU"]:
        parts = parts[2:]
    return "".join(parts) or None


def title_of(raw: str) -> str:
    """The title without its statement of responsibility.

    ISBD punctuation: 'Rumori : saggio ... / Attali'. The half after ' / ' is
    who made it, not what it is called — but it is the only place some records
    name a translator, so `parse_record` reads it before dropping it.
    """
    return (raw or "").split(" / ", 1)[0].strip()


def parse_labelled(items) -> list:
    """['[Traduttore]  Mancini, Sergio'] -> [('Traduttore', 'Mancini, Sergio')].

    Shared by `nomi` and `numeri`, which use the same '[LABEL]  value' shape.
    """
    out = []
    for raw in items or []:
        m = _LABELLED_RE.match(clean_text(raw) or "")
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
        elif raw:
            out.append(("", raw.strip()))
    return out


def parse_publication(pubblicazione: str | None) -> tuple:
    """'Milano : Mazzotta, c1978, (stampa 1977)' -> ('Mazzotta', '1978', 'Milano').

    The year is the imprint's **first** year and nothing more: which of several
    years a record was published in, when a calendar other than the Gregorian
    wrote one of them, is `core.dates`'s to decide, from `date_statement`.
    """
    if not pubblicazione:
        return None, None, None
    text = _BRACKET_BETWEEN_DIGITS_RE.sub(" ", clean_text(pubblicazione) or "")
    text = _CRUFT_RE.sub("", text).strip()
    if is_extent(text):
        return None, None, None
    text = _TRAILING_EXTENT_RE.sub("", _strip_edition(text))
    place, rest = _split_place(text)

    year_m = _first_year(rest)
    year = year_m.group(1) if year_m else None

    publisher = rest[: year_m.start()] if year_m else rest
    if year_m:
        publisher = _DATE_QUALIFIER_RE.sub("", publisher).rstrip(" <")
        publisher = _OTHER_CALENDAR_RE.sub("", publisher)
        publisher = _REPRINT_RE.sub("", publisher)
    else:
        publisher = _PARTIAL_DATE_RE.sub("", publisher)
    publisher = publisher.strip().strip(",;:(").strip()
    # 's. d.' is *sine data* — the catalogue saying it has no date. It is the
    # year's absence, not part of the publisher's name.
    publisher = _SINE_DATA_RE.sub("", publisher)
    publisher = re.sub(r"\s*,\s*$", "", publisher)
    return (publisher or None), year, (place.strip(" ,") or None)


def is_extent(text: str) -> bool:
    """Whether an imprint-shaped value is an extent or a carrier instead."""
    return bool(_EXTENT_RE.match(text))


def _strip_edition(text: str) -> str:
    m = _EDITION_RE.match(text)
    if not m:
        return text
    rest = text[m.end():]
    for end_re in _EDITION_ENDS:
        end = end_re.search(rest.split(":", 1)[0])
        if end:
            return rest[end.end():]
    if not (":" in rest or _IMPRINT_YEAR_RE.search(rest)):
        return ""                     # the edition statement alone: `2. ed. riveduta`
    # A numbered one ends at once (`18. ed. Milano : …`); where a worded one
    # ends is not known (`Edizione abbreviata per le scuole, Milano : …`).
    return rest.lstrip(" .,") if m.group().lstrip(" ,[")[:1].isdigit() else text


def _split_place(text: str) -> tuple:
    place, _, rest = text.partition(" : ")
    if rest:
        return place, rest
    # A colon without ISBD's spaces still ends the place: `Barcelona: Plaza &
    # Janes, 2000`, `Milano :Adelphi, 2005` (2026-09-30). Unless only a year
    # follows it: `R. Piper & Co., München: 1980` names its publisher first.
    place, _, rest = text.partition(":")
    if rest.strip() and not _IMPRINT_YEAR_RE.match(rest.strip()):
        return place, rest
    return "", text


def _first_year(rest: str):
    matches = list(_IMPRINT_YEAR_RE.finditer(rest))
    if len(matches) > 1 and matches[0].start() == 0 \
            and _NAME_NUMBER_RE.match(rest, matches[0].end()):
        return matches[1]
    return matches[0] if matches else None


def date_statement(pubblicazione: str | None) -> str | None:
    """The imprint from its first year on, as the catalogue wrote it.

    `'Tihran : Aryaban, 1386 [2007!'` -> `'1386 [2007]'`. SBN writes a supplied
    bracket as `\\...!`; it is given back as `[...]`, which is what it means.
    What the page shows beside a year it could not take at face value, and what
    `core.dates` reads every candidate year from. None when there is no year.
    """
    _, year, _ = parse_publication(pubblicazione)
    if not year:
        return None
    raw = (clean_text(pubblicazione) or "").replace("\\", "[").replace("!", "]")
    raw = _TRAILING_EXTENT_RE.sub("", raw.replace("©", ""))
    _, _, after = raw.partition(" : ")
    after = after or raw
    at = after.find(year)
    if at < 0:
        # The digits were split by a bracket in the raw text (`1371[1992]`).
        m = _IMPRINT_YEAR_RE.search(after)
        at = m.start() if m else 0
    # A bracket opened before the year and closed after it (`[tra il 1970 e
    # il 1990]`) belongs to the statement.
    opened = max(after.rfind("[", 0, at), after.rfind("(", 0, at))
    if opened >= 0 and not any(c in after[opened:at] for c in "])"):
        at = opened
    statement = after[at:].strip()
    if statement.count("]") > statement.count("[") and statement.endswith("]"):
        statement = statement[:-1].rstrip()      # its `[` was before the ` : `
    return statement or None


def parse_dewey(value: str | None) -> str | None:
    codes = parse_dewey_all(value)
    return codes[0] if codes else None


def parse_dewey_all(value: str | None) -> list:
    """Every Dewey number in the field, not just the first.

    SBN runs several together without a separator, e.g.
    '616.89 (18.) PSICHIATRIA616.85 (19.) MALATTIE NERVOSE', and the second one
    is as good a matching signal as the first.
    """
    text = clean_text(value) or ""
    seen, out = set(), []
    # No word boundary before the number: SBN concatenates the previous caption
    # straight onto it ('PSICHIATRIA616.85'), and a letter-to-digit transition is
    # not a \b, so 616.85 was being read as 85. Look behind for digit-or-dot.
    for m in re.finditer(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)(?=\s*\(\d)", text):
        code = m.group(1)
        if code not in seen:
            seen.add(code)
            out.append(code)
    if not out:
        m = _DEWEY_RE.search(text)
        if m:
            out.append(m.group(1))
    return out


def publisher_names(publisher: str) -> list:
    """The publisher statement split into publishers, ISBD's way.

    ISBD writes 'Place : Publisher ; Place : Publisher'. `parse_publication` has
    already cut the leading place, so the first piece is a publisher (a ' : '
    inside it separates a co-publisher); in later pieces the part before ' : ' is
    a place, and a piece with no ' : ' is a place alone.

    Splitting is the source's own convention, so it is parsing. What counts as
    the *same* publisher is a judgement and is `core/fold.py`'s.
    """
    names = []
    for i, piece in enumerate(publisher.split(";")):
        if i and re.match(r"\s*in association with\b", piece, flags=re.I):
            names.append(piece)
            continue
        parts = re.split(r"\s+:\s+", piece)
        names += parts if i == 0 else parts[1:]
    return [n.strip() for name in names
            for n in re.split(r"\bin association with\b", name, flags=re.I) if n.strip()]


def parse_holdings(localizzazioni) -> list:
    """[{'library', 'city', 'isil'}] — libraries holding a copy.

    The field names lie about their content: SBN puts the library name in
    `shelfmark` and the city in `invNum`. Consistent, just not what it says.
    """
    out = []
    for loc in localizzazioni or []:
        for sm in loc.get("shelfmarks") or [{}]:
            out.append({
                "library": clean_text(sm.get("shelfmark") or loc.get("denominazione")) or "",
                "city": clean_text(sm.get("invNum")) or "",
                "isil": clean_text(loc.get("isil")) or "",
            })
    return out


def parse_record(rec: dict) -> dict:
    """One brief or full record as plain fields, named the way a `Record` is.

    A dict rather than a `core.model.Record` because `catalog/` may not import
    `core/`: the field names line up, so a producer builds one with
    `Record(**parse_record(rec), provenance=...)` and nothing about this API
    leaks into the pure layer.

    A brief record has no language, so `language` stays 'unknown' until the
    record is enriched — never inferred from the country of publication.
    """
    bid = short_bid(rec.get("codiceIdentificativo"))
    publisher, year, place = parse_publication(rec.get("pubblicazione"))
    date = date_statement(rec.get("pubblicazione"))

    names = parse_labelled(rec.get("nomi"))
    translators = [v for label, v in names if label.lower().startswith("tradutt")]
    # The authors are worth keeping: for an Italian title that Wikidata does not
    # know, they are the only route back to the original work.
    authors = [v for label, v in names if label.lower().startswith("autore")]

    # Every ISBN on the row, not just the first: one `numeri` field often lists
    # the paperback and the hardback, and either can be the one another catalogue
    # printed. `core/fold.py` normalises them and decides what merges.
    isbns_raw = [v for label, v in parse_labelled(rec.get("numeri"))
                 if label.upper() == "ISBN"]
    if rec.get("isbn"):
        isbns_raw.append(rec["isbn"])
    isbn = isbns_raw[0] if isbns_raw else None

    evidence = []
    for note in rec.get("note") or []:
        note = clean_text(note)
        if note and TRANSLATION_RE.search(note):
            evidence.append(note)
    raw_title = clean_text(rec.get("titolo")) or ""
    _, _, responsibility = raw_title.partition(" / ")
    if responsibility and (RESPONSIBILITY_RE.search(responsibility)
                           or TRANSLATION_RE.search(responsibility)):
        evidence.append(responsibility.strip())
    evidence += [f"Traduttore: {t}" for t in translators]

    dewey = parse_dewey_all(rec.get("classificazioneDewey"))
    return {
        "source": "SBN",
        "id": bid,
        "title": title_of(raw_title),
        "publisher": ", ".join(filter(None, [publisher, place])) or None,
        "year": year,
        "date": date,
        "language": langs.from_sbn(rec.get("linguaPubblicazione")),
        "isbn": isbn,
        "isbns_raw": isbns_raw,
        "url": PERMALINK.format(bid) if bid else None,
        "series": clean_text(rec.get("collezione")),
        "physical": clean_text(rec.get("descrizioneFisica")),
        "dewey": dewey[0] if dewey else None,
        "dewey_all": dewey,
        "medium": clean_text(rec.get("tipo")),
        "cover_url": rec.get("copertina") or None,
        "authors": authors,
        "translators": translators,
        "evidence": evidence,
        "holdings": parse_holdings(rec.get("localizzazioni")),
        "publisher_names": publisher_names(publisher) if publisher else [],
        "places": [place] if place else [],
    }


def payload_error(data) -> str | None:
    """The reason to reject a body, or None. Given to the cache, not the caller.

    SBN answers a query it cannot run with **HTTP 200** and an `error` object,
    so nothing below the JSON decode can tell the failure from an answer. One
    slash in a free-text value is enough — Solr reads it as the opening of a
    regex literal and an unterminated one is a parse error (verified
    2026-09-18: `title=alpha / beta` errors, `alpha beta` and `alpha / beta /
    gamma` do not). Open Library hands the pipeline titles like
    'Die Verwandlung / la Metamorfosi', which is how three books reported
    `SBN partial (1 request failed)` in every run with no request having failed:
    the error body was cached and replayed for 24 h (`docs/DECISIONS.md` pitfall 8, U8).

    A bogus BID is *not* this shape — `full.json` answers it with a skeleton
    record carrying no `codiceIdentificativo` (F13), which is a real body and
    stays cached.
    """
    if isinstance(data, dict) and data.get("error"):
        err = data["error"]
        return str(err.get("msg", err) if isinstance(err, dict) else err)
    return None


def _request(endpoint: str, params: dict):
    clean = {k: v for k, v in params.items() if k in PARAMS and v not in (None, "")}
    if endpoint == "full.json":
        clean = {"bid": params["bid"]}
    return cached_get_json(f"{BASE}/{endpoint}", clean, validate=payload_error)


def search(title=None, author=None, any_=None, subject=None, isbn=None, rows=200) -> tuple:
    """(brief records, facets). Raises SourceError on a validation error."""
    params = {"title": title, "author": author, "any": any_,
              "subject": subject, "isbn": isbn, "rows": rows, "start": 0}
    if not any(params.get(k) for k in ("title", "author", "any", "subject", "isbn")):
        return [], []
    data = _request("search.json", params)
    return (data.get("briefRecords") or []), (data.get("facetRecords") or [])


def full_record(bid: str) -> dict:
    return _request("full.json", {"bid": bid})
