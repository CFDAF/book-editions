"""Ground truth, catalogue side: national-library records for each book.

For every book: the earliest catalogued edition of the original (BnF for
French, DNB for German, LoC for the rest, SBN for Italian), and a record for
each entry title (SBN for Italian titles, LoC for English ones). Extra queries
cover the first editions that are expected to differ from the original
(Živago in Italian, Kundera in French, Le Petit Prince in English).

Records count only when their title matches the searched title at >= 0.6
(core or full title), so a study guide or an adaptation does not become the
"earliest edition". A bogus-title control runs once per catalogue.

Output: results/stage-1/gt_catalogues.json. The ground truth itself is written
by hand into corpus.json from this file plus the Wikipedia pages.
"""

import json
import re
import unicodedata
import xml.etree.ElementTree as ET

import common

net = common.setup("stage-1/gt", log_name="gt_catalogues")
from lookup import opac  # noqa: E402
from lookup.matching import core_title, sbn_title_of, surname, title_similarity  # noqa: E402
from lookup.sbn import clean_text, parse_publication  # noqa: E402

YEAR = re.compile(r"\b(1[4-9]\d\d|20[0-2]\d)\b")
SRU = {
    "loc": ("http://lx2.loc.gov:210/LCDB", "1.1", "dc", 50),
    "bnf": ("https://catalogue.bnf.fr/api/SRU", "1.2", "dublincore", 50),
    "dnb": ("https://services.dnb.de/sru/dnb", "1.1", "oai_dc", 100),
}
MAX = 300


def fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def sim(a, b):
    return max(title_similarity(a, b), title_similarity(core_title(a), core_title(b)))


def cql(cat, title, author):
    t = fold(core_title(title)).replace('"', "")
    a = fold(surname(author))
    return {"loc": f'bath.title="{t}" and bath.author={a}',
            "bnf": f'bib.title all "{t}" and bib.author all "{a}"',
            "dnb": f'tit="{t}" and per={a}'}[cat]


def sru(cat, query):
    url, version, schema, page = SRU[cat]
    records, start, total = [], 1, None
    while True:
        r = net.session().get(url, params={"version": version, "operation": "searchRetrieve", "query": query,
                                           "recordSchema": schema, "maximumRecords": page, "startRecord": start},
                              timeout=(10, 60))
        r.raise_for_status()
        root = ET.fromstring(r.content)
        n = next((e.text for e in root.iter() if e.tag.endswith("numberOfRecords")), "0")
        total = int(n or 0)
        batch = [e for e in root.iter() if e.tag.endswith("}recordData") or e.tag == "recordData"]
        for rd in batch:
            rec = {}
            for e in rd.iter():
                name = e.tag.rsplit("}", 1)[-1]
                if name in ("title", "date", "publisher", "language", "creator", "identifier") and e.text:
                    rec.setdefault(name, []).append(e.text.strip())
            records.append(rec)
        start += page
        if not batch or start > min(total, MAX):
            break
    return total, records


def catalogue(cat, title, author):
    q = cql(cat, title, author)
    try:
        total, recs = sru(cat, q)
    except Exception as exc:
        return {"catalogue": cat, "query": q, "failed": f"{type(exc).__name__}: {str(exc)[:160]}"}
    rows = []
    for rec in recs:
        t = (rec.get("title") or [""])[0]
        m = YEAR.search(" ".join(rec.get("date") or []))
        if sim(title, t.split(" / ")[0]) >= 0.6:
            rows.append({"title": t[:150], "year": m.group(1) if m else None,
                         "publisher": (rec.get("publisher") or [None])[0],
                         "language": (rec.get("language") or [None])[0]})
    dated = sorted((r for r in rows if r["year"]), key=lambda r: r["year"])
    return {"catalogue": cat, "query": q, "total": total, "fetched": len(recs), "title_matches": len(rows),
            "earliest": dated[:3]}


