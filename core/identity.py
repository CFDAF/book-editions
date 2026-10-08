"""Every gate in the project. Pure, offline, and the only place that decides.

Four unrelated judgements live here because they are all pure and they all
answer one question — *is this the same work?* — from different evidence:

1. **The SBN work guard (A/B)**: which uniform title is this work's, and may it
   be believed. `pick_work` + `affinity_a` + `share_b` + `tier`.
2. **The Wikidata title test**: may this item be believed. `title_test`.
3. **The second signal** (decision A): a refused or weak W that the accepted
   Wikidata item agrees with is accepted after all. `second_signal`.
4. **The identifying-signal gate**: does this *record* belong to the work.
   `identifies`, and the two record-level judgements
   `is_book_medium` and `language_contradicts_itself`.

Ported from `lookup/pipeline.py` (1, 4) and from the benchmark's own measured
implementations, Stage 1's A1 (1, 2) and Stage 2's second signal, decision A
(3), by reading them rather than rewriting: each threshold below was paid for
once, and `CLAUDE.md` rule 6 forbids moving one without re-checking the
counterexamples in `docs/limits.md` and `docs/DECISIONS.md` §7.

**One word means two things here and they must not be confused.** `STRONG` is a
verdict about a *record* — this row belongs to the work. `WORK_STRONG` is a tier
of the *work guard* — this uniform title may be believed as the work's. A record
can be STRONG under a work that was never resolved at all.
"""

import re
import unicodedata

from catalog import langs
from .text import (author_display, author_matches, fold_variants,
                   normalize, romanise, similarity, surname, variant_affinity)

# ---------------------------------------------------------------------------
# Thresholds. CLAUDE.md rule 6: do not move one without docs/limits.md.
# ---------------------------------------------------------------------------

# Title similarity that counts as identifying a work on its own. At 0.45,
# "L'ordine delle notizie" qualified as an edition of "L'invenzione delle
# notizie" on one shared word, while the correct record matched its core title
# at 1.0 — so the bar can be well above half.
#
# Measured over 758 rows at 21 thresholds (Step 2, U2): **the threshold is not
# the lever.** 580 of 608 same-work rows score exactly 0.0 or exactly 1.0, so
# every value from 0.05 to 0.65 admits within 2% of the same set. What the gate
# really tests is whether the work's title set holds a title in the record's
# language.
IDENTIFYING_TITLE_MATCH = 0.6

# The work guard and the Wikidata title test use the same number, and it is the
# same argument: a title agreement below this is a coincidence of short words.
WORK_TITLE_MATCH = 0.6

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

# What `identifies` found. A Dewey class is never one (decision AH, Step 16):
# it is a subject, and one author's books mostly share it.
STRONG = "strong"

# The work guard's tiers, with the strings the benchmark recorded, so a result
# file from Stage 1 still compares.
WORK_STRONG = "strong"
WORK_WEAK = "weak"
WORK_REJECTED = "rejected"
WORK_NONE = "no work"

# Why a candidate was pulled, when SBN's uniform-title authority linked it to
# the work. It is the one reason that identifies a record on its own, because it
# is the catalogue's statement rather than this tool's inference.
WORK_AUTHORITY = "SBN work authority"

# 'Kafka on the shore / Haruki Murakami ; translated from the Japanese by Philip
# Gabriel'. A record saying this cannot be in the language it names.
TRANSLATED_FROM = re.compile(
    r"\b(translated from|tradotto dal|tradotta dal|traduit du|traducido del)\b", re.I)

# '<film ; 1986>', '<serie tv ; 2018>' — an adaptation is linked to the work but
# is not an edition of it, and SBN's facet lists both.
ADAPTATION = re.compile(r"<\s*(film|serie tv|video|dvd|audiolibro)\b", re.I)

# SBN 'tipo' values that are not editions of a text. A documentary *about* the
# author shares enough of the title to pass a title match — 'An ecology of mind:
# a daughter's portrait of Gregory Bateson' scored 0.67 against 'Steps to an
# Ecology of Mind' — so it has to be excluded on what it is, not what it is
# called. Sound recordings stay: an audiobook is an edition of the text.
NON_BOOK_MEDIA = {
    "documento da proiettare o video",
    "musica manoscritta",
    "musica a stampa",
    "materiale cartografico a stampa",
    "manoscritto cartografico",
    "grafica",
    "oggetto tridimensionale",
}


