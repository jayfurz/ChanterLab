# PROD-04: Accessibility, Responsive, And Performance Gates

Status: ready after `BASE-02` frontend gate. Priority: P2.

Dependencies: stable browser smoke and representative long scores.

Owned files: accessibility tests, responsive screenshot suite, targeted UI fixes,
performance harnesses.

## Goal

Make the practice and library surfaces usable with keyboard, assistive
technology, zoom, small screens, and long content while preventing regressions.

## Scope

Keyboard/focus/modal behavior; accessible names/states; screen-reader landmarks;
contrast; reduced motion; 200%/400% zoom; dynamic text fit; 360/390 phone and
desktop screenshots; nonblank canvases; touch targets; library virtualization;
long-score parse/render/scroll; memory and interaction budgets.

## Acceptance

Automated audit has no unwaived serious issue; complete practice loop is keyboard
usable; dialogs trap/restore focus; no overlap/clipping at target viewports/zoom;
score/scope remain inspectable; 3,000+ library and long scores meet recorded
budgets; real-device spot checks accompany automated evidence.

