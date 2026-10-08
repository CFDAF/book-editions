"""One language vocabulary for four sources that each use a different one.

Canonical form is ISO 639-2/B ('ita', 'eng', 'fre'), because that is what Open
Library uses and it is the least lossy of the four.

The important rule this module exists to enforce: an *unknown* language stays
unknown. The original script folded blank languages into English
(``if "eng" in langs or not langs``), which quietly inflated the English list
with records whose language was simply not recorded.
"""

UNKNOWN = "unknown"

# SBN linguaPubblicazione labels -> ISO 639-2/B.
#
# **Every row below was read off SBN, not guessed.** The OPAC's `lingua[]`
# facet answers with the ISO code *and* the label SBN prints for it, and Stage 3
# recorded both for 778 full records, so the map is the catalogue's own
# (F7: 740 of 740 agree, and the 21 labels this table had no code for in Step 6
# all resolved from the same evidence). Adding a row by guessing the code from
# the Italian name is how `SLOVACCO` would become `slk` where SBN says `slo`.
_SBN = {
    "ITALIANO": "ita", "INGLESE": "eng", "FRANCESE": "fre", "TEDESCO": "ger",
    "SPAGNOLO": "spa", "PORTOGHESE": "por", "RUSSO": "rus", "LATINO": "lat",
    "OLANDESE": "dut", "GRECO ANTICO": "grc", "GRECO MODERNO": "gre",
    "CATALANO": "cat", "POLACCO": "pol", "CECO": "cze", "SVEDESE": "swe",
    "DANESE": "dan", "NORVEGESE": "nor", "FINLANDESE": "fin", "UNGHERESE": "hun",
    "GIAPPONESE": "jpn", "CINESE": "chi", "ARABO": "ara", "EBRAICO": "heb",
    "TURCO": "tur", "ROMENO": "rum", "CROATO": "hrv", "SERBO": "srp",
    "SLOVENO": "slv", "MULTILINGUE": "mul",
    # Step 7. The 17 single-language labels of the Stage 3 gap, each with the
    # code SBN's own listing files those records under.
    "ALBANESE": "alb", "COREANO": "kor", "ESPERANTO": "epo", "ESTONE": "est",
    "GRECO MODERNO (DAL 1453)": "gre", "INDONESIANO": "ind", "ISLANDESE": "ice",
    "LETTONE": "lav", "LITUANO": "lit", "OLANDESE, FIAMMINGO": "dut",
    "PERSIANO MODERNO": "per", "RUMENO, MOLDAVO": "rum", "SARDO": "srd",
    "SERBO-CROATO": "hbs", "SLOVACCO": "slo",
    "TURCO MODERNO (DAL 1928)": "tur", "UCRAINO": "ukr",
}

# A label naming two languages, e.g. 'ITALIANO - INGLESE' or 'CECO - ITALIANO'
# — a parallel-text edition. SBN's listing files such a record under **both**
# codes (verified on all four in the Stage 3 gap), so no single code is the
# whole truth and `mul` would lose which two. `from_sbn` answers with the first
# language named, which is always one of the two the listing uses; the listing
# path never needs this, because the facet gives the codes directly.
_PAIR = " - "

# ISO 639-1 (Wikipedia) -> ISO 639-2/B
_TWO = {
    "it": "ita", "en": "eng", "fr": "fre", "de": "ger", "es": "spa",
    "pt": "por", "ru": "rus", "la": "lat", "nl": "dut", "el": "gre",
    "ca": "cat", "pl": "pol", "cs": "cze", "sv": "swe", "da": "dan",
    "no": "nor", "fi": "fin", "hu": "hun", "ja": "jpn", "zh": "chi",
    "ar": "ara", "he": "heb", "tr": "tur", "ro": "rum", "hr": "hrv",
    "sr": "srp", "sl": "slv",
}

# Wikidata language items -> ISO 639-2/B
_WIKIDATA = {
    "Q652": "ita", "Q1860": "eng", "Q150": "fre", "Q188": "ger",
    "Q1321": "spa", "Q5146": "por", "Q7737": "rus", "Q397": "lat",
    "Q7411": "dut", "Q9129": "gre", "Q35497": "grc", "Q7026": "cat",
    "Q809": "pol", "Q9056": "cze", "Q9027": "swe", "Q9035": "dan",
    "Q9043": "nor", "Q1412": "fin", "Q9067": "hun", "Q5287": "jpn",
    "Q7850": "chi", "Q13955": "ara", "Q9288": "heb", "Q256": "tur",
    "Q7913": "rum", "Q6654": "hrv", "Q9299": "srp", "Q9063": "slv",
}

