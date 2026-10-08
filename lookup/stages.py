"""The stages, in the new tree: S0 to S4 — Steps 6, 7, 9 and 12.

    S0  romanise and validate the question          < 1 ms
    S1  identify the work once                      ~2 s
    S2  list the editions of that identity          ~1.5 s
    S3  recover what the listing cannot reach       ~1.5 s, behind the page
    S4  read every admitted SBN row in full         behind the page

`identify(title, author)` returns one `core.model.Work` and the evidence behind
it. **Nothing after it may use what the user typed** (build rule 11);
the one sanctioned exception is the recovery route (S3), which uses the
typed title to find candidates it then gates on the *work's* titles.

`list_editions(identity)` then fills a `RecordStore` from that identity alone —
SBN's work listing a language page at a time, Open Library's editions by work
key. **It calls no title gate**: every record it holds is there because a
catalogue filed it under this work, which is a statement and not an inference.
The gate is S3's, where records arrive with no statement behind them.

`recover(identity, store)` is that gate. The listing is incomplete **by
construction** — 334 SBN same-work records over 40 books are not linked to W —
so three routes run beside it, each writing into the same store, and every row
they return is matched against the *work's* titles at
`core.identity.IDENTIFYING_TITLE_MATCH`. A record it refuses is **kept**, with
its score, because "what was refused" is a disclosure (decision N) and a record
that was dropped cannot be audited.

Four sources answer, and none of them is believed on its own:

* **Wikidata** is the only place a free source *states* an original language and
  year, and the only step that hands back an author for nothing. It is accepted
  only when the typed title matches one of the item's own names at 0.6 — a rule
  that never accepted a wrong item in 91 entries and rejects all six the old
  resolver returns **M**.
* **SBN's uniform-title authority** is the catalogue stating that two records
  are one work, which no other bridge does. It is read through the A/B guard and
  never by top facet count, and **the author is mandatory** — bare *Rumori*
  returns Russolo (`CLAUDE.md` rule 3).
* **The second signal** (decision A) is the only way a weak or refused W is
  accepted: the Wikidata item already accepted for this entry has to name the
  same work. Loosening B is settled against — the known *wrong* works sit at
  B = 0.5, above every refused classic **M**.
* **Open Library** is searched with the *original* title, never with the typed
  one, and the title test decides which work it is; the edition count only
  breaks ties, because the count alone picks *Animal Farm* for *1984* **M**.

This module orchestrates and reports. It fetches through `catalog/`, which never
decides, and every judgement it makes is a call into `core/identity.py`, which
is pure. The split is the layering `tests/test_tree_layering.py` enforces.
"""

from dataclasses import dataclass, field, replace

from catalog import langs
from catalog import openlibrary as ol
from catalog import sbn_mobile, sbn_opac, wikidata
from catalog.http import Pool, SourceError
from core import authors, buylinks, dates
from core import identity as gate
from core.fold import fold
from core.model import (AUTHOR_SWEEP, DUPLICATE_WORK, ENRICHED, ISBN_MATCH,
                        ISBN_PROBE, REFUSED, TITLE_MATCH, TITLE_PROBE,
                        UNIFORM_TITLE, WORK_EDITIONS, WORK_KEY, WORK_LISTING,
                        Holding, Provenance, Record, Work)
from core.store import RecordStore
from core.text import (author_matches, core_title, is_latin, normalize, similarity,
                       romanise, surname, variant_affinity)

# Phase 1 asks three questions that do not depend on each other. Phase 2 — the
# Open Library work and the name authority — needs phase 1's original title and
# its author names, so neither can start earlier. Both stay within the
# politeness the benchmark measured (OPAC 4 at a time).
S1_WORKERS = 3

# How many name forms the authority is asked for before it gives up. Two: the
# fullest one identity found, then what the reader typed.
AUTHORITY_QUERIES = 2

# Pages the guard reads for B, and it is not `sbn_opac.MAX_PAGES`. That cap is
# 12 because a *work* has at most ~143 records; B's first query is free text and
# can return two thousand (*Odysseia* + Homer did). B is a share of the whole
# query set, so reading a twelfth of it answers a different question — and the
# benchmark that measured the tiers read 100 pages. The cost is what Step 6
# reports per case: 637 requests over 59 entries there, max 151.
GUARD_MAX_PAGES = 100

OK = "ok"


# ---------------------------------------------------------------------------
# S0 — the question, romanised
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Question:
    """What was asked, in the script the catalogues can take.

    `sendable` is not politeness: the OPAC **discards** free text it cannot use
    and answers with the unfiltered set (F15, verified), so a question that
    cannot be romanised must not be sent there at all. Open Library and
    Wikipedia take any script and are asked anyway.
    """
    title: str
    author: str
    typed_title: str
    typed_author: str
    notes: list = field(default_factory=list)

    @property
    def sendable(self) -> bool:
        """May this go to the OPAC as free text?"""
        return bool(self.title and self.author
                    and is_latin(self.title) and is_latin(self.author))


def prepare(title: str, author: str) -> Question:
    """S0. Romanise both halves and say what changed.

    Cyrillic and Greek are transliterated; Japanese, Chinese and Arabic have no
    letter-by-letter romanisation and none is invented (`core.text.romanise`).
    UC3 is what covers those: a title in another script is typed romanised.
    """
    title, author = (title or "").strip(), (author or "").strip()
    out, notes = {}, []
    for name, value in (("title", title), ("author", author)):
        latin = romanise(value)
        if latin != value:
            notes.append(f"{name} romanised: {value!r} -> {latin!r}")
        elif value and not is_latin(value):
            notes.append(f"{name} is not in Latin script and cannot be romanised: "
                         f"{value!r} — SBN's OPAC would discard the term and "
                         "answer with the unfiltered set (F15), so it is not sent")
        out[name] = latin
    return Question(title=out["title"], author=out["author"],
                    typed_title=title, typed_author=author, notes=notes)


# ---------------------------------------------------------------------------
# S1, part 1 — Wikidata
# ---------------------------------------------------------------------------

def _candidate_qids(title: str, author: str) -> list:
    """Candidate items, best-first: the exact page before the search hits.

    Both wikis are consulted at once and the candidates are returned unvalidated,
    because validating them needs their claims and `wbgetentities` takes 50 ids
    in one request.
    """
    query = f"{title} {author}".strip() if author else title

    def per_wiki(wiki):
        found = []
        try:
            qid = wikidata.page_to_qid(wiki, title)
            if qid:
                found.append(qid)
        except SourceError:            # on the ledger, which reports it
            pass
        try:
            pages = wikidata.search_pages(wiki, query)
            resolved = wikidata.titles_to_qids(wiki, pages)
            found += [resolved[p] for p in pages if p in resolved]
        except SourceError:            # on the ledger, which reports it
            pass
        return found

    with Pool(len(wikidata.WIKIS)) as pool:
        batches = list(pool.map(per_wiki, wikidata.WIKIS))
    seen, ordered = set(), []
    for qid in (q for batch in batches for q in batch):
        if qid not in seen:
            seen.add(qid)
            ordered.append(qid)
    return ordered


def _wikidata_item(q: Question) -> dict:
    """The one item that may be believed for this question, or none.

    Every rejection is kept with its reason. They are the difference between
    "Wikidata has never heard of this book" — normal, and expected for anything
    without a Wikipedia article — and "Wikidata offered six items and the title
    test refused them all", which is the state that used to be a wrong header.
    """
    res = {"state": OK, "qid": None, "rejected": [], "candidates": 0}
    if not q.typed_title:
        return res
    try:
        candidates = _candidate_qids(q.typed_title, q.typed_author)
        res["candidates"] = len(candidates)
        entities = wikidata.entities(candidates)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    return _judge_items(res, candidates, entities, q.author, [q.title])


def _wikidata_by_work(q: Question, titles: list) -> dict:
    """The item again, judged against the **work's** titles, not the typed one.

    S1's first ask tests each candidate against what was typed, and a typed
    title is often one no item carries: *Vita da uomo*, *The Outsider*,
    *Umibe no Kafuka* each score 0.00 against the item that is the book
    (Q183883, Q163297, Q579744). SBN's accepted uniform title and Open
    Library's spelling of the work are catalogue statements of what the work is
    called, so the candidates of those titles, and of the typed one, are judged
    against them — the same author check, the same edition refusal, the same
    0.6. Measured before it was written (Step 15B): fitting originals by
    language 45 right · 0 wrong → 51 · 0; no item it accepted is wrong.
    """
    res = {"state": OK, "qid": None, "rejected": [], "candidates": 0}
    try:
        candidates = list(dict.fromkeys(
            qid for t in [q.typed_title, *titles]
            for qid in _candidate_qids(t, q.typed_author)))
        res["candidates"] = len(candidates)
        entities = wikidata.entities(candidates)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    return _judge_items(res, candidates, entities, q.author, titles)


def _judge_items(res: dict, candidates: list, entities: dict, author: str,
                 titles: list) -> dict:
    """The first candidate that is a written work, not an edition, by the
    author, and titled like one of `titles` at 0.6; `res` filled in."""
    for qid in candidates:
        entity = entities.get(qid) or {}
        claims = entity.get("claims") or {}
        if not wikidata.is_written_work(claims):
            res["rejected"].append((qid, "not a written work"))
            continue
        # An edition of the work is not the work, and Wikidata does not always
        # link the two: believed as a work, the 2024 Spanish translation of
        # *Müdigkeitsgesellschaft* makes the header say the book was first
        # published in 2024 in Spanish. Refused, never corrected — the next
        # candidate is judged on its own and N13's English entry then states no
        # original at all, which is what its other two entries already say.
        if wikidata.is_edition(claims):
            res["rejected"].append((qid, "an edition of a work, not the work"))
            continue
        author_qids = wikidata.claim_ids(claims, "P50")
        translator_qids = wikidata.claim_ids(claims, "P655")
        try:
            names = wikidata.labels(author_qids + translator_qids)
            every = wikidata.names(author_qids)
        except SourceError as exc:
            res["state"] = f"error: {exc}"
            return res
        author_names = [names[a] for a in author_qids if a in names]
        # Every label the person carries, not the one shown: Q991 is *Fyodor
        # Dostoyevsky* in English and *Fëdor Dostoevskij* in Italian (N04).
        # A wrong work by the right author is not stopped by this — the
        # title test below is what stops it.
        spelled = [n for a in author_qids for n in every.get(a, [])] or author_names
        if author and spelled and not author_matches(author, spelled):
            res["rejected"].append((qid, "author disagrees"))
            continue
        # Not romanised here: `core.text.normalize` romanises inside every
        # comparison, so a Cyrillic P1476 is matched without being rewritten.
        forms = wikidata.item_forms(entity)
        score, form = max((gate.title_test(t, forms) for t in titles),
                          key=lambda pair: pair[0])
        if not gate.item_is_accepted(score):
            res["rejected"].append((qid, f"title {score:.2f} < {gate.WORK_TITLE_MATCH} "
                                         f"(closest {form!r})"))
            continue
        res.update(qid=qid, entity=entity, forms=forms, score=round(score, 3),
                   matched_form=form, author_names=author_names,
                   translators=[names[t] for t in translator_qids if t in names])
        return res
    return res


# ---------------------------------------------------------------------------
# S1, part 2 — the SBN work guard
# ---------------------------------------------------------------------------

def _catalogued_title(row: dict) -> str:
    """The title half of an OPAC row, as the guard compares it.

    ISBD punctuation and SBN's invisible non-sorting markers (`\\x88Il \\x89`)
    both come off first, because B counts rows whose *title* matches and neither
    of those is part of one.
    """
    return sbn_mobile.title_of(sbn_mobile.clean_text(row.get("title")) or "")


def _sbn_work(q: Question) -> dict:
    """W, A, B and the tier — the guard exactly as the benchmark measured it.

    A is one request. B is the expensive half and runs only when A is below the
    bar: the query's pages and the work's pages, 637 extra OPAC requests over 59
    entries and 151 for the worst one **M**, which is why it is reported per
    case rather than averaged.
    """
    res = {"state": OK, "W": None, "tier": gate.WORK_NONE, "A": None, "B": None,
           "requests": 0, "b_requests": 0, "total": 0}
    if not q.sendable:
        res["state"] = "not asked: the OPAC would discard the term (F15)"
        return res
    try:
        facet = sbn_opac.work_facet(q.title, q.author)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res

    res["requests"] = 1
    res["total"] = facet["total"]
    res["facet_top"] = [(i.get("value"), i.get("results"))
                        for i in sorted(facet["items"],
                                        key=lambda i: -(i.get("results") or 0))[:5]]
    res["facet_truncated"] = len(facet["items"]) >= 50      # F11
    work = gate.pick_work(facet["items"])
    if not work:
        return res

    res.update(W=work["value"], W_count=work["count"], W_ties=work["ties"],
               A=round(gate.affinity_a(q.title, work["value"]), 3))
    if res["A"] >= gate.WORK_TITLE_MATCH:
        res["tier"] = gate.WORK_STRONG
        return res

    # B: of the query's records that really carry this title, how many does SBN
    # file under W. Only reached below the bar, and paid for in requests.
    try:
        base = {"core": "sbn", sbn_opac.ANY: q.title, sbn_opac.AUTHOR: q.author}
        asked = sbn_opac.all_rows(base, first=facet["first"], cap=GUARD_MAX_PAGES)
        # **`ANY` stays in the record pull.** B is the share of the *query's*
        # matching records that SBN also files under W, so the second query is
        # `ANY + AUTHOR + W` and its answer is the intersection (F2: 89 of the
        # work's 143 records for *Cent'anni*). Asking `AUTHOR + W` instead —
        # which is the *listing* query, not the guard's — pulls the whole work
        # and drives B down through a denominator that was never in the
        # question: it put N03 eng at 0.375 where the benchmark measured 0.875,
        # and hit the 12-page cap on the way.
        under_w = sbn_opac.all_rows({**base, sbn_opac.WORK: work["value"]},
                                    cap=GUARD_MAX_PAGES)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    rows = [{"id": r["id"], "title": _catalogued_title(r)} for r in asked["rows"]]
    b, matched, in_work = gate.share_b(
        q.title, rows, [{"id": r["id"]} for r in under_w["rows"]])
    res.update(B=round(b, 3) if b is not None else None,
               B_counts=[len(in_work), len(matched)],
               tier=gate.tier(res["A"], b),
               query_rows=len(asked["rows"]), work_rows=len(under_w["rows"]),
               b_requests=(asked["pages"] - 1) + under_w["pages"],
               truncated=asked["truncated"] or under_w["truncated"],
               failed_pages=asked["failed"] + under_w["failed"])
    res["requests"] += res["b_requests"]
    return res


