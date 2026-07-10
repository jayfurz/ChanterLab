# PROD-05: Privacy-Conscious Observability And Versioned PWA

Status: observability blocked on owner data decision; PWA is ready for asset
versioning/compatibility design now that `CAT-02` is complete. Priority: P2.

Dependencies: release identity, security policy, rights/privacy policy.

Owned files: approved diagnostics/telemetry adapter, service worker, cache tests,
offline UI.

## Goal

See operational failures and support intentional offline practice without
collecting sensitive audio or serving incompatible mixed versions.

## Steps

1. Propose minimal events for load, score parse, audio lifecycle, report intake,
   catalog release, and no-result searches; approve fields/vendor/retention.
2. Keep microphone samples and recordings local by default.
3. Add local diagnostic export before remote telemetry where sufficient.
4. Version application assets and catalog releases independently with a declared
   compatibility matrix.
5. Cache an explicit offline set and make catalog availability visible.
6. Test upgrade, interrupted install, stale cache, rollback, storage pressure,
   and offline deletion.

## Acceptance

No unapproved data leaves the browser; diagnostics identify release/app versions;
offline never mixes incompatible manifest/MusicXML/app assets; rollback purges or
selects compatible caches; users can inspect/clear stored data; PWA failures do
not block ordinary online use.
