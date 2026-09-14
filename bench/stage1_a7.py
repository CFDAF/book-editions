"""A7: do authorities group an author's variant forms?

    python stage1_a7.py sbn   SBN name authority (OPAC core=autori), then records by that authority
    python stage1_a7.py ol    Open Library: openlibrary.resolve_author_keys, plus the raw author search
    python stage1_a7.py wd    Wikidata: wbsearchentities per variant, first item that is a human (P31=Q5)

VIAF personal clusters: stage1_viaf.py persons.

SBN controls: a bogus free-text value and a bogus authority id must return 0;
a free-text term the OPAC drops (non-Latin script, see probe_nonlatin_any.json)
shows up as a total equal to the bare core total.
"""

import json
import sys

import common

PART = sys.argv[1]
net = common.setup(f"stage-1/a7-{PART}", log_name=f"a7_{PART}",
                   user_agent=common.UA_CONTACT if PART == "wd" else None)
from lookup import opac, openlibrary  # noqa: E402
from lookup.matching import normalize  # noqa: E402

NOMI = "item:5032:Nomi::@frase@"
SURNAMES = {"P01": "Bateson", "P02": "Murakami", "P03": "Dostoevskij", "P04": "Ferrante", "P05": "Attali",
            "P06": "Eco", "P07": "Eshun", "P08": "Han", "P09": "Garcia Marquez"}


def person_tokens(person):
    return normalize(person)


# ---------------------------------------------------------------- SBN -----

def autori(text, page=1):
    return opac._post({"core": "autori", opac.ANY: text, "page": str(page)})