# ---------------------------------------------------------------------------
# 1. The SBN work guard (A/B)
# ---------------------------------------------------------------------------

def pick_work(facet_items) -> dict | None:
    """W: the highest-count `titolo_uniformef[]` value, adaptations excluded.

    `{"value", "label", "count", "ties"}`, or None when the facet holds nothing
    usable. A work is **never** accepted on this count alone — that is what the
    tiers below are for. Share and dominance were both ruled out as acceptance
    rules: Bauman's *Modernità liquida* is correct at 0.48 and *Angelus Novus*
    is questionable at 0.43, so no threshold on share separates them.
    """
    items = [i for i in facet_items or []
             if i.get("value") and not ADAPTATION.search(str(i.get("label") or ""))]
    if not items:
        return None
    top = max(items, key=lambda i: i.get("results") or 0)
    count = top.get("results") or 0
    return {
        "value": str(top["value"]).strip(),
        "label": str(top.get("label") or "").strip(),
        "count": int(count),
        "ties": [str(i["value"]).strip() for i in items
                 if i is not top and (i.get("results") or 0) == count],
    }


def affinity_a(query_title: str, work_title: str) -> float:
    """**A**: how much the typed title looks like the uniform title itself.

    The cheap half of the guard — one request has already answered it. A ≥ 0.6
    and nothing more is needed; the expensive half only runs below that.
    """
    return similarity(query_title or "", work_title or "")


def share_b(query_title: str, query_rows, work_rows) -> tuple:
    """**B**: of the query's records that really carry this title, how many does
    SBN file under W. Returns `(b, matched, in_work)` — b is None when nothing
    matched, which is a different answer from 0.0.

    This is what separates a work SBN has linked thinly from a work that is not
    this book at all. It costs the query's pages and W's pages, and only runs
    when A is below the threshold: 637 extra OPAC requests over 59 entries, max
    151 for one.

    Rows are `{"id", "title"}` — anything with those two keys.
    """
    matched = {r["id"] for r in query_rows
               if similarity(query_title or "", r.get("title") or "") >= WORK_TITLE_MATCH}
    in_work = matched & {r["id"] for r in work_rows}
    if not matched:
        return None, matched, in_work
    return len(in_work) / len(matched), matched, in_work


def tier(a: float | None, b: float | None) -> str:
    """The guard's verdict: WORK_STRONG, WORK_WEAK, WORK_REJECTED or WORK_NONE.

    A ≥ 0.6, **or** B > 0.5, is strong. B exactly 0.5 is weak — the tier where
    the second signal applies. Anything else is refused.

    **Loosening B is settled against, with evidence** (`docs/DECISIONS.md` §7): the known
    *wrong* works sit at B = 0.5 — *Tesi di filosofia della storia*, *Angelus
    Novus* — which is **above** every refused classic (B ≤ 0.375: *Crime and
    Punishment* eng 9/31, *Der Process* 2/15, *Blindness* 3/8). The classics are
    refused because their records are thinly linked, not because the guard is
    miscalibrated, so the way in is the second signal and not a lower bar.
    """
    if a is None:
        return WORK_NONE
    if a >= WORK_TITLE_MATCH:
        return WORK_STRONG
    if b is None:
        return WORK_REJECTED
    if b > 0.5:
        return WORK_STRONG
    if b == 0.5:
        return WORK_WEAK
    return WORK_REJECTED


def work_is_accepted(tier_: str, second_signal_agrees: bool = False) -> bool:
    """May this uniform title be used as the work's identity?

    Strong, or rescued by the second signal. **Weak on its own is not enough**:
    B = 0.5 is exactly where the two known wrong works sit (*Tesi di filosofia
    della storia*, *Angelus Novus*), so a weak tier that no Wikidata item agrees
    with is refused like a rejection. That is the whole reason decision A adds a
    second signal instead of lowering B.
    """
    return tier_ == WORK_STRONG or (second_signal_agrees
                                    and tier_ in (WORK_WEAK, WORK_REJECTED))


