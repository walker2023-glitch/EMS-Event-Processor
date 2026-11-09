"""Adapter for the supplied EMS Setup Worksheet's merged report layout.

Columns are located from the repeated report header. Quantity and description
are the two indented detail columns beneath Location / Event. All source rows
remain attached to their occurrence; no operational details are inferred.
"""

import re
from typing import TYPE_CHECKING

from .models import SourceRow, Value
from .normalize import parse_date, text

if TYPE_CHECKING:
    from .parser import ReportParser

HEADERS = {
    "res start": "Reservation Start",
    "evt start": "Event Start",
    "evt end": "Event End",
    "res end": "Reservation End",
    "location / event": "Location",
    "setup / event type": "Setup/Event Type",
    "group": "Group",
    "status": "Status",
    "ec": "Event Coordinator",
}


class SetupWorksheetLayout:
    def __init__(self) -> None:
        self.columns: dict[str, int] = {}
        self.id_column: int | None = None
        self.sheet = ""
        self.section_kind = ""

    def consume(self, parser: "ReportParser", row: SourceRow) -> bool:
        if self.sheet != row.sheet:
            self.columns = {}
            self.id_column = None
            self.sheet = row.sheet
            self.section_kind = ""
        for index, value in enumerate(row.cells):
            if re.fullmatch(r"Res ID\s+Book ID", text(value), re.I):
                self.id_column = index
                return True
        detected = {
            HEADERS[text(value).casefold()]: index
            for index, value in enumerate(row.cells)
            if text(value).casefold() in HEADERS
        }
        if {"Reservation Start", "Event Start", "Location"}.issubset(detected):
            self.columns = detected
            return True
        if not self.columns:
            return False
        values = {i: value for i, value in enumerate(row.cells) if text(value)}
        if not values:
            return True
        single = text(next(iter(values.values()))) if len(values) == 1 else ""
        if single.casefold() in {"setup worksheet", "brigham young university - idaho"}:
            return True
        if re.fullmatch(r"Page\s+\d+(?:\s+of\s+\d+)?", single, re.I):
            return True
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M(?:\s+\w+)?", single, re.I):
            return True  # Report-generated timestamp, not an event date.
        if single and (day := parse_date(single)):
            if parser.event and parser.event.get("Event Date") != day:
                parser.finish()
            parser.current_date, parser.date_original = day, single
            return True
        parser.seen_content = True
        location_column = self.columns["Location"]
        description_column = location_column + 3
        quantity_column = location_column + 1
        identifier_column = self.id_column

        def get(key: str) -> Value:
            index = self.columns.get(key)
            return values.get(index) if index is not None else None

        times = [
            key
            for key in ("Reservation Start", "Event Start", "Event End", "Reservation End")
            if get(key) is not None
        ]
        if times:
            parser.finish()
            parser.start(row)
            self.section_kind = ""
            for key in self.columns:
                if (value := get(key)) is not None:
                    parser.set_field(key, value, row)
            if identifier_column is not None and identifier_column in values:
                parser.set_field("Reservation ID", values[identifier_column], row)
            parser.raw.append(row.text)
            return True
        if parser.event is None:
            parser.issue(
                row, "Unattached report row", "No event header precedes this report detail."
            )
            return True
        parser.raw.append(row.text)
        # Repeat IDs anchor wrapped metadata on a new printed page. They do not
        # start another occurrence or turn a status/group continuation into a contact.
        if identifier_column is not None and identifier_column in values:
            identifier = values[identifier_column]
            if text(identifier) in {"*", "**"}:
                parser.append(parser.event, "Source Flags", identifier)
                parser.issue(
                    row, "Uninterpreted marker", "Report marker retained without interpretation."
                )
            elif parser.event.get("Book ID") is None:
                parser.set_field("Book ID", identifier, row)
            elif text(identifier) != text(parser.event["Book ID"]):
                parser.issue(
                    row, "Conflicting identifier", "Unexpected booking identifier retained."
                )
            for key in ("Location", "Group", "Status"):
                value = get(key)
                if value is not None:
                    old = text(parser.event.get(key))
                    parser.event[key] = old + (" " if old else "") + text(value)
            coordinator = get("Event Coordinator")
            if coordinator is not None:
                parser.append(parser.event, "Source Flags", coordinator)
            return True
        # Primary/additional contacts occupy the Group column on detail rows.
        group_column = self.columns.get("Group")
        if group_column in values and len(values) == 1:
            key = (
                "Primary Contact"
                if not parser.event.get("Primary Contact")
                else "Additional Contacts"
            )
            parser.append(parser.event, key, values[group_column])
            return True
        if location_column in values and text(values[location_column]) not in {"*", "**"}:
            heading = text(values[location_column])
            event_type = get("Setup/Event Type")
            known_section = heading.casefold().startswith(
                (
                    "facility services",
                    "university catering",
                    "a student event coordinator",
                    "an event timeline",
                    "set up notes",
                    "setup notes",
                    "event notes",
                    "takedown notes",
                )
            )
            if not parser.event.get("Event Name") and not known_section:
                parser.event["Event Name"] = values[location_column]
                if event_type is not None:
                    parser.event["Event Type"] = event_type
                return True
            if event_type is not None:
                parser.append(parser.event, "Event Name", values[location_column])
                parser.append(parser.event, "Event Type", event_type)
                return True
            parser.section = heading
            parser.category = heading
            parser.request = None
            lower = heading.casefold()
            self.section_kind = (
                "contact"
                if "event coordinator" in lower
                else "notes"
                if lower
                in {
                    "an event timeline",
                    "set up notes",
                    "setup notes",
                    "event notes",
                    "notes",
                    "takedown notes",
                }
                else "request"
            )
            if self.section_kind == "notes":
                parser.append(parser.event, "Event Notes", heading)
            if description_column not in values:
                return True
        if description_column in values:
            description = values[description_column]
            count = values.get(quantity_column)
            if self.section_kind == "contact":
                if count is not None:
                    parser.append(parser.event, "Additional Contacts", description)
                else:
                    parser.append(parser.event, "Event Notes", description)
            elif count is not None or self.section_kind == "request" and not parser.request:
                parser.add_request(row, {"Quantity": count, "Equipment Description": description})
            elif parser.request is not None and self.section_kind == "request":
                parser.append(parser.request, "Request Notes", description)
            else:
                parser.append(parser.event, "Event Notes", description)
            if text(values.get(location_column)) in {"*", "**"}:
                parser.append(parser.event, "Source Flags", values[location_column])
                parser.issue(
                    row, "Uninterpreted marker", "Detail marker retained without interpretation."
                )
            return True
        if set(values) == {self.columns.get("Setup/Event Type")}:
            parser.append(parser.event, "Event Type", get("Setup/Event Type"))
            return True
        # No silent fallback: keep every non-layout row that did not fit the grammar.
        parser.issue(row, "Unparsed report row", "Report detail requires manual classification.")
        return True
