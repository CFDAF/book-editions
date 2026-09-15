"""A4: do (language, year, normalised publisher) collisions find the SBN-Open Library
duplicates that a shared ISBN proves? Offline, over stage3_fetch.py's records.

    python stage3_analyse.py

Universe: per book, every SBN row of the Stage 1 listing whose full record was
fetched, against every Open Library edition of the Stage 1 listing. Nothing
outside those listings is added (Stage 2's 334 unlinked SBN records and 98
duplicate-work Open Library editions stay out), so a duplicate whose SBN or
Open Library side sits outside the listing is invisible here.

Truth: an SBN-Open Library pair is a duplicate when they share a normalised
ISBN-13 (ISBN-10 converted). SBN ISBNs come from every `[ISBN]` entry of
`numeri` in the full record, plus a top-level `isbn` if present; Open Library's
from `isbn_10` and `isbn_13` in the listing.

Workaround: a pair is a candidate duplicate when it collides on language, year
and publisher (see `publisher_keys`). The primary rule is RULES["primary"];
the other two change one component each, to show what that component costs.
"""

import collections
import itertools
import json
import re
import statistics
import sys
import unicodedata

import common
import judgements
from stage3_runs import BOOKS

sys.path.insert(0, str(common.ROOT))
from lookup.sbn import parse_labelled  # noqa: E402

R1 = common.BENCH / "results" / "stage-1" / "listings"
R3 = common.BENCH / "results" / "stage-3"
RAW3 = common.BENCH / "raw" / "stage-3" / "full"
NO_LANGUAGE = {"und", "zxx", "mis"}

# --- ISBN -----------------------------------------------------------------
ISBN_RE = re.compile(r"(?<![0-9X])(97[89][0-9]{10}|[0-9]{9}[0-9X])(?![0-9X])")


def _valid(code: str) -> bool:
    if len(code) == 10:
        return sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(code)) % 11 == 0
    return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(code)) % 10 == 0


def _to13(code: str) -> str:
    if len(code) == 13:
        return code
    body = "978" + code[:9]
    return body + str((10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(body)) % 10) % 10)


def isbns_in(values) -> tuple:
    """(normalised ISBN-13s, values with a bad check digit) from raw strings.

    Hyphens and spaces between digits are dropped first ('978-88-502-6890-0').
    A bad check digit is reported but still normalised: both catalogues copy
    what is printed on the book, so an invalid ISBN can still join them.
    """
    out, invalid = set(), []
    for v in values or []:
        compact = re.sub(r"(?<=[0-9Xx])[\s\-‐–](?=[0-9Xx])", "", str(v)).upper()
        for m in ISBN_RE.finditer(compact):
            code = m.group(1)
            if not _valid(code):
                invalid.append(code)
            out.add(_to13(code))
    return out, invalid


def sbn_isbns(rec: dict) -> tuple:
    raw = [v for label, v in parse_labelled(rec.get("numeri")) if label.upper() == "ISBN"]
    if rec.get("isbn"):
        raw.append(rec["isbn"])
    return isbns_in(raw)


def sbn_annotated_isbns(rec: dict) -> dict:
    """ISBN-13 -> SBN's note beside it ('(errato)', 'ricavato dalla 2. ed.', 'rist. 1998')."""
    out = {}
    for label, v in parse_labelled(rec.get("numeri")):
        if label.upper() != "ISBN":
            continue
        codes, _ = isbns_in([v])
        note = re.sub(r"[0-9Xx][0-9Xx\s\-]{8,}[0-9Xx]", "", v).strip(" ,;")
        if note:
            out.update({c: note for c in codes})
    return out


