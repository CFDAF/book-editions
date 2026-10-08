"""Normalising, comparing and scoring titles and names. Pure, no I/O.

Was `lookup/matching.py` (and before that `book_editions.py` lines 68-142);
moved here in Step 5, unchanged apart from the two additions at the foot of the
file. `lookup/matching.py` re-exports it until Step 16.

**The two things Step 6 added** are `romanise` (decision B) and
`fold_variants` (decision G), and both move the 0.6 gate, which is why they
waited for the step that re-checks the counterexamples. Neither is a loosening:
romanisation turns a script `normalize` used to discard into tokens, and the
fold collapses two spellings of one sound. Both were measured before they
landed — 0 of 5,152 cross-book title pairs raised over the gate (U3), and on
700 judged records the fold admits 5 more same-work rows and **not one more
leak** (U2, `work/plain` 386/18 against `work/folded` 391/18).

`STOPWORDS` gained the bare `de` and `en` in the same step, for the same
reason and on the same evidence: they were the hole the missing `delle` was,
and closing it blocked two wrong-work records that were clearing 0.6 on a
shared function word while costing no same-work record at all.
"""

import re
import unicodedata
from typing import Optional

# Function words only. The original list had "della" but not "delle", which
# made "delle" count as a meaningful token: "L'ordine delle notizie" then scored
# 0.67 against "L'invenzione delle notizie" while the correct record scored 0.43,
# ranking a different book above the right one.
STOPWORDS = {
    # English
    "the", "a", "an", "of", "and", "or", "in", "on", "to", "for", "is",
    "at", "by", "with", "from", "as", "its", "that", "this", "into", "about",
    "be", "are", "was", "were", "it", "his", "her", "their", "how",
    # Italian
    "la", "le", "lo", "il", "gli", "un", "una", "uno",
    "di", "del", "dei", "degli", "della", "delle", "dello",
    "al", "alla", "alle", "ai", "agli", "allo",
    "dal", "dalla", "dalle", "dai", "dagli",
    "nel", "nella", "nelle", "nei", "negli",
    "sul", "sulla", "sulle", "sui", "sugli",
    "con", "per", "tra", "fra", "che", "non", "ed", "come",
    # French / Spanish / Portuguese fragments that turn up in original titles.
    # `de` and `en` arrived in Step 6, the last of the `delle` family's holes:
    # while they counted as meaningful tokens, *Apostille au Nom de la rose*
    # scored exactly 0.6 against *Il nome della rosa* and *Una unidad sagrada*
    # 0.625 against *Verso un'ecologia della mente* — two different books each.
    # Measured over the 700 judged rows of U2: leaks 18 -> 16, same-work
    # records admitted unchanged at 393, and 0 of 5,152 cross-book title pairs
    # move across the gate in either direction.
    "les", "des", "du", "de", "en", "sur", "essai", "el", "los", "las", "y",
}


def normalize(text: str) -> set:
    """Lowercase, romanise, strip accents/punctuation, drop stopwords, tokenise.

    `romanise` runs first (decision B, Step 6). Without it the ASCII encode
    below drops a Cyrillic or Greek title to *nothing* and every comparison
    involving it is 0.0 — which is a silent 'no match', not a refusal. It can
    only add tokens where there were none, so it moves no score down; the
    cross-book re-check is in `tests/test_translit_folding.py`.
    """
    if not text:
        return set()
    text = unicodedata.normalize("NFKD", romanise(text)).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 1}


def core_title(title: str) -> str:
    """Title with any subtitle (after ':' or ' - ') stripped off."""
    for sep in (":", " - ", " — "):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title.strip()


def title_similarity(query_title: str, candidate_title: str) -> float:
    """Token overlap, each token folded to its transliteration-neutral form.

    The fold is decision G and arrived in Step 6: `Doktor Zhivago` is the same
    title as SBN's `doktor zivago`, and `Odysseia` the same as `odyssea`, and
    nothing but a fold can see it. It is applied here rather than in `normalize`
    so that author matching and the Dewey title key keep comparing the spelling
    the catalogue actually used.
    """
    q = {fold_variants(t) for t in normalize(query_title)}
    c = {fold_variants(t) for t in normalize(candidate_title)}
    if not q or not c:
        # Nothing to compare — unless the two strings are the same string. A
        # title in a script with no romanisation tokenises to nothing, so
        # `海辺のカフカ` scored 0.0 against **itself** and Open Library's own
        # record of the work was refused by the title test. An exact match is
        # the strongest title evidence there is, and a Latin title has always
        # scored 1.0 for it; this is the same answer for the other scripts.
        a, b = (query_title or "").strip().casefold(), (candidate_title or "").strip().casefold()
        return 1.0 if a and a == b else 0.0
    overlap = len(q & c)
    return overlap / max(len(q), len(c))


def author_matches(query_author: Optional[str], candidate_authors: list) -> bool:
    if not query_author:
        return True  # no author given, don't penalize
    qa = normalize(query_author)
    for cand in candidate_authors or []:
        if normalize(cand) & qa:
            return True
    return False


# ---------------------------------------------------------------------------
# Additions for the crosswalk
# ---------------------------------------------------------------------------

def surname(author: str) -> str:
    """Best-effort surname, for catalogues that index 'Surname, Forename'.

    SBN's author index is far more forgiving of a bare surname than of a full
    name in the wrong order, so queries use this rather than the raw input.
    """
    if not author:
        return ""
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = author.split()
    return parts[-1] if parts else ""


