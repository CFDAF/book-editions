"""The transport: `POST /lookup` returns a job id, `GET /lookup/<id>?v=N` a
versioned snapshot (decision M, Step 8).

It is the new tree's outside edge. `catalog/` fetches, `core/` decides,
`lookup/stages.py` orchestrates, and this publishes what they produce. Nothing
here parses a catalogue or judges a record; if a rule appears in this package it
is in the wrong place.
"""