# --- Publisher normalisation ---------------------------------------------
# Words that name the form of a company rather than the company. Removed, with
# every one-letter token (initials: 'A. Mondadori', 'A.A. Knopf', 's.p.a.').
GENERIC = {
    # Italian
    "editore", "editori", "editrice", "edizioni", "edizione", "ed", "edit", "casa", "editoriale", "gruppo",
    "spa", "srl", "sas",
    # English
    "press", "publishing", "publishers", "publisher", "publications", "publication", "pubns", "pub", "publ",
    "books", "book", "inc", "incorporated", "ltd", "limited", "co", "company", "corp", "corporation",
    "group", "llc", "plc",
    # French, Spanish, Portuguese
    "editions", "edition", "editeur", "editeurs", "sarl", "editorial", "ediciones", "editora", "editores",
    "grupo", "lda", "ltda",
    # German
    "verlag", "gmbh", "kg", "ag",
    # connectors and the article that fronts English company names
    "and", "et", "und", "the",
}
# SBN imprint noise that parse_publication leaves in the publisher ('Gallimard, dep. leg.').
NOISE = {"dep", "leg", "stampa", "impr"}


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _plain(text: str) -> str:
    return " ".join(re.findall(r"\w+", fold(text)))


def key_of(name: str) -> frozenset:
    s = fold(name).replace("&", " and ")
    s = re.sub(r"\b(\w)\s*/\s*(\w)\b", r"\1\2", s)  # 'E/O' -> 'eo', not two initials
    return frozenset(t for t in re.findall(r"\w+", s)
                     if len(t) > 1 and not t.isdigit() and t not in GENERIC and t not in NOISE)


def strip_places(name: str, places: set) -> str:
    """'Milano, Mondadori' / 'London : Penguin' / 'Rowohlt, Reinbek' -> the publisher.

    Only a place set off by a comma or colon is removed, so 'Cambridge
    University Press' keeps 'Cambridge'. `places` holds every place the eight
    books' own records name (SBN imprint place, Open Library publish_places).
    """
    parts = [p.strip() for p in re.split(r"\s*[,:]\s+", name) if p.strip()]
    kept = [p for p in parts if _plain(p) not in places]
    return ", ".join(kept) if kept else ""


def sbn_names(publisher: str) -> list:
    """SBN imprint publisher statement -> publisher names.

    ISBD writes 'Place : Publisher ; Place : Publisher'. parse_publication has
    already cut the first place, so the first piece is a publisher (a ' : '
    inside it separates a co-publisher); in later pieces the part before ' : '
    is a place, and a piece without ' : ' is a place alone.
    """
    names = []
    for i, piece in enumerate(publisher.split(";")):
        if i and re.match(r"\s*in association with\b", piece, flags=re.I):
            names.append(piece)
            continue
        parts = re.split(r"\s+:\s+", piece)
        names += parts if i == 0 else parts[1:]
    return [n for name in names for n in re.split(r"\bin association with\b", name, flags=re.I)]


def ol_names(publishers: list) -> list:
    return [n for p in publishers for piece in p.split(";") for part in re.split(r"\s+:\s+", piece)
            for n in re.split(r"\bin association with\b", part, flags=re.I)]


def publisher_keys(names: list, places: set) -> set:
    return {k for k in (key_of(strip_places(n, places)) for n in names) if k}


# --- Collision rules -------------------------------------------------------
def pub_exact(a: set, b: set) -> bool:
    return bool(a & b)


def pub_contained(a: set, b: set) -> bool:
    """One name's words are all in the other's: 'mondadori' ~ 'oscar mondadori'."""
    return any(x <= y or y <= x for x in a for y in b)


RULES = {
    "primary": {"publisher": pub_contained, "ol_language_missing_matches": False,
                "what": "language shared, year equal, one publisher key contained in the other"},
    "exact publisher": {"publisher": pub_exact, "ol_language_missing_matches": False,
                        "what": "as primary, but publisher keys must be equal (SBN's split values stay apart)"},
    "OL language missing matches": {"publisher": pub_contained, "ol_language_missing_matches": True,
                                    "what": "as primary, but an Open Library edition with no language matches any"},
}


def collide(s: dict, o: dict, rule: dict) -> bool:
    if not (s["year"] and s["year"] == o["year"]):
        return False
    if not (s["langs"] & o["langs"] or (rule["ol_language_missing_matches"] and not o["langs"] and s["langs"])):
        return False
    return rule["publisher"](s["pubkeys"], o["pubkeys"])


