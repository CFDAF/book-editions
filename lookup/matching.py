"""Text matching helpers.

Moved unchanged from the original book_editions.py (lines 68-142); the scoring
was sound and STOPWORDS already carried Italian stopwords, which the
cross-language title crosswalk depends on.
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
    # French / Spanish fragments that turn up in original titles
    "les", "des", "du", "sur", "essai", "el", "los", "las", "y",
}


def normalize(text: str) -> set:
    """Lowercase, strip accents/punctuation, drop stopwords, return token set."""
    if not text:
        return set()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 1}


def core_title(title: str) -> str:
    """Title with any subtitle (after ':' or ' - ') stripped off."""
    for sep in (":", " - ", " — "):
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title.strip()


def title_similarity(query_title: str, candidate_title: str) -> float:
    q = normalize(query_title)
    c = normalize(candidate_title)
    if not q or not c:
        return 0.0
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


def strip_disambiguator(title: str) -> str:
    """Drop a Wikipedia disambiguator: '1984 (romanzo)' -> '1984'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title or "").strip()


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


def sbn_title_of(raw: str) -> str:
    """SBN titles carry statement-of-responsibility: 'Rumori : saggio ... / Attali'."""
    return (raw or "").split(" / ", 1)[0].strip()
