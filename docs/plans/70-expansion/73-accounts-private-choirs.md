# EXPAND-03: Accounts And Private Choir Access

Status: blocked on proven upload/cross-device need. Priority: P3.

Dependencies: approved identity/privacy architecture and working private uploads.

Owned files: authentication/authorization, tenant model, migration, security tests.

## Goal

Add accounts only for durable private repertoire, cross-device practice state,
and explicitly invited choir access.

## Scope

Least-privilege roles; user/choir ownership; invitations/revocation; score access;
practice-history privacy; export/delete; session security; audit; recovery; tenant
isolation. Public search/sharing and social profiles are excluded.

## Acceptance

Authorization is server-enforced and tenant-tested; invitation/revocation takes
effect promptly; singers cannot inspect others' detailed history by default;
account and choir deletion are complete; migration/rollback and incident response
are documented; anonymous current app remains usable if product policy requires.

