"""`catalog/wikidata.item_forms` — which names an item goes by.

The sitelinks are real, from this machine's caches on 2026-09-30: Q210784's
(*The Idiot*), abridged, and Q113244935's ja.wikipedia title. Commons and
cs.wikiquote title their pages in a namespace, and `core_title` cuts at the
colon, so every such page reduces to `Category` or `Dílo` and two unrelated
items share a title (decision AZ).
"""

from catalog import wikidata

IDIOT = {"labels": {"en": {"value": "The Idiot"}, "it": {"value": "L'idiota"}},
         "sitelinks": {"commonswiki": {"title": "Category:The Idiot (Dostoyevsky)"},
                       "cswikiquote": {"title": "Dílo:Idiot"},
                       "enwiki": {"title": "The Idiot"},
                       "ruwiki": {"title": "Идиот (роман)"},
                       "ruwikisource": {"title": "Идиот (Достоевский)"}}}


def test_the_title_test_keeps_every_page():
    assert wikidata.item_forms(IDIOT) == ["The Idiot", "L'idiota", "Category:The Idiot",
                                          "Dílo:Idiot", "Идиот"]


def test_author_mode_leaves_out_another_projects_namespaced_page():
    assert wikidata.item_forms(IDIOT, names_only=True) == ["The Idiot", "L'idiota", "Идиот"]


def test_a_wikipedia_title_with_a_colon_is_a_title():
    spider = {"sitelinks": {"jawiki": {"title": "スパイダーマン:ブランド・ニュー・デイ"}}}
    assert wikidata.item_forms(spider, names_only=True) == ["スパイダーマン:ブランド・ニュー・デイ"]