# ---------------------------------------------------------------------------
# 2. The Wikidata title test
# ---------------------------------------------------------------------------

def title_test(query_title: str, forms) -> tuple:
    """`(score, form)`: the item form the typed title agrees with best.

    An item is accepted only when this reaches 0.6. In 91 entries the rule
    **never accepted a wrong item**, and it rejected all 6 wrong items today's
    resolver returns — which is why it is a gate and not a tie-break.

    `forms` are the item's own names, gathered by `catalog/wikidata.py`: labels,
    sitelink titles with the disambiguator stripped (`itwiki` for `Q208460` is
    `1984 (romanzo)` and the label is `1984`), and P1476.
    """
    return max(((similarity(query_title or "", f), f) for f in forms if f),
               default=(0.0, None))


def work_language_contradicted(work_title: str, records_in_language: list) -> bool:
    """Does SBN's own record set contradict the language its work authority states?

    The authority is a catalogue's statement and usually right — INGLESE for
    *invention of news*, GIAPPONESE for *umibe no kafuka* — but it is not always:
    Mahfouz's *bain el-qasrain* is filed ITALIANO. SBN holds Italian records of
    that work, and every one is titled *Tra i due palazzi*; a work whose own
    language is Italian would have one titled like it. So the statement is
    **disbelieved, never corrected**, when records in the stated language exist
    and none of them carries the work's title — `language_contradicts_itself`'s
    shape, one level up. No records in that language contradict nothing: SBN
    holds no Japanese *Kafka*, and the language stands.

    `records_in_language` are `{"title", "full"}`: the catalogued title and the
    whole title with its statement of responsibility. A record whose own title
    says it was *translated from* something is not evidence of the language it
    is filed under (rule 4) and is left out: `UBO4636099`, *Kafka on the shore
    … translated from the Japanese*, is SBN's only "Japanese" *Kafka*.

    A title also agrees when it is the work's title with the spaces taken out:
    SBN writes the pinyin of 活着 as *Huo zhe* in the records and *huozhe* in the
    uniform title, which token similarity scores 0.0. This is this check's own
    and moves no gate: it can only keep a statement, never make one.
    """
    titles = [r["title"] for r in records_in_language
              if not TRANSLATED_FROM.search(r.get("full") or "")]
    if not titles:
        return False
    squashed = _squashed(work_title)
    return not any(similarity(work_title or "", t or "") >= WORK_TITLE_MATCH
                   or (squashed and _squashed(t) == squashed)
                   for t in titles)


def _squashed(title: str) -> str:
    """Letters and digits only, lowercased and unaccented: `Huo zhe` → `huozhe`."""
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode()
    return "".join(re.findall(r"[a-z0-9]+", text.lower()))


def item_is_accepted(score: float) -> bool:
    return score >= WORK_TITLE_MATCH


# ---------------------------------------------------------------------------
# 3. The second signal (decision A)
# ---------------------------------------------------------------------------

def second_signal(work_title: str, item_forms) -> tuple:
    """Does the accepted Wikidata item agree with W? `(agrees, score, form)`.

    A refused or weak W is accepted when the item Wikidata's own test already
    accepted for this entry names the same work. Measured: **7 refusals
    rescued** (E16 eng, N14 eng, N21 eng, N22 eng + ita, N23 eng + ita) and **0
    agreements in 2,024 cross-book pairs**; the positive control is 44 of 47
    strong entries agreeing, and the 3 wrong-W refusals have no accepted item
    and stay refused.

    It compares W against the *item's* forms, never against the typed title —
    the typed title is what the guard already doubted.
    """
    score, form = title_test(work_title, item_forms)
    return item_is_accepted(score), score, form


# ---------------------------------------------------------------------------
# 4. The identifying-signal gate
# ---------------------------------------------------------------------------