def sbn_variant(person, variant):
    first = autori(variant)
    total = first.get("total") or 0
    rows = list(first.get("results") or [])
    for p in range(2, min((total + 19) // 20, 3) + 1):
        rows += autori(variant, p).get("results") or []
    out = []
    names = [t for t in (person_tokens(person), normalize(variant)) if t]
    for r in rows:
        heading = ((r.get("title") or {}).get("text") or "").strip()
        h = normalize(heading)
        m = opac.BID.match(str(r.get("id") or ""))
        out.append({"id": m.group(1) if m else r.get("id"), "heading": heading,
                    "kind": (r.get("infos") or [None])[0],
                    "exact_name": any(t == h for t in names),
                    "same_name": any(t <= h for t in names)})
    persons = [r for r in out if r["kind"] == "Persona"]
    exact = [r for r in out if r["exact_name"]]
    subset = [r for r in out if r["same_name"]]
    if exact:
        chosen, rule = exact[0], "heading tokens equal the name's"
    elif subset:
        chosen, rule = subset[0], "heading tokens contain the name's"
    elif len(persons) == 1 and total < 1000:
        chosen, rule = persons[0], "sole Persona result (heading in another transliteration)"
    else:
        chosen, rule = None, "no match"
    res = {"variant": variant, "total": total, "returned": len(out), "authorities": out[:30],
           "chosen": chosen["id"] if chosen else None, "chosen_heading": chosen["heading"] if chosen else None,
           "chosen_rule": rule}
    if chosen:
        d = opac._post({"core": "sbn", NOMI: chosen["id"], "page": "1"})
        res["records_by_authority"] = d.get("total")
    surname = max(person_tokens(person), key=len)
    res["namesakes"] = [r["heading"] for r in out if surname in normalize(r["heading"]) and not r["same_name"]][:10]
    return res


def run_sbn(corpus):
    controls = {
        "bare_autori_total": opac._post({"core": "autori", "page": "1"}).get("total"),
        "bogus_text_total": autori("zzqxqv").get("total"),
        "bogus_authority_records": opac._post({"core": "sbn", NOMI: "ZZQX999999", "page": "1"}).get("total"),
    }
    print("controls", controls, flush=True)
    persons = {}
    for p in corpus["authors"]:
        rows = []
        for v in p["variants"]:
            try:
                r = sbn_variant(p["person"], v)
                r["text_dropped"] = r["total"] == controls["bare_autori_total"]
            except net.SourceError as exc:
                r = {"variant": v, "failed": str(exc)[:200], "chosen": None}
            rows.append(r)
        surname = SURNAMES[p["id"]]
        probe = autori(surname)
        probe_rows = [((r.get("title") or {}).get("text") or "").strip() for r in probe.get("results") or []]
        latin = [r["chosen"] for r in rows if normalize(r["variant"])]
        persons[p["id"]] = {"person": p["person"], "variants": rows,
                            "one_id": len({r["chosen"] for r in rows}) == 1 and rows[0]["chosen"] is not None,
                            "one_id_latin_forms": len(set(latin)) == 1 and latin[0] is not None,
                            "surname_probe": {"text": surname, "total": probe.get("total"),
                                              "first_page_persons": [h for h, r in zip(probe_rows, probe.get("results") or [])
                                                                     if (r.get("infos") or [None])[0] == "Persona"]}}
        print(p["id"], [(r["variant"], r.get("total"), r["chosen"], r.get("chosen_heading"), r.get("records_by_authority")) for r in rows], flush=True)
    return {"controls": controls, "persons": persons}


# ------------------------------------------------------- Open Library -----

def run_ol(corpus):
    persons = {}
    for p in corpus["authors"]:
        rows = []
        for v in p["variants"]:
            try:
                keys = openlibrary.resolve_author_keys(v)
                raw = net.cached_get_json(f"{openlibrary.BASE}/search/authors.json", {"q": v})
                docs = [{"key": d.get("key"), "name": d.get("name"), "work_count": d.get("work_count"),
                         "birth_date": d.get("birth_date"), "alternate_names": (d.get("alternate_names") or [])[:5]}
                        for d in (raw.get("docs") or [])[:10]]
                rows.append({"variant": v, "resolve_author_keys": keys, "num_found": raw.get("numFound"),
                             "top_docs": docs})
            except net.SourceError as exc:
                rows.append({"variant": v, "failed": str(exc)[:200], "resolve_author_keys": []})
        sets = [frozenset(r["resolve_author_keys"]) for r in rows]
        persons[p["id"]] = {"person": p["person"], "variants": rows,
                            "same_key_set": len(set(sets)) == 1 and bool(sets[0]),
                            "shared_keys": sorted(frozenset.intersection(*sets)) if sets else []}
        print(p["id"], [(r["variant"], r["resolve_author_keys"]) for r in rows], flush=True)
    return {"persons": persons}


# ----------------------------------------------------------- Wikidata -----

WD = "https://www.wikidata.org/w/api.php"


def script_langs(text):
    langs = ["en", "it"]
    if any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text):
        langs += ["ja", "zh"]
    if any("가" <= ch <= "힯" for ch in text):
        langs += ["ko"]
    if any("Ѐ" <= ch <= "ӿ" for ch in text):
        langs += ["ru"]
    if any(ch in "ïëéè" for ch in text):
        langs += ["fr"]
    return langs


def run_wd(corpus):
    persons = {}
    for p in corpus["authors"]:
        rows = []
        for v in p["variants"]:
            cands = []
            try:
                for lang in script_langs(v):
                    d = net.cached_get_json(WD, {"action": "wbsearchentities", "search": v, "language": lang,
                                                 "uselang": "en", "type": "item", "limit": 10, "format": "json"})
                    for s in d.get("search") or []:
                        if s["id"] not in [c["id"] for c in cands]:
                            cands.append({"id": s["id"], "label": s.get("label"), "description": s.get("description"),
                                          "via": lang})
                ids = [c["id"] for c in cands][:40]
                ents = net.cached_get_json(WD, {"action": "wbgetentities", "ids": "|".join(ids), "props": "claims",
                                                "format": "json"}).get("entities", {}) if ids else {}
                for c in cands:
                    claims = (ents.get(c["id"]) or {}).get("claims") or {}
                    c["human"] = any(((x.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id") == "Q5"
                                     for x in claims.get("P31", []))
                humans = [c for c in cands if c["human"]]
                rows.append({"variant": v, "candidates": cands[:12], "chosen": humans[0]["id"] if humans else None,
                             "humans": [(c["id"], c["label"], c["description"]) for c in humans][:8]})
            except net.SourceError as exc:
                rows.append({"variant": v, "failed": str(exc)[:200], "chosen": None})
        persons[p["id"]] = {"person": p["person"], "variants": rows,
                            "one_id": len({r["chosen"] for r in rows}) == 1 and rows[0]["chosen"] is not None}
        print(p["id"], [(r["variant"], r["chosen"]) for r in rows], flush=True)
    return {"persons": persons}


if __name__ == "__main__":
    corpus = common.load_corpus()
    out = {"sbn": run_sbn, "ol": run_ol, "wd": run_wd}[PART](corpus)
    out["requests"] = common.summarise()
    out["failures"] = common.failures()
    common.save_json(common.RESULTS / f"a7_{PART}.json", out)
    print(json.dumps(out["requests"]))