# ---------------------------------------------------------------------------
# S1, part 3 — Open Library and the name authority
# ---------------------------------------------------------------------------

def _ol_author_keys(q: Question) -> dict:
    """Open Library's own author keys for the name, every one of them.

    Duplicates are the point: 'Jacques Attali' is three author records, and
    resolving to one loses works. They are a *fallback* identity test for a doc
    whose author name is in a script `author_matches` cannot read (村上春樹).
    """
    if not q.typed_author:
        return {"state": OK, "keys": []}
    try:
        return {"state": OK, "keys": [a["key"] for a in ol.author_keys(q.typed_author)]}
    except SourceError as exc:
        return {"state": f"error: {exc}", "keys": []}


def _authority(q: Question, forms=()) -> dict:
    """SBN's name-authority id for the author: one per person for every Latin
    form (A7). Romanised before it is asked, because the OPAC drops the rest.

    **Asked with the fullest name first.** `core=autori` matches the name
    anywhere in a record and returns the rows *alphabetically*, so a bare
    surname buys a window of the alphabet rather than a shortlist — 194 rows for
    *Eco*, of which the first 40 are A–C. Wikidata's P50 label is the way out of
    that, and it costs one request, not one per form: the typed name is only
    asked when the fuller one resolves nothing.
    """
    res = {"state": OK, "id": None, "tried": []}
    if not (q.author and is_latin(q.author)):
        res["state"] = "not asked: the OPAC would discard the term (F15)"
        return res
    queries, seen = [], set()
    for text in [*forms, q.author]:
        key = " ".join(sorted(normalize(text or "")))
        if text and is_latin(text) and key and key not in seen:
            seen.add(key)
            queries.append(text)
    for text in queries[:AUTHORITY_QUERIES]:
        try:
            found = sbn_opac.authorities(text)
        except SourceError as exc:
            res["state"] = f"error: {exc}"
            return res
        # No `dropped` check, and deliberately: the OPAC returns the *bare*
        # `core=autori` total for a term it discarded (4,393,389 on 2026-09-22,
        # and it moves as the authority file grows), so that comparison is a
        # live control and not a constant. `is_latin` is what makes it
        # unreachable here; the control is a live one (F15).
        chosen = gate.pick_authority(found["rows"], q.author, found["total"], forms)
        res["tried"].append({"asked": text, "total": found["total"],
                             "rows": len(found["rows"]), "rule": chosen["rule"]})
        res.update(returned=len(found["rows"]), total=found["total"], asked=text,
                   **chosen)
        if chosen["id"]:
            break
    return res


def _ol_work(q: Question, searches: list, known: list, author_keys: list) -> dict:
    """The main Open Library work, searched by the work's own titles in turn.

    The *original* title first, then the uniform title SBN files it under, and
    only then what was typed — which is the last resort and never the first,
    because a translation's title finds the translation's own work record and
    that is the duplicate-work problem, not the work.

    **What is searched with and what is matched against are not the same list.**
    A search needs one string; the title test needs every title the work is
    known by, because Open Library files *Umibe no Kafuka* under `Kafka on the
    Shore` and the romanised uniform title matches neither the Japanese original
    nor the English record. Scoring the docs against the whole set is also what
    U2 measured the gate on, and it is what makes three entry titles of one book
    reach one work rather than three.

    **When no title's free-text search names a work, each is asked again with
    title and author in their own fields.** The free text finds nothing at all
    for `Müdigkeitsgesellschaft Byung-Chul Han`, and the fielded search finds
    the work (Step 15B). It is a second pass, not a second try per title: asked
    first, the fielded search for the original `活着` finds a one-edition record
    before *To Live* finds the three-edition work.
    """
    res = {"state": OK, "key": None, "tried": []}
    shapes = [("", lambda t: {"q": f"{t} {q.typed_author}".strip()})]
    if q.typed_author:
        shapes.append((", fielded", lambda t: {"title": t, "author": q.typed_author}))
    for shape, params in shapes:
        for label, title in searches:
            if not title:
                continue
            try:
                docs = [ol.parse_doc(d) for d in ol.search(limit=20, **params(title))]
            except SourceError as exc:
                res["state"] = f"error: {exc}"
                res["tried"].append({"by": label + shape, "title": title,
                                     "error": str(exc)[:200]})
                return res
            picked = gate.pick_ol_work(docs, [*known, title], q.typed_author, author_keys)
            res["tried"].append({"by": label + shape, "title": title, "docs": len(docs),
                                 "key": (picked or {}).get("key"),
                                 "closest": None if picked else _closest(docs, [*known, title])})
            if picked:
                doc = next((d for d in docs if d.get("id") == picked["key"]), {})
                res.update(found_by=label + shape,
                           authors=list(doc.get("authors") or []), **picked)
                return res
    return res


def _closest(docs: list, titles: list) -> list:
    """The three nearest docs the title test refused, for the report to name.

    'No confident work match' with nothing beside it is unreadable; the same
    line with the titles that nearly passed says whether the search was wrong or
    the book is simply not there.
    """
    scored = sorted(((round(variant_affinity(d.get("title") or "", titles), 3),
                      d.get("title") or "") for d in docs), reverse=True)
    return scored[:3]


# ---------------------------------------------------------------------------
# S1
# ---------------------------------------------------------------------------

@dataclass
class Identity:
    """One `Work`, and how every part of it was reached.

    The evidence is not decoration. The coverage ledger, the loose-match band
    and the header all read provenance rather than recomputing it, and a
    refusal that cannot say why is indistinguishable from a source being down
    (`CLAUDE.md` rule 5).
    """
    work: Work
    evidence: dict


# Other spellings of the work's title a lookup will try (Step 14). Each costs
# a work-facet request and, below the guard's bar, its B pages; Mahfouz's
# novels carry three or four, which is the case this is for.
MAX_VARIANTS = 6


def _spellings(title: str, variants, cap: int | None = MAX_VARIANTS) -> list:
    """The Latin spellings worth trying beyond the typed one, deduplicated on
    their tokens against it and each other, at most `cap`. The OPAC discards
    any other script (F15), so a non-Latin one is not a spelling it can be
    asked."""
    seen = {frozenset(normalize(title or ""))}
    out = []
    for v in variants or []:
        key = frozenset(normalize(v or ""))
        if v and key and is_latin(v) and key not in seen:
            seen.add(key)
            out.append(v)
    return out[:cap]


def _by_variants(spellings: list, author: str, item: dict, sbn: dict) -> tuple:
    """Wikidata and the SBN guard asked again, one spelling at a time (UC4's
    click, Step 14).

    Nothing is loosened: an item is believed only through the same title test,
    against the spelling that found it, and a uniform title only through the
    guard (or the second signal) on its own question. What changes is that a
    work SBN files under two romanisations — *bain el-qasrain.* holding 8 of
    Mahfouz's records and *bayn al-qasrayn* the one Wikidata agrees with — is
    reached under both, and the item under whichever spelling it knows.
    """
    tried = []
    with Pool(S1_WORKERS) as pool:
        futures = [(v, pool.submit(_wikidata_item, prepare(v, author))
                    if not item["qid"] else None,
                    pool.submit(_sbn_work, prepare(v, author))) for v in spellings]
    for v, item_f, sbn_f in futures:
        got_item = item_f.result() if item_f else None
        got_sbn = sbn_f.result()
        tried.append({"spelling": v, "qid": (got_item or {}).get("qid"),
                      "W": got_sbn["W"], "tier": got_sbn["tier"],
                      "states": [s for s in ((got_item or {}).get("state"),
                                             got_sbn["state"]) if s and s != OK]})
        if got_item and got_item["qid"] and not item["qid"]:
            item = {**got_item, "via_spelling": v}
    return item, [sbn, *[sbn_f.result() for _, _, sbn_f in futures]], tried


def _item_spellings(entity: dict) -> list:
    """The title switch's spellings (decision AV): every name the accepted item
    goes by, its original's own title first. A translation's title is worth
    asking too, because SBN files translations under the original's uniform
    title — *Palace Walk* is how the OPAC reaches `bain el-qasrain.`."""
    p1476 = wikidata.claim_first(entity.get("claims") or {}, "P1476") or {}
    first = [p1476.get("text")] if isinstance(p1476, dict) and p1476.get("text") else []
    return [*first, *wikidata.item_forms(entity)]


def _guards(spellings: list, author: str) -> tuple:
    """The SBN guard on each spelling, and the `tried` rows that record it."""
    with Pool(S1_WORKERS) as pool:
        guards = list(pool.map(lambda v: _sbn_work(prepare(v, author)), spellings))
    tried = [{"spelling": v, "qid": None, "W": g["W"], "tier": g["tier"],
              "states": [g["state"]] if g["state"] != OK else []}
             for v, g in zip(spellings, guards)]
    return guards, tried


def _accept_guards(work: Work, guards: list, item: dict, notes: list,
                   typed_first: bool = True) -> dict | None:
    """Write each guard's W onto the work, if it is believed; the typed
    question's second signal, or None.

    Each is accepted or refused on its own question, exactly as a lookup of
    that spelling would. With `typed_first` the first guard is the typed
    title's, whose refusal is noted and whose second signal is evidence.
    """
    second = None
    for i, guard in enumerate(guards):
        typed = typed_first and i == 0
        if not guard["W"]:
            continue
        agrees = False
        if guard["tier"] != gate.WORK_STRONG and item.get("qid"):
            agrees, score, form = gate.second_signal(guard["W"], item["forms"])
            if typed:
                second = {"agrees": agrees, "score": round(score, 3), "form": form}
        if not gate.work_is_accepted(guard["tier"], agrees):
            if typed:
                notes.append(f"SBN files nothing under a work this question can be "
                             f"believed to be: {guard['W']!r} is {guard['tier']}")
            continue
        if work.sbn_work is None:
            work.sbn_work = guard["W"]
            work.sbn_work_tier = guard["tier"]
            work.sbn_work_via_second_signal = agrees
        elif guard["W"] != work.sbn_work and guard["W"] not in work.sbn_other_works:
            work.sbn_other_works.append(guard["W"])
    return second


def _other_authorities(q: Question) -> dict:
    """The author switch (decision AV): the SBN name-authority records one
    person is filed under in other spellings.

    SBN holds Naguib Mahfouz under four ids, and the one the typed name
    resolves to holds one record; *Bayn al-qaṣrayn* (Cairo 2009) is under
    `Maḥfūẓ, Naǧīb`. So Wikidata's person is looked up by the typed name, as
    author mode does, and each of its Latin names is asked of `core=autori`.
    **An id is kept only when `pick_authority` resolves it for that name** —
    the rule S1 applies to the typed one, with its refusals: two people under
    one name, or a bare surname against a set larger than the rows read, give
    no id rather than a namesake. What the sweep then brings is title-gated
    like every S3 row, so nothing here admits a record.
    """
    res = {"state": OK, "wikidata": OK, "asked": False, "person": None, "forms": [],
           "answers": [], "ids": []}
    if not q.author:
        res["why_not"] = "no author to spell otherwise"
        return res
    person, res["wikidata"] = _person(q.typed_author)
    if res["wikidata"] != OK:
        return res
    if not person:
        res["why_not"] = "Wikidata has no person under this name, so there were no other spellings of it to ask"
        return res
    forms = authors.latin_forms(q.author, person.get("names") or [])[:AUTHOR_FORMS]
    res.update(asked=True, person=person["qid"], forms=forms)

    def ask(form):
        try:
            found = sbn_opac.authorities(form)
        except SourceError as exc:
            return {"form": form, "id": None, "error": str(exc)}
        picked = gate.pick_authority(found["rows"], form, found["total"])
        return {"form": form, "total": found["total"], "id": picked["id"],
                "heading": picked.get("heading"), "rule": picked["rule"]}

    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        res["answers"] = list(pool.map(ask, forms))
    failed = [a for a in res["answers"] if a.get("error")]
    if failed:
        res["state"] = f"error: {failed[0]['error']}"
    res["ids"] = list(dict.fromkeys(a["id"] for a in res["answers"] if a["id"]))
    return res


RECORD_TITLES = 3            # of the SBN work's catalogued titles, most filed first


def _work_record_titles(sbn_work: str, author: str, asked: list) -> dict:
    """The titles SBN's records under the work go by, most frequent first.

    The first page of the listing S2 asks anyway (`AUTHOR` + the work, which
    rule 3 allows), so S2 reads it from the cache. Only Latin titles, and none
    already asked, so no request is spent twice.
    """
    res = {"state": OK, "titles": [], "rows": 0}
    try:
        facet = sbn_opac.work_languages(sbn_work, author)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    rows = sbn_opac.parse_rows(facet["first"])
    res["rows"] = len(rows)
    counts: dict = {}
    for row in rows:
        title = core_title(_catalogued_title(row)).strip()
        if title and is_latin(title) and not any(similarity(title, a) >= gate.WORK_TITLE_MATCH
                                                 for a in asked if a):
            counts[title] = counts.get(title, 0) + 1
    res["titles"] = sorted(counts, key=lambda t: (-counts[t], t))[:RECORD_TITLES]
    return res


