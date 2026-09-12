"""Orchestration: resolve one work cluster, then present it from either side.

The original script had two destinations, english_editions and
italian_editions, and an English title as the only possible input. This resolves
a single cluster language-agnostically and lets the caller ask from whichever
side they hold.

The hard part is not fetching, it is deciding which Italian record is *this*
book. Nothing links a translation to its original, and cross-language title
similarity is worthless — title_similarity('Noise', 'Rumori') is exactly 0.0.
Three signals do the work instead, in descending order of authority:

  1. A title variant from Wikidata, or a shared ISBN. Decisive when present.
  2. Dewey. It is numeric, therefore language-neutral. The original Bruits/Noise
     work is ddc 306.484 / 780.07; SBN's Rumori is 780.07. That match is what
     ties them together, and it correctly declines to tie in 'Quale socialismo,
     quale Europa' (Dewey 335) which is the same author in the same year.
  3. Explicit translation evidence in the SBN record, plus year plausibility.

Candidates are generated cheaply from brief records, then the top few are
enriched with full.json — which is the only place language and Dewey live.
"""

import os
import re
from concurrent.futures import ThreadPoolExecutor

from . import buylinks, langs, openlibrary as ol, sbn, wikidata
from .matching import author_display, core_title, normalize, surname, title_similarity
from .models import (HIGH, LOW, MEDIUM, ORIGINAL, REPRINT, TRANSLATION,
                     UNCONFIRMED, Edition, LanguageSpan, Overview, Report)
from .net import SourceError, Tally

ENRICH_BUDGET = 45       # full.json calls per lookup
ENRICH_WORKERS = 6
SIBLING_PROBES = 10      # Italian sibling titles probed against SBN


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# Shortest shared Dewey prefix that still means something. A bare 3-digit class
# does not: 306 is the whole of 'culture and institutions', which is how Attali's
# unrelated 'Chemins de sagesse' (306.4) matched the original's 306.484 and was
# wrongly presented as an edition of it.
DEWEY_MIN_PREFIX = 6

# Title similarity that counts as identifying a work on its own.
IDENTIFYING_TITLE_MATCH = 0.6


def _dewey_key(code: str) -> str:
    """Normalise Dewey notation so the same class compares equal.

    Cataloguers pad the decimal part differently: Open Library has 'The
    Invention of News' at 070.09 and SBN has the Einaudi translation at 070.9.
    Both mean history of journalism, but as strings they share only '070.',
    which is too little to match on. Stripping leading and trailing zeros from
    the fraction makes them identical without merging genuinely distinct
    classes — 306.4 and 306.484 stay apart, as do 616.89 and 616.85.
    """
    whole, _, frac = (code or "").strip().partition(".")
    frac = frac.strip().lstrip("0").rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def _dewey_affinity(dewey: str | None, original_ddc: list) -> float:
    """How strongly a Dewey class agrees with the original work's classes."""
    if not dewey or not original_ddc:
        return 0.0
    key = _dewey_key(dewey)
    best = 0.0
    for ddc in original_ddc:
        ddc = (ddc or "").strip()
        if not ddc:
            continue
        if dewey == ddc:
            return 0.35
        if key and key == _dewey_key(ddc):
            best = max(best, 0.32)      # same class, different zero padding
            continue
        shared = len(os.path.commonprefix([dewey, ddc]))
        if shared >= DEWEY_MIN_PREFIX and (dewey.startswith(ddc) or ddc.startswith(dewey)):
            best = max(best, 0.18)
    return best


def _year_affinity(year: str | None, original_year: str | None) -> float:
    """Translations follow their original; a book published before it is not one."""
    if not year or not original_year:
        return 0.0
    try:
        delta = int(year) - int(original_year)
    except ValueError:
        return 0.0
    if delta < -2:
        return -0.25          # predates the original: cannot be its translation
    if delta <= 60:
        return 0.10
    return 0.0


def _variant_affinity(title: str, variants: list) -> float:
    """Same-language title comparison, which is the only kind that means anything."""
    best = 0.0
    for variant in variants:
        best = max(best,
                   title_similarity(variant, title),
                   title_similarity(core_title(variant), core_title(title)))
    return best


