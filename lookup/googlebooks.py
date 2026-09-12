"""Google Books — optional, and genuinely unusable without a key.

The shared anonymous quota is permanently exhausted:

    429 Quota exceeded for quota metric 'Queries' and limit 'Queries per day'
        of service 'books.googleapis.com'

The original script called this "the most reliable automated signal for
translations" while, in practice, it returned nothing on every call. Here it is
explicitly optional: without GOOGLE_BOOKS_API_KEY the source reports 'skipped'
and the lookup proceeds on Open Library + SBN, rather than silently yielding an
empty Italian list that reads like "no translation exists".
"""

import os

from . import langs
from .models import Edition
from .net import SourceError, cached_get_json

ENDPOINT = "https://www.googleapis.com/books/v1/volumes"


def api_key() -> str | None:
    return os.environ.get("GOOGLE_BOOKS_API_KEY") or None


def available() -> bool:
    return bool(api_key())


def search(query: str, lang_restrict: str | None = None, max_results: int = 40) -> list:
    key = api_key()
    if not key:
        raise SourceError("no GOOGLE_BOOKS_API_KEY set")
    params = {"q": query, "maxResults": min(max_results, 40), "key": key}
    if lang_restrict:
        params["langRestrict"] = lang_restrict
    data = cached_get_json(ENDPOINT, params)
    if data.get("error"):
        raise SourceError(f"Google Books: {data['error'].get('message')}")

    out = []
    for item in data.get("items") or []:
        info = item.get("volumeInfo") or {}
        sale = item.get("saleInfo") or {}
        isbn = None
        for ident in info.get("industryIdentifiers") or []:
            if ident.get("type") == "ISBN_13":
                isbn = ident.get("identifier")
                break
            if ident.get("type") == "ISBN_10" and not isbn:
                isbn = ident.get("identifier")
        out.append(Edition(
            source="Google Books",
            title=info.get("title") or "",
            publisher=info.get("publisher"),
            year=(info.get("publishedDate") or "")[:4] or None,
            language=langs.from_two_letter(info.get("language")),
            isbn=isbn,
            url=sale.get("buyLink") or info.get("infoLink"),
        ))
    return out