def _adopt_item(work: Work, item: dict, via: str = "") -> None:
    """Write an accepted Wikidata item onto the work: the one stated original."""
    entity = item["entity"]
    work.qid = item["qid"]
    # Stored as the catalogue spells them. Matching romanises on the way
    # past (`core.text.normalize`), so nothing is rewritten to be findable.
    work.titles_by_lang = wikidata.titles_by_language(entity)
    work.authors = list(item["author_names"]) or work.authors
    original = wikidata.claim_first(entity.get("claims") or {}, "P1476") or {}
    language = wikidata.original_language(entity)
    work.original_title = original.get("text") or work.titles_by_lang.get(language)
    work.original_language = None if language == langs.UNKNOWN else language
    work.original_year = wikidata.original_year(entity)
    work.original_date = wikidata.original_date(entity)
    work.stated_by = "Wikidata"
    work.basis = (f"item {item['qid']} accepted: {via + ' ' if via else ''}"
                  f"matches {item['matched_form']!r} at {item['score']}")


SBN_LANGUAGE_PAGES = 2       # of the stated language's records, for the check


def _sbn_work_language(work_value: str, author: str) -> dict:
    """The language SBN's own work authority states, and whether to believe it.

    `GET title?core=opere` on the work's id (Step 15B: 10 of 14 works carry a
    *Lingua*, none a year; a bogus id answers `data: null`). The id is the
    *Titolo di opera* link on a record filed under the work. It is not always
    right — *bain el-qasrain* is filed ITALIANO — so it is checked against the
    work's own records (`core.identity.work_language_contradicted`).
    """
    res = {"state": OK, "id": None, "label": None, "stated": None, "believed": None,
           "requests": 0}
    try:
        first = sbn_opac.work_languages(work_value, author)
        res["requests"] += 1
        work_id = None
        for row in sbn_opac.parse_rows(first["first"])[:3]:
            links = sbn_opac.work_links(sbn_opac.record(row["id"]))
            res["requests"] += 1
            best = max(links, key=lambda l: similarity(l["label"], work_value),
                       default=None)
            if best and similarity(best["label"], work_value) >= gate.WORK_TITLE_MATCH:
                work_id = best["id"]
                break
        if not work_id:
            return res
        res["id"] = work_id
        authority = sbn_opac.work_authority(work_id)
        res["requests"] += 1
        res["label"] = authority["language"]
        code = langs.from_sbn(authority["language"])
        if code == langs.UNKNOWN:
            return res
        res["stated"] = code
        titles = []
        if any(i.get("value") == code for i in first["items"]):
            got = sbn_opac.all_rows({"core": "sbn", sbn_opac.AUTHOR: author,
                                     sbn_opac.WORK: work_value, sbn_opac.LANGUAGE: code},
                                    language=code, cap=SBN_LANGUAGE_PAGES)
            res["requests"] += got["pages"]
            titles = [{"title": _catalogued_title(r), "full": r.get("title")}
                      for r in got["rows"]]
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res["contradicted"] = gate.work_language_contradicted(work_value, titles)
    if not res["contradicted"]:
        res["believed"] = code
    return res


TITLE_BOOK_ROWS = 100         # SBN brief records read for a bare title


def title_books(title: str) -> dict:
    """S0 for a title with no author: the books it names, and whose they are.

    Rule 3 stands: the OPAC is not asked. Wikidata's items, Open Library's work
    docs and the mobile gateway's brief records are, each titled like the
    question at 0.6, and `core.identity.title_books` groups them by person.
    One book means one author the sources agree on, and the lookup runs with
    them; several mean the reader picks (decision AN). The old path adopted an
    author from Open Library alone, and only when its matched works agreed.
    """
    q = prepare(title, "")
    res = {"books": [], "candidates": 0, "sources": {}}

    def wikidata_books():
        out = []
        try:
            qids = _candidate_qids(q.typed_title, "")
            entities = wikidata.entities(qids)
            for qid in qids:
                claims = (entities.get(qid) or {}).get("claims") or {}
                if not wikidata.is_written_work(claims) or wikidata.is_edition(claims):
                    continue
                score, _ = gate.title_test(q.title, wikidata.item_forms(entities[qid]))
                if not gate.item_is_accepted(score):
                    continue
                names = wikidata.labels(wikidata.claim_ids(claims, "P50"))
                year = wikidata.original_year(entities[qid])
                out.append({"source": "Wikidata", "title": q.typed_title,
                            "authors": list(names.values()),
                            "year": int(year) if year else None, "editions": 1})
        except SourceError as exc:
            return out, f"error: {exc}"
        return out, OK

    def open_library_books():
        out = []
        try:
            for doc in ol.search(title=q.typed_title, limit=50):
                parsed = ol.parse_doc(doc)
                if similarity(q.title, parsed["title"]) < gate.WORK_TITLE_MATCH:
                    continue
                out.append({"source": "Open Library", "title": parsed["title"],
                            "authors": parsed["authors"],
                            "year": int(parsed["year"]) if parsed["year"] else None,
                            "editions": parsed["edition_count"] or 1})
        except SourceError as exc:
            return out, f"error: {exc}"
        return out, OK

    def sbn_books():
        out = []
        if not is_latin(q.title):
            return out, "not asked: a title in another script"
        try:
            records, _ = sbn_mobile.search(title=q.title, rows=TITLE_BOOK_ROWS)
        except SourceError as exc:
            return out, f"error: {exc}"
        for rec in records:
            row = sbn_mobile.parse_record(rec)
            shown = _catalogued_title({"title": rec.get("titolo")})
            if not gate.is_text_medium(row["medium"]):
                continue
            if similarity(q.title, shown) < gate.WORK_TITLE_MATCH:
                continue
            main = sbn_mobile.clean_text(rec.get("autorePrincipale"))
            out.append({"source": "SBN", "title": shown,
                        "authors": [main] if main else row["authors"][:1],
                        "year": int(row["year"]) if (row["year"] or "").isdigit() else None,
                        "editions": 1})
        return out, OK

    with Pool(3) as pool:
        futures = {"Wikidata": pool.submit(wikidata_books),
                   "Open Library": pool.submit(open_library_books),
                   "SBN": pool.submit(sbn_books)}
    candidates = []
    for name, future in futures.items():
        found, state = future.result()
        candidates += found
        res["sources"][name] = state
    res["candidates"] = len(candidates)
    res["books"] = gate.title_books(candidates)
    return res


def identify(title: str, author: str, variants=(), *, title_spellings: bool = False,
             author_spellings: bool = False) -> Identity:
    """S1. One `Work` for this question, or a `Work` that says it found nothing.

    **A book with no identity is normal, not an error state** (A1: no source
    reaches one identity for every entry title — SBN 22 of 37 books, Wikidata
    14, Open Library 13), so this returns an unidentified `Work` rather than
    raising, and the lookup carries on.

    `variants` are other spellings of the same title, handed over by author
    mode's row (Step 14). With none, nothing below changes.

    The two switches are the reader's (decision AV), off unless ticked, because
    each costs requests on every lookup and helps few. `title_spellings` asks
    the SBN guard again under the accepted Wikidata item's other names;
    `author_spellings` finds the SBN name records the person is filed under in
    other spellings, for S3 to sweep. Neither loosens a gate.
    """
    q = prepare(title, author)
    with Pool(S1_WORKERS) as pool:
        item_f = pool.submit(_wikidata_item, q)
        sbn_f = pool.submit(_sbn_work, q)
        keys_f = pool.submit(_ol_author_keys, q)
        item, sbn, keys = item_f.result(), sbn_f.result(), keys_f.result()
    offered = _item_spellings(item["entity"]) if title_spellings and item["qid"] else []
    spellings = _spellings(q.title, [*variants, *offered])
    by_title = {"on": title_spellings, "item": item["qid"],
                "offered": len(_spellings(q.title, [*variants, *offered], cap=None)),
                "asked": list(spellings)}
    guards, tried = [sbn], []
    if spellings:
        item, guards, tried = _by_variants(spellings, q.author, item, sbn)

    work = Work()
    notes = list(q.notes)

    # -- Wikidata: the only source that *states* an original --------------
    if item["qid"]:
        _adopt_item(work, item)
    elif item["rejected"]:
        notes.append(f"Wikidata: {len(item['rejected'])} candidate(s), none accepted "
                     f"({item['rejected'][0][1]})")

    # -- SBN: the work authority, through the guard and the second signal ---
    # One guard per spelling asked; the typed one first.
    second = _accept_guards(work, guards, item, notes)

    # -- Open Library: by the work's titles, never by the typed one first ---
    # Each title is searched with, and its core title after it: a search
    # carrying a subtitle finds nothing at all — `Noise: The Political Economy
    # of Music` returns zero docs where `Noise` returns the work — which is why
    # the benchmark tried `original_core` as a query of its own.
    seen, wanted = set(), []
    # Open Library files most works under their English title — *If on a
    # Winter's Night a Traveler*, not Calvino's own — so an accepted item's
    # English title is asked too, after the three the work goes by.
    for label, title in (("original title", work.original_title),
                         ("uniform title", work.sbn_work),
                         ("typed title", q.typed_title),
                         ("English title", work.titles_by_lang.get("eng"))):
        for form, spelling in ((title, label), (core_title(title or ""), f"{label}, core")):
            if form and form.lower() not in seen:
                seen.add(form.lower())
                wanted.append((spelling, form))
    with Pool(3) as pool:
        ol_f = pool.submit(_ol_work, q, wanted, work.titles(), keys["keys"])
        authority_f = pool.submit(_authority, q, work.authors)
        others_f = pool.submit(_other_authorities, q) if author_spellings else None
        ol_work, authority = ol_f.result(), authority_f.result()
        by_author = others_f.result() if others_f else None
    if ol_work["key"]:
        work.ol_keys = [ol_work["key"]]
        work.ol_title = ol_work["title"]
        if not work.authors:
            work.authors = [a for a in (ol_work.get("authors") or [])]
        # The uniform title is a normalised search key and is never displayed;
        # what it finds in Open Library is the same work properly spelled, and
        # that *is* a catalogue's statement of what the work is called.
        if not work.original_title and str(ol_work.get("found_by")).startswith("uniform title"):
            work.original_title = ol_work["title"]
            work.stated_by = "SBN uniform title, spelled by Open Library"
            work.basis = (f"SBN files it under {work.sbn_work!r} "
                          f"({sbn['tier']}); Open Library has that work as "
                          f"{ol_work['title']!r}")
    # -- Wikidata again, by the work's own titles --------------------------
    # Only when the typed title found no item and a catalogue has said what the
    # work is called: SBN through the guard, or Open Library.
    by_work = None
    titles = [t for t in dict.fromkeys([work.ol_title, work.sbn_work]) if t]
    if not work.qid:
        if titles:
            by_work = _wikidata_by_work(q, titles)
            if by_work["qid"]:
                _adopt_item(work, by_work, via="the work's title")
    # -- ... and by the titles SBN files under its work ---------------------
    # A romanised uniform title matches no item whose names are in kanji or
    # hanzi (*umibe no kafuka*, *huozhe*), but the records SBN files under the
    # work carry its translations' titles — *Kafka sulla spiaggia*, *Vivere!* —
    # and those are the item's own labels (Step 15B, E04 and N16).
    by_records = None
    if not work.qid and work.sbn_work and q.sendable:
        by_records = _work_record_titles(work.sbn_work, q.author, [q.typed_title, *titles])
        if by_records["titles"]:
            by_records.update(_wikidata_by_work(q, by_records["titles"]))
            if by_records["qid"]:
                _adopt_item(work, by_records, via="a title SBN files under its work")
    # An item adopted here came after Open Library was asked, so its titles
    # were never searched with; *Kafka on the Shore* is filed under `海辺のカフカ`.
    ol_again = None
    late = (by_work or {}).get("qid") or (by_records or {}).get("qid")
    if late and not work.ol_keys:
        again = [(label, t) for label, t in (("original title", work.original_title),
                                             ("English title", work.titles_by_lang.get("eng")))
                 if t]
        ol_again = _ol_work(q, again, work.titles(), keys["keys"])
        if ol_again["key"]:
            work.ol_keys = [ol_again["key"]]
            work.ol_title = ol_again["title"]
    # The title switch, for an item adopted only now: its names were never
    # asked of the guard, and a work the typed title cannot reach (a title in
    # Arabic script is never sent, F15) is reached by them or not at all.
    if title_spellings and late and not item["qid"]:
        late_item = by_work if (by_work or {}).get("qid") else by_records
        asked = {frozenset(normalize(v)) for v in spellings}
        extra = [v for v in _spellings(q.title, _item_spellings(late_item["entity"]), cap=None)
                 if frozenset(normalize(v)) not in asked]
        by_title.update(item=late_item["qid"], offered=len(extra),
                        asked=extra[:MAX_VARIANTS])
        if by_title["asked"]:
            late_guards, late_tried = _guards(by_title["asked"], q.author)
            _accept_guards(work, late_guards, late_item, notes, typed_first=False)
            guards += late_guards
            tried += late_tried

    # -- SBN's work authority: the language, when nothing else stated one ---
    sbn_language = None
    if work.sbn_work and not work.original_language and q.sendable:
        sbn_language = _sbn_work_language(work.sbn_work, q.author)
        if sbn_language.get("believed"):
            work.original_language = sbn_language["believed"]
            work.stated_by = work.stated_by or "SBN work authority"
            work.basis = "; ".join(b for b in (
                work.basis, f"SBN's work authority {sbn_language['id']} states the "
                            f"language {sbn_language['label']}") if b)

    if work.author_id is None and authority.get("id"):
        work.author_id = authority["id"]
    if by_author:
        work.author_other_ids = [i for i in by_author["ids"] if i != work.author_id]
    # SBN's own spelling of the author, kept for matching and never shown. It is
    # what tells a record credited to a *different person* from one credited to
    # the same man under another transliteration — `Maḥfūẓ, Naǧīb` against the
    # typed `Naguib Mahfouz` (`core.identity.credited_to_another`).
    work.author_headings = [h for h in (authority.get("heading"),
                                        authority.get("display")) if h]

    return Identity(work=work, evidence={
        "question": {"title": q.title, "author": q.author,
                     "typed_title": q.typed_title, "typed_author": q.typed_author,
                     "sendable_to_opac": q.sendable},
        # The forms stay: they are the second signal's input, and a rescue that
        # cannot say which name it agreed with cannot be audited.
        "wikidata": {k: v for k, v in item.items() if k != "entity"},
        "sbn_work": sbn, "second_signal": second, "open_library": ol_work,
        "wikidata_by_work": ({k: v for k, v in by_work.items() if k != "entity"}
                             if by_work else None),
        "wikidata_by_records": ({k: v for k, v in by_records.items() if k != "entity"}
                                if by_records else None),
        "open_library_again": ol_again,
        "sbn_work_language": sbn_language,
        "spellings": tried,
        "title_spellings": by_title if title_spellings else None,
        "author_spellings": by_author,
        "ol_author_keys": keys, "authority": authority, "notes": notes,
        "sources": {"Wikidata": _worst(item["state"], *([by_work["state"]] if by_work else []),
                                       *([by_author["wikidata"]] if by_author else [])),
                    "SBN": _worst(sbn["state"], *([sbn_language["state"]] if sbn_language else [])),
                    "Open Library": _worst(ol_work["state"], keys["state"]),
                    "SBN authority": _worst(authority["state"],
                                            *([by_author["state"]] if by_author else []))},
    })


