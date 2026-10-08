"""Which year a catalogue's date means, and how sure of it the page can be.

Decision AY, on its year probe's live sweep (2,190 SBN records in 32
languages). SBN dates a record in the calendar its imprint uses: 65 of 156
Persian records read `1386 [2007]`, Ottoman ones `1308 AH [1891]`, Hindi ones
`2012 [1955]` — a Bikram Sambat year no plausibility check can see — and the
first year was the one the page drew, so a Persian row led the language list
above the original. Two second readings exist and **each was wrong once**: the
year in brackets (`1958 ʻĀ.Me. [1966]`, where SBN's own index says 1958) and
SBN's `dataf[]` index. So neither is trusted alone:

* **plain** — one year, 1450 to next year, no calendar mark. Taken as written;
  95% of the sweep.
* otherwise the record's SBN index is read (`lookup.stages.check_dates`), and
  - the index has the first year and no bracketed year contradicts it: the
    first year, no label — `c1978, stampa 1977`, `1876-1884`;
  - the index has exactly one other year the imprint wrote: that year,
    labelled **inferred** — `1386 [2007]` -> 2007;
  - anything else: no year, labelled **unsure**, and every year either reading
    gave is shown (`1958 / 1966`).
* a date no index was read for is **unsure** (Open Library has none), or
  **unchecked** if the check failed; one whose only years carry a calendar mark
  or cannot be Gregorian and that nothing converted is **other calendar**.

A row with no settled year is undated for the header, the language order and
the year filter; it still shows what the catalogue wrote. Nothing here reads
the network or a clock: `this_year` is the caller's.
"""

import re
from collections import Counter
from dataclasses import replace

EARLIEST = 1450                 # printing in Europe; an earlier year is not plain

INFERRED = "inferred"
PRINTED = "printed"
UNSURE = "unsure"
UNCHECKED = "unchecked"
OTHER_CALENDAR = "other calendar"
NO_DATE = "no date"
# The one a row shows when its records disagree: the least certain wins.
SEVERITY = (UNCHECKED, UNSURE, OTHER_CALENDAR, INFERRED, PRINTED, NO_DATE)

# Any four digits from 1000 to 2999: `2044 [1987]` and `2064` are Bikram Sambat.
_YEAR = re.compile(r"(?<!\d)([12]\d{3})(?!\d)")
_BRACKETED = re.compile(r"[\[<]([^\]>]*)[\]>]")
# A calendar's mark on the year it follows: `1304 h`, `1373H`, `1333 eg.`,
# `1308 AH`, `1331 A.H.`, `1958 ʻĀ.Me.`, `1313 h./[1934]`. Not `s.n.`.
_MARK = re.compile(r"(?<!\d)[12]\d{3}\s?(?:A\.?\s?H\.?|H|h|s|eg|ʻĀ\.\s?Me|E\.\s?C)"
                   r"(?=$|\.|[\s/\[\(,;])(?!\.[^\W\d_])")
_RANGE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})\s*$")
# A printing is not a reading of the publication year: SBN's index files
# `1996, stampa 1997` under 1997, and the edition is 1996's.
_PRINTING = re.compile(r"\b(?:stampa|ristampa|rist\.|impr\.|printed|printing)\s*"
                       r"(?:\d{4}|\[\d{4}\])", re.I)
# A multi-volume run, `1988-2006`, starts in its first year; so does a year of
# another calendar written as the two Gregorian ones it straddles, `[1925/1926]`
# or `[2004 o 2005]` — those only when the two are consecutive.
_SPAN = re.compile(r"(?<!\d)([12]\d{3})\s?(-|/|\so\s|\sor\s)\s?([12]\d{3})(?!\d)")


def _span(m) -> str:
    first, last = int(m.group(1)), int(m.group(3))
    run = first < last if m.group(2) == "-" else last == first + 1
    return m.group(1) if run else m.group(0)


def printing_years(statement: str | None) -> list:
    """The years a printing statement names: `1996, stampa 1997` -> [1997]."""
    return list(dict.fromkeys(int(y) for m in _PRINTING.finditer(statement or "")
                              for y in _YEAR.findall(m.group(0))))


def candidates(statement: str | None) -> list:
    """Every year the statement writes as a publication year, in order, once
    each: printings dropped, a run of years read as its first."""
    text = _PRINTING.sub(" ", statement or "")
    text = _SPAN.sub(_span, text)
    return list(dict.fromkeys(int(y) for y in _YEAR.findall(text)))


def bracketed(statement: str | None) -> list:
    return list(dict.fromkeys(y for inside in _BRACKETED.findall(statement or "")
                              for y in candidates(inside)))


def indexed_years(values) -> set:
    """`dataf[]` values as years: `2007`, and a range `1977-1991` as both ends."""
    out = set()
    for value in values or []:
        text = str(value)
        m = _RANGE.match(text)
        if m:
            out |= {int(m.group(1)), int(m.group(2))}
        elif text.strip().isdigit():
            out.add(int(text))
    return out


def _covers(value, year: int) -> bool:
    """Is `year` inside one `dataf[]` value — the year itself, or a range's span."""
    m = _RANGE.match(str(value))
    if m:
        return int(m.group(1)) <= year <= int(m.group(2))
    return str(value).strip() == str(year)


