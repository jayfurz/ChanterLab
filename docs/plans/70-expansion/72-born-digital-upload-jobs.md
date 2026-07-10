# EXPAND-02: Born-Digital Upload Jobs And Correction

Status: blocked on `EXPAND-01`. Priority: P3.

Dependencies: approved backend, parser release contract, trust ledger, reviewer
workbench, correction lifecycle.

Owned files: upload/job service, private artifact storage, status UI, integration
tests. Do not broaden parser to scans.

## Goal

Accept authorized born-digital PDFs, process them as immutable jobs, expose
honest confidence/review status, and let the uploader correct or delete them.

## Lifecycle

Upload and validate -> hash/scan/isolate -> extract with parser release -> stage
private catalog candidate -> confidence gate -> user/reviewer correction ->
private promotion -> practice -> retention/deletion.

## Acceptance

Jobs are idempotent/resumable; malicious/unsupported inputs fail safely; source
and output never become public by default; progress/errors are understandable;
every score names parser/input identity; deletion covers primary, derived, cache,
and scheduled backup expiry; correction and rollback are available.

