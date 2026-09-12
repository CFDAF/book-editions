"""Bidirectional title crosswalk via Wikipedia sitelinks and Wikidata labels.

No catalogue records a link between a translation and its original: Open
Library has no translation_of field, and SBN records carry no uniform title.
Wikidata does — not through P629/P747, whose coverage is thin, but through the
plain labels and Wikipedia sitelinks of the work item:

    One Hundred Years of Solitude -> Q178869 -> labels.it  Cent'anni di solitudine
    Cent'anni di solitudine       -> Q178869 -> labels.en  One Hundred Years of Solitude
                                              P1476       Cien anos de soledad (es)
                                              P407        Spanish   <- original language
                                              P577        1967      <- original year

P407/P577 are the only place any free source states what language a work was
written in, which is what makes an Italian-first lookup answerable.

Precision is high, recall is bounded by Wikipedia notability: Attali's Bruits
has sitelinks for en/es/fa/zh and no Italian label at all, so a miss here is
expected and must fall through to the Open Library author cluster, not fail.
"""

from concurrent.futures import ThreadPoolExecutor

from . import langs
from .matching import author_matches, core_title, normalize, strip_disambiguator
from .models import TitleCluster
from .net import SourceError, cached_get_json

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Wikis consulted, in order. Italian first: an Italian-first lookup is the
# direction the old script could not express, so it gets first refusal.
WIKIS = ("it", "en")

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
    "Q3331189",  # version, edition or translation
    "Q1667921",  # novel series
    "Q13136",    # reference work
    "Q2382443",  # essay collection
}


def _claim_ids(claims, prop):
    out = []
    for c in claims.get(prop, []):
        val = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(val, dict) and val.get("id"):
            out.append(val["id"])
    return out


def _claim_first(claims, prop):
    for c in claims.get(prop, []):
        val = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if val is not None:
            return val
    return None


def _page_to_qid(wiki: str, title: str) -> str | None:
    """Exact page (following redirects) -> Wikidata item."""
    data = cached_get_json(
        f"https://{wiki}.wikipedia.org/w/api.php",
        {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
         "redirects": "1", "titles": title, "format": "json"},
    )
    for page in (data.get("query", {}).get("pages") or {}).values():
        if "missing" in page:
            continue
        qid = (page.get("pageprops") or {}).get("wikibase_item")
        if qid:
            return qid
    return None


def _titles_to_qids(wiki: str, titles: list) -> dict:
    """Resolve many page titles to items in one call (titles accepts up to 50)."""
    if not titles:
        return {}
    data = cached_get_json(
        f"https://{wiki}.wikipedia.org/w/api.php",
        {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
         "redirects": "1", "titles": "|".join(titles), "format": "json"},
    )
    query = data.get("query") or {}
    # Follow both normalisation and redirect hops back to what we asked for.
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
        while title in alias:          # walk back to the originally requested title
            title = alias[title]
        out[title] = qid
    return out


def _search_pages(wiki: str, query: str, limit: int = 4) -> list:
    data = cached_get_json(
        f"https://{wiki}.wikipedia.org/w/api.php",
        {"action": "query", "list": "search", "srsearch": query,
         "srlimit": limit, "format": "json"},
    )
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def _entities(qids: list, props: str, languages: str) -> dict:
    if not qids:
        return {}
    data = cached_get_json(
        WIKIDATA_API,
        {"action": "wbgetentities", "ids": "|".join(qids[:40]),
         "props": props, "languages": languages, "format": "json"},
    )
    return data.get("entities") or {}


def _label_map(qids: list) -> dict:
    """QID -> a readable label, batched into one request."""
    ents = _entities(qids, "labels", "it|en|fr|es|de")
    out = {}
    for qid, ent in ents.items():
        labels = ent.get("labels") or {}
        for lang in ("en", "it", "fr", "es", "de"):
            if lang in labels:
                out[qid] = labels[lang]["value"]
                break
    return out


