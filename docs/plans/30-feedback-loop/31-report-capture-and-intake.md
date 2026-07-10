# LOOP-01: Report Capture And Intake

Status: blocked on owner storage decision. Priority: P1.

Dependencies: immutable score/release IDs and trust schema. Blocks: reviewer UI.

Owned files: report schema, current-piece/transport capture, report UI, chosen
intake adapter, tests. Conflicts with library provenance UI; schedule integration.

## Goal

Let a singer report the current transcription issue with enough automatic
context to reproduce it.

## Required Payload

Report ID, score/source/release/parser IDs, measure, selected voice, playback
position, issue category, user description, source PDF reference, app version,
and optional local screenshot/diagnostics under explicit consent.

## Steps

1. Present local-export and service-backed designs, privacy, spam, and ops costs.
2. Record owner decision and freeze schema/retention rules.
3. Add a restrained `Report transcription issue` command near the PDF control.
4. Capture context without requiring the singer to transcribe identifiers.
5. Validate and acknowledge submission; support offline/local failure safely.
6. Add desktop/mobile/keyboard/screen-reader browser coverage.

## Non-Goals

No general support chat, public comments, automatic correction, account system,
or microphone upload.

## Acceptance

Reports point to immutable content; categories cover pitch/rhythm/note/voice/
lyric/divisi/layout/metadata; sensitive fields require consent; duplicate clicks
are idempotent; failed intake never loses an exportable report.

