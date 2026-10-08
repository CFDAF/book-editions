"""Builds one fixed store and prints the digest of its snapshot.

Run as a script so `tests/test_core_view.py` can invoke it under two different
`PYTHONHASHSEED` values. Set iteration order for strings depends on that seed
across processes, so two runs agreeing is evidence `core/view.py` does not
iterate a set anywhere — which 100 runs *inside* one process cannot show, since
they all share the one seed.

Not named `test_*`, so pytest does not collect it.
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from catalog import langs                                      # noqa: E402
from core import view                                          # noqa: E402
from core.model import (AUTHOR_SWEEP, DUPLICATE_WORK, REFUSED, TITLE_MATCH,  # noqa: E402
                        UNIFORM_TITLE, WORK_EDITIONS, WORK_LISTING, Holding,
                        Provenance, Record, Work)
from core.store import RecordStore                             # noqa: E402


def sbn(rec_id, evidence=UNIFORM_TITLE, route=WORK_LISTING, score=None, **kw):
    return Record(source="SBN", id=rec_id,
                  provenance=Provenance("SBN", route, evidence, score), **kw)


def ol(rec_id, evidence=TITLE_MATCH, route=WORK_EDITIONS, score=None, **kw):
    return Record(source="Open Library", id=rec_id,
                  provenance=Provenance("Open Library", route, evidence, score), **kw)


def build() -> tuple:
    """A store with every shape the view has to order: several languages, a
    shared ISBN, an unrecorded language, two authors, a refusal."""
    work = Work(
        sbn_work="cien anos de soledad", sbn_work_tier="strong", qid="Q480861",
        ol_keys=["OL274505W"], author_id="CFIV000263",
        titles_by_lang={"ita": "Cent'anni di solitudine",
                        "eng": "One Hundred Years of Solitude",
                        "spa": "Cien años de soledad"},
        original_title="Cien años de soledad", original_language="spa",
        original_year="1967", authors=["García Márquez, Gabriel"],
        stated_by="Wikidata", basis="P407 + P577",
    )
    store = RecordStore()
    store.put_all([
        sbn("MIL0871878", title="Cent'anni di solitudine", year="1985",
            language="ita", publisher="Mondadori, Milano",
            publisher_names=["Mondadori"], places=["Milano"],
            isbns_raw=["88-45-90686-2"], authors=["Garcia Marquez, Gabriel"],
            translators=["Cicogna, Enrico"], dewey="863.44",
            holdings=[Holding("Biblioteca Nazionale", "Roma", "IT-RM0267")]),
        sbn("MIL0871879", title="Cent'anni di solitudine", year="2003",
            language="ita", publisher="Mondadori, Milano",
            publisher_names=["Mondadori"], places=["Milano"],
            isbns_raw=["978-88-459-0686-2"], authors=["García Márquez, Gabriel"]),
        sbn("TO01234567", title="Cien años de soledad", year="1967",
            language="spa", publisher="Sudamericana, Buenos Aires",
            publisher_names=["Sudamericana"], places=["Buenos Aires"],
            authors=["Garcia Marquez, Gabriel"]),
        sbn("UBO4636099", title="One hundred years of solitude", year="1970",
            language=langs.UNKNOWN, publisher="Harper, New York",
            publisher_names=["Harper"], places=["New York"],
            authors=["Garcia Marquez, Gabriel"]),
        ol("OL7355623M", title="One Hundred Years of Solitude", year="1998",
           language="eng", publisher="Penguin", publisher_names=["Penguin"],
           isbns_raw=["9780140157512"], authors=["Gabriel García Márquez"]),
        ol("OL9999999M", title="Cent'anni di solitudine", year="1985",
           language="ita", publisher="Mondadori", publisher_names=["Mondadori"],
           authors=["Gabriel García Márquez"]),
        # A second sighting of a record already held, through another route.
        sbn("MIL0871878", route=AUTHOR_SWEEP, evidence=TITLE_MATCH, score=1.0,
            title="Cent'anni di solitudine", series="Oscar Mondadori"),
        # Refused: the loose-match band's row. A companion essay sharing the
        # work's title is exactly what no threshold can reach (Step 2, U2).
        sbn("NAP0001111", evidence=REFUSED, route=AUTHOR_SWEEP, score=0.5,
            title="Postille a Cent'anni di solitudine", year="1984",
            language="ita", publisher="Bompiani", publisher_names=["Bompiani"],
            authors=["Eco, Umberto"]),
        # Added by the reader from another Open Library record (Step 13): in the
        # groups, out of the header, in a language nothing else reaches.
        Record(source="Open Library", id="OL1234567M", title="Cien años de soledad",
               year="1969", language="cat", publisher="Edhasa",
               publisher_names=["Edhasa"],
               provenance=Provenance("Open Library", DUPLICATE_WORK, DUPLICATE_WORK,
                                     via="OL43144891W")),
    ])
    return store, work


# The list the reader added from, with one row added and one that failed.
EVIDENCE = {"duplicates": {"asked": True, "added": ["OL43144891W"],
                           "failed": {"OL28027117W": "timed out"}, "rows": [
    {"key": "OL43144891W", "title": "Cien Años De Soledad", "editions": 1},
    {"key": "OL28027117W", "title": "Cien Años de Soledad", "editions": 1}]}}


def digest() -> str:
    store, work = build()
    snapshot = view.snapshot(store, work, version=3, evidence=EVIDENCE)
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=False).encode()).hexdigest()


if __name__ == "__main__":
    print(digest())
