"""VIAF, keyless: A6 work census and A7 personal clusters.

    python stage1_viaf.py works     -> results/stage-1/a6_viaf.json
    python stage1_viaf.py persons   -> results/stage-1/a7_viaf.json

API: GET https://viaf.org/viaf/search?query=<CQL>, Accept: application/json
(spec: developer.api.oclc.org/docs/viaf/openapi-external-prod.yaml). Full
cluster records, at most 10 per page. JSON keys carry a per-record namespace
prefix (ns2:, ns3:, ...), stripped on read.

Controls, run first: a bogus index and a bogus value must both return 0
records rather than an unfiltered set.
"""

import json
import re
import sys
import unicodedata

import common

MODE = sys.argv[1]
net = common.setup("stage-1/viaf-lookup", log_name=f"viaf_{MODE}")
from lookup import langs  # noqa: E402
from lookup.matching import core_title, normalize, title_similarity  # noqa: E402

SEARCH = "https://viaf.org/viaf/search"
HEADERS = {"Accept": "application/json"}
PAGE = 10
# Results come back in viafID-descending order, not by relevance (sortKey is
# ignored: holdingscount and a bogus key give the same order), so main clusters
# with short ids sink. Persons are paged further for that reason.
MAX_RECORDS = 50 if MODE == "works" else 200


def unns(o):
    if isinstance(o, dict):
        return {(k.split(":", 1)[1] if k.startswith("ns") and ":" in k else k): unns(v) for k, v in o.items()}
    if isinstance(o, list):
        return [unns(x) for x in o]
    return o


def L(x):
    return x if isinstance(x, list) else ([] if x in (None, "") else [x])


def ascii_fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]+", " ", text).strip()


def search(cql: str) -> dict:
    """Every record for a CQL query, up to MAX_RECORDS. {total, records, requests}."""
    records, start, total, m0 = [], 1, None, common.mark()
    while True:
        d = unns(common.cached_get(SEARCH, {"query": cql, "maximumRecords": PAGE, "startRecord": start},
                                   HEADERS, "stage-1/viaf"))["searchRetrieveResponse"]
        total = int((d.get("numberOfRecords") or {}).get("content") or 0)
        if d.get("diagnostics"):
            return {"total": total, "records": [], "diagnostic": d["diagnostics"], "requests": common.mark() - m0}
        page = [r["recordData"]["VIAFCluster"] for r in L((d.get("records") or {}).get("record"))]
        records += page
        start += PAGE
        if not page or start > min(total, MAX_RECORDS):
            break
    return {"total": total, "records": records, "requests": common.mark() - m0}


def headings(c) -> list:
    return [str(h.get("text")) for h in L((c.get("mainHeadings") or {}).get("data")) if h.get("text") is not None]


def controls() -> dict:
    return {
        "bogus_index": search('local.zzqxbogus all "cien anos de soledad"')["total"],
        "bogus_value": search('local.uniformTitleWorks all "zzqxqv qvzzq"')["total"],
        "real_value": search('local.uniformTitleWorks all "garcia marquez cien anos de soledad"')["total"],
    }


# ------------------------------------------------------------------ A6 -----