def _identifies(e: Edition, reason: str, variants: list, original_ddc: list) -> bool:
    """Is there any signal tying this record to *this* work?

    Without this gate an author sweep drags in every book the author ever wrote,
    which is the failure mode of the original script's SBN handling. Author and
    year agreement are necessary but nowhere near sufficient — 'Quale socialismo,
    quale Europa' (Attali, 1977) matches both and is a different book entirely.
    """
    if reason == "isbn match":
        return True
    # A short title needs a strong match to identify a work. At 0.45,
    # "L'ordine delle notizie" qualified as an edition of "L'invenzione delle
    # notizie" on the strength of one shared word. The correct record matches on
    # its core title at 1.0, so the bar can be well above half.
    if _variant_affinity(e.title, variants) >= IDENTIFYING_TITLE_MATCH:
        return True
    if _dewey_affinity(e.dewey, original_ddc) >= 0.18:
        return True
    # Nothing ties it. Note especially that an 'Open Library sibling' probe is
    # NOT self-justifying: the mechanism deliberately probes SBN with the titles
    # of *other* Italian books by the author, and only Dewey can then say which
    # one is this book. With no Dewey reference it cannot discriminate at all, so
    # its hits are rejected rather than trusted — otherwise a lookup for 'Per una
    # economia positiva' returns Rumori, Karl Marx and Lessico per il futuro.
    return False


def _tag(e: Edition, reason: str) -> Edition:
    e.match_reasons = list(dict.fromkeys([*e.match_reasons, reason]))
    if reason == "same Open Library work":
        e.confidence = HIGH
        e.score = max(e.score, 0.8)
    return e


def _confidence(score: float, reasons: list) -> str:
    if "isbn match" in reasons or "Wikidata title" in reasons:
        return HIGH
    if score >= 0.65:
        return HIGH
    if score >= 0.35:
        return MEDIUM
    return LOW


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

_FIELD_WEIGHT = ("publisher", "year", "isbn", "series", "physical", "dewey", "cover_url")


def _richness(e: Edition) -> int:
    return (sum(1 for f in _FIELD_WEIGHT if getattr(e, f))
            + len(e.holdings) + len(e.evidence) + (2 if e.language != langs.UNKNOWN else 0))


def _merge_into(base: Edition, other: Edition) -> Edition:
    """Fold `other` into `base`, keeping whichever value is actually present."""
    for f in (*_FIELD_WEIGHT, "url", "sbn_bid", "title"):
        if not getattr(base, f) and getattr(other, f):
            setattr(base, f, getattr(other, f))
    if base.language == langs.UNKNOWN and other.language != langs.UNKNOWN:
        base.language = other.language
    for f in ("translators", "evidence", "holdings", "match_reasons"):
        seen = {repr(x) for x in getattr(base, f)}
        getattr(base, f).extend(x for x in getattr(other, f) if repr(x) not in seen)
    base.score = max(base.score, other.score)
    order = [LOW, UNCONFIRMED, MEDIUM, HIGH]
    if order.index(other.confidence) > order.index(base.confidence):
        base.confidence = other.confidence
    if base.source != other.source and other.source not in base.source:
        base.source = f"{base.source} + {other.source}"
    return base


def _dedupe(editions: list) -> list:
    """Collapse the same physical edition seen through different sources."""
    index, out = {}, []
    for e in sorted(editions, key=_richness, reverse=True):
        hit = None
        for key in e.dedupe_keys():
            if key in index:
                hit = index[key]
                break
        if hit is None:
            out.append(e)
            for key in e.dedupe_keys():
                index.setdefault(key, e)
        else:
            _merge_into(hit, e)
            for key in e.dedupe_keys():
                index.setdefault(key, hit)
    return out


# ---------------------------------------------------------------------------
# SBN candidate generation
# ---------------------------------------------------------------------------

