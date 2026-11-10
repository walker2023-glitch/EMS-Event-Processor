# UI update: Stitch layout and light/dark themes

This change is based on the five HTML states supplied from the approved Google
Stitch project: Initial, File Selected, Processing, Complete and Error. The
original project URL did not expose the design in this environment; the exported
HTML supplied in chat is the design reference.

## Scope and appearance

`ui.py` controls widgets, file/save dialogs, background-worker integration, status
and completion rendering. `ui_theme.py` contains palettes and ttk styles. Parser,
normalization, processing, summary, model, Excel exporter and issue-reporting
modules are unchanged, as are their tests and the generated workbook structure.
There are no new runtime or development dependencies.

The interface follows the reference's slate background, white bordered cards,
`#0F4C5C` primary color, large title, Input Excel File area, Processing area and
separate completion metrics/generated-file display. Dark mode uses charcoal/navy
surfaces and a lighter teal accent, including readonly paths, disabled controls,
progress, and success/warning/error text. Status always includes explanatory text.
Enabled text and status palette pairs have automated 4.5:1 contrast checks.

The original workflow remains Choose Excel File → Process File → output save
dialog → results. Choosing or saving can still be canceled. The UI enables
processing only for an existing `.xls` or `.xlsx` selection; workbook readability
is checked by the unchanged engine. No sample filename, size, percentage, count,
or issue explanation from the mockup is substituted for actual source/results.
Progress remains indeterminate with the engine's real status messages.

## Themes, keyboard access and scaling

The top-right Light Mode / Dark Mode control defaults to light. Selection lasts
for the current application session only, including when Process Another File
resets the workflow. Switching themes never starts/stops a worker or changes its
input/output. No preference file or database is created.

Keyboard shortcuts (in addition to normal Tab/Space navigation):

| Shortcut | Action |
| --- | --- |
| Alt+C | Choose / Change File |
| Alt+P | Process File |
| Alt+O | Open Output Folder |
| Alt+A | Process Another File |
| Alt+L / Alt+D | Light Mode / Dark Mode |

Busy controls stay disabled, including when reached by a shortcut. After
completion the folder button receives focus; reset returns focus to file
selection. The window can resize, long labels wrap, metric cards use two or four
columns as space permits, and vertical scrolling keeps controls reachable at
larger scaling. Keyboard focus scrolls its control into view when necessary.

## Validation

- The original **83 test scenarios** passed before editing and remain covered.
  A timing-dependent assertion in an existing UI test now allows fast completion
  during the first Tk update; the new gated-worker tests verify responsiveness
  deterministically. Parser/export regression tests remain unchanged.
- The full suite currently has **106 tests**, including 23 new UI checks for
  initial/selected/invalid input, themes, switching during real worker processing,
  progress/status, successful and failed completion, reset, source protection,
  workbook/issue sheets, folder actions, contrast and 100%/150% equivalent Tk
  scaling. `tests/test_ui_themes.py` adds these checks.
- Run `python -m pytest -q` on Windows, or with a display on Linux (for example
  `DISPLAY=:99 .venv/bin/pytest -q`). Run `ruff check .`, `ruff format --check .`,
  and `mypy` as well. No parser/export regression test was edited.
- CI builds the Windows executable with the existing PyInstaller spec and runs
  the existing startup/shutdown smoke check. `scripts/smoke_ui_windows.py` also
  drives the packaged app's real native file/save dialogs using Windows keyboard
  input, switches themes, processes both invented fixtures, verifies generated
  sheets and unchanged source bytes, invokes folder opening/reset, and checks an
  unreadable-file error. It captures sanitized Windows review images.
- The Windows review-image and executable artifacts are attached to the UI PR's
  verification workflow. CI results and remaining manual checks are reported in
  the PR; the existence of a workflow is not itself evidence that it passed.

## Desktop differences and limits

Tkinter retains native operating-system title-bar controls and dialogs rather
than drawing the mockup's fake Windows frame. Dialog/title-bar appearance follows
the OS theme. Standard ttk borders replace web shadows, dashed/rounded cards and
Material Symbols; no remote fonts, icon/CDN requests, or web framework is needed.
Inter is used if already installed, followed by Segoe UI and an installed system
sans-serif fallback. Web-perfect font metrics and CSS rendering are not expected.

Automated Tk scaling checks exercise 100%/150% equivalent font/layout scaling.
Actual employee-device Windows DPI settings and native-dialog operation should
still receive a final visual review. Windows screenshots permit review of the
CI desktop; they do not establish behavior on every monitor/theme configuration.