def identifies(record, reason: str, variants: list) -> str:
    """Whether a signal ties this record to *this* work — STRONG or "".

    Without this gate an author sweep drags in every book the author ever wrote,
    which is the failure mode of the original script's SBN handling. Author and
    year agreement are necessary but nowhere near sufficient — 'Quale socialismo,
    quale Europa' (Attali, 1977) matches both and is a different book entirely.

    `record` is anything carrying `.title`.
    """
    # The catalogue's own uniform-title authority. Every other signal here is an
    # inference that two records describe one work; this one is SBN stating it.
    if reason == WORK_AUTHORITY:
        return STRONG
    if reason == "isbn match":
        return STRONG
    if variant_affinity(record.title, variants) >= IDENTIFYING_TITLE_MATCH:
        return STRONG
    # Nothing ties it. Note especially that an 'Open Library sibling' probe is
    # NOT self-justifying: it probes SBN with the titles of *other* books by the
    # author, so its hits are rejected rather than trusted — otherwise a lookup
    # for 'Per una economia positiva' returns Rumori, Karl Marx and Lessico per
    # il futuro. A shared Dewey class is not a signal either: García Márquez is
    # 863.44 and so is every novel he wrote (decision AH).
    return ""


def is_book_medium(record) -> bool:
    """Is this an edition of a text, rather than a film or a map?"""
    return (getattr(record, "medium", None) or "").strip().lower() not in NON_BOOK_MEDIA


# Vowels, for the consonant skeleton below. Deliberately **not** in
# `core/text.py`: nothing but the label below may reach it, and a function
# living beside `fold_variants` would end up inside `title_similarity` — which
# is the identifying gate, and `CLAUDE.md` rule 6 is about exactly that.
_VOWELS = re.compile(r"[aeiou]")


# How many consonants a stem needs before one may be read as the start of the
# other. At 2 the corpus collapses three real pairs of different authors; at 3
# it collapses none.
NAME_STEM_MIN = 3


def name_skeleton(name: str) -> set:
    """A surname's consonants, folded. **A label's tie-breaker, never a gate.**

    `Maḥfūẓ` and `Mahfouz` are one man in two romanisations, and `normalize`
    reduces them to `mahfuz` and `mahfouz`, which share no token; `fold_variants`
    does not close it either, because the difference is a vowel and the fold was
    measured on consonant digraphs (decision G, U3). Dropping the vowels does
    close it — `mhfz` both ways — at the price of a comparison too loose for any
    gate, which is why nothing but `names_agree` may call it.
    """
    return {_VOWELS.sub("", fold_variants(t))
            for t in normalize(surname(name) or "")} - {""}


def names_agree(a: str, b: str) -> bool:
    """Are these two catalogue spellings the same person? **Label use only.**

    Token agreement first, which is `author_matches` and is what every other
    caller in the project uses. Then, and only for a label, two fallbacks for
    the same problem — one name rendered by two conventions:

    * **another romanisation**: `Maḥfūẓ, Naǧīb` against `Naguib Mahfouz`, which
      share the consonants and nothing else;
    * **a Latinised form**: SBN heads 848 of the corpus's Homer records
      `Homerus` where the reader typed `Homer`, so one stem has to be readable
      as the start of the other.

    Measured before it shipped, at `NAME_STEM_MIN = 3`: over 1,326 cross-author
    pairs of the 40-book corpus it agrees on **0** pairs `author_matches` keeps
    apart, and over the 2,603 listing rows `credited_to_another` still labels
    exactly **27** — the same 27, every one genuinely not an edition. At 2 it
    collapses three real pairs, which is why the bar is where it is.

    It is deliberately **not** in `core/text.py`: a comparison this loose next
    to `fold_variants` would end up inside `title_similarity`, which is the
    identifying gate (`CLAUDE.md` rule 6).
    """
    if author_matches(a, [b]):
        return True
    sa, sb = name_skeleton(a), name_skeleton(b)
    if not (sa and sb):
        return False
    if sa & sb:
        return True
    return any(x.startswith(y) or y.startswith(x)
               for x in sa if len(x) >= NAME_STEM_MIN
               for y in sb if len(y) >= NAME_STEM_MIN)


