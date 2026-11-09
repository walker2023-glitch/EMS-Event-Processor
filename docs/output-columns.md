# Output columns
Column order is stable and defined in `models.py`. Dates are Excel dates, times
are Excel times, quantities use readable numeric formats, and unparseable values
remain source strings. Every sheet has filters and frozen headers. Blank fields
represent absent source data; they are not inferred.

## Events
| Column | Meaning |
| --- | --- |
| Event ID | Deterministic identifier for this source event occurrence. |
| Parent Reservation ID | Parent reservation identifier only when explicitly supplied. |
| Reservation ID | Source reservation identifier; text identifiers retain leading zeros. |
| Book ID | Source booking/occurrence identifier from the report detail row. |
| Event Date | Source calendar date; invalid source dates remain text and are flagged. |
| Reservation Start | Source reservation start time, without inferred setup time. |
| Event Start | Source event start time. |
| Event End | Source event end time. |
| Reservation End | Source reservation end time, without inferred takedown time. |
| Location | Source room/location, with wrapped report text joined. |
| Event Name | Source event name; wrapped source text remains available. |
| Setup/Event Type | Setup value from the report metadata row, or labeled setup/event type. |
| Group | Source group/organization. |
| Status | Source booking status, including wrapped text. |
| Primary Contact | First explicit source contact detail. |
| Additional Contacts | Other contact details and coordinator contacts; no inferred roles. |
| Event Notes | Source event/coordinator notes and explicit timelines/setup notes. |
| Source File | Original input filename. |
| Source Page | Printed report page when available; otherwise blank. |
| Source Row | One-based physical row in the source worksheet. |
| Data Quality Status | OK or Review required; consult the companion issues workbook. |
| Recurrence ID | Shared relationship for occurrences with the same explicit parent/reservation ID. |
| Source Sheet | Worksheet name in the source. |
| Original Source Text | Original event-block row text, including layout separators and inherited date context. |
| Event Type | Event type from the separate event-name/type report row. |
| Event Coordinator | Source EC initials/code from the event metadata header row. |
| Source Flags | Uninterpreted source markers or flags; associated issues explain review needs. |

## Equipment Requests
| Column | Meaning |
| --- | --- |
| Equipment Request ID | Deterministic identifier for a source request row. |
| Event ID | Deterministic identifier for this source event occurrence. |
| Event Date | Source calendar date; invalid source dates remain text and are flagged. |
| Location | Source room/location, with wrapped report text joined. |
| Action or Section | Source service/section heading; no inferred setup/takedown action. |
| Equipment Category | Exact trimmed source service-section/category label; no inferred inventory class. |
| Equipment Description | Trimmed source item/service description; spelling, case and internal spaces preserved. |
| Quantity | Clearly parsed nonnegative numeric quantity; blank for uncertain/missing values. |
| Original Request Text | Original source cells from the request row, joined with column separators. |
| Request Notes | Source note/continuation lines attached to this request; do not change totals. |
| Source File | Original input filename. |
| Source Page | Printed report page when available; otherwise blank. |
| Source Row | One-based physical row in the source worksheet. |
| Data Quality Status | OK or Review required; consult the companion issues workbook. |
| Source Sheet | Worksheet name in the source. |

## Equipment Summary
| Column | Meaning |
| --- | --- |
| Event Date | Source calendar date; invalid source dates remain text and are flagged. |
| Location | Source room/location, with wrapped report text joined. |
| Equipment Category | Exact trimmed source service-section/category label; no inferred inventory class. |
| Equipment Description | Trimmed source item/service description; spelling, case and internal spaces preserved. |
| Total Quantity | Sum of clear quantities for the exact date/location/category/description key. |
| Request Count | Number of confidently quantified requests included in this summary row. |

## Issues (separate workbook)
| Column | Meaning |
| --- | --- |
| Issue ID | Deterministic identifier for an issue in this processing run. |
| Issue Type | Classification such as Ambiguous equipment, Missing event value, or Unparsed row. |
| Severity | Warning: source information requires human review. |
| Description | Plain-language explanation of the parsing/data-quality problem. |
| Original Text | Relevant source row text preserved for comparison. |
| Related Event ID | Associated occurrence when recognized; blank for unattached content. |
| Reservation ID | Source reservation identifier; text identifiers retain leading zeros. |
| Book ID | Source booking/occurrence identifier from the report detail row. |
| Source File | Original input filename. |
| Source Page | Printed report page when available; otherwise blank. |
| Source Row | One-based physical row in the source worksheet. |
| Suggested Review Action | Compare with the source and correct the working output manually. |
| Source Sheet | Worksheet name in the source. |

Source text uses ` | ` between original cell values and newlines between rows.
Excel-invalid controls become visible `\uXXXX` escapes. If a text value exceeds
the Excel cell limit, the optional **Text Continuations** sheet preserves every
ordered chunk with its sheet, row and column references.
