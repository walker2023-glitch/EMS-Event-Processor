# MVP implementation and verification checklist

Source: every section of `plan/1.1_ems_event_processor_mvp.md` (read before coding).

- [x] Inspect initial tree and Git status: plan only; clean working tree.
- [x] Identify runtime, dependencies, structure, packaging: Python 3.11+, Tkinter,
  openpyxl, xlrd; src layout; Windows PyInstaller build and CI artifact.
- [x] Sections 1–4: local standalone application, user stories and scope boundaries.
- [x] Section 5: FR-1–20 implemented and exercised.
- [x] Section 6: responsiveness, privacy, keyboard access, record isolation, local log.
- [x] Section 7: AC-1–9 individually reviewed with evidence.
- [x] Section 8: Events, Equipment Requests, Equipment Summary, Issues schemas,
  conservative normalization, original values and provenance.
- [x] Section 9: independent process_workbook and ProcessingResult.
- [x] Section 10: single-screen choose/process/save/progress/completion/folder flow.
- [x] Sections 11–12: deterministic local processing; no external integrations.
- [ ] Section 13: implement/test dependencies in sequence; Windows build and manual test.
- [x] Section 14: layout, notes, quantity, malformed-record and format mitigations.
- [ ] Section 15: sanitized local validation, executable, pilot/rollback instructions.
- [x] Section 16: unit/integration/UI/error/preservation tests and workbook inspection.
- [x] Section 17: README, user guide, column reference and developer notes.
- [x] Section 18: document smallest assumptions without inventing source data.
- [x] Section 19: validate actual referenced Setup Worksheet when available.

The Setup Worksheet was subsequently supplied and inspected. Its 463 occurrences
and 1,621 service requests were independently audited against all generated
summary totals; see `verification.md`. Sanitized fixtures use invented data only.
Sections 13 and 15 remain partially verified until manual employee-device
review and EMS staff acceptance/pilot complete. Windows executable building and
startup/shutdown now pass in CI. All nine ACs pass in the tested Windows/Linux
runtimes; automated checks and manual rollout checks are distinguished in the
verification record.