def credited_to_another(record, author_forms) -> str | None:
    """The record's own main author, when SBN credits it to somebody else.

    **The listing contains non-editions** (F16) and neither `tiporec[]` nor
    `level[]` separates them: a York Notes study guide, a Penguin Readers
    retelling and a Meridiani omnibus are all `Testo - Monografia` under the
    work. The row is not filtered — SBN linked it, and hiding what a catalogue
    says is the opposite of this project's disclosure rule — so it is labelled
    instead, with the one thing on it that is a catalogue *fact* rather than an
    inference: SBN's own main-author heading for the record.

    Measured over the 2,603 listing rows of 32 works: it names **27** of them
    (1.0%) — graphic novels, operas, a screenplay, a choral setting, pop-up
    retellings, `TO10037839` (Penguin Readers, credited to MacKenzie) — and on
    this corpus every one of the 27 is genuinely not an edition of the work.
    Comparing names with `author_matches` alone named 35, and over the live
    corpus **885**: the extras are one name rendered two ways, `Maḥfūẓ, Naǧīb`
    for `Naguib Mahfouz` (8) and `Homerus` for `Homer` (848). `names_agree` is
    what silences them, and SBN's authority cannot — it holds Naguib Mahfouz
    under **four** ids (`BMCV001724`, `LO1V444420`, `CFIV093786`,
    `TSAV609028`) and no id at all for Homer.

    It is **not** a filter and it is not complete. `VIA0214939` (the York Notes
    study guide) and `TO02081267` (the Meridiani *Romanzi e saggi*) are both
    credited to Orwell and carry no label at all. Naming what it misses is the
    point of labelling rather than pretending to filter.
    """
    names = [n for n in (record.authors or []) if n]
    if not names:
        return None
    forms = [f for f in (author_forms or []) if f]
    if not forms:
        return None
    for name in names:
        if any(names_agree(form, name) for form in forms):
            return None
    return author_display(names[0]) or None


def has_translation_evidence(record) -> bool:
    return bool(record.translators or record.evidence)


def language_contradicts_itself(record, original_language: str | None) -> bool:
    """Does this record claim to be in the language it says it was translated from?

    SBN record UBO4636099 is 'Kafka on the shore / Haruki Murakami ; translated
    from the Japanese by Philip Gabriel', London : Vintage, 2005, ISBN
    9780099494096 — and carries linguaPubblicazione GIAPPONESE, paese GIAPPONE.
    It is the English translation, catalogued as Japanese. Believed, it put a
    2005 edition under a header reading 'first published 2002 in giapponese',
    which is how it was noticed.

    `linguaPubblicazione` is still the only language signal there is
    (`CLAUDE.md` rule 4), so this does not guess a replacement — a record that
    contradicts itself simply stops being evidence of a language.
    """
    if not (original_language and record.language == original_language
            and record.language != langs.UNKNOWN):
        return False
    # The translator is not always in `nomi` or `note`. On this record it is in
    # the title's own statement of responsibility, which nothing else parses.
    return bool(has_translation_evidence(record)
                or TRANSLATED_FROM.search(record.title or ""))


def language_contradicts_script(record) -> bool:
    """Does this record's title contradict the language it claims, by script?

    The other half of the same lie. `Преступлéние и наказáние. 1/2` is a real
    SBN record of *Crime and Punishment* filed `linguaPubblicazione: INGLESE`:
    a Cyrillic title is not an English edition, and since Step 6 romanises, that
    record reaches the candidate set and takes its claimed language with it
    (decision Y, which accepted the visible consequence and routed the rule
    here).

    **Narrow on purpose**, and narrower than the first attempt at it. It fires
    only where the title is *mostly* written in a script the project romanises —
    Cyrillic or Greek — and the claimed language is one
    `catalog.langs.LATIN_SCRIPT` names. A language written in more than one
    script is absent from that set, so Serbian is never disbelieved; a title in
    a script with no romanisation (Japanese, Chinese, Arabic) is not judged at
    all, because nothing here can read it.

    **Mostly, not at all**, and that clause was bought with the one row the
    first version got wrong: `LIGE001533` is `4: Odyssea P-Ω`, a Greek/Latin
    parallel edition filed `lat`, and the single Greek capital in a volume range
    is not evidence the title is Greek. Counting letters instead of looking for
    one costs nothing and silences it.

    Like its sibling it **disbelieves rather than corrects**: the record's
    language becomes unrecorded. `linguaPubblicazione` is still the only
    language signal there is (`CLAUDE.md` rule 4), and inferring `rus` from the
    alphabet would be the guess rule 8 forbids.
    """
    if record.language not in langs.LATIN_SCRIPT:
        return False
    title = record.title or ""
    latin = sum(1 for ch in title if ch.isalpha() and romanise(ch) == ch)
    other = sum(1 for ch in title if ch.isalpha() and romanise(ch) != ch)
    return other > latin


