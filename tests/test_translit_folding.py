"""U3 — what romanisation and the transliteration fold do to the 0.6 gate.

Decisions B and G **shipped in Step 6**, inside `core/text.py`: `normalize`
romanises Cyrillic and Greek, and `title_similarity` folds each token to a form
two romanisations of it share. Step 1B measured a *candidate* fold on unchanged
code and found it safe; this file is the re-check U3's own caveat demanded —
"Step 6 must re-run that test against whatever fold it actually ships" — so the
reference implementation moved here instead, and what is measured is the code.

`unfolded_affinity` below is the gate **as it was before Step 6**: no
romanisation, no fold, and STOPWORDS without the bare `de`/`en`. Everything is
scored against it, so the numbers are the step's own effect and not a tautology.

Result, measured 2026-09-22 over `tests/data/corpus.json` (40 books, 103 titles):

    cross-book title pairs scored ........................ 5,152
    pairs Step 6 pushes from below 0.6 to >= 0.6 .........     0
    pairs Step 6 pushes from >= 0.6 to below .............     0
    same-book pairs recovered ............................     5
    gate counterexamples moved ...........................     0

The five are the fold's own (N23 *Odysseia* ~ *Odissea*) and four that
romanisation adds, each an entry title finally matching its own original:
*Doktor Zhivago* ~ Доктор Живаго, *Prestuplenie i nakazanie* ~ Преступление и
наказание, and *Odysseia* / *Odissea* ~ Ὀδύσσεια.

The U2 title-gate measurement (`docs/DECISIONS.md` §9) scored its judged
records with `folded_affinity` from here: the gate with the fold in force.
"""

import itertools
import json
import pathlib
import re
import unicodedata

import pytest

from core import text as T
from core.text import STOPWORDS
from core import identity as I

GATE = I.IDENTIFYING_TITLE_MATCH

# The gate before Step 6, kept as the thing to measure against. It is a copy on
# purpose: a reference that imports the code under test measures nothing.
BEFORE_STEP_6 = STOPWORDS - {"de", "en"}


def _tokens_before(text: str) -> set:
    if not text:
        return set()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in BEFORE_STEP_6 and len(t) > 1}


def _similarity_before(a: str, b: str) -> float:
    q, c = _tokens_before(a), _tokens_before(b)
    if not q or not c:
        return 0.0
    return len(q & c) / max(len(q), len(c))


def unfolded_affinity(a: str, b: str) -> float:
    """Full title or core title, whichever wins — as Step 5 left it."""
    return max(_similarity_before(a, b),
               _similarity_before(T.core_title(a), T.core_title(b)))


def folded_affinity(a: str, b: str) -> float:
    """The shipped gate."""
    return T.similarity(a, b)


def _corpus_titles() -> dict:
    path = pathlib.Path(__file__).resolve().parent / "data" / "corpus.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    titles = {}
    for book in corpus["books"]:
        found = {t for t in [book.get("original_title")] if t}
        found |= {e["title"] for e in book.get("entries") or [] if e.get("title")}
        titles[book["id"]] = found
    return titles


class TestFoldingRecoversItsTargets:
    """The two misses decision G exists for, and the scripts decision B reaches."""

    def test_doktor_zhivago_reaches_sbns_doktor_zivago(self):
        assert unfolded_affinity("Doktor Zhivago", "doktor zivago") < GATE
        assert folded_affinity("Doktor Zhivago", "doktor zivago") == 1.0

    def test_odysseia_reaches_sbns_odyssea(self):
        assert unfolded_affinity("Odysseia", "odyssea") == 0.0
        assert folded_affinity("Odysseia", "odyssea") == 1.0

    def test_odysseia_reaches_the_italian_odissea(self):
        assert folded_affinity("Odysseia", "Odissea") == 1.0

    def test_a_cyrillic_title_reaches_its_own_romanisation(self):
        """Before Step 6 this was 0.0 — the ASCII encode dropped the title
        entirely, so a work matched *itself* at nothing."""
        assert unfolded_affinity("Doktor Zhivago", "Доктор Живаго") == 0.0
        assert folded_affinity("Doktor Zhivago", "Доктор Живаго") == 1.0


