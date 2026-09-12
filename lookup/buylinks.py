"""Where to actually get a copy.

No Italian retailer offers a free stock/price API, and scraping one would break
on the next markup change, so these are deterministic search deep links. Every
URL template below was checked to return 200; the ones that looked plausible but
404 are recorded so nobody re-adds them:

    libraccio.it/ricerca/?searchTerm=    404  (search is an ASP.NET POST form,
                                              <form name="aspnetForm" method="post">,
                                              so no GET deep link exists at all)
    lafeltrinelli.it/libri/ricerca?query=  404  (correct path is /search)
    mondadoristore.it/ricerca/?g=          404  (correct path is /search/)

For an out-of-print book the honest answer is not a shop at all — it is SBN's
holdings list, handled in sbn.py.
"""

from urllib.parse import quote_plus

from .models import BuyLink

# (store, kind, template). {q} is the ISBN, or a title+author string.
STORES = (
    ("IBS",         "new",  "https://www.ibs.it/search/?ts=as&query={q}"),
    ("Amazon.it",   "new",  "https://www.amazon.it/s?k={q}"),
    ("Feltrinelli", "new",  "https://www.lafeltrinelli.it/search?query={q}"),
    ("Mondadori",   "new",  "https://www.mondadoristore.it/search/?q={q}"),
    ("AbeBooks",    "used", "https://www.abebooks.it/servlet/SearchResults?isbn={q}"),
    ("Maremagnum",  "used", "https://www.maremagnum.com/search?q={q}"),
)
# AbeBooks' isbn= parameter only means anything for an actual ISBN.
ISBN_ONLY = {"AbeBooks"}


def for_edition(isbn: str | None, title: str | None, author: str | None = None) -> list:
    isbn_clean = (isbn or "").replace("-", "").replace(" ", "").strip()
    fallback = " ".join(filter(None, [title, author])).strip()
    if not isbn_clean and not fallback:
        return []

    links = []
    for store, kind, template in STORES:
        if store in ISBN_ONLY and not isbn_clean:
            continue
        query = isbn_clean or fallback
        links.append(BuyLink(store=store, kind=kind, url=template.format(q=quote_plus(query))))
    return links
