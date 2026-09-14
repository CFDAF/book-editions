"""Ground truth, encyclopaedia side: the Wikipedia articles for each book.

Wikidata is used only to *locate* articles (sitelinks of items A1 found and
checked by hand); every fact is read from the article text, never from a
Wikidata claim, since Wikidata is under test in A5.

Fetches, per book, the English article and the article in the original's
language, in batches of up to 50 titles per wiki (one request each). Writes
bench/raw/gt/wikipedia.json (full wikitext, not committed) and
results/stage-1/gt_wikipedia.json: infobox fields, the first lines of the
lead, and sentences naming a number of languages.
"""

import json
import re

import common

net = common.setup("stage-1/gt-wiki", log_name="gt_wikipedia", user_agent=common.UA_CONTACT)

WD = "https://www.wikidata.org/w/api.php"
# Items whose identity was checked in A1 (label and description read by hand).
QIDS = {
    "E01": "Q178869", "E02": "Q1970551", "E03": "Q7047658", "E04": "Q579744", "E09": "Q172850",
    "E12": "Q330979", "E16": "Q206870", "N01": "Q917055", "N02": "Q25338", "N03": "Q836036",
    "N05": "Q183883", "N06": "Q208460", "N07": "Q1032190", "N08": "Q22263533", "N09": "Q1427187",
    "N10": "Q163297", "N11": "Q595140", "N12": "Q36097", "N14": "Q826428", "N15": "Q219437",
    "N16": "Q151919", "N17": "Q3149381", "N18": "Q25519071", "N19": "Q115818209", "N20": "Q31067292",
    "N21": "Q5219975", "N22": "Q15991228", "N23": "Q35160",
}
# No checked item: look the article up by title instead.
EN_TITLES = {
    "E05": "The Invention of News", "E06": "More Brilliant than the Sun", "E07": "Liquid Modernity",
    "E08": "Communication: The Social Matrix of Psychiatry", "N04": "Crime and Punishment",
    "N13": "The Burnout Society", "E15": "The Essential Knuth",
}
EXTRA = {"N13": [("de", "Müdigkeitsgesellschaft")], "E13": [("it", "Angelus Novus (Benjamin)")],
         "E14": [("fr", "Pour une économie positive")], "E10": [], "E11": [], "N24": []}
WIKI = {"spa": "es", "fre": "fr", "jpn": "ja", "ita": "it", "ger": "de", "rus": "ru", "cze": "cs",
        "por": "pt", "chi": "zh", "ara": "ar", "eng": "en", "grc": "el"}
CLAIMED_LANG = {
    "E01": "spa", "E02": "eng", "E03": "fre", "E04": "jpn", "E05": "eng", "E06": "eng", "E07": "eng",
    "E08": "eng", "E09": "ita", "E10": "ita", "E11": "ita", "E12": "ger", "E13": "ita", "E14": "fre",
    "E15": "eng", "E16": "rus", "N01": "cze", "N02": "fre", "N03": "ita", "N04": "rus", "N05": "eng",
    "N06": "eng", "N07": "ita", "N08": "ita", "N09": "ita", "N10": "fre", "N11": "fre", "N12": "ger",
    "N13": "ger", "N14": "por", "N15": "spa", "N16": "chi", "N17": "ara", "N18": "eng", "N19": "eng",
    "N20": "eng", "N21": "spa", "N22": "fre", "N23": "grc", "N24": "ita",
}
FIELDS = re.compile(r"^\s*\|\s*(title_orig|orig_lang|language|lingua|langue|sprache|idioma|publisher|editore|"
                    r"éditeur|editorial|verlag|pub_date|published|release_date|first_published|annoorig|"
                    r"date de parution|fecha|erscheinungsjahr|erstausgabe|country|paese|lieu de parution|"
                    r"translator|traduttore|media_type|editora|data|anno|ano|published_in|genre)\s*=\s*(.+)$",
                    re.I | re.M)
LANGS = re.compile(r"[^.\n]{0,160}\b(\d{2,3}|forty|fifty|sixty|thirty|twenty)[\w\s+-]{0,12}\s(languages|lingue|langues|idiomas|Sprachen|lenguas|línguas)\b[^.\n]{0,120}", re.I)


def main():
    corpus = common.load_corpus()
    sitelinks = net.cached_get_json(WD, {"action": "wbgetentities", "ids": "|".join(QIDS.values()),
                                         "props": "sitelinks", "format": "json"})["entities"]
    wanted = {}   # wiki -> {title: [book ids]}
    for book in corpus["books"]:
        bid = book["id"]
        pages = []
        if bid in QIDS:
            links = (sitelinks.get(QIDS[bid]) or {}).get("sitelinks") or {}
            for wiki in {"en", WIKI.get(CLAIMED_LANG[bid], "en"), "it"}:
                if f"{wiki}wiki" in links:
                    pages.append((wiki, links[f"{wiki}wiki"]["title"]))
        if bid in EN_TITLES:
            pages.append(("en", EN_TITLES[bid]))
        pages += EXTRA.get(bid, [])
        for wiki, title in pages:
            wanted.setdefault(wiki, {}).setdefault(title, []).append(bid)

    raw, summary = {}, {}
    for wiki, titles in wanted.items():
        names = list(titles)
        for i in range(0, len(names), 50):
            d = net.cached_get_json(f"https://{wiki}.wikipedia.org/w/api.php", {
                "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
                "titles": "|".join(names[i:i + 50]), "redirects": "1", "format": "json", "formatversion": "2"})
            q = d.get("query") or {}
            alias = {m["to"]: m["from"] for hop in ("normalized", "redirects") for m in q.get(hop) or []}
            for page in q.get("pages") or []:
                asked = page["title"]
                while asked in alias:
                    asked = alias[asked]
                text = ((page.get("revisions") or [{}])[0].get("slots") or {}).get("main", {}).get("content")
                for bid in titles.get(asked, []):
                    raw.setdefault(bid, {})[f"{wiki}:{page['title']}"] = text
                    if text is None:
                        summary.setdefault(bid, {})[f"{wiki}:{page['title']}"] = {"missing": True}
                        continue
                    lead = re.sub(r"\{\{[^{}]*\}\}", "", text)
                    lead = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", lead, flags=re.S)
                    first = next((p.strip() for p in lead.split("\n\n") if len(p.strip()) > 200
                                  and not p.strip().startswith(("{", "|", "[[File", "[[Image", "[[Datei", "[[Fichier"))), "")
                    summary.setdefault(bid, {})[f"{wiki}:{page['title']}"] = {
                        "url": f"https://{wiki}.wikipedia.org/wiki/{page['title'].replace(' ', '_')}",
                        "infobox": [f"{m.group(1).strip()} = {m.group(2).strip()[:160]}" for m in FIELDS.finditer(text[:12000])][:14],
                        "lead": first[:700],
                        "language_counts": [m.group(0).strip()[:300] for m in LANGS.finditer(text)][:4],
                    }
    common.save_json(common.BENCH / "raw" / "gt" / "wikipedia.json", raw)
    common.save_json(common.RESULTS / "gt_wikipedia.json", {"books": summary, "requests": common.summarise(),
                                                            "failures": common.failures()})
    print(json.dumps(common.summarise()), sum(len(v) for v in summary.values()), "articles")


if __name__ == "__main__":
    main()
