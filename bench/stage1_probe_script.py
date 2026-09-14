"""Control: does the OPAC ignore a non-Latin free-text term (ANY)?

Compares ANY+AUTHOR with AUTHOR alone, and with a bogus Latin ANY value.
If ANY+AUTHOR equals AUTHOR alone, the term was silently dropped.
"""
import json
import common
net = common.setup("stage-1/probe-script", log_name="probe_script")
from lookup import opac  # noqa: E402

def total(body):
    return opac._post({"core": "sbn", "page": "1", **body}).get("total")

cases = [("Доктор Живаго", "Pasternak"), ("Ὀδύσσεια", "Homer"), ("بين القصرين", "Naguib Mahfouz"),
         ("活着", "Yu Hua"), ("Преступление и наказание", "Fëdor Dostoevskij"), ("海辺のカフカ", "Murakami Haruki"),
         ("Umibe no Kafuka", "Murakami Haruki")]
out = []
for title, author in cases:
    row = {"title": title, "author": author,
           "any_plus_author": total({opac.ANY: title, opac.AUTHOR: author}),
           "author_alone": total({opac.AUTHOR: author}),
           "bogus_any_plus_author": total({opac.ANY: "zzqxqv", opac.AUTHOR: author}),
           "any_alone": total({opac.ANY: title})}
    row["any_ignored"] = row["any_plus_author"] == row["author_alone"]
    out.append(row)
    print(json.dumps(row, ensure_ascii=False))
common.save_json(common.RESULTS / "probe_nonlatin_any.json", {"cases": out, "requests": common.summarise()})
