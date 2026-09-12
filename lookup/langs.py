"""One language vocabulary for four sources that each use a different one.

Canonical form is ISO 639-2/B ('ita', 'eng', 'fre'), because that is what Open
Library uses and it is the least lossy of the four.

The important rule this module exists to enforce: an *unknown* language stays
unknown. The original script folded blank languages into English
(``if "eng" in langs or not langs``), which quietly inflated the English list
with records whose language was simply not recorded.
"""

UNKNOWN = "unknown"

# SBN linguaPubblicazione labels -> ISO 639-2/B
_SBN = {
    "ITALIANO": "ita", "INGLESE": "eng", "FRANCESE": "fre", "TEDESCO": "ger",
    "SPAGNOLO": "spa", "PORTOGHESE": "por", "RUSSO": "rus", "LATINO": "lat",
    "OLANDESE": "dut", "GRECO ANTICO": "grc", "GRECO MODERNO": "gre",
    "CATALANO": "cat", "POLACCO": "pol", "CECO": "cze", "SVEDESE": "swe",
    "DANESE": "dan", "NORVEGESE": "nor", "FINLANDESE": "fin", "UNGHERESE": "hun",
    "GIAPPONESE": "jpn", "CINESE": "chi", "ARABO": "ara", "EBRAICO": "heb",
    "TURCO": "tur", "ROMENO": "rum", "CROATO": "hrv", "SERBO": "srp",
    "SLOVENO": "slv", "MULTILINGUE": "mul",
}

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
_DISPLAY = {
    "ita": "italiano", "eng": "inglese", "fre": "francese", "ger": "tedesco",
    "spa": "spagnolo", "por": "portoghese", "rus": "russo", "lat": "latino",
    "dut": "olandese", "gre": "greco", "grc": "greco antico", "cat": "catalano",
    "pol": "polacco", "cze": "ceco", "swe": "svedese", "dan": "danese",
    "nor": "norvegese", "fin": "finlandese", "hun": "ungherese",
    "jpn": "giapponese", "chi": "cinese", "ara": "arabo", "heb": "ebraico",
    "tur": "turco", "rum": "romeno", "hrv": "croato", "srp": "serbo",
    "slv": "sloveno", "mul": "multilingue", UNKNOWN: "lingua non indicata",
}

# ISO 639-2/B -> the Wikipedia subdomain / Wikidata label code we query with
_TO_TWO = {v: k for k, v in _TWO.items()}


def from_sbn(label: str | None) -> str:
    """SBN linguaPubblicazione. Never falls back to a guess."""
    if not label:
        return UNKNOWN
    return _SBN.get(label.strip().upper(), UNKNOWN)


# Codes that mean "not recorded" rather than naming a language.
_INDETERMINATE = {"und", "mis", "zxx", "", "unknown"}


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