def _sbn_probe(title=None, author=None, isbn=None, rows=25, tally=None):
    try:
        return sbn.search(title=title, author=author, isbn=isbn, rows=rows)
    except SourceError as exc:
        if tally is not None:
            tally.note("SBN", exc)
        return [], []


def _collect_sbn_candidates(report, cluster, author, isbns, sibling_titles, tally=None):
    """(candidates, facets) — brief records tagged with why they were pulled."""
    variants = cluster.variants() if cluster else []
    probes = []

    for isbn in list(isbns)[:12]:
        probes.append(({"isbn": isbn}, "isbn match"))
    for variant in variants:
        probes.append(({"title": variant, "author": surname(author or "")}, "Wikidata title"))
    for title in sibling_titles[:SIBLING_PROBES]:
        probes.append(({"title": title, "author": surname(author or "")}, "Open Library sibling"))
    if report.query_title and not variants:
        probes.append(({"title": report.query_title, "author": surname(author or "")}, "query title"))
    if author:
        probes.append(({"author": author, "rows": 500}, "author sweep"))

    candidates, facets = [], []
    with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as pool:
        results = list(pool.map(lambda p: _sbn_probe(tally=tally, **p[0]), probes))

    for (params, reason), (records, got_facets) in zip(probes, results):
        # The author sweep returns the richest facets, and is also the only probe
        # broad enough for them to be meaningful.
        if got_facets and (not facets or reason == "author sweep"):
            facets = got_facets
        for rec in records:
            candidates.append((rec, reason))
    return candidates, facets


def _prescore(rec, cluster, variants, author, priority=()):
    """Rank on brief data only — language and Dewey need a full.json call."""
    title = sbn.sbn_title_of(sbn.clean_text(rec.get("titolo")) or "")
    _, year, _ = sbn.parse_publication(rec.get("pubblicazione"))
    score = _variant_affinity(title, variants) if variants else 0.0
    if priority and _variant_affinity(title, list(priority)) >= 0.6:
        score += 0.4
    if cluster:
        score += _year_affinity(year, cluster.original_year)
    if author and normalize(surname(author)) & normalize(rec.get("autorePrincipale") or ""):
        score += 0.15
    return score


def _enrich(bid, tally=None):
    try:
        return sbn.to_edition(sbn.full_record(bid))
    except SourceError as exc:
        if tally is not None:
            tally.note("SBN", exc)
        return None


# ---------------------------------------------------------------------------
# Reverse expansion: from a confirmed Italian edition back to the original
# ---------------------------------------------------------------------------

def _reverse_expand(italian: list, known_titles: list, tally=None) -> tuple:
    """(editions, notes) — find the original work behind an Italian translation.

    Needed when Wikidata has never heard of the book, which leaves no foreign
    title to search Open Library with, so the lookup would otherwise report the
    Italian editions alone and nothing else.

    SBN records no original title; the only translation trace is a note naming
    the translator. What it does record is the authors and a Dewey class, and
    together those are enough: 'La matrice sociale della psichiatria' gives
    Ruesch and Bateson at 616.89, and Open Library holds their 'Communication'
    at ddc 616.89. The forward mechanism, pointed the other way.

    Worked per record, never pooled across them. Two SBN records can share an
    Italian title while being different books — that exact title is Ruesch and
    Bateson in 1976 and Michael Shepherd in 1990 — so pooling their authors
    demands a work by all three and finds nothing.
    """
    notes, keys, by_key = [], [], {}
    described = None

    for edition in italian[:3]:
        codes = [edition.dewey] if edition.dewey else []
        # Dewey alone is coarse: 616.89 is all of psychiatry, and by itself it
        # matched Ruesch's unrelated 'Therapeutic communication' just as well.
        # Requiring every credited author is what discriminates.
        required = set()
        for name in edition.authors:
            required |= normalize(surname(name))
        if not required or not codes:
            continue

        def per_author(name):
            try:
                return ol.search_works(author=name, limit=60)
            except SourceError as exc:
                if tally is not None:
                    tally.note("Open Library", exc)
                return []

        with ThreadPoolExecutor(max_workers=3) as pool:
            batches = list(pool.map(per_author, edition.authors[:3]))

        for docs in batches:
            for doc in docs:
                ddc = doc.get("ddc") or []
                if not ddc:
                    continue
                # Dewey known on both sides and disagreeing means a different
                # work, so this rejects rather than merely failing to confirm.
                if not any(_dewey_affinity(c, ddc) >= 0.18 for c in codes):
                    continue
                credited = set()
                for candidate in doc.get("author_name") or []:
                    credited |= normalize(candidate)
                if not required <= credited:
                    continue
                if _variant_affinity(doc.get("title", ""), known_titles) >= 0.6:
                    continue        # that is the Italian edition, not the original
                key = (doc.get("key") or "").replace("/works/", "")
                if key and key not in keys:
                    keys.append(key)
                    # The original is by the same people as the translation, so
                    # carry the authorship across; without it these editions
                    # belong to no work and cannot be disambiguated.
                    by_key[key] = list(doc.get("author_name") or edition.authors)
                    described = described or (edition.authors, codes[0])

    if not keys:
        return [], []

    editions, _ = ol.expand(keys[:3], tally, by_key)
    found = []
    for e in editions:
        _tag(e, "Dewey and authorship agreement")
        e.confidence = MEDIUM      # weaker than a Wikidata-confirmed title
        found.append(e)

    who = " and ".join(a.split(",")[0] for a in described[0])
    notes.append(
        "Wikidata did not know this title, so the original was found through the "
        f"Italian record's authors ({who}) and Dewey class ({described[1]}) instead "
        "— a weaker match than a confirmed title, so shown as medium confidence")
    return found, notes