def sbn(title, author, lang=None):
    if not fold(title).strip():
        return {"catalogue": "sbn", "skipped": "non-Latin title (the OPAC drops it)"}
    base = {"core": "sbn", opac.ANY: title, opac.AUTHOR: author}
    if lang:
        base["lingua[]"] = lang
    rows, total, page = [], None, 1
    try:
        while True:
            d = opac._post({**base, "page": str(page)})
            total = d.get("total") or 0
            for r in d.get("results") or []:
                t = sbn_title_of(clean_text((r.get("title") or {}).get("info")) or "")
                infos = r.get("infos") or []
                imprint = clean_text(infos[0]) if infos else None
                if sim(title, t) >= 0.6:
                    publisher, year, place = parse_publication(imprint)
                    rows.append({"bid": r.get("id"), "title": t[:150], "imprint": imprint, "year": year})
            page += 1
            if page > min((total + 19) // 20, 15):
                break
    except net.SourceError as exc:
        return {"catalogue": "sbn", "failed": str(exc)[:160]}
    dated = sorted((r for r in rows if r["year"]), key=lambda r: r["year"])
    return {"catalogue": "sbn", "query": {"any": title, "author": author, "lingua": lang}, "total": total,
            "title_matches": len(rows), "earliest": dated[:3]}


ORIGINAL_CATALOGUE = {"fre": "bnf", "ger": "dnb"}
# The original language as the corpus sources claim it (§9, STRATEGY); only
# used to pick a catalogue. Ground truth checks the claim.
CLAIMED_LANG = {
    "E01": "spa", "E02": "eng", "E03": "fre", "E04": "jpn", "E05": "eng", "E06": "eng", "E07": "eng",
    "E08": "eng", "E09": "ita", "E10": "ita", "E11": "ita", "E12": "ger", "E13": "ger", "E14": "fre",
    "E15": "eng", "E16": "rus", "N01": "cze", "N02": "fre", "N03": "ita", "N04": "rus", "N05": "eng",
    "N06": "eng", "N07": "ita", "N08": "ita", "N09": "ita", "N10": "fre", "N11": "fre", "N12": "ger",
    "N13": "ger", "N14": "por", "N15": "spa", "N16": "chi", "N17": "ara", "N18": "eng", "N19": "eng",
    "N20": "eng", "N21": "spa", "N22": "fre", "N23": "grc", "N24": "ita",
}
EXTRA = {
    "E16": [("sbn", "Il dottor Živago", "Pasternak", "ita")],
    "N01": [("bnf", "L'insoutenable légèreté de l'être", "Kundera", None)],
    "N02": [("loc", "The Little Prince", "Saint-Exupery", None)],
    "N05": [("sbn", "Vita da uomo", "Salinger", None)],
}


def main():
    corpus = common.load_corpus()
    out = {"controls": {
        "loc_bogus_title": sru("loc", 'bath.title="zzqxqv qvzzq" and bath.author=salinger')[0],
        "bnf_bogus_title": sru("bnf", 'bib.title all "zzqxqv qvzzq" and bib.author all "camus"')[0],
        "dnb_bogus_title": sru("dnb", 'tit="zzqxqv qvzzq" and per=Kafka')[0],
        "sbn_bogus_title": opac._post({"core": "sbn", opac.ANY: "zzqxqv", opac.AUTHOR: "Calvino", "page": "1"}).get("total"),
    }, "books": {}}
    print("controls", out["controls"], flush=True)
    for book in corpus["books"]:
        a = book["query_author"]
        res = {"original": [], "entries": {}, "extra": []}
        original = book.get("original_title_romanised") or book["original_title"]
        lang = CLAIMED_LANG[book["id"]]
        if lang == "ita":
            res["original"].append(sbn(original, a, "ita"))
        else:
            res["original"].append(catalogue(ORIGINAL_CATALOGUE.get(lang, "loc"), original, a))
        for e in book["entries"]:
            if e["title"] == book["original_title"]:
                continue
            if e["lang"] == "ita":
                res["entries"][e["key"]] = sbn(e["title"], a)
            elif e["lang"] == "eng":
                res["entries"][e["key"]] = catalogue("loc", e["title"], a)
        for cat, t, au, lg in EXTRA.get(book["id"], []):
            res["extra"].append(sbn(t, au, lg) if cat == "sbn" else catalogue(cat, t, au))
        out["books"][book["id"]] = res
        brief = lambda r: (r.get("catalogue"), r.get("total"), r.get("title_matches"),
                           [(x.get("year"), (x.get("publisher") or x.get("imprint") or "")[:40]) for x in r.get("earliest", [])[:1]],
                           r.get("failed") or r.get("skipped"))
        print(book["id"], "orig", [brief(r) for r in res["original"]],
              {k: brief(v) for k, v in res["entries"].items()}, [brief(r) for r in res["extra"]], flush=True)
    out["requests"] = common.summarise()
    out["failures"] = common.failures()
    common.save_json(common.RESULTS / "gt_catalogues.json", out)


if __name__ == "__main__":
    main()
