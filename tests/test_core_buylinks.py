"""`core/buylinks.py` — the deep links, ISBN only.

Pure and network-free: these are search URLs built from what the row already
carries, not a stock lookup. No Italian retailer offers a free stock or price
API, and the three templates that looked plausible but 404 are recorded in the
module so nobody re-adds them.
"""

from urllib.parse import parse_qs, urlsplit

import pytest

from core import buylinks


def query_value(url: str) -> str:
    """The one search term in a deep link, whatever the shop calls the key."""
    fields = parse_qs(urlsplit(url).query)
    for key in ("query", "k", "q", "isbn"):
        if key in fields:
            return fields[key][0]
    raise AssertionError(f"no search term in {url}")


class TestWhatIsSearchedFor:
    def test_an_isbn_is_searched_as_an_isbn(self):
        links = buylinks.links("978-88-459-0686-2")
        assert {query_value(link["url"]) for link in links} == {"9788845906862"}

    @pytest.mark.parametrize("isbn", [None, "", "  "])
    def test_without_an_isbn_there_are_no_links(self, isbn):
        """A title search lands on whichever edition the shop sells now, not the
        row the reader opened, so the user asked for it to go (2026-09-28)."""
        assert buylinks.links(isbn) == []


class TestTheShape:
    def test_every_store_appears_once_in_a_fixed_order(self):
        links = buylinks.links("9788845906862")
        assert [link["store"] for link in links] == [s[0] for s in buylinks.STORES]

    def test_the_used_shops_are_marked_as_used(self):
        kinds = {link["store"]: link["kind"] for link in buylinks.links("9788845906862")}
        assert kinds["AbeBooks"] == "used" and kinds["Maremagnum"] == "used"
        assert kinds["IBS"] == "new"