# ---------------------------------------------------------------------------
# Distinct books sharing one title
# ---------------------------------------------------------------------------

def _group_key(e: Edition) -> str:
    """Which book an edition belongs to, keyed on its first author's surname.

    Titles are not unique. 'La matrice sociale della psichiatria' is Ruesch and
    Bateson in 1976 and Michael Shepherd in 1990 — two unrelated books — and
    'Noise' is both Attali and Kahneman. Without this they are silently mixed
    into one answer.
    """
    for name in e.authors:
        tokens = normalize(surname(name))
        if tokens:
            return " ".join(sorted(tokens))
    return ""


def _assign_groups(editions: list, fallback_authors: list) -> None:
    for e in editions:
        if not e.authors and fallback_authors:
            # An edition with no recorded author belongs to the work it came
            # from, so inherit rather than landing in a phantom group.
            e.authors = list(fallback_authors)
        e.work_group = _group_key(e)


def _build_choices(editions: list) -> list:
    """One entry per distinct book, newest first. Empty when unambiguous."""
    groups = {}
    for e in editions:
        if not e.work_group:
            continue
        g = groups.setdefault(e.work_group, {"authors": [], "years": [], "count": 0,
                                             "titles": {}, "key": e.work_group})
        g["count"] += 1
        for name in e.authors:
            display = author_display(name)
            if display and display not in g["authors"]:
                g["authors"].append(display)
        year = _year_of(e.year)
        if year:
            g["years"].append(year)
        g["titles"][e.title] = g["titles"].get(e.title, 0) + 1

    if len(groups) < 2:
        return []

    out = []
    for g in groups.values():
        title = max(g["titles"], key=lambda t: g["titles"][t]) if g["titles"] else ""
        out.append({
            "key": g["key"],
            "authors": g["authors"][:3],
            "title": title,
            "first_year": min(g["years"]) if g["years"] else None,
            "last_year": max(g["years"]) if g["years"] else None,
            "editions": g["count"],
        })
    out.sort(key=lambda c: (c["last_year"] or 0), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _assign_role(e: Edition, cluster) -> str:
    original_language = cluster.original_language if cluster else None
    if sbn.has_translation_evidence(e):
        return TRANSLATION
    if original_language and e.language != langs.UNKNOWN:
        if e.language != original_language:
            return TRANSLATION
        if cluster.original_year and e.year == cluster.original_year:
            return ORIGINAL
    return REPRINT


def _representative(editions: list) -> Edition:
    """The edition worth naming: proven translation, widely held, earliest."""
    def rank(e):
        year = _year_of(e.year) or 9999
        return (bool(e.translators or e.evidence), len(e.holdings), -year)
    return max(editions, key=rank)


def _display_title(editions: list, cluster, fallback: str | None) -> str:
    """The work's name, preferring the original title then the commonest one."""
    if cluster and cluster.original_title:
        return cluster.original_title
    if cluster and cluster.original_language:
        known = cluster.titles_by_lang.get(cluster.original_language)
        if known:
            return known
    # No Wikidata record: the earliest edition carries the original title, which
    # is more meaningful than whichever spelling happens to recur most. Counting
    # occurrences picked the Italian title for 'The Invention of News', because
    # the two English records differ in article and casing and so tie at one each.
    dated = [(y, e) for y, e in ((_year_of(e.year), e) for e in editions) if y]
    if dated:
        return core_title(min(dated, key=lambda pair: pair[0])[1].title)
    counts = {}
    for e in editions:
        base = core_title(e.title)
        if base:
            counts[base] = counts.get(base, 0) + 1
    if counts:
        return max(counts, key=lambda t: counts[t])
    return fallback or ""


def _build_overview(report, cluster, grouped: dict, author: str | None) -> Overview:
    editions = [e for group in grouped.values() for e in group]
    years = [y for y in (_year_of(e.year) for e in editions) if y]

    spans = []
    for code, group in grouped.items():
        group_years = [y for y in (_year_of(e.year) for e in group) if y]
        spans.append(LanguageSpan(
            code=code,
            name=langs.display(code),
            editions=len(group),
            first_year=min(group_years) if group_years else None,
            last_year=max(group_years) if group_years else None,
            is_original=bool(cluster and cluster.original_language == code),
        ))
    # Earliest first: the original leads and translations follow in the order
    # they appeared, which is the shape of a publication history. Undated spans
    # come after the dated ones, and an unrecorded language last of all.
    spans.sort(key=lambda s: (s.code == langs.UNKNOWN,
                              s.first_year is None,
                              s.first_year or 0,
                              -s.editions))

    names = []
    for source in ([cluster.author_names] if cluster and cluster.author_names else []) + \
                  [e.authors for e in editions]:
        for name in source:
            display = author_display(name)
            if display and display not in names:
                names.append(display)
        if names:
            break
    if not names and author:
        names = [author]

    original_year = None
    if cluster and cluster.original_year and cluster.original_year.isdigit():
        original_year = int(cluster.original_year)

    return Overview(
        title=_display_title(editions, cluster, report.query_title),
        authors=names[:3],
        original_language=cluster.original_language if cluster else None,
        original_language_name=(langs.display(cluster.original_language)
                                if cluster and cluster.original_language else None),
        original_year=original_year,
        first_year_seen=min(years) if years else None,
        total_editions=len(editions),
        spans=spans,
        found=bool(editions),
    )


def _note_ambiguity(report: Report) -> None:
    if len(report.choices) > 1:
        report.notes.insert(0, (
            f"{len(report.choices)} different books share this title. "
            "The verdict describes all of them together until you pick one."))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def lookup(title=None, author=None, year_from=None, year_to=None,
           publisher=None) -> Report:
    # An author with no title is a different question — every book they wrote,
    # not every edition of one book — and needs the other pipeline.
    if author and not title:
        return lookup_author(author, year_from=year_from, year_to=year_to,
                             publisher=publisher)

    report = Report(query_title=title, query_author=author)
    tally = Tally()
    editions = []
    isbns = set()
    original_ddc = []

    # --- 1. Wikidata: the only source of original language and year ----------
    cluster = None
    try:
        cluster, asked = wikidata.resolve(title, author, tally)
        report.asked_language = asked
        if cluster:
            report.cluster = cluster
            report.sources["Wikidata"] = "ok"
            if not author and cluster.author_names:
                author = cluster.author_names[0]
                report.query_author = author
        else:
            report.sources["Wikidata"] = "ok"
            report.notes.append(
                "Wikidata: no matching work (expected for anything without a "
                "Wikipedia article) — falling back to the Open Library author cluster")
    except SourceError as exc:
        report.sources["Wikidata"] = f"error: {exc}"
        report.errors.append(f"Wikidata: {exc}")

    variants = cluster.variants() if cluster else []
    if title and not any(title.lower() == v.lower() for v in variants):
        variants.append(title)
    # Titles in the language the question was asked in, plus the query itself.
    # Candidates matching these are enriched first: someone asking in Italian
    # wants the Italian printings, not 60 Spanish ones that also match a variant.
    priority = [v for v in [cluster.titles_by_lang.get(report.asked_language) if cluster else None,
                            title] if v]

    # --- 2. Open Library: editions of the work, plus unlinked siblings -------
    sibling_titles = []
    try:
        docs = ol.candidates(variants[:4], author, publisher=publisher,
                             year_from=year_from, year_to=year_to, tally=tally)
        work_keys, ranked = ol.best_works(variants or [title], author, docs)
        found, original_ddc = ol.expand(work_keys, tally, ol.authors_by_work(docs))
        editions += [_tag(e, "same Open Library work") for e in found]
        if not work_keys and ranked:
            report.notes.append(
                "Open Library: no confident work match (closest: "
                + "; ".join(f'"{t}" ({s:.2f})' for s, t, _ in ranked[:3]) + ")")

        if author:
            # Siblings supply candidate Italian *titles* to probe SBN with. They
            # are not results themselves: an Italian book by this author is not
            # evidence of being this book, and including them reproduces exactly
            # the "here are 62 records, eyeball them" problem.
            for _, doc in ol.italian_siblings(author, variants):
                sibling_titles.append(ol.work_doc_to_edition(doc).title)
        report.sources["Open Library"] = "ok"
    except SourceError as exc:
        report.sources["Open Library"] = f"error: {exc}"
        report.errors.append(f"Open Library: {exc}")

    isbns = {e.isbn.replace("-", "") for e in editions if e.isbn}

    # --- 4. SBN: authoritative for Italian, and holds foreign editions too --
    try:
        candidates, facets = _collect_sbn_candidates(
            report, cluster, author, isbns, sibling_titles, tally)
        report.facets = facets

        best_by_bid = {}
        for rec, reason in candidates:
            bid = sbn.short_bid(rec.get("codiceIdentificativo"))
            if not bid:
                continue
            pre = _prescore(rec, cluster, variants, author, priority)
            if reason in ("isbn match", "Wikidata title"):
                pre += 0.5
            elif reason == "Open Library sibling":
                pre += 0.3
            prior = best_by_bid.get(bid)
            if not prior or pre > prior[0]:
                best_by_bid[bid] = (pre, reason)

        dropped = 0
        ranked = sorted(best_by_bid.items(), key=lambda kv: kv[1][0], reverse=True)
        chosen = ranked[:ENRICH_BUDGET]
        with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as pool:
            enriched = list(pool.map(lambda kv: _enrich(kv[0], tally), chosen))

        for (bid, (pre, reason)), edition in zip(chosen, enriched):
            if edition is None:
                continue
            score = pre + _dewey_affinity(edition.dewey, original_ddc)
            reasons = [reason]
            if sbn.has_translation_evidence(edition):
                score += 0.15
                reasons.append("translation evidence")
            if _dewey_affinity(edition.dewey, original_ddc):
                reasons.append("Dewey agreement")
            edition.score = round(score, 3)
            edition.confidence = _confidence(score, reasons)
            edition.match_reasons = reasons
            if _identifies(edition, reason, variants, original_ddc):
                editions.append(edition)
            else:
                dropped += 1

        if dropped:
            report.notes.append(
                f"SBN: {dropped} fetched record(s) discarded for lacking any identifying "
                "signal (no shared ISBN, no title match, no Dewey agreement)")
        if len(ranked) > ENRICH_BUDGET:
            report.notes.append(
                f"SBN: {len(ranked)} candidate records, top {ENRICH_BUDGET} fetched in full "
                "(only the full record carries language and Dewey)")
        report.sources["SBN"] = "ok"
    except SourceError as exc:
        report.sources["SBN"] = f"error: {exc}"
        report.errors.append(f"SBN: {exc}")

    # --- 4b. No cluster and nothing but Italian? Work backwards -------------
    if not cluster:
        so_far = _dedupe(editions)
        italian = [e for e in so_far if e.language == "ita" and (e.authors or e.dewey)]
        other = [e for e in so_far if e.language not in ("ita", langs.UNKNOWN)]
        if italian and not other:
            try:
                extra, extra_notes = _reverse_expand(
                    italian, [e.title for e in italian], tally)
                editions += extra
                report.notes += extra_notes
            except SourceError as exc:
                report.errors.append(f"Open Library (reverse lookup): {exc}")

    # --- 5. Classify, filter, group -----------------------------------------
    editions = _dedupe(editions)
    non_book = [e for e in editions if not sbn.is_book_medium(e)]
    editions = [e for e in editions
                if sbn.is_book_medium(e) and _passes(e, year_from, year_to, publisher)]
    if non_book:
        report.notes.append(
            f"Excluded {len(non_book)} non-book record(s) — "
            + ", ".join(sorted({e.medium for e in non_book if e.medium})))
    for e in editions:
        e.role = _assign_role(e, cluster)
        e.buy_links = buylinks.for_edition(e.isbn, e.title, author)

    _assign_groups(editions, (cluster.author_names if cluster else None) or
                   ([author] if author else []))
    report.choices = _build_choices(editions)

    # Most recent first; editions with no recorded year sort last, and score
    # only breaks ties within a year.
    grouped = {}
    for e in sorted(editions, key=lambda e: (-(_year_of(e.year) or 0), -e.score, e.title)):
        grouped.setdefault(e.language, []).append(e)

    report.editions_by_language = {
        code: grouped[code] for code in _language_order(grouped, report, cluster)
    }
    report.overview = _build_overview(report, cluster, report.editions_by_language, author)
    _note_ambiguity(report)
    _report_partial(report, tally)
    return report


def _report_partial(report: Report, tally) -> None:
    """Downgrade any source that lost requests, and say the list may be short.

    Without this a flaky network produces a confident-looking answer with a
    language quietly missing — indistinguishable from that language genuinely
    having no editions.
    """
    if not len(tally):
        return
    for name in ("Wikidata", "Open Library", "SBN"):
        missed = tally.count(name)
        if missed and report.sources.get(name) == "ok":
            report.sources[name] = f"partial ({missed} request(s) failed)"
    report.notes.insert(0, (
        f"Incomplete: {len(tally)} request(s) failed, so editions are probably missing "
        "— a whole language can drop out this way. Everything that did arrive is cached, "
        "so running the same search again is fast and usually fills the gaps."))


def _year_of(value) -> int | None:
    """First four-digit year anywhere in the string.

    Open Library publish_date is free text — '1985', 'June 1985', '1972-01-01',
    'December 31, 1985' — so slicing the first four characters dropped every
    month-name date, which silently removed most English editions whenever a
    year filter was set.
    """
    m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", str(value or ""))
    return int(m.group(1)) if m else None


def _passes(e: Edition, year_from, year_to, publisher) -> bool:
    """Year and publisher filters applied locally — SBN accepts neither."""
    if year_from or year_to:
        year = _year_of(e.year)
        if year is None:
            return False
        if year_from and year < int(year_from):
            return False
        if year_to and year > int(year_to):
            return False
    if publisher and publisher.lower() not in (e.publisher or "").lower():
        return False
    return True


def _language_order(grouped, report, cluster) -> list:
    """Asked language first, then the original's, then by size; unknown last."""
    order = []
    for code in (report.asked_language,
                 cluster.original_language if cluster else None,
                 "ita", "eng"):
        if code and code in grouped and code not in order and code != langs.UNKNOWN:
            order.append(code)
    rest = sorted((c for c in grouped if c not in order and c != langs.UNKNOWN),
                  key=lambda c: -len(grouped[c]))
    order += rest
    if langs.UNKNOWN in grouped:
        order.append(langs.UNKNOWN)
    return order


# ---------------------------------------------------------------------------
# Author-only lookup
# ---------------------------------------------------------------------------

AUTHOR_WORK_LIMIT = 200


def _author_key(title: str) -> str:
    return " ".join(sorted(normalize(title)))


def lookup_author(author: str, year_from=None, year_to=None, publisher=None) -> Report:
    """Every book by one author, one row per work rather than per edition.

    A different question from "which editions of this book exist", so it needs a
    different shape: there is no single work to identify, which means the
    identifying-signal gate that protects a title lookup does not apply here —
    everything by the author genuinely belongs in the answer.
    """
    report = Report(mode="author", query_author=author)
    tally = Tally()
    rows = {}

    # --- Open Library: the works, with edition counts and languages ---------
    try:
        for doc in ol.search_works(author=author, limit=AUTHOR_WORK_LIMIT):
            edition = ol.work_doc_to_edition(doc)
            if not edition.title:
                continue
            edition.edition_count = doc.get("edition_count") or None
            edition.available_languages = [
                c for c in (langs.from_openlibrary(x) for x in doc.get("language") or [])
                if c != langs.UNKNOWN]
            edition.confidence = HIGH
            edition.match_reasons = ["Open Library work"]
            rows[_author_key(edition.title)] = edition
        report.sources["Open Library"] = "ok"
    except SourceError as exc:
        report.sources["Open Library"] = f"error: {exc}"
        report.errors.append(f"Open Library: {exc}")

    # --- SBN: which of them exist in Italy, and in what language ------------
    try:
        records, facets = sbn.search(author=author, rows=500)
        report.facets = facets

        # One representative record per distinct title; only the full record
        # carries the language, so the budget is spent on titles not copies.
        by_title = {}
        for rec in records:
            bid = sbn.short_bid(rec.get("codiceIdentificativo"))
            title = sbn.sbn_title_of(sbn.clean_text(rec.get("titolo")) or "")
            if not bid or not title:
                continue
            by_title.setdefault(_author_key(title), (bid, rec))

        chosen = list(by_title.items())[:ENRICH_BUDGET]
        with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as pool:
            enriched = list(pool.map(lambda kv: _enrich(kv[1][0], tally), chosen))

        for (key, _), edition in zip(chosen, enriched):
            if edition is None:
                continue
            edition.confidence = HIGH
            edition.match_reasons = ["SBN author search"]
            existing = rows.get(key)
            if existing:
                _merge_into(existing, edition)
                if edition.language != langs.UNKNOWN and \
                        edition.language not in existing.available_languages:
                    existing.available_languages.append(edition.language)
            else:
                edition.available_languages = (
                    [edition.language] if edition.language != langs.UNKNOWN else [])
                rows[key] = edition

        if len(by_title) > ENRICH_BUDGET:
            report.notes.append(
                f"SBN: {len(by_title)} distinct titles by this author, "
                f"top {ENRICH_BUDGET} fetched in full")
        report.sources["SBN"] = "ok"
    except SourceError as exc:
        report.sources["SBN"] = f"error: {exc}"
        report.errors.append(f"SBN: {exc}")

    report.sources.setdefault("Wikidata", "skipped (not needed for an author search)")

    editions = [e for e in rows.values()
                if sbn.is_book_medium(e) and _passes(e, year_from, year_to, publisher)]
    for e in editions:
        e.buy_links = buylinks.for_edition(e.isbn, e.title, author)

    _assign_groups(editions, [author])
    grouped = {}
    for e in sorted(editions, key=lambda e: (-(_year_of(e.year) or 0), e.title)):
        grouped.setdefault(e.language, []).append(e)
    report.editions_by_language = {
        code: grouped[code] for code in _language_order(grouped, report, None)}

    report.overview = _build_overview(report, None, report.editions_by_language, author)
    report.overview.title = f"{len(editions)} works by {author}"
    report.overview.authors = [author]
    _report_partial(report, tally)
    return report
