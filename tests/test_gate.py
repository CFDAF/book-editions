"""The identifying-signal gate, `core.identity.identifies`, and what the header
may never say.

The counterexamples here are the ones `CLAUDE.md` rule 6 forbids loosening the
gate without re-checking. They were prose in `docs/limits.md`; this file is them
as assertions. Until Step 16 they reached the gate through `lookup/pipeline.py`'s
aliases; that module is gone, so they reach `core/` directly. The Dewey tests
went with the Dewey routes (decision AH).
"""

import pathlib

from core import identity as I
from core import view
from core.text import variant_affinity

from conftest import edition as ed


class TestIdentifies:
    VARIANTS = ["L'invenzione delle notizie", "The Invention of News"]

    def test_the_work_authority_identifies_a_record_on_its_own(self):
        """The one reason that needs no corroboration: it is SBN stating the
        link, not this tool inferring it."""
        assert I.identifies(ed("anything at all"), I.WORK_AUTHORITY,
                            self.VARIANTS) == I.STRONG

    def test_a_shared_isbn_identifies_a_record_on_its_own(self):
        assert I.identifies(ed("anything at all"), "isbn match", self.VARIANTS) == I.STRONG

    def test_a_title_at_or_above_the_threshold_identifies(self):
        assert I.identifies(ed("L'invenzione delle notizie"), "author sweep",
                            self.VARIANTS) == I.STRONG

    # ---- the counterexamples CLAUDE.md rule 6 names ----

    def test_lordine_delle_notizie_is_rejected(self):
        """A different book by one shared word.

        At 0.45 it qualified as an edition of 'L'invenzione delle notizie'. It
        scores 0.5 today, and the gate sits at 0.6 — the correct record matches
        its core title at 1.0, so the bar can be well above half.
        """
        assert variant_affinity("L'ordine delle notizie", self.VARIANTS) == 0.5
        assert I.identifies(ed("L'ordine delle notizie"), "author sweep",
                            self.VARIANTS) == ""

    def test_quale_socialismo_quale_europa_is_rejected(self):
        """Attali in 1977, same as 'Bruits', and a different book.

        Same author and same era is not a signal; without the gate an author
        sweep drags in everything the author ever wrote.
        """
        variants = ["Bruits : essai sur l'economie politique de la musique",
                    "Rumori", "Noise"]
        assert I.identifies(ed("Quale socialismo, quale Europa", year="1977",
                               authors=["Attali, Jacques"]),
                            "author sweep", variants) == ""

    def test_the_gate_threshold_has_not_moved(self):
        assert I.IDENTIFYING_TITLE_MATCH == 0.6

    def test_a_shared_dewey_class_identifies_nothing(self):
        """`CLAUDE.md` rule 7, as decision AH left it: García Márquez is 863.44
        and so is every novel he wrote."""
        e = ed("L'autunno del patriarca", dewey="863.44",
               authors=["García Márquez, Gabriel"])
        assert I.identifies(e, "author sweep", ["Cien años de soledad"]) == ""

    def test_an_open_library_sibling_probe_is_not_self_justifying(self):
        """The probe asks SBN for the titles of *other* books by the author, so
        its hits are rejected — otherwise 'Per una economia positiva' returns
        Rumori, Karl Marx and Lessico per il futuro."""
        assert I.identifies(ed("Rumori"), "Open Library sibling",
                            ["Per una economia positiva"]) == ""


class TestAssignGroups:
    """What `tests/test_core_view.py` does not already cover."""

    def test_one_book_is_not_split_by_spelling_or_by_a_credited_translator(self):
        """Keying on the first author's surname alone split one book four ways:
        the same man spelled two ways, his translator credited as an author, and
        his English translator credited ahead of him."""
        rows = [
            ed("Cent'anni di solitudine", authors=["García Márquez, Gabriel"]),
            ed("Cent'anni di solitudine", authors=["Garcia Marquez, Gabriel"]),
            ed("Cent'anni di solitudine", authors=["Cicogna, Enrico"],
               translators=["Cicogna, Enrico"]),
            ed("One hundred years of solitude",
               authors=["Rabassa, Gregory", "Garcia Marquez, Gabriel"],
               translators=["Rabassa, Gregory"]),
            ed("Cien años de soledad", authors=["Gabriel García Márquez"]),
        ]
        assert len(set(view.assign_groups(rows, []))) == 1

    def test_a_compound_surname_and_a_bare_one_are_the_same_person(self):
        """Open Library's 'Gabriel García Márquez' yields {marquez}; SBN's
        'García Márquez, Gabriel' yields {garcia, marquez}. Containment says so."""
        assert view.same_person({"marquez"}, {"garcia", "marquez"}) is True
        assert view.same_person({"marquez"}, {"shepherd"}) is False
        assert view.same_person(set(), {"marquez"}) is False

    def test_a_translator_only_record_joins_the_biggest_group(self):
        rows = [
            ed("Cent'anni di solitudine", authors=["García Márquez, Gabriel"]),
            ed("Cent'anni di solitudine", authors=["García Márquez, Gabriel"]),
            ed("Cent'anni di solitudine", authors=["Cicogna, Enrico"],
               translators=["Cicogna, Enrico"]),
        ]
        keys = view.assign_groups(rows, [])
        assert all(keys) and len(set(keys)) == 1

    def test_a_row_bridging_two_components_merges_them(self):
        rows = [ed("A", authors=["Ruesch, Jurgen"]),
                ed("B", authors=["Bateson, Gregory"]),
                ed("C", authors=["Ruesch, Jurgen", "Bateson, Gregory"])]
        assert len(set(view.assign_groups(rows, []))) == 1

    def test_no_rows_does_not_raise(self):
        assert view.assign_groups([], []) == []


class TestNoFirstEditionDiffersInference:
    def test_the_phrase_does_not_exist_in_the_codebase(self):
        """Decision D / A5 FAIL: the listing rule gave 8 false flags and 1 miss
        over 36 books. **Step 11's gate is this clause**, so the scan covers the
        page as well as the code.

        It is a text match, which means the phrase has to stay out of the
        prose too — the same discipline `tests/test_net_ledger.py` keeps for
        `Pool`. Where a docstring needs to say the inference does not exist, it
        says so in other words.
        """
        root = pathlib.Path(__file__).resolve().parent.parent
        scanned, offenders = 0, []
        for folder in ("lookup", "core", "catalog", "app"):
            for pattern in ("*.py", "web/*.js", "web/*.html", "web/*.css"):
                for path in sorted((root / folder).glob(pattern)):
                    scanned += 1
                    if "first edition differs" in path.read_text(encoding="utf-8").lower():
                        offenders.append(str(path.relative_to(root)))
        for path in (root / "server.py", root / "book_editions.py"):
            scanned += 1
            if "first edition differs" in path.read_text(encoding="utf-8").lower():
                offenders.append(path.name)
        assert offenders == []
        assert scanned > 20          # the scan found the files, not an empty glob
