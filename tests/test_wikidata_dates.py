"""`catalog/wikidata.original_date` and `original_year` — P577 as it is stated.

Every value below is a real P577 from decision AY's year probe (461
works, 2026-09-29), with its item named: the traps are a precision the year
reading ignored and a first value that was not the earliest.
"""

import pytest

from catalog import wikidata

JULIAN = "http://www.wikidata.org/entity/Q1985786"


def entity(*values, rank="normal"):
    """An item whose P577 holds `(time, precision[, julian])` values."""
    claims = []
    for v in values:
        time, precision = v[0], v[1]
        claims.append({"rank": rank, "mainsnak": {"datavalue": {"value": {
            "time": time, "precision": precision,
            "calendarmodel": JULIAN if len(v) > 2 else
            "http://www.wikidata.org/entity/Q1985727"}}}})
    return {"claims": {"P577": claims}}


class TestOriginalDate:
    @pytest.mark.parametrize("values,expected", [
        # Q165318 Crime and Punishment: to the year.
        ([("+1866-00-00T00:00:00Z", 9), ("+1886-01-01T00:00:00Z", 9)], (1866, 9)),
        # Q95850477 Le livre des rois: a century, not the year 1838.
        ([("+1838-00-00T00:00:00Z", 7)], (1838, 7)),
        # Q666014 Convivio: a decade, Julian.
        ([("+1304-00-00T00:00:00Z", 8, "J")], (1304, 8)),
        # Q1328064 Batrachomyomachia: a century BCE.
        ([("-0600-00-00T00:00:00Z", 7, "J")], (-600, 7)),
        # Q17523219 Eclogue 4: a year BCE.
        ([("-0039-01-01T00:00:00Z", 9)], (-39, 9)),
        # Q55816319 The story of the Iliad: the first value listed is not the
        # earliest (1895, 1891, 1911, 1892, 1907).
        ([("+1895-00-00T00:00:00Z", 9), ("+1891-00-00T00:00:00Z", 9),
          ("+1911-00-00T00:00:00Z", 9), ("+1892-00-00T00:00:00Z", 9),
          ("+1907-00-00T00:00:00Z", 9)], (1891, 9)),
        # Q480 Don Quixote: two parts; the first appeared first.
        ([("+1605-00-00T00:00:00Z", 9), ("+1615-00-00T00:00:00Z", 9)], (1605, 9)),
    ])
    def test_the_earliest_value_with_its_precision(self, values, expected):
        assert wikidata.original_date(entity(*values)) == expected

    def test_a_deprecated_value_is_not_read(self):
        ent = entity(("+1605-00-00T00:00:00Z", 9))
        ent["claims"]["P577"] += entity(("+1600-00-00T00:00:00Z", 9),
                                        rank="deprecated")["claims"]["P577"]
        assert wikidata.original_date(ent) == (1605, 9)

    def test_no_p577_is_no_date(self):
        assert wikidata.original_date({"claims": {}}) is None
        assert wikidata.original_date({}) is None


class TestOriginalYear:
    @pytest.mark.parametrize("values,expected", [
        ([("+1866-00-00T00:00:00Z", 9), ("+1886-01-01T00:00:00Z", 9)], "1866"),
        ([("+1895-00-00T00:00:00Z", 9), ("+1891-00-00T00:00:00Z", 9)], "1891"),
        # Coarser than a year, or BCE: no year a printing can be compared with.
        ([("+1838-00-00T00:00:00Z", 7)], None),
        ([("+1304-00-00T00:00:00Z", 8, "J")], None),
        ([("-0039-01-01T00:00:00Z", 9)], None),
    ])
    def test_only_a_year_stated_to_the_year(self, values, expected):
        assert wikidata.original_year(entity(*values)) == expected
