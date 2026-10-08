"""Where to actually get a copy. Deep links only — pure, and no network.

Was `lookup/buylinks.py` through Step 9; moved here in Step 10 because the new
tree needs it when a row is expanded, and there may be only one implementation
(`CLAUDE.md`, *The short version*). `lookup/buylinks.py` now wraps these dicts
in its own `BuyLink` and adds nothing else.

No Italian retailer offers a free stock/price API, and scraping one would break
on the next markup change, so these are deterministic search deep links. Every
URL template below was checked to return 200; the ones that looked plausible but
404 are recorded so nobody re-adds them:

    libraccio.it/ricerca/?searchTerm=    404  (search is an ASP.NET POST form,
                                              <form name="aspnetForm" method="post">,
                                              so no GET deep link exists at all)
    lafeltrinelli.it/libri/ricerca?query=  404  (correct path is /search)
    mondadoristore.it/ricerca/?g=          404  (correct path is /search/)

**Only for a row with an ISBN.** A title-and-author search lands on whichever
edition the shop sells now, not the row the reader opened, so the user asked
for those links to go (2026-09-28). With no ISBN there are no links, and the
answer to "where do I get a copy" is SBN's holdings list, or the Internet
Archive where Open Library records a scan.
"""

from urllib.parse import quote_plus

# (store, kind, template). {q} is the ISBN.
STORES = (
    ("IBS",         "new",  "https://www.ibs.it/search/?ts=as&query={q}"),
    ("Amazon.it",   "new",  "https://www.amazon.it/s?k={q}"),
    ("Feltrinelli", "new",  "https://www.lafeltrinelli.it/search?query={q}"),
    ("Mondadori",   "new",  "https://www.mondadoristore.it/search/?q={q}"),
    ("AbeBooks",    "used", "https://www.abebooks.it/servlet/SearchResults?isbn={q}"),
    ("Maremagnum",  "used", "https://www.maremagnum.com/search?q={q}"),
)


def links(isbn: str | None) -> list:
    """`[{"store", "kind", "url"}]`, in `STORES` order. `[]` without an ISBN,
    which is 38% of SBN full records (F12)."""
    isbn_clean = (isbn or "").replace("-", "").replace(" ", "").strip()
    if not isbn_clean:
        return []
    return [{"store": store, "kind": kind,
             "url": template.format(q=quote_plus(isbn_clean))}
            for store, kind, template in STORES]
