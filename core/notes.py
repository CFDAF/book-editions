"""How a lookup states what it did not manage: one wording, every client.

`partial (N failed)`, the *Incomplete* note and the slow-lookup note are three
readings of one `Ledger` (`CLAUDE.md` rule 5), and the truncation lines are rule
10's — *every truncation is on the page*. They are phrased **here**, in `core/`,
for the reason the transport refused to phrase them in `app/`: two places
wording the same number are two places that can disagree, and the CLI, the page
and a test would then each say something slightly different about the same
lookup.

Nothing in this module touches the network or reads a clock. It takes counts
that were already measured and returns sentences, which is what makes every
line below testable offline and the whole file reachable by the suite.

Two rules it exists to keep:

- **A failed request is never an empty result.** A source that lost requests is
  said to be partial even when it reported nothing wrong, because the ledger
  counts the failure whether or not the source that swallowed it does.
- **A truncation is a statement about what was read, never about what exists.**
  "read 240 of 1,366 records filed under this name" is a fact about the query;
  there is no census here and there cannot be one (decision C).
"""

# The ledger names hosts by catalogue, and these are the three it knows. A
# state carrying any other name (`SBN authority`, say, whose requests the
# ledger counts under SBN) is left as its source wrote it rather than being
# charged the same failures twice.
LEDGER_SOURCES = ("Wikidata", "Open Library", "SBN")

OK = "ok"


# ---------------------------------------------------------------------------
# The network reading
# ---------------------------------------------------------------------------

def source_states(states: dict, failed_by_source) -> dict:
    """Each source's state, with `partial (N failed)` where the ledger says so.

    `failed_by_source` is a callable — `Ledger.failed` — so this stays pure and
    a test can hand it a dict's `get`. A source already reporting an error keeps
    it: `error:` is worse than `partial` and the worse state is the true one.
    """
    out = dict(states)
    for name in LEDGER_SOURCES:
        if out.get(name) != OK:
            continue
        missed = failed_by_source(name) or 0
        if missed:
            out[name] = f"partial ({missed} failed)"
    return out


def incomplete(failed: int) -> str | None:
    """The note that says the answer is short, and why. None when nothing failed.

    It is deliberately not phrased as an error: the lookup did answer, and what
    a reader needs to know is that a language can be missing from an answer that
    otherwise looks complete.
    """
    if not failed:
        return None
    calls = "request" if failed == 1 else "requests"
    return (f"Incomplete: {failed} {calls} failed, so editions are probably missing "
            "— a whole language can drop out this way. Everything that did arrive "
            "is cached, so running the same search again is fast and usually fills "
            "the gaps.")


def slow(elapsed: float, causes: list, threshold: float) -> str | None:
    """What a slow lookup spent its time on — only what the ledger measured.

    Nothing is inferred: a lookup that was slow for a reason the network layer
    cannot see gets no cause at all and says so, rather than naming a plausible
    one (decision K).

    The request-time clause `Ledger.slow_causes` produces is a **sum over calls
    that ran in parallel**, so it can exceed the lookup's own wall time — 75 s
    of Wikidata inside a 62 s lookup is accurate and reads as nonsense unless it
    is labelled. This is where it is labelled.
    """
    if elapsed <= threshold:
        return None
    if not causes:
        return (f"Slow lookup ({elapsed:.0f} s), though no request in it went to "
                "the network.")
    return (f"Slow lookup ({elapsed:.0f} s). Measured in it: {'; '.join(causes)}. "
            "Request times are summed across requests that ran in parallel, so "
            "they can add up to more than the lookup took.")


# ---------------------------------------------------------------------------
# The truncations
# ---------------------------------------------------------------------------

def _read_of(read: int, total, what: str) -> str:
    return f"read {read:,} of {total:,} {what}" if total else f"read {read:,} {what}"


def truncations(evidence: dict) -> list:
    """One line per cap this lookup hit, in the order the stages ran.

    Rule 10: every truncation is on the page. The caps are real and they are
    each other's opposite — the page cap keeps an author's whole catalogue out
    of an answer, and saying nothing about it would make a partial read look
    like the whole of SBN.
    """
    out = []
    out += _identity_truncations(evidence.get("identity") or {})
    out += _listing_truncations(evidence.get("listing") or {})
    out += _recovery_truncations(evidence.get("recovery") or {})
    out += _enrich_truncations(evidence.get("enrich") or {})
    out += _date_truncations(evidence.get("dates") or {})
    out += _reconcile_truncations(evidence.get("dates") or {})
    out += _duplicate_truncations(evidence.get("duplicates") or {})
    return out