def _worst(*states) -> str:
    """One state for one source: the first failure, or ok. Two Open Library
    calls that disagree must not report as healthy because one of them worked."""
    return next((s for s in states if s != OK), OK)


# ---------------------------------------------------------------------------
# S2 — list the editions of that identity
# ---------------------------------------------------------------------------

@dataclass
class Listing:
    """Every record the work's identity reaches, and how the reaching went.

    `store` is a `RecordStore`, so the view is derived from it rather than
    assembled here (build rule 3), and S3, S4 and the duplicate
    works write into the same one. `evidence` is what the coverage ledger and
    the *Incomplete* note read: totals, per-language counts, the pages that
    failed, and every record whose stated language was disbelieved.
    `date_buckets` is each language page's `dataf[]` facet and the ids it held,
    which `check_dates` reconciles; kept off the evidence, which the page reads.
    """
    store: RecordStore
    evidence: dict
    date_buckets: list = field(default_factory=list)


def _listing_language_pages(work: str, author: str, facet: dict) -> dict:
    """Every language page of one work, `{code: rows}`, deterministic.

    The pages run `sbn_opac.PAGE_WORKERS` at a time but are **assembled in
    facet order**, not in completion order: a record filed under two languages
    (51 of 2,603 rows — a parallel Russian/Italian text, a Latin/Italian
    edition) is written once, and which of its languages it keeps must not
    depend on which thread finished first. The store's arrival order is what
    breaks ties in every derivation downstream of it.
    """
    codes = [str(i["value"]) for i in
             sorted(facet["items"], key=lambda i: (-(i.get("results") or 0), str(i.get("value"))))
             if i.get("value")]
    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        futures = {code: pool.submit(sbn_opac.work_records, work, author, code)
                   for code in codes}
    out = {}
    for code in codes:                      # facet order, not completion order
        try:
            out[code] = futures[code].result()
        except SourceError as exc:
            out[code] = {"rows": [], "total": None, "pages": 0, "truncated": False,
                         "failed": [{"page": "all", "error": str(exc)[:200]}]}
    return out


def _sbn_listing(work: Work, author: str) -> dict:
    """W's listing, and every further uniform title S1 accepted beside it.

    The others (`Work.sbn_other_works`) are the same work under another
    romanisation, each through the guard on its own spelling; their rows join
    W's, once per record id, and their counts join W's evidence so the
    coverage ledger counts what was read.
    """
    res = _sbn_listing_one(work.sbn_work, author)
    if not work.sbn_other_works or not res["asked"]:
        return res
    seen = {r["id"] for r in res["rows"]}
    res["others"] = []
    for other in work.sbn_other_works:
        got = _sbn_listing_one(other, author)
        res["others"].append({k: got[k] for k in ("W", "state", "total", "requests")})
        if got["state"] != OK and res["state"] == OK:
            res["state"] = got["state"]
        res["requests"] += got["requests"]
        res["total"] += got["total"]
        res["failed"] += got["failed"]
        res["truncated"] = res["truncated"] or got["truncated"]
        for code, n in got["by_language"].items():
            res["by_language"][code] = (res["by_language"].get(code) or 0) + (n or 0)
        res["multi_language"].update(got["multi_language"])
        res["recovered"] += got["recovered"]
        res["date_buckets"] += got["date_buckets"]
        for row in got["rows"]:
            if row["id"] not in seen:
                seen.add(row["id"])
                res["rows"].append(row)
    return res


def _sbn_listing_one(sbn_work: str | None, author: str) -> dict:
    """Every SBN record filed under W, placed by the language page that held it.

    The listing query is `{core, AUTHOR, W}` and **never carries `ANY`** — that
    is the guard's query and its answer is the intersection (F2). No full record
    is fetched: a row already carries its BID, its catalogued title, its main
    author, its imprint and — from the page it came back on — its language, and
    98.4% of them parse a year (A3). That is the whole 34.5 s -> 3.5 s.
    """
    res = {"state": OK, "asked": True, "W": sbn_work, "total": 0, "rows": [],
           "requests": 0, "by_language": {}, "failed": [], "truncated": False,
           "facet_truncated": False, "multi_language": {}, "recovered": [],
           "date_buckets": []}
    if not (sbn_work and author):
        # **Not asked is not a failure.** A book with no accepted work is a
        # normal answer (A1), and reporting it as an unhealthy source would put
        # `partial` on a lookup where nothing went wrong (`CLAUDE.md` rule 5 is
        # the other direction: a failure must never look like an empty result).
        res.update(asked=False, why_not="no accepted SBN work for this question")
        return res
    try:
        facet = sbn_opac.work_languages(sbn_work, author)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res["requests"] = 1
    res["total"] = facet["total"]
    res["facet_truncated"] = len(facet["items"]) >= 50          # F11
    res["by_language"] = {str(i["value"]): i.get("results")
                          for i in facet["items"] if i.get("value")}

    pages = _listing_language_pages(sbn_work, author, facet)
    seen, rows = {}, []
    for code, answer in pages.items():
        res["requests"] += answer["pages"]
        res["truncated"] = res["truncated"] or answer["truncated"]
        res["failed"] += [{"language": code, **f} for f in answer["failed"]]
        if answer.get("years"):
            res["date_buckets"].append({
                "work": sbn_work, "language": code, "years": answer["years"],
                "ids": [row["id"] for row in answer["rows"]],
                "complete": not (answer["truncated"] or answer["failed"])})
        for row in answer["rows"]:
            if row["id"] in seen:
                seen[row["id"]].append(code)        # a parallel-text edition
                continue
            seen[row["id"]] = [code]
            rows.append(row)
    res["multi_language"] = {bid: codes for bid, codes in seen.items() if len(codes) > 1}

    # **A bucket never shrinks silently.** The language pages are the whole work
    # on every book measured so far (2,603 of 2,603 rows over 32 works), but the
    # facet caps at 50 items (F11) and a failed page loses its rows, so when the
    # count comes back short the unfiltered work is paged to name what is
    # missing. Those rows keep no language rather than being guessed into one.
    if len(rows) < facet["total"]:
        try:
            whole = sbn_opac.all_rows({"core": "sbn", sbn_opac.AUTHOR: author,
                                       sbn_opac.WORK: sbn_work},
                                      first=facet["first"],
                                      cap=sbn_opac.COMPLETENESS_MAX_PAGES)
        except SourceError as exc:
            res["state"] = f"error: {exc}"
            return res
        res["requests"] += whole["pages"] - 1       # page 1 was the facet's
        res["failed"] += [{"language": None, **f} for f in whole["failed"]]
        for row in whole["rows"]:
            if row["id"] not in seen:
                seen[row["id"]] = []
                rows.append(row)
                res["recovered"].append(row["id"])
    res["rows"] = rows
    return res


def _ol_listing(work: Work) -> dict:
    """Open Library's own editions of the main work, by key and never by title.

    `/works/<key>/editions.json?limit=1000`, following `links.next` — verified
    to return every known edition for 45 of 45 works (F19). The duplicate work
    records this misses are Step 13's, and they are opened by key as well.
    """
    res = {"state": OK, "asked": True, "keys": list(work.ol_keys), "rows": [],
           "size": None, "failed": []}
    if not work.ol_keys:
        res.update(asked=False, why_not="no Open Library work for this question")
        return res
    for key in work.ol_keys:
        try:
            answer = ol.editions(key)
        except SourceError as exc:
            res["state"] = f"error: {exc}"
            return res
        res["rows"] += answer["rows"]
        res["failed"] += answer["failed"]
        res["size"] = (res["size"] or 0) + (answer["size"] or 0)
    if res["failed"] and res["state"] == OK:
        res["state"] = f"error: {res['failed'][0]}"
    return res


def _place(record, work: Work, notes: list) -> None:
    """Believe, or disbelieve, the language this record states about itself.

    Two contradictions, both `CLAUDE.md` rule 4's: a record that names a
    translator while claiming the work's original language, and a record whose
    title is in a script the language it claims is not written in. Neither is
    corrected — `linguaPubblicazione` is the only language signal there is, so a
    record that contradicts itself simply stops being evidence of a language and
    the row lands under *lingua non indicata*.
    """
    if gate.language_contradicts_itself(record, work.original_language):
        notes.append({"record": record.id, "language": record.language,
                      "why": "names a translator while claiming the work's "
                             "original language"})
        record.language = langs.UNKNOWN
    elif gate.language_contradicts_script(record):
        notes.append({"record": record.id, "language": record.language,
                      "why": "the title is not in a script that language is "
                             "written in"})
        record.language = langs.UNKNOWN


def list_editions(identity: Identity, store: RecordStore | None = None) -> Listing:
    """S2. The work's editions, from every identity S1 reached.

    **Nothing here uses what the reader typed** except the author, which every
    OPAC query must carry (`CLAUDE.md` rule 3) and which is the string the guard
    was measured with. The titles are gone: a record is here because a catalogue
    filed it under this work, not because its title looked right — which is why
    nothing in S2 calls the title gate at all. That gate is S3's, where records
    arrive with no such statement behind them.

    Both halves run at once; they are different hosts and neither waits on the
    other. A source that fails leaves its state on the report and the other
    source's records stand (`CLAUDE.md` rule 5).
    """
    work = identity.work
    author = identity.evidence["question"]["author"]
    store = store if store is not None else RecordStore()
    with Pool(2) as pool:
        sbn_f = pool.submit(_sbn_listing, work, author)
        ol_f = pool.submit(_ol_listing, work)
        sbn, ol_rows = sbn_f.result(), ol_f.result()

    disbelieved = []
    for row in sbn["rows"]:
        record = Record(**sbn_opac.listing_record(row),
                        provenance=Provenance("SBN", WORK_LISTING, UNIFORM_TITLE))
        _place(record, work, disbelieved)
        store.put(record)
    for row in ol_rows["rows"]:
        fields = {k: v for k, v in row.items()
                  if k not in ("translation_of", "works")}
        record = Record(**fields, provenance=Provenance("Open Library", WORK_EDITIONS,
                                                        WORK_KEY))
        _place(record, work, disbelieved)
        store.put(record)

    return Listing(store=store, date_buckets=sbn.get("date_buckets") or [], evidence={
        "sbn": {k: v for k, v in sbn.items() if k not in ("rows", "date_buckets")},
        "sbn_rows": len(sbn["rows"]),
        "open_library": {k: v for k, v in ol_rows.items() if k != "rows"},
        "open_library_rows": len(ol_rows["rows"]),
        "language_disbelieved": disbelieved,
        "records": len(store),
        "sources": {"SBN": sbn["state"], "Open Library": ol_rows["state"]},
    })


# ---------------------------------------------------------------------------
# S3 — the recovery route (Step 9)
# ---------------------------------------------------------------------------

# Pages of one candidate query. 12 is the guard's own cap and 240 rows is what
# it buys; a free-text probe and an author sweep are both open-ended, and an
# author's whole catalogue is not the answer to anything. What the cap loses is
# reported rather than hidden (build rule 10).
RECOVERY_MAX_PAGES = sbn_opac.MAX_PAGES

# ISBNs probed against SBN per lookup, and the rows one probe reads. The
# benchmark's ISBN route found 25 records over 40 books and leaked 1 **M**, so
# this is a cheap route with a small yield and it is capped like one.
ISBN_PROBES = 12
ISBN_ROWS = 25

# The typed-title branch only, and it is the only place S3 reads a full record:
# the brief rows of *both* SBN APIs carry no language, which is the 34.5 s this
# shape was built to stop paying. Nothing outside a book with **no identity at
# all** pays it here; the rest waits for S4 (Step 12).
REVERSE_ENRICH = 25
REVERSE_WORKERS = 6