# ---------------------------------------------------------------------------
# 5. Which record is this work, and which authority is this person (Step 6)
# ---------------------------------------------------------------------------

def pick_ol_work(docs: list, titles: list, author: str | None,
                 author_keys=()) -> dict | None:
    """Which Open Library work is this work — by title, with the count as a tie-break.

    **The order matters and is the measured part.** Open Library ranks a search
    for `1984` with *Animal Farm* above it on edition count, so a rule that
    takes the most-published author match picks the wrong book outright. The
    title test decides; the count only separates docs the title test cannot.

    Author agreement is required and is checked two ways, because
    `author_matches` compares ASCII tokens and so cannot match an author Open
    Library files under 村上春樹 or نجيب محفوظ: a doc also passes when its
    `author_keys` are among the keys Open Library's own author search returns
    for the name (A7 — and it omits the main record for Murakami, Dostoevsky and
    Han, so neither check subsumes the other).

    Returns `{"key", "title", "score", "edition_count", "by", "others"}`, or
    None with nothing invented when no doc passes.
    """
    keys = _author_key_set(author_keys)
    scored = []
    for doc in docs or []:
        if not doc.get("id"):
            continue
        by_name, by_key = _ol_author_agrees(doc, author, keys)
        if not (by_name or by_key):
            continue
        score = variant_affinity(doc.get("title") or "", [t for t in titles if t])
        if score < WORK_TITLE_MATCH:
            continue
        scored.append((round(score, 3), doc.get("edition_count") or 0,
                       "author name" if by_name else "author key", doc))
    if not scored:
        return None
    best = max(scored, key=lambda row: (row[0], row[1]))
    return {"key": best[3]["id"], "title": best[3].get("title"), "score": best[0],
            "edition_count": best[1], "by": best[2],
            "others": [(r[3]["id"], r[3].get("title"), r[1]) for r in scored
                       if r[3] is not best[3]][:4]}


# A name authority's free-text search can return thousands of rows for a common
# word, and the "sole Persona" rule below is only safe on a small result set.
AUTHORITY_SOLE_PERSONA_MAX = 1000


def _author_key_set(author_keys) -> set:
    return {k if str(k).startswith("/") else f"/authors/{k}" for k in author_keys or ()}


def _ol_author_agrees(doc: dict, author: str | None, keys: set) -> tuple:
    """`(by_name, by_key)`: the two author tests `pick_ol_work` reads."""
    return (author_matches(author, doc.get("authors") or []),
            bool(keys & set(doc.get("author_keys") or [])))


def duplicate_works(docs: list, titles: list, author: str | None,
                    author_keys=(), main_keys=()) -> list:
    """The other Open Library work records a reader may add (decision J).

    **The same two tests `pick_ol_work` applies, and nothing looser**: the
    author agrees by name or by key, and the doc's title scores at least
    `WORK_TITLE_MATCH` against the *work's* titles — never the typed one alone
    (build rule 11). Measured in Step 13 over 64 entries, the title
    test cuts the list from 674 rows to 246 and loses one known duplicate of 31
    (*Rumori* against *Bruits*, 0.0). What it lets through is what a reader has
    to judge — omnibus volumes, *The Poems of Doctor Zhivago* — so each row
    carries its title and edition count, and nothing here is admitted: a row is
    an offer, and only the reader adding it puts its editions in the store.

    The main work is left out: its editions are S2's. Rows come back most
    editions first, then title and key, so the list is the same for the same
    docs whatever order the searches finished in.
    """
    keys = _author_key_set(author_keys)
    main = {str(k).replace("/works/", "").strip("/") for k in main_keys or ()}
    out, seen = [], set()
    for doc in docs or []:
        key = doc.get("id")
        if not key or key in main or key in seen:
            continue
        by_name, by_key = _ol_author_agrees(doc, author, keys)
        if not (by_name or by_key):
            continue
        score = variant_affinity(doc.get("title") or "", [t for t in titles if t])
        if score < WORK_TITLE_MATCH:
            continue
        seen.add(key)
        out.append({"key": key, "title": doc.get("title") or "",
                    "editions": doc.get("edition_count") or 0,
                    "languages": list(doc.get("languages") or []),
                    "year": doc.get("year"), "score": round(score, 3),
                    "by": "author name" if by_name else "author key"})
    out.sort(key=lambda r: (-r["editions"], r["title"].lower(), r["key"]))
    return out