# English (VIAF's usual) and a few other free-text language names -> ISO 639-2/B.
# Tried only after lookup.langs, which knows SBN's Italian names and codes.
NAMES = {
    "english": "eng", "italian": "ita", "french": "fre", "german": "ger", "spanish": "spa",
    "portuguese": "por", "russian": "rus", "latin": "lat", "dutch": "dut", "flemish": "dut",
    "greek": "gre", "greek, modern": "gre", "modern greek": "gre", "greek, ancient": "grc",
    "ancient greek": "grc", "catalan": "cat", "polish": "pol", "czech": "cze", "swedish": "swe",
    "danish": "dan", "norwegian": "nor", "norwegian bokmal": "nob", "norwegian nynorsk": "nno",
    "finnish": "fin", "hungarian": "hun", "japanese": "jpn", "chinese": "chi", "arabic": "ara",
    "hebrew": "heb", "turkish": "tur", "romanian": "rum", "croatian": "hrv", "serbian": "srp",
    "slovenian": "slv", "slovak": "slo", "bulgarian": "bul", "ukrainian": "ukr", "belarusian": "bel",
    "korean": "kor", "persian": "per", "hindi": "hin", "bengali": "ben", "gujarati": "guj",
    "marathi": "mar", "tamil": "tam", "telugu": "tel", "kannada": "kan", "malayalam": "mal",
    "urdu": "urd", "punjabi": "pan", "vietnamese": "vie", "thai": "tha", "indonesian": "ind",
    "malay": "may", "estonian": "est", "latvian": "lav", "lithuanian": "lit", "icelandic": "ice",
    "irish": "gle", "welsh": "wel", "basque": "baq", "galician": "glg", "albanian": "alb",
    "macedonian": "mac", "bosnian": "bos", "armenian": "arm", "georgian": "geo", "azerbaijani": "aze",
    "kazakh": "kaz", "uzbek": "uzb", "mongolian": "mon", "esperanto": "epo", "afrikaans": "afr",
    "swahili": "swa", "yiddish": "yid", "tagalog": "tgl", "filipino": "fil", "sinhalese": "sin",
    "sinhala": "sin", "nepali": "nep", "burmese": "bur", "khmer": "khm", "lao": "lao",
    "tibetan": "tib", "faroese": "fao", "frisian": "fry", "luxembourgish": "ltz", "maltese": "mlt",
    "occitan": "oci", "romansh": "roh", "sardinian": "srd", "friulian": "fur", "corsican": "cos",
    "scottish gaelic": "gla", "breton": "bre", "kurdish": "kur", "pashto": "pus", "tajik": "tgk",
    "turkmen": "tuk", "kyrgyz": "kir", "tatar": "tat", "chuvash": "chv", "bashkir": "bak",
    "amharic": "amh", "hausa": "hau", "yoruba": "yor", "igbo": "ibo", "zulu": "zul", "xhosa": "xho",
    "somali": "som", "malagasy": "mlg", "javanese": "jav", "sundanese": "sun", "quechua": "que",
    "guarani": "grn", "aymara": "aym", "greenlandic": "kal", "sanskrit": "san", "pali": "pli",
    "syriac": "syr", "coptic": "cop", "church slavic": "chu", "old norse": "non", "moldavian": "rum",
    "valencian": "cat", "serbo-croatian": "hbs", "chinese, classical": "chi", "sorbian": "wen",
    "upper sorbian": "hsb", "lower sorbian": "dsb", "scots": "sco", "interlingua": "ina",
    "anglès": "eng", "francès": "fre", "castellà": "spa", "italià": "ita", "alemany": "ger",
    "anglais": "eng", "allemand": "ger", "espagnol": "spa", "italien": "ita",
    "englisch": "eng", "deutsch": "ger", "französisch": "fre", "spanisch": "spa", "italienisch": "ita",
    "inglés": "eng", "francés": "fre", "alemán": "ger", "italiano": "ita", "español": "spa",
    # Polish cataloguing abbreviations ("(wł.)" is włoski, Italian)
    "(pol.)": "pol", "(ang.)": "eng", "(fr.)": "fre", "(niem.)": "ger", "(wł.)": "ita", "(hisz.)": "spa",
    "(ros.)": "rus", "(norw.)": "nor", "(port.)": "por", "(chiń.)": "chi", "(ukr.)": "ukr", "(czes.)": "cze",
    "(słowac.)": "slo", "(tur.)": "tur", "(łac.)": "lat", "(węg.)": "hun", "(bułg.)": "bul", "(niderl.)": "dut",
    "(słoweń.)": "slv", "(serb.)": "srp", "(białorus.)": "bel", "(pers.)": "per", "(jap.)": "jpn", "(hebr.)": "heb",
    # Swedish, Czech/Slovak, Catalan and other names seen in the corpus
    "svenska": "swe", "spanska": "spa", "engelska": "eng", "franska": "fre", "ryska": "rus", "finska": "fin",
    "ungerska": "hun", "albanska": "alb", "polska": "pol", "tyska": "ger", "italienska": "ita",
    "esperantsky": "epo", "makedonsky": "mac", "ukrajinsky": "ukr", "srbsky": "srp", "bosensky": "bos",
    "mongolsky": "mon", "turecky": "tur", "albánsky": "alb", "català": "cat", "eslovè": "slv", "serbi": "srp",
    "français": "fre", "ruso": "rus", "panjabi": "pan", "greek, modern (1453-)": "gre",
    "greek (modern greek)": "gre", "haitian french creole": "hat", "gaelic": "gae", "tahitian": "tah",
    "ladino": "lad", "bambara": "bam", "santomenc": "cpp", "totonac": "nai", "qashqai": "tut",
}
UNMAPPED_MARKERS = {"null", "none", "", "und", "mul", "zxx"}


def norm_langs(label):
    """Every code in a label: 'English & Greek' names two languages."""
    parts = [p for p in re.split(r"\s*&\s*", str(label))] if label is not None else [None]
    return [norm_lang(p) for p in parts]