def _gregorian(year: int, this_year: int | None) -> bool:
    return year >= EARLIEST and (this_year is None or year <= this_year + 1)


def is_plain(statement: str | None, this_year: int | None = None) -> bool:
    """One year a Gregorian reader can take as written."""
    years = candidates(statement)
    return (len(years) == 1 and _gregorian(years[0], this_year)
            and not _MARK.search(statement or ""))


def needs_check(record, this_year: int | None = None) -> bool:
    """Is SBN's index worth asking about this record's date?"""
    return (record.source == "SBN" and bool(record.date)
            and not is_plain(record.date, this_year))


def plain_year(record, this_year: int | None = None) -> int | None:
    return candidates(record.date)[0] if is_plain(record.date, this_year) else None


def values_to_ask(years: list, records: list, capped: bool,
                  this_year: int | None = None) -> tuple:
    """`(values, absent)` for one listing bucket: the `dataf[]` values whose
    count SBN gives differs from the count its records' years give, most
    different first, and the years SBN files none of the bucket under.

    `years` is the bucket's facet (`[{value, results}]`); a record counts under
    its plain year, or under the values the index already gave it. Where every
    count agrees nothing is asked — a swap of two years within one bucket is the
    one disagreement this cannot see. A facet cut at 50 values (`capped`, F11)
    cannot say a year is absent, so those years are asked instead.
    """
    facet = {str(it["value"]): int(it.get("results") or 0) for it in years
             if it.get("value")}
    expected = Counter()
    for r in records:
        year = plain_year(r, this_year)
        if year is not None:
            expected[str(year)] += 1
        else:
            expected.update(str(v) for v in r.date_indexed or [])
    ask = sorted((v for v in facet if facet[v] != expected[v]),
                 key=lambda v: (-abs(facet[v] - expected[v]), v))
    unlisted = sorted(v for v in expected if v not in facet)
    if capped:
        return ask + unlisted, set()
    return ask, set(unlisted)


def contradicted(record, answers: dict, absent: set, this_year: int | None = None):
    """The values SBN files a plain-dated record under when its own year is not
    one of them, else None. `answers` is `{value: ids}` for the values asked and
    answered; a year neither asked nor absent agreed by count, so it stands."""
    year = plain_year(record, this_year)
    if year is None:
        return None
    under = sorted(v for v, ids in answers.items() if record.id in ids)
    if any(_covers(v, year) for v in under):
        return None
    if str(year) not in answers and str(year) not in absent:
        return None
    return under


def settle(record, this_year: int | None = None) -> tuple:
    """`(year, note, shown)` for one record: the year the page may use (a
    string, or None), why it was not taken as written, and the years an
    unsettled row shows instead."""
    statement = record.date
    if not statement:
        if record.year:                 # a source that gives a year and no text
            return record.year, None, []
        return None, NO_DATE, []
    if is_plain(statement, this_year):
        year = candidates(statement)[0]
        index = indexed_years(record.date_indexed)
        # A plain year carries an index only where the listing's counts said
        # SBN files it elsewhere (`contradicted`): both are shown, neither kept.
        if record.date_indexed is None or record.date_check_failed or year in index:
            return str(year), None, []
        # SBN filed the printing the imprint itself states: nothing is unsure,
        # the row is the publication year and names the printing (the user's
        # call on decision AY). `shown` carries the printing year for the label.
        printed = sorted(index & set(printing_years(statement)))
        if printed:
            return str(year), PRINTED, printed
        return None, UNSURE, sorted({year} | index)
    years = candidates(statement)
    if not years:                       # Open Library's `199u`, `19xx`: a decade
        return None, UNSURE, [statement]
    index = indexed_years(record.date_indexed)
    shown = sorted(set(years) | index)
    if record.date_indexed is not None and not record.date_check_failed:
        first, agreed = years[0], [y for y in years if y in index]
        contradicted = [y for y in bracketed(statement) if y not in index]
        if first in index and not contradicted:
            return str(first), None, []
        if len(agreed) == 1 and agreed[0] != first:
            return str(agreed[0]), INFERRED, []
    if record.date_check_failed:
        return None, UNCHECKED, shown
    if not any(_gregorian(y, this_year) for y in years) or (
            _MARK.search(statement) and not bracketed(statement) and len(years) == 1):
        return None, OTHER_CALENDAR, shown
    return None, UNSURE, shown


def settled(record, this_year: int | None = None):
    """The view's copy of a record, with the settled year in `year`."""
    year, note, shown = settle(record, this_year)
    return replace(record, year=year, year_note=note,
                   years_shown=[str(y) for y in shown])


def row_note(records: list) -> tuple:
    """`(note, shown, statements)` for one edition's settled records.

    `no date` only when no record behind the row has a year: a printing SBN
    dates beside one Open Library leaves blank is a dated row.
    """
    notes = [r.year_note for r in records if r.year_note]
    if any(r.year for r in records):
        notes = [n for n in notes if n != NO_DATE]
    note = next((n for n in SEVERITY if n in notes), None)
    shown = sorted({y for r in records for y in r.years_shown})
    statements = list(dict.fromkeys(r.date for r in records
                                    if r.date and r.year_note))
    return note, shown, statements