def _identity_truncations(identity: dict) -> list:
    out = []
    sbn = identity.get("sbn_work") or {}
    if sbn.get("facet_truncated"):
        out.append("SBN offered 50 uniform titles for this question and stops there, "
                   "so the work was chosen from the first 50")
    by_title = identity.get("title_spellings") or {}
    asked = len(by_title.get("asked") or [])
    if asked and (by_title.get("offered") or 0) > asked:
        out.append(f"of the {by_title['offered']} other spellings of the title Wikidata "
                   f"gives, the first {asked} were asked of SBN")
    return out


# ---------------------------------------------------------------------------
# What the reader's spelling switches asked (decision AV)
# ---------------------------------------------------------------------------

def spellings(identity: dict, recovery: dict) -> list:
    """One line per switch the reader ticked: what it asked, and what it found.

    A switch that could ask nothing says why — a title switch with no Wikidata
    item has no other spellings to ask, and reading that as "SBN has nothing
    under other spellings" would be the empty-result confusion rule 5 is about.
    """
    out = []
    by_title = identity.get("title_spellings")
    if by_title is not None:
        asked = by_title.get("asked") or []
        tried = {t.get("spelling"): t for t in identity.get("spellings") or []}
        works = sorted({tried[v]["W"] for v in asked if (tried.get(v) or {}).get("W")})
        if not by_title.get("item"):
            out.append("other spellings of the title: none asked — Wikidata has no "
                       "item for this work to give them")
        elif not asked:
            out.append("other spellings of the title: Wikidata gives none SBN can be asked")
        else:
            found = (f"; SBN files them under {', '.join(repr(w) for w in works)}"
                     if works else "; SBN files none of them under a work")
            out.append(f"other spellings of the title asked of SBN: "
                       f"{', '.join(repr(v) for v in asked)}{found}")
    by_author = identity.get("author_spellings")
    if by_author is not None:
        if not by_author.get("asked"):
            out.append(f"other spellings of the author: none asked — "
                       f"{by_author.get('why_not') or 'Wikidata did not answer'}")
        else:
            forms = len(by_author.get("forms") or [])
            sweeps = (recovery.get("routes") or {}).get("other_author_sweeps") or []
            primary = (identity.get("authority") or {}).get("id")
            others = [i for i in by_author.get("ids") or [] if i != primary]
            if others and not sweeps:
                out.append(f"other spellings of the author: SBN files the same person "
                           f"under {len(others)} more name record"
                           f"{'s' if len(others) != 1 else ''} ({', '.join(others)}), "
                           f"not swept: this lookup found no work to check their "
                           f"records against")
            elif sweeps:
                read = ", ".join(f"{s.get('authority')} ({s.get('rows') or 0:,} "
                                 f"record{'' if s.get('rows') == 1 else 's'})"
                                 for s in sweeps)
                out.append(f"other spellings of the author: {forms} asked of SBN, which "
                           f"files the same person under {len(sweeps)} more name "
                           f"record{'s' if len(sweeps) != 1 else ''}, swept: {read}")
            else:
                out.append(f"other spellings of the author: {forms} asked of SBN, which "
                           f"files the person under no other name record")
    return out


def _listing_truncations(listing: dict) -> list:
    out = []
    sbn = listing.get("sbn") or {}
    rows, total = listing.get("sbn_rows") or 0, sbn.get("total") or 0
    if sbn.get("truncated") or (total and rows < total):
        out.append("the SBN listing " + _read_of(rows, total,
                                                 "records filed under this work"))
    if sbn.get("facet_truncated"):
        out.append("SBN lists at most 50 languages for a work, so a language "
                   "beyond the 50th was reached only by the unfiltered pass")
    return out