def _one_person(rows: list) -> list:
    """The rows of `rows` that are the same person, or [] when they are not.

    SBN holds *Pasternak , Boris Leonidovič* twice, once with life dates and
    once without, so two ids are not two people. The heading with its dates
    stripped is what says which: same name, one person, and the duplicate is
    reported rather than treated as an ambiguity.
    """
    names = {frozenset(normalize(author_display(r.get("heading") or ""))) for r in rows}
    return rows if len(names) == 1 else []


def pick_authority(rows: list, author: str, total: int | None = None,
                   forms=()) -> dict:
    """Which SBN name-authority record is this person (A7's rule, guarded).

    A7's cascade, applied to the **Persona** rows only and to the *fullest* name
    form first: a heading whose tokens are the name's, else one that contains
    them, else the sole Persona in a small result set — which is how a name SBN
    files in another transliteration is reached at all.

    Every guard below was put there by what the unguarded rule did the first
    time it ran live, and each failure is a different shape:

    * *Garcia Marquez* reached **`Comite impulsor del juicio de
      responsabilidades contra Luis Garcia Marquez y sus colaboradores`**, a
      corporate body whose heading contains both tokens — hence Persona only.
    * *Pasternak* reached **E. V. Pasternak**, the novelist's son — hence the
      fuller forms (Wikidata's P50 labels) are tried before the typed name.
    * *Leopardi* reached **`Ciriaco Greto , Leopardi`**, a person whose forename
      is Leopardi. `core=autori` matches the name anywhere in the record and
      returns the rows **alphabetically**, not by relevance: 184 rows for
      *Leopardi*, of which the first 40 are A–C, and Giacomo is not among them.
      So a **bare surname against a result set larger than the window read is
      not resolvable**, and saying so is the only honest answer. A7 never met
      this because it asked with full name forms, where the set is small.

    **Several people, no answer.** When the best form still matches two
    different people, this returns `id=None` with the candidates named rather
    than the first row: an author id that might be the wrong person would send
    the author sweep after another writer's bibliography, and a wrong identity
    is the one thing the guard has never done (A1: 0 wrong works in 91 entries).
    """
    persons = [r for r in rows or [] if (r.get("kind") or "").strip() == "Persona"]
    truncated = (total or 0) > len(rows or [])
    wanted, seen = [], []
    for name in [*forms, author, surname(author)]:
        tokens = normalize(name or "")
        if tokens and tokens not in seen:
            seen.append(tokens)
            wanted.append((name, tokens))
    res = {"id": None, "rule": "no match", "matched_form": None,
           "namesakes": [r.get("heading") for r in persons
                         if normalize(surname(author)) <= normalize(r.get("heading") or "")][:5]}
    if not wanted:
        return res

    for name, tokens in wanted:
        headings = [(r, normalize(r.get("heading") or "")) for r in persons]
        for bucket, rule in (([r for r, h in headings if h == tokens],
                              "heading tokens equal the name's"),
                             ([r for r, h in headings if tokens <= h],
                              "heading tokens contain the name's")):
            if not bucket:
                continue
            same = _one_person(bucket)
            if not same:
                # A poorer form can only match more rows, so stop and say so.
                res.update(rule=f"ambiguous: {rule}", matched_form=name,
                           candidates=[(r.get("id"), r.get("heading")) for r in bucket][:5])
                return res
            if len(tokens) < 2 and truncated:
                res.update(rule="not resolved: a bare surname, and the result set "
                                f"is larger ({total}) than the rows read ({len(rows)})",
                           matched_form=name)
                return res
            chosen = same[0]
            res.update(id=chosen.get("id"), heading=chosen.get("heading"),
                       display=author_display(chosen.get("heading") or ""),
                       rule=rule, matched_form=name,
                       duplicate_ids=[r.get("id") for r in same[1:]])
            return res

    if len(persons) == 1 and (total or 0) < AUTHORITY_SOLE_PERSONA_MAX:
        chosen = persons[0]
        res.update(id=chosen.get("id"), heading=chosen.get("heading"),
                   display=author_display(chosen.get("heading") or ""),
                   rule="sole Persona (heading in another transliteration)")
    return res