def miss_causes(s: dict, o: dict, rule: dict) -> tuple:
    causes = []
    if not s["langs"] or not o["langs"]:
        causes.append("language missing")
    elif not s["langs"] & o["langs"]:
        causes.append("language differs")
    if not s["year"] or not o["year"]:
        causes.append("year missing")
    elif s["year"] != o["year"]:
        causes.append("year differs")
    if not s["pubkeys"] or not o["pubkeys"]:
        causes.append("publisher missing")
    elif not rule["publisher"](s["pubkeys"], o["pubkeys"]):
        causes.append("publisher differs")
    return tuple(causes)


# --- Load -------------------------------------------------------------------
def load_book(book: str) -> dict:
    listing = json.loads((R1 / f"{book}.json").read_text())
    fetched = json.loads((RAW3 / f"{book}.json").read_text())["records"]
    meta = json.loads((R3 / "fetch" / f"{book}.json").read_text())
    sbn, seen = [], set()
    for s in listing["sbn"] or []:
        for r in s.get("items") or []:
            if r["bid"] in seen:
                continue
            seen.add(r["bid"])
            rec = fetched.get(r["bid"])
            isbns, invalid = sbn_isbns(rec) if rec else (set(), [])
            sbn.append({"id": r["bid"], "title": r["title"], "imprint": r["imprint"], "year": r["year"],
                        "publisher": r["publisher"], "place": r["place"], "fetched": rec is not None,
                        "langs": {c for c in r["langs"] if c not in NO_LANGUAGE},
                        "isbns": isbns, "invalid": invalid,
                        "annotated": sbn_annotated_isbns(rec) if rec else {},
                        "numeri_labels": [label for label, _ in parse_labelled((rec or {}).get("numeri"))],
                        "full_lang": (rec or {}).get("linguaPubblicazione")})
    ol = []
    for e in listing["ol"]["items"]:
        isbns, invalid = isbns_in((e["isbn_10"] or []) + (e["isbn_13"] or []))
        ol.append({"id": e["key"], "title": e["title"], "publish_date": e["publish_date"], "year": e["year"],
                   "publishers": e["publishers"], "publish_places": e["publish_places"],
                   "langs": {c for c in e["languages"] if c not in NO_LANGUAGE},
                   "isbns": isbns, "invalid": invalid})
    return {"id": book, "sbn": sbn, "ol": ol, "meta": meta}


def brief(r: dict) -> dict:
    out = {"id": r["id"], "title": (r["title"] or "")[:80], "year": r["year"], "langs": sorted(r["langs"]),
           "isbns": sorted(r["isbns"]), "pubkeys": sorted(" ".join(sorted(k)) for k in r["pubkeys"])}
    out["publisher"] = r["imprint"] if "imprint" in r else r["publishers"]
    return out