class TestFoldingDoesNotBreakTheGate:
    """The re-check CLAUDE.md rule 6 and `docs/DECISIONS.md` §7 both demand."""

    def test_lordine_delle_notizie_stays_rejected(self):
        variants = "L'invenzione delle notizie"
        assert unfolded_affinity("L'ordine delle notizie", variants) == 0.5
        assert folded_affinity("L'ordine delle notizie", variants) == 0.5 < GATE

    @pytest.mark.parametrize("variant", [
        "Bruits : essai sur l'economie politique de la musique",
        "Rumori",
        "Noise",
    ])
    def test_quale_socialismo_quale_europa_stays_rejected(self, variant):
        query = "Quale socialismo, quale Europa"
        assert unfolded_affinity(query, variant) == 0.0
        assert folded_affinity(query, variant) == 0.0 < GATE

    def test_cross_language_titles_are_not_rescued_by_folding(self):
        # Folding is a transliteration tool, not a translation one.
        assert folded_affinity("Noise", "Rumori") == 0.0
        assert folded_affinity("One Hundred Years of Solitude",
                               "Cien años de soledad") == 0.0


class TestFoldingOnTheWholeCorpus:
    def test_no_cross_book_pair_is_raised_over_the_gate(self):
        """The measurement U3 asks for, as an assertion.

        Every title of every book scored against every title of every *other*
        book: Step 6 must not push a pair from below the gate to at or above it.
        0 of 5,152, the same as the candidate fold measured in Step 1B.
        """
        titles = _corpus_titles()
        raised, lowered, scored = [], [], 0
        for (b1, t1), (b2, t2) in itertools.combinations(titles.items(), 2):
            for a in t1:
                for b in t2:
                    scored += 1
                    before, after = unfolded_affinity(a, b), folded_affinity(a, b)
                    if after >= GATE > before:
                        raised.append((b1, a, b2, b))
                    if before >= GATE > after:
                        lowered.append((b1, a, b2, b))
        assert scored == 5152, f"corpus changed shape: {scored} pairs, expected 5152"
        assert raised == [], f"Step 6 raised {len(raised)} cross-book pairs over the gate"
        assert lowered == [], f"Step 6 dropped {len(lowered)} cross-book pairs below it"

    def test_no_cross_book_pair_reaches_the_gate_even_before_step_6(self):
        """The baseline the test above is measured against."""
        titles = _corpus_titles()
        over = [(b1, a, b2, b)
                for (b1, t1), (b2, t2) in itertools.combinations(titles.items(), 2)
                for a in t1 for b in t2
                if unfolded_affinity(a, b) >= GATE]
        assert over == []

    def test_step_6_recovers_exactly_five_same_book_pairs(self):
        """Recorded as a number so a later change to the fold or the romanisation
        shows up as a changed count and not a silent one. One is the fold's
        (N23), four are romanisation reaching a script that used to vanish."""
        titles = _corpus_titles()
        recovered = [(bid, a, b)
                     for bid, ts in titles.items()
                     for a, b in itertools.combinations(sorted(ts), 2)
                     if folded_affinity(a, b) >= GATE > unfolded_affinity(a, b)]
        assert sorted(bid for bid, *_ in recovered) == ["E16", "N04", "N23", "N23", "N23"]

    def test_no_same_book_pair_is_lost(self):
        titles = _corpus_titles()
        lost = [(bid, a, b)
                for bid, ts in titles.items()
                for a, b in itertools.combinations(sorted(ts), 2)
                if unfolded_affinity(a, b) >= GATE > folded_affinity(a, b)]
        assert lost == []
