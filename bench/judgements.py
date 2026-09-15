"""Hand judgements shared by the analysis scripts: which identity is the right one.

They were made by hand from the ground truth and the labels each source
returned (the evidence is in the Stage 1 result files named beside them), and
are kept in one place so every PASS/FAIL can be traced to them.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lookup.matching import core_title, title_similarity  # noqa: E402

# --- Stage 1 --------------------------------------------------------
# Wikidata items whose label/description was read (a1_wd.json, gt_wikipedia.py).
RIGHT_QID = {
    "E01": "Q178869", "E02": "Q1970551", "E03": "Q7047658", "E04": "Q579744", "E09": "Q172850",
    "E12": "Q330979", "E16": "Q206870", "N01": "Q917055", "N02": "Q25338", "N03": "Q836036",
    "N04": "Q165318", "N05": "Q183883", "N06": "Q208460", "N07": "Q1032190", "N08": "Q22263533",
    "N09": "Q1427187", "N10": "Q163297", "N11": "Q595140", "N12": "Q36097", "N13": "Q138528911",
    "N14": "Q826428", "N15": "Q219437", "N16": "Q151919", "N17": "Q3149381", "N18": "Q25519071",
    "N19": "Q115818209", "N20": "Q31067292", "N21": "Q5219975", "N22": "Q15991228", "N23": "Q35160",
}
# SBN uniform titles that denote the book (a1_sbn.json facet values). Sets where
# SBN splits one work across several uniform titles.
RIGHT_W = {
    "E01": {"cien anos de soledad"}, "E02": {"steps to an ecology of mind"},
    "E03": {"bruits : essai sur l'economie politique de la musique"}, "E04": {"umibe no kafuka"},
    "E05": {"invention of news"}, "E06": {"more brilliant than the sun"}, "E07": {"liquid modernity."},
    "E08": {"communication: the social matrix of psychiatry."}, "E09": {"nome della rosa"},
    "E12": {"uber den begriff der geschichte"}, "E16": {"doktor zivago"},
    "N01": {"nesnesitelna lehkost byti"}, "N02": {"petit prince"}, "N03": {"se questo e un uomo"},
    "N04": {"prestuplenie i nakazanie"}, "N05": {"catcher in the rye"}, "N06": {"nineteen eighty-four"},
    "N07": {"se una notte d'inverno un viaggiatore"}, "N08": {"amica geniale : infanzia, adolescenza"},
    "N09": {"formaggio e i vermi"}, "N10": {"etranger."}, "N11": {"disparition."}, "N12": {"prozess"},
    "N13": {"mudigkeitsgesellschaft"}, "N14": {"ensaio sobre a cegueira"}, "N15": {"2666."},
    "N16": {"huozhe"}, "N17": {"bain el-qasrain.", "bayn al-qasrayn"},
    "N18": {"capitalist realism : is there no alternative?"}, "N19": {"tomorrow, and tomorrow, and tomorrow"},
    "N20": {"metaphors we live by."}, "N21": {"veinte poemas de amor y una cancion desesperada."},
    "N22": {"capital au xxie siecle", "capital au 21. siecle", "capitale nel xxi secolo"},
    "N23": {"odyssea"}, "N24": {"tutto per una casa"},
}
# Open Library main work records (a1_ol.json docs: title, author, edition count).
RIGHT_OL = {
    "E01": "/works/OL274505W", "E02": "/works/OL486424W", "E03": "/works/OL685250W",
    "E04": "/works/OL2625431W", "E05": "/works/OL19983430W", "E06": "/works/OL2693265W",
    "E07": "/works/OL527224W", "E08": "/works/OL12269244W", "E09": "/works/OL8996439W",
    "E12": "/works/OL16171243W", "E14": "/works/OL23302246W", "E15": "/works/OL36428365W",
    "E16": "/works/OL258301W", "N01": "/works/OL8972751W", "N02": "/works/OL10263W",
    "N03": "/works/OL860066W", "N04": "/works/OL166894W", "N05": "/works/OL3335245W",
    "N06": "/works/OL1168083W", "N07": "/works/OL15321W", "N08": "/works/OL16520879W",
    "N09": "/works/OL14872792W", "N10": "/works/OL1230613W", "N11": "/works/OL1715351W",
    "N12": "/works/OL498463W", "N13": "/works/OL17795654W", "N14": "/works/OL27420W",
    "N15": "/works/OL712025W", "N17": "/works/OL1599742W", "N18": "/works/OL15683250W",
    "N19": "/works/OL26004554W", "N20": "/works/OL1952983W", "N21": "/works/OL979517W",
    "N22": "/works/OL16814568W",
}
# Records of the right work that the automatic title check cannot see as such:
# 'Huo zhe' (romanised, 5 editions) and 'Viver - To Live' (Portuguese, 1 edition), both by 余华.
SPLIT_OL = {("N16", "eng"), ("N16", "ita")}
# Not one book (generic titles) or insights only: excluded from pass/fail.
NOT_A_WORK = {"E10", "E11"}
INSIGHTS = {"N23"}


def sim(a, b):
    if not a or not b:
        return 0.0
    return max(title_similarity(a, b), title_similarity(core_title(a), core_title(b)))


def known_titles(book):
    gt = book["ground_truth"]
    forms = [re.sub(r"\s*\(.*\)\s*$", "", gt["original_title"]), book["original_title"]]
    forms += [book.get("original_title_romanised")]
    # corpus v2 moved script and Stage 1 titles aside; they are still forms of the book
    forms += [t for e in book["entries"] for t in (e["title"], e.get("script_title"), e.get("stage1_title"))]
    if book["id"] == "N12":
        forms += ["Der Prozess", "Der Proceß", "Der Prozeß"]
    return [f for f in forms if f]


# --- Stage 2 --------------------------------------------------------
# Records today's runs show outside the Stage 1 listing whose title the automatic
# check cannot tie to the book, judged by hand from the record and its OPAC or
# Open Library work (results/stage-2/losses.json).
# (book, BID or Open Library edition key) -> ("same work" | "wrong-work leak" | "other: <what>", why)
_LEAK_WD = "a different book, reached through the Wikidata item today's resolver picks (Stage 1 A1)"
STAGE2 = {
    # E01 Cien años de soledad
    ("E01", "BAS0261650"): ("same work", "French translation"),
    ("E01", "RMS2914158"): ("same work", "German translation"),
    **{("E01", b): ("wrong-work leak", "Crónica de una muerte anunciada, via Open Library sibling + Dewey")
       for b in ("PAL0262835", "PUV0939637", "RT10060267")},
    # E02 Steps to an Ecology of Mind
    ("E02", "UMC0068721"): ("wrong-work leak", "Una unidad sagrada = A Sacred Unity (1991), another Bateson book"),
    # E07 Liquid Modernity
    **{("E07", k): ("wrong-work leak", "Liquid Love; " + _LEAK_WD)
       for k in ("/books/OL29173102M", "/books/OL9514764M", "PBE0067063", "RMB0826924", "UBO2343318")},
    # E09 Il nome della rosa
    ("E09", "BVE0342887"): ("same work", "Spanish translation"),
    **{("E09", b): ("wrong-work leak", "Postille a Il nome della rosa (uniform title TSA1311710), a separate essay")
       for b in ("RMS2242621", "TO01850712", "IEI0375268", "RAV0128117", "TSA1571247")},
    # E10 Opere (not scored)
    **{("E10", k): ("wrong-work leak", "L'infinito; " + _LEAK_WD) for k in ("/books/OL44385826M", "/books/OL44516927M")},
    # E12 Tesi di filosofia della storia
    **{("E12", k): ("wrong-work leak", "Das Kunstwerk im Zeitalter…; " + _LEAK_WD)
       for k in ("/books/OL18710391M", "/books/OL19542562M", "/books/OL28166720M", "/books/OL29314126M",
                 "/books/OL32452904M", "/books/OL35089767M", "/books/OL38592174M", "/books/OL39942511M",
                 "/books/OL57454663M", "/books/OL9050187M", "/books/OL9050364M")},
    ("E12", "USM1885046"): ("same work", "vol. 19 of the collected works: Über den Begriff der Geschichte"),
    **{("E12", b): ("wrong-work leak", "Das Kunstwerk… / L'opera d'arte nell'epoca…; " + _LEAK_WD)
       for b in (
                "BCT0021417", "CAG1632134", "CFI0957814", "LI30012079", "LIA0166984", "LO11417606",
                "MIL0833216", "MOD0185060", "MOD1475341", "MOD1698002", "PAV0158932", "PCM0029925",
                "PCM0043101", "PMI0025422", "RAV0015909", "REA0021500", "RLZ0072788", "RLZ0190587",
                "RLZ0317747", "RMS1059054", "SBT0017338", "TO00426940", "TO01079088", "TO01882342",
                "TSA1905003", "UBO3824371", "UBO3854289", "UBO4288365", "UFI0240157", "UFI0242807",
                "UFI0336346", "USM1879580", "UTO1412515", "VEA0134446", "VEA1102302", "VIA0189096")},
    # E13 Angelus Novus (the Italian anthology)
    ("E13", "USM1885046"): ("wrong-work leak", "Über den Begriff der Geschichte, not the anthology"),
    ("E13", "SBT0038915"): ("wrong-work leak", "Suhrkamp's German Angelus Novus, a different selection"),
    ("E13", "CAG0945416"): ("wrong-work leak", "Suhrkamp's German Angelus Novus, a different selection"),
    # E16 Doktor Živago
    **{("E16", b): ("same work", "French or German translation")
       for b in ("CAG0720181", "LO11361723", "MOD0088938", "PUV1047641", "URB0613059")},
    ("E16", "CAG1250642"): ("same work", "vol. 4 of the collected works: the novel"),
    ("E16", "UFI0053934"): ("other: volume with other works", "novel with short stories and prose fragments"),
    ("E16", "TO01701421"): ("other: volume with other works", "novel with poems, 798 p."),
    ("E16", "LIG0066492"): ("wrong-work leak", "booklet about David Lean's film"),
    # N01 Nesnesitelná lehkost bytí
    ("N01", "RMS3040437"): ("same work", "Chinese translation; filed under the French uniform title"),
    ("N01", "RMS3062870"): ("same work", "Polish translation"),
    ("N01", "VIA0648262"): ("same work", "French translation"),
    # N02 Le Petit Prince
    **{("N02", k): ("same work", "Spanish translation, a separate Open Library work")
       for k in ("/books/OL47116985M", "/books/OL47117347M", "/books/OL47117431M", "/books/OL47132194M",
                 "/books/OL47134272M", "/books/OL47134281M")},
    **{("N02", b): ("same work", "Spanish or German translation")
       for b in ("LO11338713", "MOD1630537", "MOD1719105", "PBE0094262", "RT10204232", "TO01774700",
                 "TSA0577142", "TSA0991064", "UBO2224119")},
    ("N02", "PCM0052370"): ("wrong-work leak", "adaptation 'basado en la obra original' (uniform title Le petit prince pour les enfants)"),
    ("N02", "RMB0802091"): ("wrong-work leak", "adaptation 'raccontati da Carlo Scataglini'"),
    ("N02", "RMB0664037"): ("same work", "bilingual English-Arabic edition"),
    # N03 Se questo è un uomo
    ("N03", "RAV2019702"): ("wrong-work leak", "Così fu Auschwitz, another Levi book, via Open Library sibling + Dewey"),
    ("N03", "RMS1560464"): ("other: volume with other works", "with La tregua"),
    ("N03", "RLZ0193682"): ("other: volume with other works", "with La tregua"),
    # N04 Crime and Punishment (no SBN listing)
    ("N04", "TO10025459"): ("other: volume with other works", "I capolavori: five novels"),
    ("N04", "SBL0486482"): ("other: volume with other works", "with Tre romanzi brevi"),
    ("N04", "PBE0152862"): ("same work", "vol. 1 of an edition"),
    ("N04", "UM10195574"): ("same work", "audiobook"),
    ("N04", "IEI0268252"): ("wrong-work leak", "Coles study notes"),
    ("N04", "NAP0825329"): ("wrong-work leak", "stage designs for a production"),
    ("N04", "NAP0825011"): ("wrong-work leak", "stage designs for a production"),
    # N05 The Catcher in the Rye
    ("N05", "PUV0185597"): ("wrong-work leak", "Monarch critical commentary"),
    # N06 Nineteen Eighty-Four
    ("N06", "IEI0103425"): ("same work", "vol. 9 of the complete works: the novel"),
    # N07 Se una notte d'inverno un viaggiatore (no Open Library listing)
    **{("N07", k): ("same work", "French or Spanish translation, a separate Open Library work")
       for k in ("/books/OL8833997M", "/books/OL8834545M", "/books/OL9141913M")},
    # N08 L'amica geniale
    ("N08", "RMS2820714"): ("wrong-work leak", "vol. 2 of the tetralogy, Storia del nuovo cognome"),
    ("N08", "TO02100493"): ("wrong-work leak", "graphic-novel adaptation 'dal romanzo di Elena Ferrante'"),
    ("N08", "/books/OL47307526M"): ("wrong-work leak", "graphic-novel adaptation"),
    ("N08", "/books/OL60860290M"): ("other: volume with other works", "the four volumes"),
    ("N08", "PAR1243186"): ("same work", "French translation"),
    # N11 La Disparition
    ("N11", "URB0080304"): ("same work", "Spanish translation, El secuestro"),
    # N12 Der Process
    **{("N12", b): ("same work", "French, Spanish or Czech translation")
       for b in ("BRI0481917", "BVE0332462", "BVE0519531", "NAP0797913", "PAR0956691", "PBE0020302",
                 "PUV0628548", "PUV1132161", "RMS1265761", "TO01968006", "UBO2938809", "UFI0266143",
                 "URB0360930", "USM1697592")},
    ("N12", "LO10322503"): ("wrong-work leak", "Gide and Barrault's stage adaptation"),
    ("N12", "UBO2178919"): ("wrong-work leak", "Pinter's screenplay 'adapted from the novel'"),
    ("N12", "RAV0212860"): ("other: excerpt", "the parable Before the Law only"),
    ("N12", "LUA0513781"): ("same work", "Demetra edition, tr. Danila Moro (OPAC detail)"),
    # N14 Ensaio sobre a cegueira
    ("N14", "RL10092000"): ("wrong-work leak", "Veltroni's Buonvino e il caso del bambino scomparso, via an ISBN match"),
    ("N14", "TSA1247357"): ("wrong-work leak", "Ensayo sobre la lucidez (Seeing), another Saramago book"),
    ("N14", "UBO2409402"): ("wrong-work leak", "Ensaio sobre a lucidez (Seeing), another Saramago book"),
    ("N14", "UMC0093110"): ("same work", "Spanish translation"),
    ("N14", "TO01751676"): ("same work", "Spanish translation; its uniform title 'Ensaio sobre Cegueira.' is not W "
                                         "'ensaio sobre a cegueira' (the full-title score ignores 'a')"),
    # N17 بين القصرين
    ("N17", "CAG2101847"): ("same work", "German translation"),
    ("N17", "MOD0207547"): ("same work", "French translation; filed under a third transliteration, Bayan al-Qasrayn"),
    # N19 Tomorrow, and Tomorrow, and Tomorrow
    ("N19", "BCT0074386"): ("same work", "French translation"),
    # N20 Metaphors We Live By
    **{("N20", k): ("wrong-work leak", "Where Mathematics Comes From; " + _LEAK_WD)
       for k in ("/books/OL26474752M", "/books/OL7593603M", "/books/OL7593604M", "RAV1324368", "UBO1593933")},
    # N21 Veinte poemas de amor y una canción desesperada
    **{("N21", k): ("same work", "French translation")
       for k in ("/books/OL25267820M", "/books/OL8839092M", "LO11653987", "RMS2781496")},
    **{("N21", b): ("other: volume with other works", "with Cien sonetos de amor")
       for b in ("TSA0457099", "UBO1521418", "UBO3449380")},
    ("N21", "RLZ0324513"): ("other: volume with other works", "with Crepuscolario"),
    # N22 Le Capital au XXIe siècle
    ("N22", "PAV3226418"): ("wrong-work leak", "La crisis del capital en el siglo 21 (uniform title Peut-on sauver l'Europe?)"),
}