# `core.identity.identifies` reads this exact string and answers STRONG: a
# shared ISBN is the catalogue agreeing on an object, not an inference about
# one. The route's own name is `core.model.ISBN_PROBE`; this is the verdict's.
ISBN_REASON = "isbn match"


@dataclass
class Recovery:
    """What the routes reached beside the listing, and what the gate did with it.

    The store is S2's — S3 is a producer writing into it, not a second list
    (build rule 2). `evidence` carries the per-probe counts, the
    admitted and refused totals with their scores, and every truncation, which
    is what the coverage ledger and the loose-match band read in Step 11.
    """
    store: RecordStore
    evidence: dict


def gate_variants(work: Work) -> list:
    """The titles a recovered record's own title is matched against.

    `Work.titles()` leaves the uniform title out on purpose — it is normalised,
    accent-stripped and sometimes punctuated, a search key and not a title. U2
    measured this gate against the Wikidata cluster **plus W** plus Open
    Library's title, so W goes back in here or the number Step 2 reports is not
    the number this ships (noticed in Step 9).
    """
    seen, out = set(), []
    for title in [*work.titles(), work.sbn_work, *work.sbn_other_works]:
        if title and title.lower() not in seen:
            seen.add(title.lower())
            out.append(title)
    return out


def _probeable(title: str, author: str) -> str | None:
    """Why this free-text probe must not be sent, or None.

    Two refusals, both of them a query that would come back looking like an
    answer. Non-Latin text is **discarded** by the OPAC, which then answers with
    the unfiltered set (F15). And a single `/` makes Solr read the value as an
    unterminated regex literal: HTTP 200, an `error` object, no records
    (`docs/sbn-api.md` trap 8) — a request that
    can only fail, so it is not made rather than made and counted.
    """
    if not (title and author):
        return "no title or no author"
    if not (is_latin(title) and is_latin(author)):
        return ("not Latin script: the OPAC discards the term and answers with "
                "the unfiltered set (F15)")
    if "/" in title:
        return "a single '/' makes SBN's Solr answer 200 with an error and no records"
    return None


def _title_probe(title: str, author: str) -> dict:
    """Every SBN record matching one of the work's titles, with the author.

    `{core, ANY, AUTHOR}` — the guard's own query, asked again with a title the
    *work* is known by rather than the one the reader typed. What comes back is
    candidates and nothing more: the gate below decides, and a record reached
    this way carries no catalogue statement that it belongs to the work.
    """
    res = {"title": title, "state": OK, "asked": False, "rows": [], "pages": 0,
           "total": 0, "truncated": False, "failed": []}
    why_not = _probeable(title, author)
    if why_not:
        res["why_not"] = why_not
        return res
    res["asked"] = True
    try:
        answer = sbn_opac.all_rows({"core": "sbn", sbn_opac.ANY: title,
                                    sbn_opac.AUTHOR: author},
                                   cap=RECOVERY_MAX_PAGES)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res.update(rows=answer["rows"], pages=answer["pages"], total=answer["total"],
               truncated=answer["truncated"], failed=answer["failed"])
    return res


def _author_sweep(work: Work) -> dict:
    """Every SBN record filed under this person's name authority.

    The route the work listing cannot replace: SBN's work links are partial —
    334 same-work records over 40 books are not linked to W **M** — and
    `UFI0556368` is reachable only this way. It asks the *authority id*, not a
    name, so it never matches a namesake; the cost is that a book whose author
    has no authority id gets no sweep at all, and `work.author_id` is None for
    12 of 96 entries **M** because `pick_authority` refuses a bare surname
    against a result set larger than the window it read.
    """
    return _sweep(work.author_id)


def _sweep(authority_id: str | None) -> dict:
    """One name authority's records, as `_author_sweep` describes."""
    res = {"state": OK, "asked": False, "authority": authority_id, "rows": [],
           "pages": 0, "total": 0, "truncated": False, "failed": []}
    if not authority_id:
        res["why_not"] = "no SBN name authority was accepted for this person"
        return res
    res["asked"] = True
    try:
        answer = sbn_opac.records_by_authority(authority_id)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res.update(rows=answer["rows"], pages=answer["pages"], total=answer["total"],
               truncated=answer["truncated"], failed=answer["failed"])
    return res


def _isbn_probe(isbn: str) -> dict:
    """SBN's records for one ISBN. The mobile gateway, because the OPAC has no
    ISBN key and `post()` refuses one that is not on its whitelist."""
    res = {"isbn": isbn, "state": OK, "records": []}
    try:
        records, _ = sbn_mobile.search(isbn=isbn, rows=ISBN_ROWS)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res["records"] = records
    return res


def _store_isbns(store: RecordStore) -> list:
    """ISBNs already in hand, in arrival order, capped.

    They come from Open Library: an SBN listing row carries no ISBN (F5), so
    every one of these is the other source's, which is what makes the probe
    worth making at all.
    """
    seen = []
    for record in store.records():
        for raw in [record.isbn, *record.isbns_raw]:
            value = (raw or "").replace("-", "").strip()
            if value and value not in seen:
                seen.append(value)
            if len(seen) >= ISBN_PROBES:
                return seen
    return seen


def _candidates(work: Work, author: str, store: RecordStore) -> tuple:
    """(candidates, evidence) — every route's rows, as `(Record, route, reason)`.

    The three routes run at once and none of them decides anything: a producer
    fetches, parses and returns (build rules 1 and 2). A route that
    fails leaves its state on the evidence and the others' rows stand.
    """
    titles = gate_variants(work)
    isbns = _store_isbns(store)
    with Pool(3) as pool:
        probes_f = pool.submit(lambda: [_title_probe(t, author) for t in titles])
        sweep_f = pool.submit(_author_sweep, work)
        # The author switch's other name authorities (decision AV), one at a
        # time beside the rest: each is up to `MAX_PAGES` OPAC pages.
        others_f = pool.submit(lambda: [_sweep(i) for i in work.author_other_ids])
        probes, sweep, others = probes_f.result(), sweep_f.result(), others_f.result()
    with Pool(min(len(isbns), sbn_opac.PAGE_WORKERS) or 1) as pool:
        isbn_probes = list(pool.map(_isbn_probe, isbns))

    out = []
    for probe in probes:
        for row in probe["rows"]:
            out.append((Record(**sbn_opac.listing_record(row),
                               provenance=Provenance("SBN", TITLE_PROBE, REFUSED)),
                        TITLE_PROBE, TITLE_PROBE))
    for row in [r for s in (sweep, *others) for r in s["rows"]]:
        out.append((Record(**sbn_opac.listing_record(row),
                           provenance=Provenance("SBN", AUTHOR_SWEEP, REFUSED)),
                    AUTHOR_SWEEP, AUTHOR_SWEEP))
    for probe in isbn_probes:
        for raw in probe["records"]:
            fields = full_fields(sbn_mobile.parse_record(raw))
            if not fields["id"]:
                continue
            out.append((Record(**fields, provenance=Provenance("SBN", ISBN_PROBE, REFUSED)),
                        ISBN_PROBE, ISBN_REASON))

    evidence = {
        "titles": titles,
        "title_probes": [{k: v for k, v in p.items() if k != "rows"} | {"rows": len(p["rows"])}
                         for p in probes],
        "author_sweep": {k: v for k, v in sweep.items() if k != "rows"} | {"rows": len(sweep["rows"])},
        "other_author_sweeps": [{k: v for k, v in s.items() if k != "rows"}
                                | {"rows": len(s["rows"])} for s in others],
        "isbn_probes": [{k: v for k, v in p.items() if k != "records"}
                        | {"records": len(p["records"])} for p in isbn_probes],
        "candidates": len(out),
        "sources": {"SBN": _worst(*[p["state"] for p in probes], sweep["state"],
                                  *[s["state"] for s in others],
                                  *[p["state"] for p in isbn_probes])},
    }
    return out, evidence


def _judge(candidates: list, work: Work, author: str, store: RecordStore) -> dict:
    """Apply the identifying-signal gate and write every candidate to the store.

    **A refusal is stored, not dropped** (decision N): the record keeps its
    route and its score and the loose-match band reads them in Step 11, because
    a record that was thrown away cannot be audited and "what was refused" is a
    disclosure. Nothing here displays it.
    """
    variants = gate_variants(work)
    res = {"admitted": 0, "refused": 0, "by_evidence": {}, "admitted_ids": [],
           "already_held": 0, "scores": {}, "language_disbelieved": []}
    strong, refused = [], []
    for record, route, reason in candidates:
        score = round(variant_affinity(record.title, variants), 3) if variants else 0.0
        if gate.identifies(record, reason, variants) == gate.STRONG:
            evidence = ISBN_MATCH if reason == ISBN_REASON else TITLE_MATCH
            strong.append((record, route, evidence, score))
        else:
            refused.append((record, route, REFUSED, score))

    for record, route, evidence, score in strong + refused:
        record.provenance = Provenance(record.source, route, evidence, score)
        _place(record, work, res["language_disbelieved"])
        held = store.put(record)
        if evidence != REFUSED:
            res["admitted"] += 1
            res["by_evidence"][evidence] = res["by_evidence"].get(evidence, 0) + 1
            if held is not record:
                res["already_held"] += 1
            else:
                res["admitted_ids"].append(record.id)
        else:
            res["refused"] += 1
    res["admitted_ids"] = sorted(res["admitted_ids"])
    # The band's shape, not its rows: how many refusals scored anything at all
    # is what says whether a floor would empty it (Step 11 decides that).
    res["scores"] = {"refused_above_zero": sum(1 for *_, s in refused if s > 0),
                     "refused_at_zero": sum(1 for *_, s in refused if not s)}
    return res


def recover(identity: Identity, store: RecordStore | None = None) -> Recovery:
    """S3. The records the authority listing cannot reach, title-gated.

    The listing is incomplete **by construction**: 334 SBN same-work records
    over 40 books are not linked to W and 98 Open Library editions sit in
    duplicate work records **M**. So three routes run beside it — the work's
    titles as free text, the author's name authority, and the ISBNs already in
    hand — and every row they return is gated on the *work's* titles at
    `core.identity.IDENTIFYING_TITLE_MATCH`, never on the title the reader typed
    (decision AB, 2026-09-23, on Step 2's curve).

    **The routes run for any work with titles to gate on** — a W the guard
    accepted, or a Wikidata item or Open Library work with none (decision AP,
    Step 15B). Step 9 ran them only beside W, on Step 2's measurement that the
    class with no work admits least (33 of 199, against 266 of 288); but *least*
    was all: N04's *Delitto e castigo* and *Crime and Punishment* and N16's *To
    Live* reached no SBN record at all, where the old path listed 115, 33 and 10.
    Its rows are gated and labelled as every S3 row is (decisions Z, AL) — a
    record SBN heads under somebody else, Gozzano's *Le poesie* for *Poesie* +
    Montale, stays in the list, credited to him.

    A book with **no identity at all** is a different question and gets a
    different branch, `_reverse`.
    """
    work = identity.work
    author = identity.evidence["question"]["author"]
    typed = identity.evidence["question"]["typed_title"]
    store = store if store is not None else RecordStore()
    evidence = {"asked": False, "routes": {}, "gate": {},
                "threshold": gate.IDENTIFYING_TITLE_MATCH, "reverse": None,
                "sources": {}}

    if work.sbn_work or (work.identified and gate_variants(work)):
        candidates, routes = _candidates(work, author, store)
        evidence.update(asked=True, routes=routes,
                        gate=_judge(candidates, work, author, store),
                        sources=routes["sources"])
    elif not work.identified:
        evidence["reverse"] = _reverse(typed, work, author, store)
        evidence["sources"] = evidence["reverse"]["sources"]
    else:
        evidence["why_not"] = "the work was identified with no title to gate on"
    evidence["records"] = len(store)
    return Recovery(store=store, evidence=evidence)


# ---------------------------------------------------------------------------
# S3's other branch — the typed title, for a book with no identity
# ---------------------------------------------------------------------------

def full_fields(raw: dict) -> dict:
    """One parsed SBN full record, with its holdings as `core.model.Holding`.

    `catalog/` may not import `core/`, so its parsers hand back plain dicts and
    somebody has to build the dataclass. That somebody is here: a `Record` whose
    `holdings` are dicts derives an `Edition` that raises the first time the
    view reads one, which is how this was found — in the sweep, not in the
    suite, because no S2 row carries a holding at all. **S4 uses the same
    parser** (Step 12) and must come through here too.
    """
    fields = dict(raw)
    fields["holdings"] = [Holding(**h) for h in fields.get("holdings") or []]
    return fields


def _enrich(bid: str) -> dict | None:
    """One SBN full record as plain fields, or None if the fetch failed.

    The only `full.json` call in S1-S3, and it exists because **neither** SBN
    API puts a language on a brief row — the OPAC listing row carries one only
    when the page it came back on was filtered to one, and the mobile gateway's
    brief record carries none **V**. A record admitted with no identity has no
    other way to reach its language group before S4.
    """
    try:
        return full_fields(sbn_mobile.parse_record(sbn_mobile.full_record(bid)))
    except SourceError:                  # on the ledger, which reports it
        return None


