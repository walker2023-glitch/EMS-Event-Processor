# User guide

1. Open **EMS Event Processor**. Choose **Choose Excel File**, then select the
   original local `.xls` or `.xlsx` report. Its path appears on the screen.
2. Click **Process File**. In the save dialog choose a folder and `.xlsx` filename.
   Use a different filename from the source. Canceling either dialog changes no files.
3. Wait while the status moves through reading, parsing, totals and saving. The
   screen stays responsive; controls are disabled until processing finishes.
4. Read the completion summary. It lists events, requests, summary rows, issues
   and output paths. **Open Output Folder** opens the destination folder.
5. Open the organized workbook. Filter **Data Quality Status** for records needing
   review. When there is an issues workbook, compare its original text and source
   sheet/page/row with the original file. Correct the working output manually as
   appropriate; keep the original report as your reference.

**Events** contains occurrences, not reservation totals. A multi-day recurring
reservation remains multiple rows; **Recurrence ID** links occurrences only when
they share a source parent reservation or reservation ID. Matching names alone
do not establish recurrence.

**Equipment Requests** includes equipment and service lines. Coordinator entries
are contacts; report timeline and setup notes stay notes. A request's notes do
not add quantities. An unclear or missing quantity remains blank and is excluded
from **Equipment Summary**. Summary categories and descriptions are deliberately
conservative; similar names can appear on separate rows.

Asterisks and other unexplained source markers are preserved and flagged for
review. The program does not assign meaning to them. Some event fields can be
blank when the source omits them. Source pages are present when print breaks or
explicit report page markers provide them; source sheet and row are also retained.

If an error appears, check that the source is a readable Excel workbook, the
output folder exists, and the destination files are closed in Excel. The screen
does not report success on failure. Correct the problem and try again. Never
choose the original source or its aliases as an output location.

Replacing an existing output also updates its `_issues.xlsx` companion. A clean
rerun removes the old companion so earlier issues are not mistaken for new ones.
If no events were recognized, the completion warns you and the issues file
preserves the unrecognized content; do not use that output without review.

Processing is local. The organized workbooks can contain the source's contact
information, so store them in your normal approved working location. The concise
local log contains filenames, timestamps, counts and result status, not contacts
or notes. It is stored in `%LOCALAPPDATA%\EMS Event Processor\processing.log` on
Windows (`~/.local/state/EMS Event Processor/` elsewhere).

No work orders are generated and nothing is sent to the school website. Keep
using the existing work-order process. To roll back, retain the original report
and use a previous reviewed application build.