# --- Analyse ----------------------------------------------------------------
def analyse(book: dict, rule_name: str) -> dict:
    rule = RULES[rule_name]
    sbn = [s for s in book["sbn"] if s["fetched"]]
    ol = book["ol"]
    tp, fp, fn, unverifiable = [], [], [], collections.Counter()
    unverifiable_pairs = []
    colliding_sbn, colliding_sbn_ol_isbn = set(), set()
    for s, o in itertools.product(sbn, ol):
        hit = collide(s, o, rule)
        shared = s["isbns"] & o["isbns"]
        if hit:
            colliding_sbn.add(s["id"])
            if o["isbns"]:
                colliding_sbn_ol_isbn.add(s["id"])
        if s["isbns"] and o["isbns"]:
            if hit and shared:
                tp.append((s, o))
            elif hit:
                fp.append((s, o))
            elif shared:
                fn.append((s, o, miss_causes(s, o, rule)))
        elif hit:
            side = ("both lack" if not s["isbns"] and not o["isbns"]
                    else "SBN lacks" if not s["isbns"] else "Open Library lacks")
            unverifiable[side] += 1
            unverifiable_pairs.append((side, s, o))
    truth = len(tp) + len(fn)
    collisions = len(tp) + len(fp)
    same_year = [(s, o) for s, o in tp] + [(s, o) for s, o, _ in fn]
    same_year = {(s["id"], o["id"]) for s, o in same_year if s["year"] and s["year"] == o["year"]}
    ol_true = {o["id"] for s, o in tp} | {o["id"] for s, o, _ in fn}
    ol_found = {o["id"] for s, o in tp}
    ol_false_only = {o["id"] for s, o in fp} - ol_found
    return {
        "rule": rule_name,
        "verifiable_pairs": sum(1 for s in sbn if s["isbns"]) * sum(1 for o in ol if o["isbns"]),
        "truth_pairs": truth, "collisions_verifiable": collisions, "tp": len(tp), "fp": len(fp), "fn": len(fn),
        "precision": round(len(tp) / collisions, 3) if collisions else None,
        "recall": round(len(tp) / truth, 3) if truth else None,
        "truth_pairs_same_year": len(same_year),
        "tp_same_year": sum(1 for s, o in tp if (s["id"], o["id"]) in same_year),
        "ol_editions_with_true_duplicate": len(ol_true), "ol_editions_merged_with_a_true_duplicate": len(ol_found),
        "ol_editions_colliding_only_with_wrong_sbn": len(ol_false_only),
        "unverifiable": dict(unverifiable), "unverifiable_total": sum(unverifiable.values()),
        "fetches_needed": len(colliding_sbn), "fetches_needed_ol_has_isbn": len(colliding_sbn_ol_isbn),
        "fetches_all": len(sbn),
        # once a colliding row is fetched, its ISBNs can be compared with every edition, colliding or not
        "truth_pairs_reached_by_fetched_rows": sum(1 for s, o in tp if s["id"] in colliding_sbn)
        + sum(1 for s, o, _ in fn if s["id"] in colliding_sbn),
        "miss_causes": dict(collections.Counter(" + ".join(c) for *_, c in fn)),
        "_tp": [(brief(s), brief(o)) for s, o in tp],
        "_fp": [(brief(s), brief(o)) for s, o in fp],
        "_fn": [(brief(s), brief(o), list(c)) for s, o, c in fn],
        "_unverifiable": [(side, brief(s), brief(o)) for side, s, o in unverifiable_pairs],
    }


def sbn_sbn(book: dict) -> dict:
    rule = RULES["primary"]
    sbn = [s for s in book["sbn"] if s["fetched"]]
    pairs = []
    for a, b in itertools.combinations(sbn, 2):
        if (a["year"] and a["year"] == b["year"] and a["langs"] & b["langs"]
                and rule["publisher"](a["pubkeys"], b["pubkeys"])):
            pairs.append((a, b))
    return {"pairs": len(pairs), "sharing_an_isbn": sum(1 for a, b in pairs if a["isbns"] & b["isbns"]),
            "_pairs": [(brief(a), brief(b)) for a, b in pairs]}


def truth_structure(book: dict) -> dict:
    """How the ISBN truth itself is shaped: one-to-many joins and disagreements."""
    sbn = [s for s in book["sbn"] if s["fetched"]]
    pairs = [(s, o) for s, o in itertools.product(sbn, book["ol"]) if s["isbns"] & o["isbns"]]
    per_ol = collections.Counter(o["id"] for _, o in pairs)
    per_sbn = collections.Counter(s["id"] for s, _ in pairs)
    return {
        "ol_editions_with_several_sbn": sum(1 for n in per_ol.values() if n > 1),
        "sbn_records_with_several_ol": sum(1 for n in per_sbn.values() if n > 1),
        "language_differs": sum(1 for s, o in pairs if s["langs"] and o["langs"] and not s["langs"] & o["langs"]),
        "year_differs": sum(1 for s, o in pairs if s["year"] and o["year"] and s["year"] != o["year"]),
        "on_invalid_isbn": sum(1 for s, o in pairs
                               if (s["isbns"] & o["isbns"]) <= {_to13(c) for c in s["invalid"] + o["invalid"]}),
        "on_annotated_sbn_isbn_only": dict(collections.Counter(
            "; ".join(sorted({s["annotated"][c] for c in s["isbns"] & o["isbns"]}))
            for s, o in pairs if (s["isbns"] & o["isbns"]) <= set(s["annotated"]))),
    }