def _reverse(typed: str, work: Work, author: str, store: RecordStore) -> dict:
    """The typed title's route, for a book with no identity at all.

    It serves a book Wikidata has never heard of, SBN files under no work this
    question can be believed to be, and Open Library has no work record for — 2
    of 96 corpus entries **M**, and E12 and E14 get their only editions here.
    For such a book `Work.titles()` is **empty**, so the gate has nothing else
    to match on and the whole lookup would answer nothing at all.

    **This is the one place the typed title reaches a gate**, and it is a
    widening of build rule 11 rather than the sanctioned exception,
    which allows the typed title only to *find* candidates. It is flagged here
    and reported in the evidence. Where there is an identity, rule 11 stands
    untouched: this branch cannot run.

    Its other half — Open Library works matched on an Italian record's Dewey
    class and authors, and an original inferred from them — was measured in
    Step 12 and deleted in Step 16 (decision AH).
    """
    res = {"state": OK, "typed_title": typed, "widened_gate": True, "seeds": 0,
           "enriched": 0, "candidates": 0, "refused": 0,
           "language_disbelieved": [], "sources": {"SBN": OK}}
    with Pool(2) as pool:
        probe_f = pool.submit(_title_probe, typed, author)
        sweep_f = pool.submit(_author_sweep, work)
        probe, sweep = probe_f.result(), sweep_f.result()
    res["title_probe"] = {k: v for k, v in probe.items() if k != "rows"} | {"rows": len(probe["rows"])}
    res["author_sweep"] = {k: v for k, v in sweep.items() if k != "rows"} | {"rows": len(sweep["rows"])}
    res["sources"]["SBN"] = _worst(probe["state"], sweep["state"])

    seen, candidates = set(), []
    for rows, route in ((probe["rows"], TITLE_PROBE), (sweep["rows"], AUTHOR_SWEEP)):
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            candidates.append((Record(**sbn_opac.listing_record(row),
                                      provenance=Provenance("SBN", route, REFUSED)),
                               route))
    res["candidates"] = len(candidates)

    seeds = [(r, route) for r, route in candidates
             if gate.identifies(r, route, [typed]) == gate.STRONG]
    res["seeds"] = len(seeds)
    with Pool(REVERSE_WORKERS) as pool:
        enriched = list(pool.map(lambda pair: _enrich(pair[0].id), seeds[:REVERSE_ENRICH]))
    res["enriched"] = sum(1 for e in enriched if e)

    for (record, route), fields in zip(seeds[:REVERSE_ENRICH], enriched):
        if fields:
            record = Record(**fields, provenance=record.provenance)
        score = round(variant_affinity(record.title, [typed]), 3)
        record.provenance = Provenance(record.source, route, TITLE_MATCH, score)
        _place(record, work, res["language_disbelieved"])
        store.put(record)
    for record, route in seeds[REVERSE_ENRICH:]:
        score = round(variant_affinity(record.title, [typed]), 3)
        record.provenance = Provenance(record.source, route, TITLE_MATCH, score)
        store.put(record)
    for record, route in candidates:
        if record.provenance.evidence == REFUSED:
            score = round(variant_affinity(record.title, [typed]), 3)
            record.provenance = Provenance(record.source, route, REFUSED, score)
            store.put(record)
            res["refused"] += 1

    return res


# ---------------------------------------------------------------------------
# S4 — the full records, behind the page (Step 12)
# ---------------------------------------------------------------------------

# Every admitted SBN row is read in full, up to this many (decision AG). No
# corpus entry reaches it — the most is N23's 1,078 — so it exists for the
# author nobody has measured, and hitting it is a line on the page, never a
# silent subset (build rule 10). It is not `ENRICH_BUDGET`: that
# ranked candidates the old pipeline had not yet admitted, and this one reads
# rows the list already shows.
ENRICH_CAP = 1500
# The OPAC's measured politeness. A probe on 2026-09-24 read full records at
# 0.133 s each one at a time, 0.039 s at 4 and 0.031 s at 6 — no failures —
# so 4 gives up a quarter of the speed for the figure the benchmark stood on.
ENRICH_WORKERS = 4


@dataclass
class Enrichment:
    """What S4 read, and what the full records changed.

    The store is S2's again: a full record is the same row seen a second time,
    so `RecordStore.put` fills what the brief row lacked — the ISBN that folds
    printings into one edition, the language S3's recovered rows arrive without,
    the Dewey class, the holdings — and overwrites nothing.
    """
    store: RecordStore
    evidence: dict


def enrich(identity: Identity, store: RecordStore, disbelieved=()) -> Enrichment:
    """S4. Every admitted SBN row's full record, in store order, capped.

    Refused rows are not read: they are in no group and no count, and paying
    for 8,587 of them over the corpus to feed a Dewey rule measured at 0 would
    be the product paying for a measurement (decision AG — the sweep reads them
    instead).

    A record whose fetch failed keeps its brief row and is counted on the
    ledger, which is what turns SBN `partial` (`CLAUDE.md` rule 5). The language
    a full record states is judged by the same rule 4 check S2 and S3 apply;
    `disbelieved` is the ids an earlier stage already reported, so one record is
    never disclosed twice.
    """
    work = identity.work
    held = [r for r in store.records()
            if r.source == "SBN" and r.id
            and not any(p.route == ENRICHED for p in store.routes(r))]
    todo = held[:ENRICH_CAP]
    with Pool(ENRICH_WORKERS) as pool:
        fetched = list(pool.map(lambda r: _enrich(r.id), todo))

    known = set(disbelieved)
    evidence = {"rows": len(held), "asked": len(todo), "cap": ENRICH_CAP,
                "truncated": len(held) > ENRICH_CAP, "read": 0, "failed": 0,
                "empty": 0, "gained_isbn": 0, "gained_language": 0,
                "with_dewey": 0, "language_disbelieved": [],
                "sources": {"SBN": OK}}
    for record, fields in zip(todo, fetched):
        if fields is None:
            evidence["failed"] += 1              # on the ledger already
            continue
        if fields["id"] != record.id:
            # A skeleton body (F13's bogus-BID shape) or a different record:
            # either way it is not this row, and `put` would add it as one.
            evidence["empty"] += 1
            continue
        evidence["read"] += 1
        had_isbn, had_language = bool(record.isbn or record.isbns_raw), \
            record.language != langs.UNKNOWN
        full = Record(**fields, provenance=Provenance(
            "SBN", ENRICHED, record.provenance.evidence, record.provenance.score))
        notes = []
        _place(full, work, notes)
        evidence["language_disbelieved"] += [n for n in notes if n["record"] not in known]
        store.put(full)
        evidence["gained_isbn"] += (not had_isbn) and bool(record.isbn or record.isbns_raw)
        evidence["gained_language"] += (not had_language) and record.language != langs.UNKNOWN
        evidence["with_dewey"] += bool(record.dewey)
    return Enrichment(store=store, evidence=evidence)


# ---------------------------------------------------------------------------
# Dates SBN wrote in another calendar (decision AY)
# ---------------------------------------------------------------------------

# Records whose date is checked against SBN's index. The probe found 6% of SBN
# records need it (134 of 2,190), so a lookup reaches this only with an
# unusually large Persian or Ottoman list; the rest stay labelled unsure.
DATE_CHECK_CAP = 300
DATE_CHECK_PAGES = 5         # of one `author + lingua[] + dataf[]` answer


@dataclass
class DateCheck:
    evidence: dict


def _filed_under(who: dict, language: str | None, value: str) -> dict:
    body = {"core": "sbn", **who, sbn_opac.YEAR: value}
    if language:
        body[sbn_opac.LANGUAGE] = language
    return sbn_opac.all_rows(body, cap=DATE_CHECK_PAGES)


def _check_language(who: dict, language: str | None, records: list, store) -> dict:
    """One language's unsettled records, against the `dataf[]` values SBN files
    them under. Only values that hold a year the imprint wrote are asked: the
    facet names a range as one value (`1977-1991`), which asking by year would
    never reach. `who` is the author term: the name, or a name authority's id."""
    body = {"core": "sbn", "page": "1", **who}
    if language:
        body[sbn_opac.LANGUAGE] = language
    wanted = {y for r in records for y in dates.candidates(r.date)}
    try:
        facet = sbn_opac.facet_items(sbn_opac.post(body), sbn_opac.YEAR)
    except SourceError:                  # on the ledger
        for r in records:
            store.note_date(r.key, [], failed=True)
        return {"asked": 0, "failed": len(records)}
    values = [it["value"] for it in facet if dates.indexed_years([it["value"]]) & wanted]
    if len(facet) >= sbn_opac.FACET_CAP:
        # The facet stops at 50 values (F11): a year it did not list is asked as is.
        listed = {y for v in values for y in dates.indexed_years([v])}
        values += [str(y) for y in sorted(wanted - listed)]
    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        answers = dict(zip(values, pool.map(
            lambda v: _filed_under(who, language, v), values)))
    lost = any(a["failed"] for a in answers.values())
    for r in records:
        under = [v for v, a in answers.items() if any(row["id"] == r.id for row in a["rows"])]
        mine = {y for y in dates.candidates(r.date)}
        store.note_date(r.key, under,
                        failed=lost and not (dates.indexed_years(under) & mine))
    return {"asked": len(values) + 1, "failed": sum(bool(a["failed"]) for a in answers.values())}


def check_dates(identity: Identity, store: RecordStore, this_year: int | None = None,
                buckets=()) -> DateCheck:
    """Ask SBN's index which year a record is filed under, where the answer can
    change the row, and write it on the record for `core.dates` to read.

    Two passes. Every SBN record whose imprint is not one plain Gregorian year
    (`core.dates.is_plain`) is asked about. Then each listing bucket's plain
    years are reconciled with the `dataf[]` counts its first page came back
    with, and only a year whose counts disagree is asked (`_reconcile`). What an
    answer means is decided in `core.dates`, not here. Always with the author
    (`CLAUDE.md` rule 3); `dataf[]` is F10's key, sent one exact value at a
    time. A failed request is on the ledger (rule 5): a record it could have
    answered is marked unchecked, and a plain year it could have contradicted
    keeps the year it states.
    """
    author = identity.evidence["question"]["author"]
    held = [r for r in store.records() if r.id and r.date_indexed is None
            and dates.needs_check(r, this_year)]
    todo = held[:DATE_CHECK_CAP]
    evidence = {"rows": len(held), "checked": len(todo), "cap": DATE_CHECK_CAP,
                "truncated": len(held) > DATE_CHECK_CAP, "requests": 0, "failed": 0,
                "reconcile_wanted": 0, "reconcile_requests": 0,
                "reconcile_cap": RECONCILE_CAP, "reconcile_truncated": False,
                "contradicted": 0, "sources": {"SBN": OK}}
    if not author:
        return DateCheck(evidence=evidence)
    _check_records({sbn_opac.AUTHOR: author}, todo, store, evidence)
    _reconcile(author, buckets, store, this_year, evidence)
    return DateCheck(evidence=evidence)


def _check_records(who: dict, records: list, store: RecordStore, evidence: dict) -> None:
    by_language = {}
    for r in records:
        by_language.setdefault(None if r.language == langs.UNKNOWN else r.language,
                               []).append(r)
    for language, held in sorted(by_language.items(), key=lambda kv: kv[0] or ""):
        done = _check_language(who, language, held, store)
        evidence["requests"] += done["asked"]
        evidence["failed"] += done["failed"]


def check_name_dates(read: list, store: RecordStore, this_year: int | None = None) -> dict:
    """`check_dates`' first pass for author mode's records filed under no work
    (decision AY; `docs/BACKLOG.md` *Author mode's years are not settled*).

    `read` is `[(authority id, record)]`, each record held in `store`. A record
    is asked about under the name authority that filed it, which is the author
    term (rule 3) and the same `NAMES + lingua[] + dataf[]` query the works
    split already sends. The listing's plain years are not reconciled: author
    mode has no bucket whose counts are over exactly the rows read. The works'
    own years are `dataf[]` values already, SBN's index and not an imprint.
    """
    held = [(aid, r) for aid, r in read if r.id and r.date_indexed is None
            and dates.needs_check(r, this_year)]
    held = list({r.key: (aid, r) for aid, r in held}.values())
    todo = held[:DATE_CHECK_CAP]
    evidence = {"rows": len(held), "checked": len(todo), "cap": DATE_CHECK_CAP,
                "truncated": len(held) > DATE_CHECK_CAP, "requests": 0, "failed": 0}
    by_name = {}
    for aid, r in todo:
        by_name.setdefault(aid, []).append(r)
    for aid, records in by_name.items():
        _check_records({sbn_opac.NAMES: aid}, records, store, evidence)
    return evidence


# Values asked about across one lookup's buckets. The corpus needs 2 at the
# median work and 330 for the *Odysseia* (upper bounds, 2026-09-29); past this
# the rows keep the years they state, and the page says so (rule 10).
RECONCILE_CAP = 60


def _filed_in_work(author: str, work: str, language: str, value: str) -> dict:
    return sbn_opac.all_rows({"core": "sbn", sbn_opac.AUTHOR: author,
                              sbn_opac.WORK: work, sbn_opac.LANGUAGE: language,
                              sbn_opac.YEAR: value}, cap=sbn_opac.LISTING_MAX_PAGES)


def _reconcile(author: str, buckets, store: RecordStore, this_year, evidence: dict) -> None:
    """The listing's plain years against SBN's counts for the same bucket.

    A bucket is the listing's own query — author, work, language — so SBN's
    `dataf[]` counts are over exactly the rows it returned. Where a count
    differs, asking that one value names the rows SBN files there; a plain row
    missing from its own year is contradicted (`core.dates.contradicted`). Only
    whole buckets are read: a truncated or failed page would make every count
    disagree.
    """
    plans = []
    for b in buckets:
        if not b["complete"]:
            continue
        records = [r for r in (store.get("SBN", i) for i in b["ids"]) if r]
        ask, absent = dates.values_to_ask(b["years"], records,
                                          len(b["years"]) >= sbn_opac.FACET_CAP, this_year)
        plans.append((b, records, ask, absent))
    evidence["reconcile_wanted"] = sum(len(p[2]) for p in plans)
    budget, queries = RECONCILE_CAP, []
    for n, (b, _, ask, _) in enumerate(plans):
        for value in ask[:max(budget, 0)]:
            queries.append((n, b["work"], b["language"], value))
        budget -= len(ask)
    evidence["reconcile_requests"] = len(queries)
    evidence["reconcile_truncated"] = len(queries) < evidence["reconcile_wanted"]

    def ask_one(q):
        try:
            return _filed_in_work(author, q[1], q[2], q[3])
        except SourceError:                  # on the ledger
            return None

    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        answered = list(pool.map(ask_one, queries))
    answers = [{} for _ in plans]
    for (n, _, _, value), got in zip(queries, answered):
        if got is None or got["failed"] or got["truncated"]:
            evidence["failed"] += 1
            continue
        answers[n][value] = {row["id"] for row in got["rows"]}
    for (b, records, _, absent), answer in zip(plans, answers):
        for r in records:
            under = dates.contradicted(r, answer, absent, this_year)
            if under is not None:
                store.note_date(r.key, under)
                evidence["contradicted"] += 1


