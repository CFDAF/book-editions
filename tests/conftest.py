"""Shared fixtures, and the guarantee that none of this suite touches the network.

Everything under `tests/` covers pure functions. None of them should open a
socket — but "should" is how a suite ends up quietly measuring live catalogue
data and reporting success. So the ban is enforced rather than assumed, the same
argument `catalog/fixtures.py` makes for putting the replay switch under the HTTP
layer instead of around the sources.
"""

import socket

import pytest

from core.model import REFUSED, WORK_LISTING, Provenance, Record


class NetworkUsed(RuntimeError):
    """A test in this suite tried to open a socket. See the module docstring."""


@pytest.fixture(autouse=True, scope="session")
def _no_network():
    """Fail loudly on any outbound connection, for the whole session."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def blocked(self, address, *args, **kwargs):
        raise NetworkUsed(
            f"tests/ is an offline suite and something tried to reach {address!r}. "
            "Pure functions only here; anything needing a catalogue belongs in "
            "the replay suite (BOOK_FIXTURES) or the Step 1C live runner."
        )

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    try:
        yield
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex


def edition(title, **kw) -> Record:
    """A record with only the fields a test cares about.

    The gate counterexamples are hand-built rather than replayed: the point is
    the scoring rule, and a real record drags in twenty fields that have nothing
    to do with it.
    """
    kw.setdefault("source", "SBN")
    kw.setdefault("id", title)
    kw.setdefault("provenance", Provenance(kw["source"], WORK_LISTING, REFUSED))
    return Record(title=title, **kw)


@pytest.fixture
def ed():
    return edition
