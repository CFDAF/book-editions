"""Replay recorded catalogue responses instead of calling the catalogues.

Set ``BOOK_FIXTURES=<dir>`` (the suite uses ``tests/data/fixtures``) and every
request the lookup makes is answered from the bundle in that directory: a
``manifest.json`` and one gzipped body per request under ``bodies/``. Nothing
reaches the network and nothing reaches the disk cache. The bundle holds the
bodies the tests read, not a whole lookup's, and nothing here rebuilds it.

**Why it sits here and not around the sources.** A test that wraps
`sbn.search` or `openlibrary.editions` proves those functions behave; it proves
nothing about the ones that were added last week. The switch belongs under the
HTTP layer, where every source has to pass, so "offline" is a property of the
process rather than of the sources someone remembered to stub.

**A miss raises.** `FixtureMiss` is deliberately *not* a `SourceError`: every
source in this package turns a `SourceError` into "no results and a failed call
on the ledger", which is right against a real catalogue and useless in a test —
the run would go green having silently measured nothing. `FixtureMiss` is not caught
anywhere and stops the run. Falling through to the network would be worse
still: the test would pass, slowly, against live data, which is the one thing
the bundle exists to avoid.

The bundle is keyed by `catalog.http._cache_path`'s hash, so a body is found by the same
computation that would have found it in the cache.
"""

import gzip
import json
import os
import threading
from pathlib import Path

_lock = threading.Lock()
_manifest: dict | None = None
_dir: Path | None = None


class FixtureMiss(Exception):
    """A request the fixture bundle has no recorded answer for.

    Not a SourceError. See the module docstring: a swallowed miss is a test
    that measures nothing and reports success.
    """


def active() -> bool:
    return bool(os.environ.get("BOOK_FIXTURES"))


def directory() -> Path:
    global _dir
    if _dir is None:
        _dir = Path(os.environ["BOOK_FIXTURES"])
    return _dir


def manifest() -> dict:
    """Provenance, loaded once. Only read to explain a miss and to report."""
    global _manifest
    with _lock:
        if _manifest is None:
            path = directory() / "manifest.json"
            if not path.is_file():
                raise FixtureMiss(
                    f"BOOK_FIXTURES={directory()} has no manifest.json. "
                    f"The suite's bundle is tests/data/fixtures.")
            _manifest = json.loads(path.read_text(encoding="utf-8"))
        return _manifest


def load(key: str, described: str):
    """The recorded body for this cache key, or raise FixtureMiss."""
    path = directory() / "bodies" / f"{key}.json.gz"
    if not path.is_file():
        entry = next((f for f in manifest()["fixtures"] if f["key"] == key), None)
        detail = ""
        if entry:
            # in the manifest but not on disk: a truncated or half-built bundle
            detail = (f" The manifest records it (run {entry['run']}, recorded "
                      f"{entry['recorded']}) but bodies/{key}.json.gz is missing.")
        raise FixtureMiss(
            f"no recorded response for {described} (key {key}).{detail} "
            f"The bundle holds only the bodies the suite reads: the code now "
            f"asks for something that was never recorded.")
    with gzip.open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def reset() -> None:
    """Forget the cached manifest and directory. For tests that switch bundles."""
    global _manifest, _dir
    with _lock:
        _manifest, _dir = None, None