# ---------------------------------------------------------------------------
# Open Library's other records for the work (Step 13, decision J)
# ---------------------------------------------------------------------------

# Docs read per search. Open Library ranks the duplicates it holds anywhere in
# the first 75 (Step 13, 76 found); past this the page says the search was read
# in part rather than paging for them.
DUPLICATE_DOCS = 100
# Searches at once. Three to seven per lookup; a different host from S4's, so
# the stage runs beside it and costs the reader no wait.
DUPLICATE_WORKERS = 2
# Work records opened at once when the reader adds several.
ADD_WORKERS = 4


@dataclass
class Duplicates:
    """The other Open Library work records a reader may add, and how they were
    looked for. An offer, not an answer: nothing here is written to the store."""
    evidence: dict


def _duplicate_queries(identity: Identity) -> list:
    """What the list is searched with: every title the work is known by, then
    the typed title if it is not one of them.

    The typed title only **finds** candidates, which `core.identity.
    duplicate_works` then tests against the work's titles — S3's shape, the one
    exception build rule 11 allows. Step 13 measured what it buys:
    three known duplicates of *Crime and Punishment* that no work title found.
    """
    question = identity.evidence["question"]
    titles, seen, out = identity.work.titles(), set(), []
    for label, title in [("work title", t) for t in titles] + \
                        [("typed title", question["typed_title"])]:
        if title and title.lower() not in seen:
            seen.add(title.lower())
            out.append((label, title))
    return out


def find_duplicates(identity: Identity) -> Duplicates:
    """Search Open Library for this work's other records, and list them.

    **Only where S1 found the main work** (decision J: the main work is the
    listing, the rest are offered beside it). A lookup with no Open Library work
    has nothing to be a duplicate *of*, and offering every author-and-title
    match there would be a second identity route this step never measured.
    """
    work = identity.work
    author = identity.evidence["question"]["typed_author"]
    keys = identity.evidence.get("ol_author_keys", {}).get("keys") or []
    evidence = {"asked": True, "state": OK, "queries": [], "rows": [],
                "added": [], "failed": {}, "language_disbelieved": [],
                "sources": {"Open Library": OK}}
    if not work.ol_keys:
        evidence.update(asked=False, why_not="no Open Library work for this "
                        "question, so no other record of it was looked for")
        return Duplicates(evidence=evidence)
    queries = _duplicate_queries(identity)

    def ask(title):
        try:
            return ol.search_counted(f"{title} {author}".strip(), DUPLICATE_DOCS)
        except SourceError as exc:
            return {"error": str(exc)[:200]}

    with Pool(DUPLICATE_WORKERS) as pool:
        answers = list(pool.map(ask, [t for _, t in queries]))
    docs = []
    for (label, title), answer in zip(queries, answers):     # query order
        entry = {"by": label, "title": title}
        if "error" in answer:
            entry["error"] = answer["error"]
            evidence["state"] = f"error: {answer['error']}"
        else:
            entry.update(docs=len(answer["docs"]), total=answer["total"])
            docs += [ol.parse_doc(d) for d in answer["docs"]]
        evidence["queries"].append(entry)
    evidence["rows"] = gate.duplicate_works(docs, work.titles(), author, keys,
                                            work.ol_keys)
    evidence["sources"]["Open Library"] = evidence["state"]
    return Duplicates(evidence=evidence)


def add_duplicates(identity: Identity, store: RecordStore, listed: dict,
                   wanted: list) -> dict:
    """Open the work records the reader chose, by key, and put their editions in.

    **By key and never by title** (F19; the title search returns the main work
    again 24 of 33 times). Each edition is written with `DUPLICATE_WORK` as both
    route and evidence and the work key it came through, so the ledger counts it
    on its own line and the row can say which record it was added from — and so
    the header, which states what the catalogues tie to *this* work, can leave
    it out (decision AI).

    `listed` is the stage's own evidence: a key that is not on its list is
    refused rather than opened, because the list is what the title and author
    tests passed, and opening an arbitrary work would be a route around them.
    A key already added is not fetched twice. Returns what changed.
    """
    offered = {r["key"] for r in listed.get("rows") or []}
    unknown = [k for k in wanted if k not in offered]
    if unknown:
        raise KeyError(f"not on this lookup's list: {', '.join(unknown)}")
    todo = [k for k in dict.fromkeys(wanted) if k not in listed["added"]]
    with Pool(ADD_WORKERS) as pool:
        answers = list(pool.map(_open_duplicate, todo))
    out = {"asked": todo, "added": [], "failed": {}, "rows": 0,
           "language_disbelieved": []}
    for key, answer in zip(todo, answers):                # the reader's order
        if answer.get("error") or answer["failed"]:
            out["failed"][key] = answer.get("error") or answer["failed"][0]
            continue
        for row in answer["rows"]:
            fields = {k: v for k, v in row.items() if k not in ("translation_of", "works")}
            record = Record(**fields, provenance=Provenance(
                "Open Library", DUPLICATE_WORK, DUPLICATE_WORK, via=key))
            _place(record, identity.work, out["language_disbelieved"])
            store.put(record)
            out["rows"] += 1
        out["added"].append(key)
    return out


