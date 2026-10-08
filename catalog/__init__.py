"""I/O and parsing. Never decides.

One module per API, and the names say which API: `sbn_opac` and `sbn_mobile`
are two unrelated interfaces to the same catalogue, and mistaking one for the
other is how "no free catalogue records the link between a translation and its
original" became a recorded fact and was wrong (`docs/DECISIONS.md` pitfall 1).

The rule that shapes the package: **a source module fetches, parses and
returns — it does not decide.** No title gate, no work guard, no language
verdict, no merging. Those are pure and live in `core/`, and **nothing here
imports `core`** (`tests/test_tree_layering.py` fails if it ever does). The one
exception to the direction is `catalog/langs.py`, which `core` reads: it is a
vocabulary of four catalogues' language codes, which is source knowledge with
no I/O and no judgement in it, and the layering rule is one-way.
"""