def norm_lang(label):
    """(code | None, how). `how` says which table answered."""
    raw = str(label).strip() if label is not None else "null"
    low = raw.lower().strip(" .")
    if low in UNMAPPED_MARKERS:
        return None, "no language"
    if langs.from_sbn(raw) != langs.UNKNOWN:
        return langs.from_sbn(raw), "langs.from_sbn"
    if len(low) in (2, 3) and low.isalpha():
        code = langs.from_openlibrary(low) if len(low) == 3 else langs.from_two_letter(low)
        if code != langs.UNKNOWN:
            return code, "langs code"
    if low in NAMES:
        return NAMES[low], "bench table"
    return None, "unmapped"


ADAPTATION = re.compile(r"\b(film|motion picture|serial|television|telenovela|libretto|opera|"
                        r"sound recording|videorecording|comic|graphic novel|adaptation|adaptacja|wyb[oó]r|selections|excerpts)", re.I)


def author_ok(book, heading_text: str) -> bool:
    """Some credited author shares min(2, its token count) name tokens with the headings.

    Two tokens where the name has two, so 'Bateson, Mary Catherine' is not taken
    for Gregory Bateson on the surname alone.
    """
    h = normalize(heading_text)
    return any(len(normalize(a) & h) >= min(2, len(normalize(a)))
               for a in book["authors"] if normalize(a))


def sbn_works() -> dict:
    path = common.RESULTS / "a1_sbn.json"
    if not path.is_file():
        return {}
    out = {}
    for bid, b in json.loads(path.read_text())["books"].items():
        out[bid] = sorted({e["W"] for e in b["entries"].values() if e.get("W") and e.get("tier") == "strong"})
    return out


SBN_W = sbn_works()


def work_census(book) -> dict:
    a_fold = " ".join(sorted(normalize(book["query_author"])))
    titles = [book["original_title"]] + ([book["original_title_romanised"]] if book.get("original_title_romanised") else [])
    keys = [(t, "corpus original") for t in titles] + [(w, "SBN strong W") for w in SBN_W.get(book["id"], [])]
    known = titles + [e["title"] for e in book["entries"]] + SBN_W.get(book["id"], [])
    queries, clusters = [], {}
    for t, why in keys:
        t_fold = " ".join(sorted(normalize(core_title(t)) or normalize(t)))
        if not t_fold:
            queries.append({"title": t, "why": why, "skipped": "no Latin tokens to search with"})
            continue
        for cql in (f'local.uniformTitleWorks all "{a_fold} {t_fold}"', f'local.uniformTitleWorks all "{t_fold}"'):
            if any(q.get("cql") == cql for q in queries):
                continue
            try:
                res = search(cql)
            except net.SourceError as exc:
                queries.append({"cql": cql, "why": why, "failed": str(exc)[:200]})
                continue
            queries.append({"cql": cql, "why": why, "total": res["total"], "returned": len(res["records"]),
                            "requests": res["requests"]})
            for c in res["records"]:
                if c.get("nameType") == "UniformTitleWork":
                    clusters.setdefault(str(c.get("viafID")), c)
    if not any(author_ok(book, " | ".join(headings(c))) for c in clusters.values()):
        # Apostrophe words ("d'inverno") do not match VIAF's tokens; retry without them.
        for t, why in keys:
            words = " ".join(w for w in core_title(t).split() if w.isalnum())
            t_fold = " ".join(sorted(normalize(words)))
            cql = f'local.uniformTitleWorks all "{a_fold} {t_fold}"'
            if not t_fold or any(q.get("cql") == cql for q in queries):
                continue
            try:
                res = search(cql)
            except net.SourceError as exc:
                queries.append({"cql": cql, "why": why + ", apostrophe words dropped", "failed": str(exc)[:200]})
                continue
            queries.append({"cql": cql, "why": why + ", apostrophe words dropped", "total": res["total"],
                            "returned": len(res["records"]), "requests": res["requests"]})
            for c in res["records"]:
                if c.get("nameType") == "UniformTitleWork":
                    clusters.setdefault(str(c.get("viafID")), c)
    kept, dropped = [], []
    for vid, c in clusters.items():
        hs = headings(c)
        text = " | ".join(hs)
        a_ok = author_ok(book, text)
        title_score = max((title_similarity(k, h.split("|")[-1]) for k in known for h in hs), default=0.0)
        title_score = max(title_score, max((title_similarity(core_title(k), core_title(h.split("|")[-1]))
                                            for k in known for h in hs), default=0.0))
        info = {"viafID": vid, "headings": hs[:3], "author_ok": a_ok,
                "title_score": round(title_score, 2), "adaptation": bool(ADAPTATION.search(text))}
        if not a_ok or title_score < 0.6 or info["adaptation"]:
            dropped.append(info)
            continue
        exprs = L((c.get("titles") or {}).get("expression"))
        rows, codes, how = [], set(), {}
        for e in exprs:
            found = norm_langs(e.get("lang"))
            for code_i, h in found:
                how[h] = how.get(h, 0) + 1
                if code_i:
                    codes.add(code_i)
            code = next((c for c, _ in found if c), None)
            subs = L((e.get("datafield") or {}).get("subfield"))
            rows.append({"lang": e.get("lang"), "code": code, "translator": e.get("translator"),
                         "title": e.get("title") or next((s.get("content") for s in subs if s.get("code") == "t"), None),
                         "year": next((s.get("content") for s in subs if s.get("code") == "f"), None)})
        work_lang, _ = norm_lang(((c.get("languageOfEntity") or {}).get("data") or {}).get("text")
                                 if isinstance((c.get("languageOfEntity") or {}).get("data"), dict) else None)
        info.update(expressions=len(exprs), languages=sorted(codes), label_normalisation=how,
                    language_of_entity=work_lang,
                    unmapped_labels=sorted({str(r["lang"]) for r in rows if r["code"] is None}),
                    sources=[s.get("content") if isinstance(s, dict) else s
                             for s in L((c.get("sources") or {}).get("source"))][:20],
                    expression_rows=rows)
        kept.append(info)
    census = set()
    for k in kept:
        census |= set(k["languages"])
        if k["language_of_entity"]:
            census.add(k["language_of_entity"])
    return {"queries": queries, "clusters_kept": kept, "clusters_dropped": dropped,
            "work_clusters": len(kept), "census_languages": sorted(census), "census_size": len(census)}