# Italian display names, matching SBN's own facet vocabulary so the UI reads
# consistently with the facet counts it shows alongside.
#
# The second block is every other code the corpus's own listings returned — 83
# distinct codes over 32 works, of which 54 had no name and reached the reader
# as `guj` and `kor` beside *giapponese* (`docs/limits.md`, a limit this closes).
# A code with no row here still falls through to itself rather than to a guess.
_DISPLAY = {
    "ita": "italiano", "eng": "inglese", "fre": "francese", "ger": "tedesco",
    "spa": "spagnolo", "por": "portoghese", "rus": "russo", "lat": "latino",
    "dut": "olandese", "gre": "greco", "grc": "greco antico", "cat": "catalano",
    "pol": "polacco", "cze": "ceco", "swe": "svedese", "dan": "danese",
    "nor": "norvegese", "fin": "finlandese", "hun": "ungherese",
    "jpn": "giapponese", "chi": "cinese", "ara": "arabo", "heb": "ebraico",
    "tur": "turco", "rum": "romeno", "hrv": "croato", "srp": "serbo",
    "slv": "sloveno", "mul": "multilingue", UNKNOWN: "lingua non indicata",
    # Step 7.
    "alb": "albanese", "amh": "amarico", "arm": "armeno", "arn": "mapuche",
    "baq": "basco", "bel": "bielorusso", "ben": "bengalese", "bos": "bosniaco",
    "bre": "bretone",
    "bul": "bulgaro", "cmn": "cinese mandarino", "epo": "esperanto",
    "est": "estone", "fao": "faroese", "fur": "friulano", "gle": "irlandese",
    "glg": "galego", "gsw": "tedesco alemannico", "guj": "gujarati",
    "hbs": "serbo-croato", "hin": "hindi", "ice": "islandese", "ina": "interlingua",
    "ind": "indonesiano", "jav": "giavanese", "jrb": "giudeo-arabo",
    "kok": "konkani", "kor": "coreano",
    "kur": "curdo", "lav": "lettone", "lit": "lituano", "lld": "ladino",
    "mac": "macedone", "mlt": "maltese", "mwl": "mirandese", "nap": "napoletano",
    "nno": "norvegese nynorsk", "ota": "turco ottomano", "per": "persiano",
    "pro": "provenzale antico", "roa": "lingue romanze", "roh": "romancio",
    "slo": "slovacco", "srd": "sardo", "swa": "swahili", "tgl": "tagalog",
    "tha": "thai", "ukr": "ucraino", "urd": "urdu", "vie": "vietnamita",
    "wel": "gallese", "yid": "yiddish", "yue": "cinese cantonese", "zul": "zulu",
}

# ISO 639-2/B -> the Wikipedia subdomain / Wikidata label code we query with
_TO_TWO = {v: k for k, v in _TWO.items()}


def from_sbn(label: str | None) -> str:
    """SBN linguaPubblicazione. Never falls back to a guess.

    A label naming two languages answers with the **first** of them: it is a
    parallel-text edition, SBN's own listing files it under both codes, and
    `Record.language` holds one. Which one is a choice and not a fact, so it is
    the one the cataloguer wrote first rather than a rule invented here.
    """
    if not label:
        return UNKNOWN
    label = label.strip().upper()
    code = _SBN.get(label)
    if code:
        return code
    first, sep, _ = label.partition(_PAIR)
    return _SBN.get(first.strip(), UNKNOWN) if sep else UNKNOWN


# Codes that mean "not recorded" rather than naming a language.
_INDETERMINATE = {"und", "mis", "zxx", "", "unknown"}


def from_sbn_code(code: str | None) -> str:
    """The OPAC's `lingua[]` facet value, which is already an ISO 639-2/B code.

    Not `from_sbn`: the facet answers with the code *and* the Italian label, and
    the code is what the listing filters on — so the listing path never needs
    the label map at all. `und`, `mis` and `zxx` mean 'not recorded' and stay
    unknown here exactly as they do for Open Library; passed through they would
    name a language that does not exist and put editions in a phantom group.
    """
    if not code:
        return UNKNOWN
    code = code.strip().lower()
    if code in _INDETERMINATE:
        return UNKNOWN
    return code if len(code) == 3 else _TWO.get(code, UNKNOWN)


# The languages above that are written in Latin script. Used by exactly one
# gate — `core.identity.language_contradicts_script` — and it is a fact about
# writing systems, not a judgement about a record. A language written in more
# than one script (`srp`, `hbs`, `aze`) is deliberately **absent**, so a record
# in one of them is never disbelieved on its script.
LATIN_SCRIPT = frozenset({
    "alb", "baq", "bos", "bre", "cat", "cze", "dan", "dut", "epo", "est", "fao",
    "fin", "fre", "fur", "ger", "gle", "glg", "gsw", "hrv", "hun", "ice", "ina",
    "ind", "ita", "jav", "lat", "lav", "lit", "lld", "mlt", "mwl", "nno", "nor",
    "eng", "pol", "por", "pro", "roh", "rum", "slo", "slv", "spa", "srd", "swa",
    "swe", "tgl", "tur", "vie", "wel",
})


def from_openlibrary(key: str | None) -> str:
    """'/languages/ita' or 'ita'."""
    if not key:
        return UNKNOWN
    code = key.rsplit("/", 1)[-1].strip().lower()
    if code in _INDETERMINATE:
        return UNKNOWN
    return code if len(code) == 3 else _TWO.get(code, UNKNOWN)


def from_two_letter(code: str | None) -> str:
    """A two-letter code: Wikipedia subdomain, Wikidata label key."""
    if not code:
        return UNKNOWN
    code = code.strip().lower().split("-")[0]
    return _TWO.get(code, code if len(code) == 3 else UNKNOWN)


def from_wikidata(qid: str | None) -> str:
    if not qid:
        return UNKNOWN
    return _WIKIDATA.get(qid.strip().upper(), UNKNOWN)


def two_letter(code: str) -> str | None:
    """ISO 639-2/B -> two-letter, for Wikipedia/Wikidata queries."""
    return _TO_TWO.get(code)


def display(code: str | None) -> str:
    return _DISPLAY.get(code or UNKNOWN, code or UNKNOWN)