# ---------------------------------------------------------------------------
# Title only: which books the title names (decision AN)
# ---------------------------------------------------------------------------

# SBN's `tipo` values that are a text. A bare title's chooser offers books, and
# a record of another medium by somebody else is not a second book: the Modena
# City Ramblers' album *Cent'anni di solitudine*, held twice, made García
# Márquez's novel a choice (§9 H03). A record stating no medium is not refused.
TEXT_MEDIA = {"testo a stampa", "testo manoscritto"}


def is_text_medium(medium: str | None) -> bool:
    return not medium or medium.strip().lower() in TEXT_MEDIA


def title_books(candidates: list) -> list:
    """The distinct books a bare title names, one per person, largest first.

    `candidates` are `{"source", "title", "authors", "year", "editions"}`, each
    already titled like the question at 0.6. Two belong to one book when any
    author of one is the same person as any author of the other
    (`core.view.same_person`'s containment on surname tokens), so *Communication*
    by Ruesch and Bateson and *La matrice sociale* by Ruesch are one book while
    Michael Shepherd's is another. A candidate naming nobody joins nothing: a
    record with no author is not evidence of a second book.

    Each book is `{"authors", "title", "first_year", "editions", "sources"}` —
    what a chooser row shows, and what a pick reruns with.
    """
    from .view import same_person, surname_tokens     # view imports this module

    books = []                           # [[token sets], [candidates]]
    for c in candidates:
        tokens = [t for t in (surname_tokens(a) for a in c.get("authors") or []) if t]
        if not tokens:
            continue
        hits = [b for b in books
                if any(same_person(t, u) for t in tokens for u in b[0])]
        if not hits:
            books.append([tokens, [c]])
            continue
        first = hits[0]
        for other in hits[1:]:
            first[0] += other[0]
            first[1] += other[1]
            books.remove(other)
        first[0] += tokens
        first[1].append(c)

    out = []
    for _, members in books:
        names, titles = [], {}
        for c in members:
            for a in c.get("authors") or []:
                shown = author_display(a)
                if shown and not any(normalize(shown) == normalize(n) for n in names):
                    names.append(shown)
            titles[c["title"]] = titles.get(c["title"], 0) + 1
        years = [c["year"] for c in members if c.get("year")]
        out.append({
            "authors": names[:3],
            "title": max(sorted(titles), key=lambda t: titles[t]),
            "first_year": min(years) if years else None,
            "editions": sum(c.get("editions") or 1 for c in members),
            "sources": sorted({c["source"] for c in members}),
        })
    out.sort(key=lambda b: (-b["editions"], b["authors"]))
    return out


def adopted_book(books: list) -> dict | None:
    """The one book a bare title can be taken to mean, or None: then choose.

    Adopted when it is the only book, or the only one two sources agree on
    while every other is a single SBN record. A lone brief record is one
    printing of something — *Verso un'ecologia della mente* by Paolo Migrino,
    beside 28 of Bateson's across three sources — and it does not outweigh
    that; a second book anybody else knows, or SBN holds twice, does. Scored
    over every corpus entry typed without its author (Step 15B, fitting): 20
    adopted, **0 wrong**, 55 choosers. The alternatives were measured and
    refused: Wikidata and Open Library deciding alone adopted Machiavelli for
    *Opere* and Goffman for *Metafora e vita quotidiana*; one corroborated
    book alone adopted 3 wrong. Never a pick by size (decision AN).
    """
    if len(books) == 1:
        return books[0]
    agreed = [b for b in books if len(b["sources"]) >= 2]
    if len(agreed) != 1:
        return None
    rest = [b for b in books if b is not agreed[0]]
    if all(b["sources"] == ["SBN"] and b["editions"] == 1 for b in rest):
        return agreed[0]
    return None