def _recovery_truncations(recovery: dict) -> list:
    out = []
    routes = recovery.get("routes") or {}
    sweep = routes.get("author_sweep") or {}
    if sweep.get("truncated"):
        out.append("the author sweep " + _read_of(sweep.get("rows") or 0,
                                                  sweep.get("total"),
                                                  "records filed under this name"))
    for other in routes.get("other_author_sweeps") or []:
        if other.get("truncated"):
            out.append(f"the sweep of SBN's name record {other.get('authority')} "
                       + _read_of(other.get("rows") or 0, other.get("total"),
                                  "records filed under that spelling"))
    for probe in routes.get("title_probes") or []:
        if probe.get("truncated"):
            out.append(f"the title probe for {probe.get('title')!r} "
                       + _read_of(probe.get("rows") or 0, probe.get("total"), "records"))
    return out


def _enrich_truncations(enrich: dict) -> list:
    """S4's cap (decision AG). The rows past it are in the list as the listing
    has them: not folded by ISBN and, if S3 recovered them, with no language."""
    if not enrich.get("truncated"):
        return []
    return [f"full records were read for {enrich.get('asked') or 0:,} of "
            f"{enrich.get('rows') or 0:,} SBN rows; the rest are listed as the "
            "listing has them, so their printings are not grouped"]


def _date_truncations(checked: dict, what: str = "rows") -> list:
    """The date check's cap (decision AY). The rows past it say `year unsure`."""
    if not checked.get("truncated"):
        return []
    return [f"dates were checked with SBN for {checked.get('checked') or 0:,} of "
            f"{checked.get('rows') or 0:,} {what} whose year is not plain; the rest "
            "are labelled year unsure"]


def _reconcile_truncations(checked: dict) -> list:
    """The plain-year reconciliation's cap (decision AY)."""
    if not checked.get("reconcile_truncated"):
        return []
    return [f"SBN's index was asked about {checked.get('reconcile_requests') or 0:,} of "
            f"{checked.get('reconcile_wanted') or 0:,} years whose counts disagree with "
            "the listing; rows under the rest keep the year they state"]


def _duplicate_truncations(duplicates: dict) -> list:
    """Step 13's searches read the first page of each answer. Open Library
    ranked every known duplicate within its first 75, but 16 of 81 entries ask
    something with more behind it (*Odyssey Homer* finds 1,835), and a record
    past the page is not on the list. One line for all of them: N23 asks five."""
    over = [q for q in duplicates.get("queries") or []
            if q.get("total") and (q.get("docs") or 0) < q["total"]]
    if not over:
        return []
    read = max(q.get("docs") or 0 for q in over)
    most = max(q["total"] for q in over)
    if len(over) == 1:
        return [f"the search for Open Library's other records under "
                f"{over[0].get('title')!r} " + _read_of(read, most, "results")]
    return [f"the {len(over)} searches for Open Library's other records read the "
            f"first {read:,} results each, and each found more (up to {most:,})"]


# ---------------------------------------------------------------------------
# What was not asked, which is not the same as what failed
# ---------------------------------------------------------------------------

def not_asked(evidence: dict) -> list:
    """Queries this lookup refused to send, with the reason each one was refused.

    A request that could only come back looking like an answer is not made — a
    non-Latin term the OPAC discards while returning the unfiltered set (F15), a
    title holding a single `/` that Solr reads as an unterminated regex. That is
    a **disclosure, not a failure**, and the difference is the whole of rule 5:
    the ledger counts what failed, and this names what was never sent.
    """
    out = []
    listing = evidence.get("listing") or {}
    for part in ((listing.get("sbn") or {}), (listing.get("open_library") or {})):
        if part.get("asked") is False and part.get("why_not"):
            out.append(part["why_not"])
    recovery = evidence.get("recovery") or {}
    if recovery.get("why_not"):
        out.append(recovery["why_not"])
    routes = recovery.get("routes") or {}
    for probe in routes.get("title_probes") or []:
        if probe.get("asked") is False and probe.get("why_not"):
            out.append(f"{probe.get('title')!r}: {probe['why_not']}")
    sweep = routes.get("author_sweep") or {}
    if sweep.get("asked") is False and sweep.get("why_not"):
        out.append(sweep["why_not"])
    duplicates = evidence.get("duplicates") or {}
    if duplicates.get("asked") is False and duplicates.get("why_not"):
        out.append(duplicates["why_not"])
    return out


# ---------------------------------------------------------------------------
# Author mode (Step 14, decision AJ)
# ---------------------------------------------------------------------------