def md(head, rows):
    return "\n".join(["| " + " | ".join(map(str, head)) + " |", "|" + "---|" * len(head)]
                     + ["| " + " | ".join("—" if v is None else str(v) for v in r) + " |" for r in rows]) + "\n"


def tables(summary) -> str:
    pb, pooled = summary["per_book"], summary["pooled"]
    out = ["### Rules, pooled over the eight books\n",
           md(["rule", "collisions (both ISBN)", "TP", "FP", "precision", "truth pairs", "recall",
               "recall, same-year truth", "truth pairs reached once colliding rows are fetched", "OL editions with a true SBN duplicate · merged with one · only wrong",
               "unverifiable (SBN lacks · OL lacks · both)", "fetches needed (OL has ISBN) / all", "saving"],
              [[n, r["tp"] + r["fp"], r["tp"], r["fp"], r["precision"], r["tp"] + r["fn"], r["recall"],
                f"{r['tp_same_year']}/{r['truth_pairs_same_year']} = {r['recall_same_year']}",
                f"{r['truth_pairs_reached_by_fetched_rows']}/{r['tp'] + r['fn']}",
                f"{r['ol_editions_with_true_duplicate']} · {r['ol_editions_merged_with_a_true_duplicate']} · "
                f"{r['ol_editions_colliding_only_with_wrong_sbn']}",
                f"{r['unverifiable'].get('SBN lacks', 0)} · {r['unverifiable'].get('Open Library lacks', 0)} · "
                f"{r['unverifiable'].get('both lack', 0)}",
                f"{r['fetches_needed']} ({r['fetches_needed_ol_has_isbn']}) / {r['fetches_all']}", r["fetch_saving"]]
               for n, r in pooled.items()]),
           "\n### Per book, primary rule\n",
           md(["book", "SBN rows · with ISBN", "OL editions · with ISBN · with language", "truth pairs (same year)",
               "distinct shared ISBNs", "collisions (both ISBN)", "TP", "FP", "precision", "recall",
               "unverifiable", "fetches needed / all", "SBN–SBN collisions (sharing an ISBN)"],
              [[b, f"{r['sbn_fetched']} · {r['sbn_with_isbn']}",
                f"{r['ol_editions']} · {r['ol_with_isbn']} · {r['ol_with_language']}",
                f"{r['rules']['primary']['truth_pairs']} ({r['rules']['primary']['truth_pairs_same_year']})",
                r["distinct_shared_isbns"], r["rules"]["primary"]["collisions_verifiable"],
                r["rules"]["primary"]["tp"], r["rules"]["primary"]["fp"], r["rules"]["primary"]["precision"],
                r["rules"]["primary"]["recall"], r["rules"]["primary"]["unverifiable_total"],
                f"{r['rules']['primary']['fetches_needed']} / {r['rules']['primary']['fetches_all']}",
                f"{r['sbn_sbn']['pairs']} ({r['sbn_sbn']['sharing_an_isbn']})"] for b, r in pb.items()]),
           "\n### False positives involving a record that is not a plain edition (judgements.STAGE3)\n",
           md(["record", "false-positive pairs"], list(pooled["primary"]["fp_with_a_judged_record"].items())),
           "\n### Why true duplicates do not collide (primary rule, pairs)\n",
           md(["components that differ", "pairs"], list(pooled["primary"]["miss_causes"].items())),
           "\n### Shape of the ISBN truth\n",
           md(["book", "OL editions joined to several SBN records", "SBN records joined to several OL editions",
               "language differs", "year differs", "largest ISBN cluster (SBN × OL = pairs)",
               "resting only on an annotated SBN ISBN"],
              [[b, r["truth"]["ol_editions_with_several_sbn"], r["truth"]["sbn_records_with_several_ol"],
                r["truth"]["language_differs"], r["truth"]["year_differs"], r["largest_isbn_cluster"],
                "; ".join(f"{k} {v}" for k, v in r["truth"]["on_annotated_sbn_isbn_only"].items()) or "0"]
               for b, r in pb.items()]),
           "\n### Full-record fetches (mobile gateway, one at a time, cold)\n",
           md(["book", "rows", "fetched", "first-pass problems", "wall s", "requests", "failed", "retries (urllib3)",
               "bogus BID control"],
              [[b, r["fetch"]["rows"], r["fetch"]["fetched"], r["fetch"]["first_pass_problems"], r["fetch"]["wall_s"],
                sum(h["requests"] for h in r["fetch"]["requests"].values()),
                sum(h["failed"] for h in r["fetch"]["requests"].values()),
                "; ".join(f"{c}×{n}" for h in r["fetch"]["retries"].values() for c, n in h.items()) or "0",
                r["fetch"]["control"]["problem"]] for b, r in pb.items()]),
           "\n### Requests per host\n",
           md(["host", "requests", "failed", "total s", "median of per-book p50 s", "max s", "retries"],
              [[h, v["requests"], v["failed"], v["total_s"], v["median_of_book_p50_s"], v["max_s"],
                "; ".join(f"{k.split(' ', 1)[1]}×{n}" for k, n in summary["retries"].items() if k.startswith(h)) or "0"]
               for h, v in summary["hosts"].items()]),
           "\n### Same-work records outside the listings (Stage 2, found by today's routes)\n",
           md(["book · class", "distinct records"], list(summary["stage2_same_work_outside_listing"].items()))]
    return "\n".join(out)