def author_display(name: str) -> str:
    """'Pettegree, Andrew <1957- >' -> 'Andrew Pettegree'.

    SBN inverts names and appends life dates; Open Library does neither. A list
    mixing both sources reads badly unless they are brought into one form.
    """
    if not name:
        return ""
    name = re.sub(r"\s*<[^>]*>", "", name).strip().strip(",")
    if name.count(",") == 1:
        surname_part, _, forename = name.partition(",")
        if forename.strip():
            return f"{forename.strip()} {surname_part.strip()}"
    return name


# ---------------------------------------------------------------------------
# Added in Step 5
# ---------------------------------------------------------------------------

def similarity(query: str, candidate: str) -> float:
    """Title similarity, full or on core titles — the better of the two.

    One title with a subtitle and one without are the same title, and every
    gate in the project compares them this way: the SBN guard's A and B, the
    Wikidata title test, the recovery route's threshold. It was written out
    three times before this.
    """
    return max(title_similarity(query, candidate),
               title_similarity(core_title(query), core_title(candidate)))


def variant_affinity(title: str, variants) -> float:
    """The best `similarity` against any known title of the work.

    Same-language title comparison, which is the only kind that means
    anything: `title_similarity('Noise', 'Rumori')` is exactly 0.0. The gate
    reads this, so what decides a record is how many languages the work's title
    set covers — not the threshold (Step 2, U2).
    """
    return max((similarity(v, title) for v in variants), default=0.0)


# ---------------------------------------------------------------------------
# Added in Step 6 — decision B (romanise) and decision G (the fold)
# ---------------------------------------------------------------------------

# Cyrillic and Greek, letter by letter, in the romanisation the corpus itself
# uses: `Доктор Живаго` -> `Doktor Zhivago`, `Ὀδύσσεια` -> `Odysseia`,
# `Преступление и наказание` -> `Prestuplenie i nakazanie`. BGN/PCGN for the
# Cyrillic, which is what a reader types; the scientific `Živago` that SBN
# catalogues under is reached from it by the fold below, not by a second table.
_RUSSIAN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Ukrainian and the South Slavic Cyrillic letters, so a title in one of
    # them romanises whole instead of half.
    "і": "i", "ї": "yi", "є": "ye", "ґ": "g",
    "ђ": "d", "ј": "j", "љ": "lj", "њ": "nj", "ћ": "c", "џ": "dz",
}
_GREEK = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "e",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "ph", "χ": "ch", "ψ": "ps", "ω": "o",
}
_ROMANISE = {}
for _table in (_RUSSIAN, _GREEK):
    for _lower, _latin in _table.items():
        _ROMANISE[ord(_lower)] = _latin
        _ROMANISE[ord(_lower.upper())] = _latin.capitalize()
_ROMANISED_SCRIPTS = frozenset(_ROMANISE)


def is_latin(text: str) -> bool:
    """Is every letter here one a catalogue's free-text search will accept?

    The OPAC does not answer non-Latin free text with an error: it **discards
    the term** and returns the unfiltered set — `ANY + AUTHOR` equals `AUTHOR`
    alone, and bare `ANY` returns all 21,806,046 records (F15, verified). A
    query that cannot be romanised must therefore not be sent at all, and this
    is the check that says so.
    """
    return all(not unicodedata.category(ch).startswith("L")
               or "LATIN" in unicodedata.name(ch, "")
               for ch in text or "")


def romanise(text: str) -> str:
    """Cyrillic and Greek to Latin script. Everything else is returned as it is.

    Latin text is never touched, accents and all — this is a script change, not
    a normaliser, and `normalize` strips the accents a moment later anyway.
    Japanese, Chinese and Arabic have no letter-by-letter romanisation and none
    is invented here: they come back unchanged and `is_latin` still says no, so
    a caller refuses to send them rather than sending something plausible.
    UC3 is what covers that case — a title in another script is typed romanised.
    """
    if not text or text.isascii():
        return text or ""
    if not any(ord(ch) in _ROMANISED_SCRIPTS for ch in text):
        return text
    # The Greek diacritics are combining marks once decomposed, and `Ὀ` is one
    # codepoint until then, so the strip has to come before the table.
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", text)
                       if not unicodedata.combining(ch))
    return stripped.translate(_ROMANISE)


# Transliteration digraphs, longest first, applied to a token `normalize` has
# already lowercased and stripped of accents (so ž is z before this runs). The
# fold is decision G; U3 measured it over the corpus and U2 over 700 judged
# records, and both are re-run as tests.
_DIGRAPHS = (("shch", "s"), ("zh", "z"), ("kh", "h"), ("ch", "c"),
             ("sh", "s"), ("ts", "c"), ("ph", "f"))
_GREEK_ENDING = re.compile(r"eia\b")
_DOUBLED = re.compile(r"(.)\1+")
_SEMIVOWEL = re.compile(r"[jy]")


def fold_variants(token: str) -> str:
    """One token, folded to a form two romanisations of it share.

    `zhivago` and `zivago`, `odysseia` and `odyssea`, `dostoevskij` and
    `dostoevsky` — one word each, spelled by two schemes. Folding them is not a
    loosening of the 0.6 gate: it is the gate finally comparing like with like,
    and it was measured in both directions before it shipped (U3: 0 of 5,152
    cross-book pairs raised; U2: 5 more same-work records, 0 more leaks).
    """
    for digraph, letter in _DIGRAPHS:
        token = token.replace(digraph, letter)
    token = _GREEK_ENDING.sub("ea", token)
    token = _DOUBLED.sub(r"\1", token)
    return _SEMIVOWEL.sub("i", token)