def _candidate_qids(title: str, author: str | None, tally=None) -> list:
    """Candidate items, best-first: exact page hits before search hits.

    Both wikis are consulted concurrently. Candidates are returned as a list
    rather than validated one at a time, because validating them needs their
    claims and wbgetentities takes up to 50 ids in a single request — fetching
    them one by one was costing about 38 seconds per cold lookup.
    """
    query = f"{title} {author}".strip() if author else title

    def per_wiki(wiki):
        found = []
        try:
            qid = _page_to_qid(wiki, title)
            if qid:
                found.append(qid)
        except SourceError as exc:
            if tally is not None:
                tally.note("Wikidata", exc)
        try:
            pages = _search_pages(wiki, query)
            resolved = _titles_to_qids(wiki, pages)
            found += [resolved[p] for p in pages if p in resolved]
        except SourceError as exc:
            if tally is not None:
                tally.note("Wikidata", exc)
        return found

    with ThreadPoolExecutor(max_workers=len(WIKIS)) as pool:
        batches = list(pool.map(per_wiki, WIKIS))

    seen, ordered = set(), []
    for batch in batches:
        for qid in batch:
            if qid not in seen:
                seen.add(qid)
                ordered.append(qid)
    return ordered


def _is_written_work(claims) -> bool:
    if set(_claim_ids(claims, "P31")) & WORK_CLASSES:
        return True
    # Items with an author and a publication date but an unmodelled P31 are
    # accepted; an article or a person will not have both.
    return bool(_claim_ids(claims, "P50")) and _claim_first(claims, "P577")


def resolve(title: str, author: str | None = None, tally=None) -> tuple:
    """(TitleCluster | None, asked_language).

    asked_language is which wiki the title matched on, used to decide which way
    round to phrase the verdict. It is evidence, not language detection.
    """
    if not title:
        return None, langs.UNKNOWN

    candidates = _candidate_qids(title, author, tally)
    if not candidates:
        return None, langs.UNKNOWN
    # One request for every candidate's claims, then decide locally.
    ents = _entities(candidates, "labels|sitelinks|claims", "it|en|fr|es|de|pt|la")

    for qid in candidates:
        ent = ents.get(qid) or {}
        claims = ent.get("claims") or {}
        if not _is_written_work(claims):
            continue

        author_qids = _claim_ids(claims, "P50")
        translator_qids = _claim_ids(claims, "P655")
        names = _label_map(author_qids + translator_qids)
        author_names = [names[q] for q in author_qids if q in names]

        # Reject a plausible-looking but wrong work when the author disagrees.
        if author and author_names and not author_matches(author, author_names):
            continue

        labels = {k: v["value"] for k, v in (ent.get("labels") or {}).items()}
        sitelinks = {k: v["title"] for k, v in (ent.get("sitelinks") or {}).items()}

        titles_by_lang = {}
        for two, code in ((t, langs.from_two_letter(t)) for t in ("it", "en", "fr", "es", "de")):
            if two in labels:
                titles_by_lang[code] = labels[two]
            elif f"{two}wiki" in sitelinks:
                # Sitelinks carry disambiguators ('1984 (romanzo)'); labels do not,
                # so this is only a fallback.
                titles_by_lang[code] = strip_disambiguator(sitelinks[f"{two}wiki"])

        orig_title_claim = _claim_first(claims, "P1476") or {}
        original_language = langs.from_wikidata(
            (_claim_ids(claims, "P407") or [None])[0]
        )
        if original_language == langs.UNKNOWN and orig_title_claim.get("language"):
            original_language = langs.from_two_letter(orig_title_claim["language"])

        pub = _claim_first(claims, "P577") or {}
        original_year = None
        if isinstance(pub, dict) and pub.get("time"):
            original_year = pub["time"].lstrip("+")[:4]

        cluster = TitleCluster(
            qid=qid,
            titles_by_lang=titles_by_lang,
            original_title=orig_title_claim.get("text") or titles_by_lang.get(original_language),
            original_language=None if original_language == langs.UNKNOWN else original_language,
            original_year=original_year,
            author_names=author_names,
            translators=[names[q] for q in translator_qids if q in names],
            url=f"https://www.wikidata.org/wiki/{qid}",
        )

        return cluster, _guess_asked(title, titles_by_lang)

    return None, langs.UNKNOWN


def _guess_asked(title: str, titles_by_lang: dict) -> str:
    """Which known title variant the user's input actually resembles.

    Compared against each variant and its core title, so a user who types
    'Noise' still matches 'Noise: The Political Economy of Music'.
    """
    qt = normalize(title)
    if not qt:
        return langs.UNKNOWN
    best, best_score = langs.UNKNOWN, 0.0
    for code, variant in titles_by_lang.items():
        for form in {variant, core_title(variant)}:
            v = normalize(form)
            if not v:
                continue
            score = len(qt & v) / max(len(qt), len(v))
            if score > best_score:
                best, best_score = code, score
    return best if best_score >= 0.5 else langs.UNKNOWN
