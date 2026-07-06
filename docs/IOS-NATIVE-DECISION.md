# ChanterLab — Native iOS App: Build vs. Web-Only (decision memo)

*2026-07-05 · prepared for GitHub issue #87, framed by #75, evidenced by #74's three-session field
campaign and `docs/design/IOS-AUDIO-SESSION-ANALYSIS.md` · pricing angles from
`docs/BUSINESS-MODEL-2026-07.md` · decision is the owner's.*

**Recommendation: stay web-only (Option A).** Revisit only on the tripwires in §4.

---

## 1. What the web platform now delivers on iOS

Three owner field sessions (issue #74, closed 2026-07-05) fixed every audio defect that was fixable
from the web: silence-unless-mic-on (session/category management + silent-unlock element), the
📞 call-icon sticking after mic-off (explicit `navigator.audioSession.type` management), and the
volume-rocker floor (in-app volume slider reaches true zero in every mode). The app is also
installable as a PWA today — manifest + icons shipped in 0ce6f15 (issue #72), standalone display,
home-screen icon, resizes to a real desktop layout above 1000px. No service worker yet, so there is
no offline cache — but that is a web-completable gap, not a native-only capability (§2c).

**The one residual: mic+speaker crackle.** Root-caused to WebKit source (not guesswork): iOS builds
its voice-processing unit (VPIO) whenever `echoCancellation: true`, and any active microphone capture
forces the `AVAudioSession` into `PlayAndRecord` + call mode regardless of EC. VPIO changes the
hardware's sample rate/buffering out from under our `AudioContext`, which is what glitches. This is
**proven unfixable from the web** — sample-rate matching, buffer-size levers, and context recreation
were all tried and field-tested; none reach VPIO's internals (`docs/design/IOS-AUDIO-SESSION-ANALYSIS.md`
§1, §3-F2/F3). We cannot simply turn EC off to dodge VPIO in speaker mode either: EC exists specifically
to keep the accompaniment audio out of the microphone when the phone is out loud, and without it the
accompaniment leaks into the pitch tracker and scorer — corrupting the product's core loop (§3-F3).

**How degraded is this, really?** Narrower than "the iOS experience has a bug" suggests:
- **Headphones mode is the shipped default** — `training-prototype/index.html` ships the `hpMode`
  checkbox pre-checked. A user hits the crackle only by *actively switching off* the default, then
  choosing speaker over headphones, with the mic on at the same time.
- Headphones are also the objectively better practice setup for this product regardless of the bug —
  no risk of the choir accompaniment bleeding into the mic, no risk of disturbing a room, closer
  vocal isolation for the pitch trace. The crackle mitigation and the standing UX recommendation are
  the same sentence.
- The app now says so honestly: the Sound-tab copy steers speaker-mode users to headphones rather
  than hiding the tradeoff, and field-confirms clean.
- Net: the defect lives entirely inside an already-non-default, already-discouraged configuration.
  It has not been instrumented at real-user scale yet (see tripwire #1) — the claim above is "narrow
  by construction," not "measured to be rare."

## 2. What native/hybrid would actually buy — and cost

**(a) The VPIO fix.** A true native-audio bridge (AVAudioEngine driving playback and capture,
configured and owned by our Swift code instead of WebKit's) could hold its own session/echo path and
side-step this failure class entirely. This is the one benefit no web mitigation can match. Important
caveat from #75's frame, reconfirmed here: **a plain WKWebView wrapper fixes nothing** — it runs the
same WebKit WebAudio engine underneath, so it inherits the identical VPIO behavior. Only a genuine
native-audio bridge (rebuild transport/capture in Swift, bridge state to the existing JS/WASM UI)
removes the defect — that is a second real audio engine, not a wrapper.

**(b) App Store distribution + IAP.** Re-checked against the *current* legal landscape, this is worth
less than it would have been two years ago. Since **April 30, 2025**, U.S. developers may include
external payment links in iOS apps with free choice of design, language, and placement, and Apple has
been barred from collecting any commission on those linked-out purchases
([RevenueCat](https://www.revenuecat.com/blog/growth/apple-anti-steering-ruling-monetization-strategy/),
[Neon Commerce](https://www.neonpay.com/blog/apple-app-store-alternative-payment-fees-what-developers-pay-in-2026)).
In December 2025 the Ninth Circuit largely upheld this against Apple while leaving room for Apple to
seek a "reasonable commission" tied specifically to *external-link coordination*, with the framework
still to be set by the district court; Apple's stay request was denied but the Supreme Court granted
cert on the contempt question for its 2026 term
([MacRumors](https://www.macrumors.com/2026/05/21/apple-supreme-court-epic-games-case/),
[TechCrunch](https://techcrunch.com/2026/05/22/apple-says-epic-lawsuit-shouldnt-reshape-app-store-rules-for-all-developers/)).
Practically: **a native app does not need App Store IAP to escape Apple's cut** — it can link out to
the same web checkout a PWA already can, today, at zero commission. What App Store presence *actually*
buys is (i) search discoverability inside the App Store for a parish director looking for "choir
practice app," (ii) an institutional-trust signal, and (iii) satisfying a buyer's procurement policy
that specifically requires an App Store listing — not the choir-license pricing math itself
(`docs/BUSINESS-MODEL-2026-07.md` §6's ~$149/yr flat license, anchored on My Choral Coach's $175–495/yr,
is unaffected either way). The external-link regime is also not fully settled law — building a
distribution strategy around today's favorable rules carries its own reversal risk.

**(c) Background audio / offline.** Asset caching for offline use is a service-worker feature the PWA
can add without going native (currently unshipped, §1) — not a native-only capability. What genuinely
is hard on the web is *audio continuing to process while the screen is locked or Safari is backgrounded*;
iOS aggressively suspends web `AudioContext`s in that state, and only a native `AVAudioSession`
background-audio entitlement reliably survives it.

**Real costs of (a)-(c):** a second full audio engine (AVAudioEngine in Swift, duplicating the
JS/Rust-WASM pitch-detection and scoring stack already shipped and field-tuned across six sprints),
a cross-language bridge to keep native audio state and the existing web UI in sync, and Apple review
cycles — a material velocity tax for a team whose demonstrated edge (Sprints 1-7, same-day
ship-to-`chanterlab.com` repeatedly) is fast, continuous web deployment with no release gate at all.

## 3. Options and recommendation

- **(A) Stay web-only now; revisit at real user scale.** No new engine, no review cycle, keeps the
  team's whole velocity advantage. Ships the one open web-completable item (offline caching via
  service worker) whenever it's prioritized, independent of this decision.
- **(B) Thin App Store presence — PWA wrapper for distribution only, audio unchanged.** Buys App
  Store search placement and satisfies procurement-only buyers. Must be sold to the owner honestly:
  it fixes **zero** technical audio issues (same WebKit engine, §2a) — it is a marketing/procurement
  play, not an engineering one, and still costs a review cycle and a second (thin) codebase to keep in
  sync.
  - Note: current App Store guidelines require a minimum baseline of native functionality/content for
    an app to be accepted at all — a bare wrapper around a website is itself review risk, not just a
    "does nothing" option; the two costs compound.
- **(C) Native-audio hybrid — the full cost.** Only choice that actually fixes the crackle (§2a).
  Justified when the residual defect or a specific customer requirement below is real money, not
  before.

**Recommendation: (A).** ChanterLab is pre-revenue today — the business memo's pricing tiers
(`docs/BUSINESS-MODEL-2026-07.md` §6-§8) are still open owner decisions (#68), not live SKUs — so
there is no paying user base yet to weigh against a second engine's maintenance cost, and no
institutional buyer on record requiring App Store procurement. The residual defect sits inside a
non-default configuration that the product already steers users away from for independent UX
reasons. The App Store's historical strongest argument — escaping Apple's payment cut — is
neutralized by the current external-link regime, which a web-only app already benefits from equally.
Option (B) is close to a null move dressed as a native step, useful only once discoverability or a
procurement requirement (tripwire #2) is real. Option (C)'s cost is only earned once the crackle
(tripwire #1), a paying institutional customer (tripwire #2), or a capture-fidelity need the browser
truly cannot meet (tripwire #3) is measured, not hypothesized.

## 4. Tripwires — reopen this decision when any of these become true

1. **Crackle at scale**: real users hit the mic+speaker-without-headphones combination at a
   meaningful rate despite the steering copy. Not yet instrumented — add a lightweight signal (the
   existing `?audiodebug=1` diagnostics ring is a start, but it's owner-only today) before treating
   "it's a narrow, discouraged mode" as settled at real-user scale.
2. **A choir-license customer requires App Store procurement** — a parish, diocese, or school whose
   purchasing policy mandates an App Store-listed app, tied to actual `docs/BUSINESS-MODEL-2026-07.md`
   §6 choir-license revenue (~$149/yr anchor). This is the one forcing function attached to real money.
3. **Ensemble/multipitch mode (#84) needs capture ChanterLab can't get from `getUserMedia`/WebAudio** —
   the score-informed "one phone in the rehearsal room" mode may need per-part capture fidelity or
   latency beyond what the browser API delivers; if the spike's go/no-go says so, that is an
   AVAudioEngine-specific argument distinct from the crackle fix.
4. **The external-payment-link regime tightens** — if the Ninth Circuit/district-court framework (or
   the pending Supreme Court term) reinstates a real Apple commission specifically on coordinated
   external links, it reprices §2b's "native doesn't need IAP to skip Apple's cut" premise and this
   memo should be re-run against the new rules.
5. **Choir-license revenue actually launches and reaches a scale** where App Store discoverability or
   a second engine's maintenance cost is proportionate to revenue, rather than speculative.