def author_truncations(evidence: dict) -> list:
    """Every place an author's works list was cut, as one line each.

    SBN's facet stops at 50 works (F11). Decision AJ splits a list that hits it
    by language and then by exact year, so what is left to say is **what no
    split covered**: the records under the name that fell in no answer SBN gave
    in full, counted by summing the leaves' totals against the whole, and any
    leaf that still stopped at 50. Never a census (decision C) — a count of the
    records read, not of the works that exist.
    """
    out = []
    for sbn in evidence.get("sbn") or []:
        name = sbn.get("name") or "this name"
        if sbn.get("languages_capped"):
            out.append(f"SBN names at most 50 languages for {name}, so a language "
                       "past the 50th was not asked on its own")
        uncovered = (sbn.get("total") or 0) - (sbn.get("covered") or 0)
        if sbn.get("split") and uncovered > 0:
            # "At least": a record in two languages is in two leaves, so the
            # leaves' sum over-counts what they covered (Murakami 413 of 406).
            out.append(f"SBN lists at most 50 works per question, so {name}'s were "
                       f"asked again by language and by year; at least {uncovered:,} of "
                       f"{sbn['total']:,} records fell in no answer SBN gave in full, "
                       "and a work held only by them is not listed")
        capped_leaves = sbn.get("capped_leaves") or []
        if capped_leaves:
            out.append(f"{len(capped_leaves)} of those questions still stopped at 50 "
                       f"works ({', '.join(capped_leaves[:5])})")
    for source, what in (("wikidata", "Wikidata works naming this person"),
                         ("open_library", "Open Library works under this name")):
        part = evidence.get(source) or {}
        if part.get("total") and (part.get("read") or 0) < part["total"]:
            out.append(f"{_read_of(part.get('read') or 0, part['total'], what)}")
    for read in (evidence.get("unlinked") or {}).get("read") or []:
        if read.get("truncated"):
            out.append(f"{_read_of(read.get('read') or 0, read.get('total') or 0, 'records under this name')}"
                       ", so a book held only by the rest is not among those filed under no work")
    out += _date_truncations(evidence.get("dates") or {}, "records filed under no work")
    years = evidence.get("years_capped") or 0
    if years:
        works = "work has" if years == 1 else "works have"
        out.append(f"{years} {works} SBN editions in more than 50 years, so the "
                   "earliest edition shown is the earliest of the 50 SBN reports")
    return out


# ---------------------------------------------------------------------------
# Title only (decision AN)
# ---------------------------------------------------------------------------

def _listed(names: list) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def author_adopted(sources: list) -> str:
    """The byline's note when no author was typed and the sources agreed on one."""
    return f"author from {_listed(sorted(sources))} — none was typed"


def books_share_title(count: int, title: str) -> str:
    """The chooser's heading: the question has several answers, pick one."""
    return f"{count} books are called “{title}” — pick one"


# ---------------------------------------------------------------------------
# A row's year (decision AY)
# ---------------------------------------------------------------------------

YEAR_LABELS = {"inferred": "year inferred", "printed": "printed {}",
               "unsure": "year unsure",
               "unchecked": "year unchecked", "other calendar": "other calendar",
               "no date": "no year"}


def year_label(note: str, years=()) -> str:
    """The row's short label for a year not taken as the catalogue wrote it.
    `years` names the printing on a `printed` label: *printed 1997*."""
    return YEAR_LABELS[note].format(", ".join(str(y) for y in years))


def year_detail(note: str, statements: list, indexed: list, asked: bool = False) -> str:
    """The label's tooltip: what the catalogue wrote, what SBN's index said.
    `asked` is whether SBN's index was read at all for this row."""
    if note == "no date":
        return "The catalogue gives no year."
    parts = [f"Catalogue: {'; '.join(statements)}."]
    if indexed:
        parts.append(f"SBN index: {', '.join(indexed)}.")
    parts.append({"inferred": "The year both agree on is shown.",
                  "printed": "SBN files it under the printing; the year shown is "
                             "the publication's.",
                  "unsure": "They do not agree on one year." if indexed
                  else "SBN's index gives none of these years." if asked
                  else "Nothing to check it against.",
                  "unchecked": "SBN could not be asked.",
                  "other calendar": "Another calendar; not converted."}[note])
    return " ".join(parts)