# ------------------------------------------------------------------ A7 -----

def person_clusters(person: str, variant: str) -> dict:
    q = variant if not ascii_fold(variant) else ascii_fold(variant)
    try:
        res = search(f'local.personalNames all "{q}"')
    except net.SourceError as exc:
        return {"variant": variant, "sent": q, "failed": str(exc)[:200], "clusters": [], "chosen": None}
    person_toks = normalize(person)
    out = []
    for c in res["records"]:
        if c.get("nameType") != "Personal":
            continue
        hs = headings(c)
        srcs = [s.get("content") if isinstance(s, dict) else s for s in L((c.get("sources") or {}).get("source"))]
        name_toks = set().union(*[normalize(h) for h in hs]) if hs else set()
        out.append({"viafID": str(c.get("viafID")), "headings": hs[:3], "sources": len(srcs),
                    "wikidata": [s.split("|", 1)[1] for s in srcs if str(s).startswith("WKP|")],
                    "iccu": [s for s in srcs if str(s).startswith("ICCU|")],
                    "birth": c.get("birthDate"), "death": c.get("deathDate"),
                    "same_name": person_toks <= name_toks if person_toks else None})
    named = [c for c in out if c["same_name"]]
    best = max(named or out, key=lambda c: c["sources"], default=None)
    return {"variant": variant, "sent": q, "total": res["total"], "requests": res["requests"],
            "clusters": out, "chosen": best["viafID"] if best else None,
            "chosen_rule": "most sources among clusters whose heading contains every token of the person's name"
                           if named else "most sources among all personal clusters returned"}


def main():
    corpus = common.load_corpus()
    out = {"controls": controls()}
    print("controls", out["controls"], flush=True)
    if MODE == "works":
        out["books"] = {}
        for book in corpus["books"]:
            r = work_census(book)
            out["books"][book["id"]] = r
            print(book["id"], r["work_clusters"], r["census_size"],
                  [(k["viafID"], k["headings"][:1], k["expressions"]) for k in r["clusters_kept"]][:5], flush=True)
    else:
        out["persons"] = {}
        for p in corpus["authors"]:
            rows = [person_clusters(p["person"], v) for v in p["variants"]]
            out["persons"][p["id"]] = {"person": p["person"], "variants": rows,
                                       "one_id": len({r["chosen"] for r in rows}) == 1}
            print(p["id"], p["person"], [(r["variant"], r["chosen"], r["total"]) for r in rows], flush=True)
    out["requests"] = common.summarise()
    out["failures"] = common.failures()
    common.save_json(common.RESULTS / ("a6_viaf.json" if MODE == "works" else "a7_viaf.json"), out)


if __name__ == "__main__":
    main()
