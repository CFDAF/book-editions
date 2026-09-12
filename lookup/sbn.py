"""SBN / ICCU — Italy's national union catalogue.

Uses the undocumented mobile-app gateway, which is the only JSON interface SBN
exposes. Two endpoints, both reverse-engineered and verified:

    search.json   brief records + facets
    full.json?bid=<SHORTBID>   the full record  <- undocumented, 'bid' is the
                               only accepted parameter name

The brief record does NOT carry a language, so deciding whether something is an
Italian edition *requires* the full record. That is why the pipeline enriches
candidates rather than trusting a search hit.

Three traps this module exists to contain:

1. Unknown parameters are silently ignored and the endpoint returns the
   unfiltered result set. Sending 'titolo' instead of 'title' does not error,
   it returns everything — a silent wrong answer. Only PARAMS are ever sent.

2. Facets come back with counts but cannot be sent back as filters. Every
   syntax (lingua=, fq=, facet=, refine=, facetName/facetValue) is ignored.
   Filtering is the caller's job.

3. paesePubblicazione is NOT a language. Record CFI\\1172094 is an English
   'Nineteen Eighty-Four' published in Pesaro: linguaPubblicazione INGLESE,
   paesePubblicazione ITALIA. Only linguaPubblicazione is consulted.
"""

import re

from . import langs
from .matching import sbn_title_of
from .models import Edition, Holding
from .net import SourceError, cached_get_json

BASE = "https://opac.sbn.it/opacmobilegw"
PERMALINK = "https://opac.sbn.it/bid/{}"

# The only parameters the endpoint actually honours. Verified by probing:
# anything else is silently dropped rather than rejected.
PARAMS = {"any", "title", "author", "subject", "isbn", "type", "start", "rows"}

# Translation evidence in free text. 'traduzione ... a cura di' is caught by the
# trad- stem; bare 'a cura di' is deliberately NOT matched, since it means
# 'edited by' and would make every edited volume look like a translation.
TRANSLATION_RE = re.compile(r"\btrad(?:\.|uzion\w*|ott\w*|\. it\w*)|\bversione (?:italiana|di)\b", re.I)

_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
# '780.07 (19.) MUSICA. RAPPORTO CON LA SOCIETA' -> '780.07'. Dewey is numeric
# and so language-neutral: it is the one signal that can tie an Italian title to
# an English original when their words have nothing in common.
_DEWEY_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)")
# SBN marks supplied/uncertain data with \...! and [...] and © — noise for us.
_CRUFT_RE = re.compile(r"[\\!\[\]©]|\b(?:c|d\.l\.|stampa|impr\.|copyr\.)\s*(?=\d)", re.I)
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
    """'Milano : Mazzotta, c1978, (stampa 1977)' -> ('Mazzotta', '1978', 'Milano')."""
    if not pubblicazione:
        return None, None, None
    text = _CRUFT_RE.sub("", clean_text(pubblicazione) or "").strip()
    place, _, rest = text.partition(" : ")
    if not rest:
        place, rest = "", text

    year_m = _YEAR_RE.search(rest)
    year = year_m.group(1) if year_m else None

    publisher = rest[: year_m.start()] if year_m else rest
    publisher = publisher.strip().strip(",;:(").strip()
    publisher = re.sub(r"\s*,\s*$", "", publisher)
    return (publisher or None), year, (place.strip(" ,") or None)


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


def _holdings(localizzazioni) -> list:
    out = []
    for loc in localizzazioni or []:
        for sm in loc.get("shelfmarks") or [{}]:
            out.append(Holding(
                # SBN puts the library name in 'shelfmark' and the city in
                # 'invNum' — not what the field names suggest, but consistent.
                library=clean_text(sm.get("shelfmark") or loc.get("denominazione")) or "",
                city=clean_text(sm.get("invNum")) or "",
                isil=clean_text(loc.get("isil")) or "",
            ))
    return out


def _request(endpoint: str, params: dict):
    clean = {k: v for k, v in params.items() if k in PARAMS and v not in (None, "")}
    if endpoint == "full.json":
        clean = {"bid": params["bid"]}
    data = cached_get_json(f"{BASE}/{endpoint}", clean)
    if isinstance(data, dict) and data.get("error"):
        raise SourceError(f"SBN: {data['error'].get('msg', data['error'])}")
    return data


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


def to_edition(rec: dict, source="SBN") -> Edition:
    """Map a brief or full SBN record onto an Edition.

    A brief record has no language, so `language` stays 'unknown' until the
    record is enriched — never inferred from the country of publication.
    """
    bid = short_bid(rec.get("codiceIdentificativo"))
    publisher, year, place = parse_publication(rec.get("pubblicazione"))

    names = parse_labelled(rec.get("nomi"))
    translators = [v for label, v in names if label.lower().startswith("tradutt")]
    # The authors are worth keeping: for an Italian title that Wikidata does not
    # know, they are the only route back to the original work.
    authors = [v for label, v in names if label.lower().startswith("autore")]

    isbn = rec.get("isbn")
    for label, value in parse_labelled(rec.get("numeri")):
        if label.upper() == "ISBN":
            isbn = value
            break

    evidence = []
    for note in rec.get("note") or []:
        note = clean_text(note)
        if note and TRANSLATION_RE.search(note):
            evidence.append(note)
    evidence += [f"Traduttore: {t}" for t in translators]

    return Edition(
        source=source,
        title=sbn_title_of(clean_text(rec.get("titolo")) or "") or "",
        publisher=", ".join(filter(None, [publisher, place])) or None,
        year=year,
        language=langs.from_sbn(rec.get("linguaPubblicazione")),
        isbn=isbn,
        url=PERMALINK.format(bid) if bid else None,
        sbn_bid=bid,
        series=clean_text(rec.get("collezione")),
        dewey=parse_dewey(rec.get("classificazioneDewey")),
        physical=clean_text(rec.get("descrizioneFisica")),
        cover_url=rec.get("copertina") or None,
        authors=authors,
        translators=translators,
        evidence=evidence,
        holdings=_holdings(rec.get("localizzazioni")),
    )


def dewey_codes(rec: dict) -> list:
    return parse_dewey_all(rec.get("classificazioneDewey"))


def has_translation_evidence(edition: Edition) -> bool:
    return bool(edition.translators or edition.evidence)
