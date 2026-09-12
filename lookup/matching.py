"""Text matching helpers.

Moved unchanged from the original book_editions.py (lines 68-142); the scoring
was sound and STOPWORDS already carried Italian stopwords, which the
cross-language title crosswalk depends on.
"""

import re
import unicodedata
from typing import Optional

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "in", "on", "to", "for", "is",
    "at", "by", "with", "from", "as", "essai", "sur", "la", "le", "les",
    "di", "del", "della", "il", "lo", "un", "una",
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


def sbn_title_of(raw: str) -> str:
    """SBN titles carry statement-of-responsibility: 'Rumori : saggio ... / Attali'."""
    return (raw or "").split(" / ", 1)[0].strip()