def _open_duplicate(key: str) -> dict:
    """One work's editions; a page that fails leaves the work *not added*,
    whole, rather than half in the list with nothing saying which half."""
    try:
        return ol.editions(key)
    except SourceError as exc:
        return {"rows": [], "failed": [], "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Details — one row, opened by the reader (Step 10)
# ---------------------------------------------------------------------------

@dataclass
class Details:
    """One edition seen in full, and where to get a copy.

    Not a stage: nothing here writes to the store and no version follows it. It
    is the answer to a gesture — a reader opening one row — which is why it is
    paid for per row and not for the 845 rows of a list nobody has opened.
    """
    edition: dict
    evidence: dict


def details(store: RecordStore, edition_id: str) -> Details:
    """The richer half of one row: Open Library's full record, SBN's as S4 read
    it, plus buy links.

    **Only Open Library is fetched here.** SBN's full record is S4's (Step 12):
    it arrives for every admitted row in the background, so the SBN half is read
    off the store with no request — the holdings especially, which run to 851
    libraries on one record and are therefore not carried in every snapshot.
    Where S4 has not read a row's full record, `sbn.read` says so, so a panel
    with no holdings is never mistaken for a book no library holds.

    Buy links are `core.buylinks`: pure, no request, and only for a row with an
    ISBN — a title search lands on another edition. The Internet Archive link, where Open Library records a
    scan, comes off the fetched record — for an out-of-print book it is the only
    answer to "where do I get a copy" that is not a shop's guess.

    A failed fetch is reported as a failure, never as an absence
    (`CLAUDE.md` rule 5): the caller opens a `Ledger` and this returns the
    error, so "Open Library did not answer" and "Open Library records nothing
    more" are different answers on the page.
    """
    edition = _edition_in(store, edition_id)
    if edition is None:
        raise KeyError(edition_id)

    keys = [r.id for r in edition.records if r.source == "Open Library" and r.id]
    evidence = {"asked": bool(keys), "keys": keys, "failed": [], "sources": {}}
    if not keys:
        evidence["why_not"] = "Open Library has no record of this row"
    found = {}
    for key in keys:                      # in store order, so the answer is stable
        try:
            found = ol.parse_book(ol.book(key))
            evidence["sources"]["Open Library"] = OK
            break
        except SourceError as exc:
            evidence["failed"].append({"key": key, "error": str(exc)[:200]})
    if evidence["failed"] and not found:
        evidence["sources"]["Open Library"] = f"error: {evidence['failed'][0]['error']}"

    return Details(edition={
        "id": edition.id,
        "isbn": edition.isbn,
        "title": edition.title,
        "open_library": found or None,
        "sbn": _sbn_half(store, edition),
        "buy_links": buylinks.links(edition.isbn),
    }, evidence=evidence)


def _sbn_half(store: RecordStore, edition) -> dict | None:
    """What SBN's full records say about this row, off the store. None if SBN
    has no record of it.

    `read` counts the records S4 actually read in full, so "held by nobody" and
    "not read yet" are different answers.
    """
    sbn = [r for r in edition.records if r.source == "SBN"]
    if not sbn:
        return None
    read = sum(1 for r in sbn if any(p.route == ENRICHED for p in store.routes(r)))
    return {
        "records": len(sbn),
        "read": read,
        "holdings": [{"library": h.library, "city": h.city, "isil": h.isil}
                     for h in edition.holdings],
        "physical": edition.physical,
        "series": edition.series,
        "translators": edition.translators,
        "dewey": next((r.dewey for r in sbn if r.dewey), None),
    }


def _edition_in(store: RecordStore, edition_id: str):
    """The edition with this id, folded from the store exactly as the view does.

    Re-folded rather than remembered, because the snapshot the reader is looking
    at was derived the same way and a row that gained an ISBN since then is a
    *different* edition (`core.fold._edition_id`) — so an id that no longer
    exists is a stale click, and the caller is told so instead of being handed
    the wrong book.
    """
    for edition in fold(store.records()):
        if edition.id == edition_id:
            return edition
    return None


# ---------------------------------------------------------------------------
# UC4 — author mode: resolve the person, then list their works (Step 14)
# ---------------------------------------------------------------------------

# Name forms asked of `core=autori`: the typed one and Wikidata's Latin
# aliases. Mahfouz carries eleven, and the one that reaches his 531 records is
# the fourth; past eight, an alias is a longer spelling of one already asked.
AUTHOR_FORMS = 8
# Year leaves asked at once when a language is split past its facet's 50 years.
# The sweep stops between batches, as soon as the leaves add up.
YEAR_BATCH = 8


@dataclass
class AuthorResolution:
    """Who the typed name may be. `candidates` are `core.authors.Candidate`,
    in the order the chooser shows them; `skip` is decision AJ's."""
    candidates: list
    resolved: str | None
    skip: bool
    person: dict | None
    evidence: dict


@dataclass
class WorkList:
    works: list
    contributed: list
    band: list
    evidence: dict
    unlinked: list = field(default_factory=list)
    # What `read_rest` needs to redraw the group filed under no work.
    picked: list = field(default_factory=list, repr=False)
    rows: list = field(default_factory=list, repr=False)
    linked: set = field(default_factory=set, repr=False)


def _person(typed: str) -> tuple:
    """Wikidata's item for the person, or None, and its source state."""
    try:
        people = wikidata.people(typed)
    except SourceError as exc:
        return None, f"error: {exc}"
    person = authors.person_of(people, [typed]) if is_latin(typed) else None
    if person is None and not is_latin(typed) and people:
        # A name typed in its own script is compared by nothing here, so the
        # search's first person is taken — and only its aliases are used, each
        # of which reaches ids the reader sees and chooses between.
        person = people[0]
    return person, OK


def _person_named(names: list) -> dict | None:
    """Wikidata's person under the chosen authority's own name, when the typed
    spelling found none. *Han Byung-Chul* finds no item and *Byung-Chul Han*
    does, and without this the two spellings of one man listed different
    works (0.697 in the Step 14 sweep) — the one property UC4 has to keep."""
    for name in names:
        person, _ = _person(name)
        if person:
            return person
    return None


def resolve_author(typed: str) -> AuthorResolution:
    """Every SBN name-authority record the name may mean, counted.

    The typed name and Wikidata's Latin aliases are asked of `core=autori`, so
    *Naguib Mahfouz* offers the 531-record `CFIV093786` that the typed form
    never reaches. Only candidates whose name agrees with a form asked are
    counted — the rest are records that merely mention the name.
    """
    typed = (typed or "").strip()
    person, wd_state = _person(typed)
    forms = authors.latin_forms(typed, (person or {}).get("names") or [])[:AUTHOR_FORMS]
    sbn_state = OK

    def ask(form):
        try:
            found = sbn_opac.authorities(form)
            return {"form": form, "rows": found["rows"], "total": found["total"]}
        except SourceError as exc:
            return {"form": form, "rows": [], "total": 0, "error": str(exc)}

    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        answers = list(pool.map(ask, forms))
    failed = [a for a in answers if a.get("error")]
    if failed:
        sbn_state = f"error: {failed[0]['error']}"
    found = authors.candidates(answers, forms[0] if forms else typed)

    def count(c):
        try:
            facets = sbn_opac.authority_facets(c.id)
            c.records, c.languages = facets["total"], len(facets["languages"])
        except SourceError:            # on the ledger, which reports it
            pass

    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        list(pool.map(count, [c for c in found["candidates"] if c.agrees]))
    ordered = authors.order(found["candidates"], found["resolved"])
    return AuthorResolution(
        candidates=ordered, resolved=found["resolved"], skip=found["skip"], person=person,
        evidence={"typed": typed, "forms": forms, "rule": found["rule"],
                  "answers": [{"form": a["form"], "total": a["total"],
                               "persons": len(authors.persons(a["rows"])),
                               "error": a.get("error")} for a in answers],
                  "person": (person or {}).get("qid"),
                  "sources": {"SBN": sbn_state, "Wikidata": wd_state}})


def _leaves(authority_id: str, language: str, node: dict, floor, ceiling) -> dict:
    """One capped language, split by exact year until its leaves add up.

    The years the facet names first, then — only when the facet itself hit 50
    — the quiet years `core.authors.extra_years` orders, a batch at a time,
    stopping when the leaves' totals reach the language's.
    """
    got = {"nodes": [], "covered": 0, "capped": []}

    def ask(year):
        return year, sbn_opac.authority_facets(authority_id, language, year)

    def take(years):
        with Pool(sbn_opac.PAGE_WORKERS) as pool:
            futures = [pool.submit(ask, y) for y in years]
        for future in futures:
            try:
                year, leaf = future.result()
            except SourceError:        # on the ledger; the gap is uncovered
                continue
            got["nodes"].append(leaf)
            if authors.capped(leaf["works"]):
                got["capped"].append(f"{language} {year}")
            else:
                got["covered"] += leaf["total"]

    take([y["value"] for y in node["years"] if y.get("value")])
    if authors.capped(node["years"]):
        extra = authors.extra_years([y.get("value") for y in node["years"]], floor, ceiling)
        for i in range(0, len(extra), YEAR_BATCH):
            if got["covered"] >= node["total"]:
                break
            take(extra[i:i + YEAR_BATCH])
    return got


def _authority_works(authority_id: str, name: str, floor, ceiling) -> dict:
    """Every uniform title filed under one name, past the 50-item cap (AJ).

    `{"works": {value: label}, "evidence": {...}}`. A list under 50 is whole
    and costs one request. At 50 it is asked again per language; a language
    still at 50 is asked per year. `covered` is the records in answers SBN gave
    in full — the leaves' totals — so `total - covered` is what the page says
    no split reached.
    """
    root = sbn_opac.authority_facets(authority_id)
    ev = {"id": authority_id, "name": name, "total": root["total"], "split": False,
          "covered": root["total"], "capped_leaves": [], "languages_capped": False,
          "requests": 1}
    nodes = [root]
    if authors.capped(root["works"]):
        ev.update(split=True, covered=0,
                  languages_capped=authors.capped(root["languages"]))

        def ask(code):
            return code, sbn_opac.authority_facets(authority_id, code)

        with Pool(sbn_opac.PAGE_WORKERS) as pool:
            futures = [pool.submit(ask, x["value"]) for x in root["languages"]
                       if x.get("value")]
        for future in futures:
            try:
                code, node = future.result()
            except SourceError:        # on the ledger; the gap is uncovered
                continue
            nodes.append(node)
            if not authors.capped(node["works"]):
                ev["covered"] += node["total"]
                continue
            split = _leaves(authority_id, code, node, floor, ceiling)
            nodes += split["nodes"]
            ev["covered"] += split["covered"]
            ev["capped_leaves"] += split["capped"]
        ev["requests"] = len(nodes)
    return {"works": authors.works_union(nodes), "evidence": ev}


def _wikidata_works(person: dict | None) -> dict:
    """The person's works as Wikidata states them, parsed for `core.authors`."""
    res = {"state": OK, "items": [], "read": 0, "total": 0}
    if not person:
        return res
    try:
        found = wikidata.works_by(person["qid"])
        ents = {}
        for i in range(0, len(found["qids"]), wikidata.BATCH):
            ents.update(wikidata.entities(found["qids"][i:i + wikidata.BATCH]))
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res.update(read=len(found["qids"]), total=found["total"])
    classes = wikidata.WORK_CLASSES - {wikidata.EDITION_CLASS}
    for qid in found["qids"]:
        ent = ents.get(qid) or {}
        claims = ent.get("claims") or {}
        language = wikidata.original_language(ent)
        p1476 = wikidata.claim_first(claims, "P1476") or {}
        own = p1476.get("text") if isinstance(p1476, dict) else None
        year = wikidata.original_year(ent)
        res["items"].append({
            "qid": qid, "forms": wikidata.item_forms(ent, names_only=True),
            "part_of": wikidata.claim_ids(claims, "P179") + wikidata.claim_ids(claims, "P361"),
            "typed": bool(set(wikidata.work_classes(claims)) & classes),
            "edition": wikidata.is_edition(claims),
            "original_title": own or wikidata.titles_by_language(ent).get(language),
            "original_language": None if language == langs.UNKNOWN else language,
            "year": int(year) if year else None})
    return res


def _open_library_works(name: str, forms: list) -> dict:
    """Open Library's work docs under the name, those by the person only."""
    res = {"state": OK, "docs": [], "read": 0, "total": 0}
    if not name:
        return res
    try:
        keys = [a["key"] if a["key"].startswith("/") else f"/authors/{a['key']}"
                for a in ol.author_keys(name)]
        found = ol.works_by_author(name)
    except SourceError as exc:
        res["state"] = f"error: {exc}"
        return res
    res.update(read=len(found["docs"]), total=found["total"])
    for doc in found["docs"]:
        parsed = ol.parse_doc(doc)
        if not parsed["id"] or not authors.doc_is_by(parsed, forms, keys):
            continue
        res["docs"].append({"key": parsed["id"], "title": parsed["title"],
                            "year": int(parsed["year"]) if parsed["year"] else None,
                            "edition_count": parsed["edition_count"],
                            "languages": parsed["languages"]})
    return res


# Pages of the records under a name read for the group filed under no work:
# 500 records, what the old author mode read from the mobile gateway
# (`rows=500`). Eco has 2,575 and Dostoevskij 4,796; the rest is a truncation
# line, never silence (rule 10), and the reader's to read (decision BA).
UNLINKED_MAX_PAGES = 25


def list_works(resolution: AuthorResolution, chosen: list, this_year: int) -> WorkList:
    """The chosen people's works: SBN's uniform titles past the cap, Wikidata's
    works, and Open Library's docs joined to them or listed apart.

    `chosen` is authority ids — several when one person sits under several
    (Mahfouz's four). Nothing here uses what was typed except as a name form
    for recognising Open Library's authors.
    """
    picked = [c for c in resolution.candidates if c.id in set(chosen)]
    if not picked:
        raise ValueError("choose at least one of the people offered")
    names = [c.display for c in picked]
    person = resolution.person or _person_named(names)
    floor = (person or {}).get("born")
    forms = list(dict.fromkeys(
        [*names, *[n for n in (person or {}).get("names") or [] if is_latin(n)],
         *([resolution.evidence["typed"]] if is_latin(resolution.evidence["typed"])
           else [])]))
    ol_name = next((n for n in (person or {}).get("names") or [] if is_latin(n)), names[0])

    with Pool(2) as side:
        wd_f = side.submit(_wikidata_works, person)
        ol_f = side.submit(_open_library_works, ol_name, forms)
        sbn_state, sbn_ev, works = OK, [], {}
        for c in picked:
            try:
                got = _authority_works(c.id, c.display, floor, this_year)
            except SourceError as exc:
                sbn_state = f"error: {exc}"
                continue
            sbn_ev.append(got["evidence"])
            for value, label in got["works"].items():
                works.setdefault(value, {"value": value, "label": label, "ids": []})
                works[value]["ids"].append(c.id)
        wd, ol_res = wd_f.result(), ol_f.result()

    def detail(pair):
        value, aid = pair
        try:
            return value, sbn_opac.authority_work(aid, value)
        except SourceError:            # on the ledger, which reports it
            return value, None

    pairs = [(v, aid) for v, w in works.items() for aid in w["ids"]]
    with Pool(sbn_opac.PAGE_WORKERS) as pool:
        details = list(pool.map(detail, pairs))
    for value, got in details:
        if got is None:
            sbn_state = _worst(sbn_state, "partial: a work's records did not arrive")
            works[value]["failed"] = True
            continue
        w = works[value]
        w["rows"] = w.get("rows", []) + got["rows"]
        w["languages"] = w.get("languages", []) + got["languages"]
        w["years"] = w.get("years", []) + got["years"]
        w["total"] = w.get("total", 0) + got["total"]

    built = authors.rows(list(works.values()), wd["items"], ol_res["docs"],
                         [c.heading for c in picked])
    shown = authors.view(built["rows"], built["band"], names)

    linked, linked_state = _linked(works)
    sbn_state = _worst(sbn_state, linked_state)
    group = _under_name(picked, built["rows"], linked, this_year,
                        {c.id: UNLINKED_MAX_PAGES for c in picked})
    sbn_state = _worst(sbn_state, group["state"])
    evidence = {"chosen": [c.id for c in picked], "names": names,
                "sbn": sbn_ev, "sbn_works": len(works),
                "wikidata": {k: wd[k] for k in ("read", "total")},
                "open_library": {k: ol_res[k] for k in ("read", "total")},
                "years_capped": sum(1 for r in built["rows"] if r.sbn_years_capped),
                "unlinked": group["evidence"],
                "dates": group["dates"],
                "sources": {"SBN": sbn_state, "Wikidata": wd["state"],
                            "Open Library": ol_res["state"]}}
    return WorkList(works=shown["works"], contributed=shown["contributed"],
                    band=shown["band"], evidence=evidence, unlinked=group["unlinked"],
                    picked=picked, rows=built["rows"], linked=linked)


def _linked(works: dict) -> tuple:
    """Every record SBN links to a listed work, and the SBN state of reading them.

    A work's first page is in hand; one with more records is read whole, so the
    group filed under no work does not keep a translation SBN files under the
    work on page 2 — 42 of Ferrante's 65 titles there, *Brilians baratnom* and
    *Forladte dage* among them (decision BB).
    """
    linked = {r.get("id") for w in works.values() for r in w.get("rows") or []}
    longer = [(w["value"], aid) for w in works.values() if not w.get("failed")
              for aid in w["ids"] if w.get("total", 0) > sbn_opac.PAGE_SIZE]

    def whole(pair):
        value, aid = pair
        try:
            # Each id's own total is not kept, so the pages are the work's sum
            # over its ids; past an id's last page `all_rows` asks nothing.
            return sbn_opac.authority_work_records(
                aid, value, -(-works[value]["total"] // sbn_opac.PAGE_SIZE))
        except SourceError:            # on the ledger, which reports it
            return None

    state = OK
    # One work at a time: `all_rows` already pages `PAGE_WORKERS` at once.
    for got in map(whole, longer):
        if got is None or got["failed"]:
            state = "partial: a work's records did not all arrive"
        linked |= {r.get("id") for r in (got or {}).get("rows") or []}
    return linked, state


def _under_name(picked: list, rows_: list, linked: set, this_year: int, caps: dict) -> dict:
    """Decision AN: what the name authority files under the person and no work
    here names. The records under each name are read up to `caps[id]` pages
    (a truncation line past it); a work's first page already said which it
    links. Their years are settled as the edition list's are (decision AY).
    """
    read, read_ev, held, state = [], [], RecordStore(), OK
    for c in picked:
        try:
            got = sbn_opac.records_by_authority(c.id, cap=caps[c.id])
        except SourceError as exc:
            state = _worst(state, f"error: {exc}")
            continue
        read_ev.append({"id": c.id, "total": got["total"], "read": len(got["rows"]),
                        "truncated": got["truncated"], "failed": len(got["failed"])})
        if got["failed"]:
            state = _worst(state, "partial: records under the name did not all arrive")
        for r in got["rows"]:
            record = held.put(Record(**sbn_opac.listing_record(r),
                                     provenance=Provenance("SBN", AUTHOR_SWEEP, AUTHOR_SWEEP)))
            read.append((c.id, record, r))
    checked = check_name_dates([(aid, record) for aid, record, _ in read], held, this_year)
    under_name = []
    for _, record, r in read:
        record = dates.settled(record, this_year)
        under_name.append({"id": r["id"], "title": r["title"], "author": r.get("author"),
                           "year": record.year, "record": record})
    unlinked = authors.unlinked(under_name, rows_, linked, [c.heading for c in picked])
    return {"unlinked": unlinked, "dates": checked, "state": state,
            "evidence": {"read": read_ev, "rows": len(unlinked),
                         "records": sum(len(u["records"]) for u in unlinked)}}


def unread_under_name(evidence: dict) -> dict | None:
    """What the cap left unread under the chosen names, or None: the records
    and the OPAC pages a full read would add (decision BA)."""
    cut = [r for r in (evidence.get("unlinked") or {}).get("read") or [] if r.get("truncated")]
    if not cut:
        return None
    pages = sum(-(-r["total"] // sbn_opac.PAGE_SIZE) - UNLINKED_MAX_PAGES for r in cut)
    return {"records": sum(r["total"] - r["read"] for r in cut), "pages": pages}


def read_rest(works: WorkList, this_year: int) -> WorkList:
    """The reader's *read the rest* (decision BA): every record under each
    chosen name, with no cap, and the group filed under no work drawn again.

    Only that group moves: the work rows are SBN's facets and Wikidata's works,
    which the cap never touched (Dostoevskij 117, Eco 128 either way, measured
    2026-09-29). A name the first read held whole is read again whole, from the
    cache, so the group is derived from every record at once.
    """
    totals = {r["id"]: r["total"] for r in works.evidence["unlinked"]["read"]}
    caps = {c.id: max(UNLINKED_MAX_PAGES, -(-totals.get(c.id, 0) // sbn_opac.PAGE_SIZE))
            for c in works.picked}
    group = _under_name(works.picked, works.rows, works.linked, this_year, caps)
    sources = dict(works.evidence["sources"])
    sources["SBN"] = _worst(sources.get("SBN", OK), group["state"])
    evidence = {**works.evidence, "unlinked": group["evidence"], "dates": group["dates"],
                "sources": sources}
    return replace(works, unlinked=group["unlinked"], evidence=evidence)