def main():
    books = {b: load_book(b) for b in BOOKS}
    places = set()
    for bk in books.values():
        places |= {_plain(s["place"]) for s in bk["sbn"] if s["place"]}
        places |= {_plain(p) for o in bk["ol"] for p in o["publish_places"]}
    places.discard("")
    for bk in books.values():
        for s in bk["sbn"]:
            s["pubkeys"] = publisher_keys(sbn_names(s["publisher"]), places) if s["publisher"] else set()
        for o in bk["ol"]:
            o["pubkeys"] = publisher_keys(ol_names(o["publishers"]), places)

    per_book, pairs_out, records_out = {}, {}, {}
    for b, bk in books.items():
        sbn_f = [s for s in bk["sbn"] if s["fetched"]]
        rows = {
            "sbn_rows": len(bk["sbn"]), "sbn_fetched": len(sbn_f),
            "sbn_with_isbn": sum(1 for s in sbn_f if s["isbns"]),
            "sbn_invalid_isbn_values": sum(len(s["invalid"]) for s in sbn_f),
            "sbn_with_year": sum(1 for s in sbn_f if s["year"]),
            "sbn_with_publisher_key": sum(1 for s in sbn_f if s["pubkeys"]),
            "ol_editions": len(bk["ol"]), "ol_with_isbn": sum(1 for o in bk["ol"] if o["isbns"]),
            "ol_invalid_isbn_values": sum(len(o["invalid"]) for o in bk["ol"]),
            "ol_with_language": sum(1 for o in bk["ol"] if o["langs"]),
            "ol_with_year": sum(1 for o in bk["ol"] if o["year"]),
            "ol_with_publisher_key": sum(1 for o in bk["ol"] if o["pubkeys"]),
            "truth": truth_structure(bk),
            "rules": {}, "sbn_sbn": None,
            "fetch": {k: bk["meta"][k] for k in ("rows", "fetched", "first_pass_problems", "wall_s",
                                                  "requests", "retries", "failures", "control")},
        }
        pairs_out[b] = {}
        for name in RULES:
            res = analyse(bk, name)
            pairs_out[b][name] = {k[1:]: v for k, v in res.items() if k.startswith("_")}
            rows["rules"][name] = {k: v for k, v in res.items() if not k.startswith("_")}
        clusters = collections.defaultdict(lambda: (set(), set()))
        for s_, o_ in itertools.product(sbn_f, bk["ol"]):
            for code in s_["isbns"] & o_["isbns"]:
                clusters[code][0].add(s_["id"])
                clusters[code][1].add(o_["id"])
        rows["distinct_shared_isbns"] = len(clusters)
        big = max(clusters.items(), key=lambda kv: len(kv[1][0]) * len(kv[1][1]), default=None)
        rows["largest_isbn_cluster"] = (f"{big[0]}: {len(big[1][0])} × {len(big[1][1])} = "
                                        f"{len(big[1][0]) * len(big[1][1])}" if big else None)
        ss = sbn_sbn(bk)
        rows["sbn_sbn"] = {k: v for k, v in ss.items() if not k.startswith("_")}
        pairs_out[b]["sbn_sbn"] = ss["_pairs"]
        per_book[b] = rows
        records_out[b] = {s["id"]: {"fetched": s["fetched"], "isbns": sorted(s["isbns"]), "invalid": s["invalid"],
                                    "annotated": s["annotated"], "numeri_labels": s["numeri_labels"], "full_lang": s["full_lang"],
                                    "listing_langs": sorted(s["langs"])}
                          for s in bk["sbn"]}

    pooled = {}
    for name in RULES:
        rs = [per_book[b]["rules"][name] for b in BOOKS]
        tp, fp, fn = (sum(r[k] for r in rs) for k in ("tp", "fp", "fn"))
        unv = collections.Counter()
        causes = collections.Counter()
        for r in rs:
            unv.update(r["unverifiable"])
            causes.update(r["miss_causes"])
        need, need_isbn, total = (sum(r[k] for r in rs) for k in ("fetches_needed", "fetches_needed_ol_has_isbn", "fetches_all"))
        extra = {k: sum(r[k] for r in rs) for k in (
            "truth_pairs_same_year", "tp_same_year", "truth_pairs_reached_by_fetched_rows", "ol_editions_with_true_duplicate",
            "ol_editions_merged_with_a_true_duplicate", "ol_editions_colliding_only_with_wrong_sbn")}
        pooled[name] = {
            "what": RULES[name]["what"], "tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            **extra,
            "recall_same_year": round(extra["tp_same_year"] / extra["truth_pairs_same_year"], 3)
            if extra["truth_pairs_same_year"] else None,
            "unverifiable": dict(unv), "unverifiable_total": sum(unv.values()),
            "fetches_needed": need, "fetches_needed_ol_has_isbn": need_isbn, "fetches_all": total,
            "fetch_saving": round(1 - need / total, 3) if total else None,
            "miss_causes": dict(causes.most_common()),
            "per_book_precision": {b: per_book[b]["rules"][name]["precision"] for b in BOOKS},
        }
    judged = collections.Counter()
    for b in BOOKS:
        for s_, o_ in pairs_out[b]["primary"]["fp"]:
            for rid in (s_["id"], o_["id"]):
                if (b, rid) in judgements.STAGE3:
                    judged[f"{b} {rid}: {judgements.STAGE3[(b, rid)][0]}"] += 1
    pooled["primary"]["fp_with_a_judged_record"] = dict(judged)
    p = pooled["primary"]
    verdict = {
        "precision": p["precision"], "fetch_saving": p["fetch_saving"],
        "fails_precision": p["precision"] is None or p["precision"] < 0.95,
        "fails_saving": not p["fetch_saving"] or p["fetch_saving"] <= 0,
    }
    verdict["result"] = "FAIL" if verdict["fails_precision"] or verdict["fails_saving"] else "PASS"

    hosts, retries = {}, collections.Counter()
    for b in BOOKS:
        for h, v in per_book[b]["fetch"]["requests"].items():
            agg = hosts.setdefault(h, {"requests": 0, "failed": 0, "total_s": 0.0, "p50": [], "max_s": 0.0})
            agg["requests"] += v["requests"]
            agg["failed"] += v["failed"]
            agg["total_s"] = round(agg["total_s"] + v["total_s"], 2)
            agg["p50"].append(v["p50_s"])
            agg["max_s"] = max(agg["max_s"], v["max_s"])
        for h, causes in per_book[b]["fetch"]["retries"].items():
            for c, n in causes.items():
                retries[f"{h} {c}"] += n
    for agg in hosts.values():
        agg["median_of_book_p50_s"] = round(statistics.median(agg.pop("p50")), 3)

    losses = json.loads((common.BENCH / "results" / "stage-2" / "losses.json").read_text())
    outside = collections.Counter()
    seen = set()
    for l in losses:
        b = l["run"].split("__")[0]
        k = (b, l["source"], l["id"])
        if b in BOOKS and k not in seen and l["class"] in ("not linked to W", "separate OL work record"):
            seen.add(k)
            outside[(b, l["class"])] += 1

    summary = {
        "books": BOOKS, "verdict": verdict, "pooled": pooled, "per_book": per_book,
        "hosts": hosts, "retries": dict(retries),
        "normalisation": {
            "folding": "Unicode NFKD, combining marks dropped, casefold; '&' -> 'and'; 'x/y' of single letters joined",
            "tokens_removed": sorted(GENERIC), "noise_removed": sorted(NOISE),
            "one_letter_tokens": "removed (initials: 'A. Mondadori' -> mondadori, 'V. Bompiani e C.' -> bompiani)",
            "digit_only_tokens": "removed",
            "sbn_statement": "split on ';'; first piece is a publisher (a ' : ' in it separates a co-publisher); "
                             "later pieces keep only what follows ' : '; 'in association with' splits",
            "ol_statement": "each publishers[] value split on ';', ' : ' and 'in association with'",
            "places": f"a part set off by ',' or ':' is dropped when it equals one of {len(places)} places the "
                      "eight books' records name (SBN imprint place, Open Library publish_places)",
            "split_values": "primary: a key contained in the other matches ('mondadori' ~ 'oscar mondadori'); "
                            "'exact publisher' rule keeps them apart",
            "language": "shared listing code (SBN language page, Open Library languages); und/zxx/mis count as missing",
            "year": "SBN parse_publication year; Open Library first 4-digit year in publish_date; equal",
        },
        "stage2_same_work_outside_listing": {f"{b} · {c}": n for (b, c), n in sorted(outside.items())},
    }
    common.save_json(R3 / "summary.json", summary)
    (R3 / "tables.md").write_text(tables(summary), encoding="utf-8")
    common.save_json(common.BENCH / "raw" / "stage-3" / "pairs.json", pairs_out)
    compact = {b: {"primary": {k: rs["primary"][k] for k in ("fp", "tp", "fn")},
                   **{n: {"fp": [[s_["id"], o_["id"]] for s_, o_ in v["fp"]]} for n, v in rs.items()
                      if n not in ("primary", "sbn_sbn")},
                   "unverifiable": [[side, s_["id"], o_["id"]] for side, s_, o_ in rs["primary"]["unverifiable"]],
                   "sbn_sbn": [[a["id"], b_["id"]] for a, b_ in rs["sbn_sbn"]]}
               for b, rs in pairs_out.items()}
    (R3 / "pairs.json").write_text(json.dumps(compact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    common.save_json(R3 / "records.json", records_out)
    print(json.dumps({"verdict": verdict, "pooled": {k: {x: v[x] for x in ("tp", "fp", "fn", "precision", "recall",
                                                                             "unverifiable_total", "fetches_needed",
                                                                             "fetches_all", "fetch_saving")}
                                                      for k, v in pooled.items()}}, indent=1))


if __name__ == "__main__":
    main()
