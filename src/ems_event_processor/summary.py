"""Totals only for confidently parsed numeric requests, without fuzzy merging."""

from decimal import Decimal

from .models import Record


def summarize(requests: list[Record]) -> list[Record]:
    totals: dict[tuple[object, ...], Record] = {}
    columns = ("Event Date", "Location", "Equipment Category", "Equipment Description")
    for request in requests:
        count = request.get("Quantity")
        if not isinstance(count, Decimal) or not request.get("Equipment Description"):
            continue
        key = tuple(request.get(column) for column in columns)
        if key not in totals:
            totals[key] = {column: request.get(column) for column in columns}
            totals[key].update({"Total Quantity": Decimal(0), "Request Count": 0})
        total = totals[key]["Total Quantity"]
        request_count = totals[key]["Request Count"]
        assert isinstance(total, Decimal) and isinstance(request_count, int)
        totals[key]["Total Quantity"] = total + count
        totals[key]["Request Count"] = request_count + 1
    return list(totals.values())
