"""Pure, network-free, unit-tested. Every gate in the project lives here.

`Records -> fold by ISBN -> Editions -> group by language -> View`, all pure:
given the same store, `view` builds the same snapshot byte for byte. A
derivation that is not deterministic is a page that disagrees with its own
store.

Nothing here opens a socket or touches the disk, so `tests/` covers it
completely — which is the point. `catalog/` may not import this package; this
package reads `catalog/langs.py`, and nothing else of it.
"""
