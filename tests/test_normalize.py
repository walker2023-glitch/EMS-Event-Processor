from datetime import date, datetime, time
from decimal import Decimal

import pytest

from ems_event_processor.normalize import parse_date, parse_time, quantity, split_request


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Friday, November 6, 2026", date(2026, 11, 6)),
        ("11/06/2026", date(2026, 11, 6)),
        ("2026-11-06", date(2026, 11, 6)),
        (datetime(2026, 11, 6), date(2026, 11, 6)),
        ("next Friday", None),
        ("02/30/2026", None),
        ("11/06/26", None),
        (45600, None),
    ],
)
def test_dates(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("8:30 PM", time(20, 30)),
        ("08:30", time(8, 30)),
        (0.5, time(12)),
        (time(9), time(9)),
        ("after lunch", None),
        ("25:00", None),
    ],
)
def test_times(raw, expected):
    assert parse_time(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,200", Decimal(1200)),
        (2, Decimal(2)),
        ("2.5", Decimal("2.5")),
        ("0", Decimal(0)),
        ("a few", None),
        ("2-3", None),
        ("-2", None),
        ("1,20", None),
        ("NaN", None),
    ],
)
def test_quantities(raw, expected):
    assert quantity(raw) == expected


@pytest.mark.parametrize(
    "raw,description,count",
    [
        ("4 Chairs", "Chairs", Decimal(4)),
        ("2 x Tables", "Tables", Decimal(2)),
        ("Qty: 3 Microphones", "Microphones", Decimal(3)),
        ("Chairs (12)", "Chairs", Decimal(12)),
        ("Tables x 2", "Tables", Decimal(2)),
        ("6 ft Table", "6 ft Table", None),
        ("8' table", "8' table", None),
        ("Chairs as needed", "Chairs as needed", None),
    ],
)
def test_split_requests(raw, description, count):
    assert split_request(raw) == (description, count)
