# ChanterLab — Market Research: From the Orthodox Niche to the Choir-Practice Market

*2026-07-11 · GitHub issue #68 · companion to [BUSINESS-MODEL-2026-07.md](BUSINESS-MODEL-2026-07.md) — this memo **extends** that one and does not repeat it. All web claims cite a URL with access date; every URL below was accessed 2026-07-11 unless noted. Where evidence is thin, the memo says so instead of padding.*

**What the first memo already established** (see its §2–§7, not re-argued here): the rehearsal-track landscape (Cyberbass, ChoraLine, John Fletcher, Choir Player, RehearsalMix, Choralia, Soundslice, MuseScore, My Choral Coach, SingSharp, forScore, Newzik) with pricing; the Orthodox beachhead (~2,900 parishes) vs the ~200k US church-choir market; the OMR-ingestion moat and its born-digital caveat; the private-by-default rights model; pricing candidates anchored on My Choral Coach's $175–495/yr choir license.

**What this memo adds:** (1) competitors the first pass missed — including the single closest one, Harmony Helper; (2) a segment-by-segment map with *who the buyer is* in each (denominational church choirs, school/collegiate, community, barbershop, individual singers, directors); (3) the differentiator set as it actually stands today (browser-only, no account, microtonal/multi-tradition); (4) monetization options that are *realistic under GPLv3 and a single maintainer*; (5) three sequenced go-to-market experiments cheap enough for one person; (6) open questions.

---

## 1. Competitive landscape — corrections and additions

### 1a. Harmony Helper — the closest competitor, and the first memo missed it

Harmony Helper is a mobile app "made by singers for singers": real-time pitch feedback against your vocal line, per-part volume isolation, director-shareable songbooks — i.e., the same core loop as ChanterLab's training app. Consumer pricing per its App Store listing: **14-day free trial, $8/mo or $76/yr**, with group pricing ([apps.apple.com](https://apps.apple.com/us/app/harmony-helper/id1283704743), accessed 2026-07-11 via store listing).

The strategically interesting part: `harmonyhelper.com` now 301-redirects to **RWS Global** (a live-entertainment production company), which describes Harmony Helper as "RWS Global's proprietary technology… exclusively available to RWS Global partners" — i.e., the product has pivoted toward B2B theatrical/education partners rather than open consumer growth ([rwsglobal.com/harmony-helper](https://www.rwsglobal.com/harmony-helper), accessed 2026-07-11). It also distributes into the worship market through a **PraiseCharts** partnership ("practice sheet music alongside Harmony Helper," [praisecharts.com/harmony-helper](https://www.praisecharts.com/harmony-helper), accessed 2026-07-11).

**Read:** Harmony Helper validates the exact product thesis (singers will pay ~$76/yr for per-part practice with mic feedback) *and* its pivot away from direct consumer growth leaves the open-web, self-serve version of that product substantially unoccupied. It does not appear to offer user PDF ingestion (director songbooks are its content model), it requires an app install and account, and it is not microtonal. Treat it as the #1 product to track; a periodic check of its store listing and RWS positioning belongs in any quarterly review.

### 1b. Music-education platforms (the school segment's incumbents)

- **MakeMusic Cloud** (formerly SmartMusic): assessment-based practice for school ensembles; **$59.99/yr** individual All Access, custom pricing for schools ([makemusic.com/pricing](https://www.makemusic.com/pricing/), accessed 2026-07-11). Instrument-ensemble-centric; voice is not its core; entrenched in band programs.
- **Sight Reading Factory**: generated sight-singing/reading exercises; **$45/yr educator**, student accounts **as low as $3/student/yr at 100+ seats** ([sightreadingfactory.com/pricing](https://www.sightreadingfactory.com/pricing), [support article](https://sightreadingfactory.freshdesk.com/support/solutions/articles/27000011865-bulk-district-pricing-information), accessed 2026-07-11). This is the price band school choral budgets actually pay per student — useful anchor: **school per-seat prices are $3–5/yr, not $40**.

**Read:** the school market pays reliably but at very low per-seat prices, through procurement, with rostering/gradebook expectations (and FERPA/COPPA diligence) that a single maintainer should not take on early. Browser-only/no-install is a genuine advantage there (Chromebook fleets), but the account-less design cuts both ways: no accounts means no teacher dashboard, which is what the buyer pays for. Defer this segment; revisit only after choir-license traction.

### 1c. Individual-singer apps (the consumer price band)

- **Yousician** (singing track): **$7.49/mo billed annually** (Premium), $19.99 month-to-month; AI vocal coach with real-time pitch feedback ([support.yousician.com](https://support.yousician.com/hc/en-us/articles/115005189525-Premium-membership-options-in-Yousician), [account.yousician.com/plans](https://account.yousician.com/plans), accessed 2026-07-11).
- **Riyaz** — the only found competitor doing **microtonal, mic-scored practice** (Carnatic/Hindustani/pop): free tier ~8 min practice/day, premium listed from **$4.99/mo** ([riyazapp.com](https://riyazapp.com/), [Google Play listing](https://play.google.com/store/apps/details?id=com.musicmuni.riyaz), accessed 2026-07-11; the company's own [pricing-policy page](https://riyazapp.com/pricing-policy/) lists only INR 50–20,000 transaction ranges, so treat the USD figure as store-listing data). Riyaz is course/lesson-based (45+ raags with bandishes) — it teaches repertoire it curates; it does not ingest scores and has no choir/ensemble concept.

**Read:** the consumer singing-app band is **$50–90/yr**, consistent with the first memo's Soundslice/MuseScore anchors. For ChanterLab's new raga mode, Riyaz is simultaneously proof of demand (a funded company exists on microtonal pitch practice — [yourstory.com profile](https://yourstory.com/weekender/music-learning-app-riyaz-hits-right-note-self-learners-technology), accessed 2026-07-11) and a warning: content/pedagogy, not pitch detection, is their moat. ChanterLab's raga mode should stay a *practice utility* (drone + scale + feedback), not compete on curriculum.

### 1d. Barbershop — a paying practice-track economy the first memo skipped entirely

Barbershop is the one amateur-singing culture where **paying for per-part practice materials is already universal norm**:

- The **Barbershop Harmony Society (BHS)** shop sells single-song digital learning-track sets at **~$36/song** (e.g., TTBB titles; [shop.barbershop.org/audio/learning-tracks](https://shop.barbershop.org/audio/learning-tracks/), accessed 2026-07-11).
- A cottage industry of custom track makers exists: Kim Kraut (1,450+ tracks, "all parts" singles at **$1.99**, custom tracks "in as little as 48 hours"; [kimkraut.com/learning-tracks](https://www.kimkraut.com/learning-tracks/), accessed 2026-07-11), Tracks by Jen (full sets: four-part, part-alone, part-predominant, part-missing; [tracksbyjen.com](https://www.tracksbyjen.com/)), Julien Neel, and a BHS-maintained directory ([barbershop.org custom page](https://www.barbershop.org/music/arrangements-and-learning-tracks/custom-arrangements-and-learning-tracks), accessed 2026-07-11).
- **barbershoptags.com** hosts **6,978 freely downloadable tags**, many with learning tracks and sheet music, community-contributed ([barbershoptags.com](https://www.barbershoptags.com/), accessed 2026-07-11) — a ready-made culture of free short-form practice content.

Size honestly: BHS reports **~14,000 members in the US/Canada, ~660 choruses, ~930 registered quartets (plus ~1,000 unregistered), 70,000+ barbershop singers worldwide** ([barbershop.org fact sheet](https://www.barbershop.org/fact-sheet-barbershop-harmony-society), accessed 2026-07-11). Sweet Adelines International **renamed itself SingUnited International in 2026** ([singunited.org](https://singunited.org/), accessed 2026-07-11); reported membership figures conflict across sources (~15,000–23,000 members, 500–600 choruses, ~1,200 quartets per [Wikipedia](https://en.wikipedia.org/wiki/Sweet_Adelines_International), accessed 2026-07-11 — treat as approximate). BHS membership has declined from ~38,000 in the 1970s and dues keep rising ([barbershop.org dues notice](https://www.barbershop.org/dues-2024), accessed 2026-07-11).

**Read:** small, aging, but *dense, online, evangelistic, a cappella (no accompaniment needed), practice-track-native, and already paying per song*. Every quartet needs exactly what ChanterLab does: sing your part while hearing the others, with honest feedback. This is the cheapest possible test of "does ChanterLab work outside church music" — see Experiment 1 (§5).

### 1e. Adjacent evidence: choir directors already pay for choir SaaS

Not competitors, but proof of the director-as-buyer budget:

- **Chorus Connection** (choir management): tiered flat plans **$24–$120/mo**, self-described as **$6–20 per singer per year** ([chorusconnection.com/pricing](https://www.chorusconnection.com/pricing), [their budgeting guide](https://blog.chorusconnection.com/how-to-budget-for-choir-management-software), [SoftwareAdvice profile](https://www.softwareadvice.com/membership-management/chorus-connection-profile/), accessed 2026-07-11).
- **Choir Genius**: **$22 / $44 / $88 per month** ($264–$1,056/yr) flat, unlimited members ([choirgenius.com/pricing](https://www.choirgenius.com/pricing/), accessed 2026-07-11).

**Read:** organized choirs demonstrably sustain **$250–1,000/yr** software line items — for *administration*. A practice tool priced at the first memo's ~$149/yr flat choir license sits comfortably inside an already-existing budget category, and below the closest practice comparable (My Choral Coach $175–495/yr, cited in the first memo).

### 1f. Consolidated positioning (delta rows only; first-memo rows unchanged)

| Product | Price | Install/account | Mic scoring | Own repertoire in | Microtonal | Choir-aware |
|---|---|---|---|---|---|---|
| **Harmony Helper** | $8/mo, $76/yr (store listing) | App + account | **Yes** | Director songbooks (no PDF OMR found) | No | **Yes** |
| **MakeMusic Cloud** | $59.99/yr indiv. | Account, web | Yes (assessment) | Compose/import (teacher-driven) | No | Ensemble-class |
| **Sight Reading Factory** | $45/yr educator; ~$3/seat/yr bulk | Account, web | Sight-singing assessment | Generated exercises only | No | Classroom |
| **Yousician** | ~$90/yr annual-billed | App + account | Yes | No | No | No |
| **Riyaz** | from ~$4.99/mo | App + account | **Yes** | No (curated courses) | **Yes** | No |
| **BHS learning tracks** | ~$36/song | Downloads | No | No (fixed catalog) | No | Quartet/chorus |
| **ChanterLab today** | Free (GPLv3) | **None — browser URL** | **Yes** | OMR pipeline (bulk, born-digital) | **Yes (Byzantine + raga)** | **Yes** |

No product in either memo's sweep combines mic scoring + own-repertoire ingestion + microtonal support + zero-install browser delivery. The honest counterweight: several of those combinations are absent because the *market for them individually* is small (microtonal) or because the feature is monetization-hostile (no accounts) — see §3.

---

## 2. Segments — who they are, who pays, what they pay today

### 2a. Church choirs, across denominations

Overall frame (first memo): ~200k of ~250k US choruses are church choirs; congregations with choirs fell from >50% (1998) to ~40% (2018-19). Per-denomination texture added here:

| Tradition | Scale (US) | Choir culture | Practice-tool spend today | Fit notes |
|---|---|---|---|---|
| Catholic | **19,405 congregations** ([US Religion Census Catholic presentation](https://www.usreligioncensus.org/sites/default/files/2023-05/RRA%20Catholic%20presentation.pdf), accessed 2026-07-11) | Parish choirs common; paid music directors in larger parishes | Mostly $0; octavo purchases | Large; consolidation trend; Latin/chant repertoire partially PD |
| Mainline Protestant (Episcopal, Lutheran, Presbyterian, UMC) | UMC alone lost ~7,631 churches (25%) to disaffiliation 2019–23 ([UM News](https://www.umnews.org/en/news/disaffiliations-approved-by-annual-conferences), [Lewis Center](https://www.churchleadership.com/leading-ideas/twenty-five-percent-of-churches-disaffiliated-from-the-united-methodist-church/), accessed 2026-07-11) — a volatile but choir-strong tradition | Strongest surviving choir programs; RSCM affiliation in Episcopal parishes (RSCM claims 9,000+ affiliated programs worldwide; its US branch is overwhelmingly Episcopal — [rscmamerica.org](https://www.rscmamerica.org/), accessed 2026-07-11; denominational skew is community consensus, not audited data) | RSCM Choral Coach exists at £29.99/yr (first memo) | The most natural first non-Orthodox church segment: SATB octavos as born-digital PDFs, trained directors, real budgets |
| Evangelical / non-denominational | Largest congregation count | Worship-band dominant, choir declining | Already pays RehearsalMix $14.95/mo (first memo) | Served by MultiTracks/PraiseCharts ecosystem — crowded; skip |
| Orthodox | ~2,909 parishes (first memo) | Chant + choir; owner's network | ~$0 | Beachhead; not the revenue base |
| LDS | Ward choirs are standard practice | Volunteer-led, hymnal-based | $0 (church provides materials) | Hymnal largely church-published; no verified congregation-level data gathered — flagged, not sized |

**Buyer:** the music director/organist, spending either personal money or a small parish music budget. Evidence from Chorus Connection/Choir Genius (§1e) says the budget exists at $250–1,000/yr for organized ensembles; small parish choirs are closer to $0–200/yr discretionary. **Thin-evidence flag:** no survey of church-choir software budgets was found; the anchors above are vendor price points, not measured spend.

### 2b. School and collegiate choirs

~38,000 school choruses (first memo). **24% of the US high-school class of 2013 took at least a year of band/choir/orchestra** ([Elpus & Abril 2019, Journal of Research in Music Education](https://journals.sagepub.com/doi/10.1177/0022429419862837), accessed 2026-07-11) — participation is broad, but the buyer is a school, procurement is seasonal, per-seat prices are $3–5/yr (Sight Reading Factory, §1b), and rostering/privacy compliance is table stakes. Collegiate choirs (ACDA's ~22k directors include them; first memo) rehearse intensively but expect free tools. **Recommendation: not a first-year segment for a single maintainer.** No-install browser delivery on Chromebooks keeps the door open later.

### 2c. Community choirs

~12,000 US community/professional choruses; member dues $50–130/season (first memo). Buyer is a volunteer board or director; Chorus Connection's price ladder was built for exactly this segment (§1e). Good second-ring segment for the flat choir license; reachable through Chorus America/ACDA channels and the management-SaaS user base.

### 2d. Barbershop (quartets + choruses)

Sized in §1d (~30–40k organized singers in North America across BHS + SingUnited + unaffiliated). The distinctive facts: practice tracks are the *default* learning mode; singers pay per song today ($1.99–$36); repertoire is short (tags) or licensed arrangements; everything is a cappella (no accompaniment synthesis needed); community is tight and extremely online (barbershoptags.com, Facebook groups, r/barbershop). Weakness: shrinking and older demographic; licensed-arrangement copyright is a live issue for uploads (BHS sells the arrangements). **Use as validation wedge, not as the revenue market** — Experiment 1.

### 2e. Individual singers

54M+ Americans sing in choruses — 2019 data; **no newer national participation study was found** (the current Chorus America study remains the 2019 "Singing for a Lifetime" — [chorusamerica.org](https://chorusamerica.org/publications/research-reports/chorus-impact-study), accessed 2026-07-11; treat 54M as dated). What individuals demonstrably pay: $50–90/yr for app-guided practice (§1c). This is where ChanterLab's zero-friction entry (URL → sing in 30 seconds) is strongest, and where the first memo's ~$40/yr Individual Pro sits well against Yousician/Riyaz/Soundslice.

### 2f. Choir directors as the buyer (cross-cutting)

Every segment above except individuals purchases through one person: the director. The director's own tools budget is proven (§1e); their pain is *members who come to rehearsal not knowing their parts* — which is what every learning-track product monetizes. Directors are reachable cheaply: ACDA/ChoralNet, denominational music associations (first memo's PSALM/NFGOCM for Orthodox; RSCM America for Episcopal), BHS/SingUnited district channels, and the Chorus Connection/Choir Genius content-marketing playbook (their blogs rank for every "how to run a choir" query). **Evidence gap flagged:** no public data on director willingness-to-pay for *practice* (vs admin) software beyond My Choral Coach's survival at $175–495/yr; the concierge pilot (Experiment 2) is designed to produce that data first-hand.

---

## 3. Differentiators vs weaknesses — the honest table

| ChanterLab property | Where it wins | Where it costs |
|---|---|---|
| **Browser-only, zero install** | Works on any phone/Chromebook/desktop; a director can text a URL to the whole choir; no app-store gatekeeping or 30% fee | iOS Safari audio/mic quirks are ChanterLab's to absorb (see docs/IOS-AUDIO-TEST.md); no store-based discovery channel |
| **No account required** | 30-second time-to-first-note; no password support burden; nothing to breach; easiest possible "try it" ask | No saved progress across devices, no director dashboards/rosters, no retention analytics, no email list — i.e., **the features choirs would pay for require introducing optional accounts eventually** |
| **Free + GPLv3** | Trust (esp. church/Orthodox and educator communities); contributions possible; no vendor-lock objection; forkability reassures institutions | Anchors expected price at $0; anyone may legally redeploy the app; monetization must come from service, hosting, or sold exceptions (§4), not from withholding code |
| **Microtonal + multi-tradition (Byzantine scales, Hindustani raga, Western SATB)** | Literally no competitor found covers all three; each tradition is an underserved community that shares links; pitch engine generalizes | Each tradition is individually small; risk of breadth-without-depth — Riyaz shows content/pedagogy is what retains microtonal learners (§1c) |
| **Bulk OMR ingestion (born-digital)** | First memo §4 — the combination moat | Scans/photocopies still out of scope until M4 correction UI |
| **Single maintainer** | Costs ~$0 to run; total product coherence; can pivot in a weekend | Bus factor 1; no capacity for sales cycles, procurement, SLAs, or compliance regimes; every monetization idea must be judged on *support burden per dollar* |

---

## 4. Monetization under GPLv3 + single-maintainer reality

What the license actually permits, with sources:

1. **Charging money is fully GPL-compatible.** The GPL permits selling copies and charging for services/support; "free" is about freedom, not price ([GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html), accessed 2026-07-11).
2. **The browser app's JS is conveyed** to users, so whatever ChanterLab serves must remain source-available under GPLv3 — a "secret premium features" tier of the *client* is not available without relicensing. Server-side services (storage, sync, choir rosters, recording retention) are separate works and can be the paid layer.
3. **Selling exceptions is available while the owner holds all copyright.** The copyright holder may release under GPL and separately sell different terms (e.g., a white-label license to a publisher or denominational body); only the copyright holder can do this, so **accepting outside contributions without a CLA/assignment forecloses it** ([gnu.org/philosophy/selling-exceptions](https://www.gnu.org/philosophy/selling-exceptions.html), accessed 2026-07-11).
4. **Donations alone are a poor plan.** In the 2024 open-source funding survey coverage, ~60% of maintainers are unpaid and only about a quarter receive any income from their projects ([The Register on the Tidelift survey](https://www.theregister.com/2024/09/18/open_source_maintainers_underpaid/), [2024 Open Source Software Funding Report](https://opensourcefundingsurvey2024.com/), accessed 2026-07-11). Outliers exist (Caleb Porzio reached $100k/yr on GitHub Sponsors with a sponsorware strategy — [calebporzio.com](https://calebporzio.com/i-just-hit-dollar-100000yr-on-github-sponsors-heres-how-i-did-it), accessed 2026-07-11), but they are developer-audience projects. ChanterLab's audience is singers, not developers; expect donation income in the hundreds-per-year range absent deliberate effort. Choralia/Cyberbass (first memo) survive on donations *as hobbies* — that is the honest comparison.

**Ranked options for this product, this license, this capacity:**

| Option | GPL-clean? | Single-maintainer load | Verdict |
|---|---|---|---|
| **Hosted choir service** (optional director account: private uploads, roster/share links, assignment tracking, recording retention) at ~$99–149/yr flat | Yes — pay for the service, client stays GPL | Medium (support email, Stripe, backups) | **Primary.** Matches first memo's Structure 1; the buyer (§2f) and budget (§1e) exist |
| **Individual Pro service tier** (~$40/yr: cloud-saved progress/recordings, personal uploads) | Yes | Low-medium | **Secondary**, same infrastructure |
| **Donations rail** (GitHub Sponsors/Ko-fi + in-app link) | Yes | Near zero | Turn on regardless; expect little (see #4 above); it also functions as a price-sensitivity probe |
| **Sold exceptions / white-label** (publisher, denomination, or a BHS-style body embeds the engine) | Yes, while sole copyright holder | Low frequency, high per-deal effort | Opportunistic; keep copyright unified (CLA) to preserve it |
| Per-seat school SaaS | Yes | High (procurement, FERPA/COPPA, rostering) | **Defer** (§2b) |
| Ads / data | — | — | **No.** Destroys the trust positioning that is the moat's other half |

---

## 5. Recommendation — three sequenced experiments (one-person cheap)

Each has a cost cap, a success metric, and a kill criterion. They are ordered so each produces the data the next one needs, and they reuse the assets that already exist (working app, OMR pipeline, recording feature from #67).

### Experiment 1 (weeks 0–4): Barbershop tag wedge — does ChanterLab work outside church music?
- **Do:** load 20–50 *public-domain* tags (classic PD hymn/folk tags; verify per-tag status — barbershoptags.com content is community-contributed with mixed rights, so select PD-only or re-typeset; [barbershoptags.com](https://www.barbershoptags.com/), accessed 2026-07-11) as a `/tags/` practice collection. Post twice, honestly ("free browser tool, sing your part against the other three, it scores you — no app, no account"), in r/barbershop and 1–2 barbershop Facebook groups; ask one quartet for a video clip using #67's recording feature.
- **Why first:** the one segment that already pays per-song for exactly this practice mode (§1d), a cappella (zero accompaniment work), tiny content lift, tight community = fast signal, and it tests general-market appeal with zero sales motion.
- **Cost:** ≤2 weekends + $0 cash. **Success:** ≥200 unique practice sessions and ≥20% of week-1 users returning in week 2 (needs a privacy-respecting counter — see Open Questions). **Kill:** <50 sessions after both posts → barbershop is not the wedge; the finding still transfers (the SATB loop was exercised by outsiders).

### Experiment 2 (weeks 3–8, overlaps): Director concierge pilot — will anyone pay?
- **Do:** recruit 5 directors across ≥3 traditions (1 Orthodox from the owner's network, 1–2 Episcopal/Lutheran via RSCM-adjacent contacts, 1 community choir, 1 barbershop chorus director from Experiment 1). Owner personally ingests their born-digital PDF exports (the pipeline exists), hands each a private practice link for their choir, and after two weeks asks the price question directly: *"would you pay $149/yr for this to keep working, with you in control of uploads?"*
- **Why:** this is the first memo's days-30–60 step, sharpened into a pay/no-pay measurement; it produces the willingness-to-pay data that does not exist publicly (§2f), and it stress-tests ingestion on non-Orthodox repertoire.
- **Cost:** ~2–4 hrs/director. **Success:** ≥2 of 5 verbal yes at $99–149/yr (or actual prepayment — better). **Kill:** 0 of 5 yes *and* lukewarm usage → the paid layer is wrong; fall back to patronage positioning and re-examine Individual Pro instead.

### Experiment 3 (weeks 6–12): Patronage rail + decision gate
- **Do:** turn on GitHub Sponsors/Ko-fi and an unobtrusive in-app "ChanterLab is free software — keep it running" link shown after a completed practice session. Instrument (aggregate, no-account) counts only. At week 12, hold the decision meeting with three numbers on the table: Experiment 1 sessions/retention, Experiment 2 yes-rate, donation conversion.
- **Decision rule:** E2 ≥2 yes → build the hosted choir service (optional director accounts) as the 2026-Q4 monetization line. E2 fails but E1 succeeds and donations > $50/mo → stay free, patronage-funded, and grow the wedge audiences. Both fail → the market data says "useful free tool, no business yet"; keep it a sustainable hobby deliberately rather than accidentally.
- **Cost:** days, not weeks. **Kill (for the donation rail itself):** <$20/mo after 3 months with ≥1,000 monthly sessions — consistent with the base rates in §4 and worth knowing either way.

**Explicitly not recommended now:** school per-seat SaaS (§2b), public score sharing (first memo §5C), paid ads, and any motion requiring sales calls at scale.

---

## 6. Open questions

1. **Measurement without accounts:** what is the privacy-minimum telemetry (aggregate session counter, no PII) the owner is willing to ship? Every experiment above needs it; today there is no way to know if anyone returns.
2. **Barbershop rights:** which tags are actually PD vs BHS-copyrighted arrangements? Needs a per-item check before Experiment 1; the safe floor is re-typeset PD material.
3. **Harmony Helper watch:** does RWS relaunch consumer growth or sunset the store app? Either changes the open-web opportunity materially. Re-check quarterly (store listing + rwsglobal.com).
4. **CLA policy:** if outside contributors arrive, does the owner adopt a CLA/assignment to preserve the sold-exceptions option (§4.3), or deliberately give it up for community goodwill?
5. **Sweet Adelines/SingUnited data:** membership figures are inconsistent (15k–23k); if barbershop becomes more than a wedge, get real numbers from district contacts rather than Wikipedia.
6. **Newer participation data:** the 54M singers figure is 2019; is a post-COVID Chorus America study underway? (None found as of 2026-07-11.)
7. **Raga mode's market:** is it a differentiator for diaspora choirs/bhajan groups (ensemble!) or an individual-learner feature competing with Riyaz's curriculum? No evidence gathered yet; do not invest beyond the current lane until one organic user cohort appears.
8. **Accounts, eventually:** the paid choir service requires optional director accounts. What is the minimum account system (magic-link email, no passwords?) compatible with the no-account ethos for singers?

---

### Sources added by this memo (all accessed 2026-07-11)

Harmony Helper ([App Store](https://apps.apple.com/us/app/harmony-helper/id1283704743), [RWS Global](https://www.rwsglobal.com/harmony-helper), [PraiseCharts](https://www.praisecharts.com/harmony-helper)) · MakeMusic Cloud ([pricing](https://www.makemusic.com/pricing/)) · Sight Reading Factory ([pricing](https://www.sightreadingfactory.com/pricing), [bulk pricing](https://sightreadingfactory.freshdesk.com/support/solutions/articles/27000011865-bulk-district-pricing-information)) · Yousician ([plans](https://support.yousician.com/hc/en-us/articles/115005189525-Premium-membership-options-in-Yousician)) · Riyaz ([site](https://riyazapp.com/), [Play listing](https://play.google.com/store/apps/details?id=com.musicmuni.riyaz), [pricing policy](https://riyazapp.com/pricing-policy/), [YourStory](https://yourstory.com/weekender/music-learning-app-riyaz-hits-right-note-self-learners-technology)) · BHS ([fact sheet](https://www.barbershop.org/fact-sheet-barbershop-harmony-society), [learning tracks shop](https://shop.barbershop.org/audio/learning-tracks/), [custom tracks](https://www.barbershop.org/music/arrangements-and-learning-tracks/custom-arrangements-and-learning-tracks), [dues](https://www.barbershop.org/dues-2024)) · Kim Kraut ([learning tracks](https://www.kimkraut.com/learning-tracks/)) · Tracks by Jen ([site](https://www.tracksbyjen.com/)) · barbershoptags.com ([site](https://www.barbershoptags.com/)) · SingUnited ([site](https://singunited.org/), [Wikipedia](https://en.wikipedia.org/wiki/Sweet_Adelines_International)) · Chorus Connection ([pricing](https://www.chorusconnection.com/pricing), [budget guide](https://blog.chorusconnection.com/how-to-budget-for-choir-management-software), [SoftwareAdvice](https://www.softwareadvice.com/membership-management/chorus-connection-profile/)) · Choir Genius ([pricing](https://www.choirgenius.com/pricing/)) · Chorus America ([Impact Study](https://chorusamerica.org/publications/research-reports/chorus-impact-study)) · US Religion Census Catholic ([presentation](https://www.usreligioncensus.org/sites/default/files/2023-05/RRA%20Catholic%20presentation.pdf)) · UMC disaffiliation ([UM News](https://www.umnews.org/en/news/disaffiliations-approved-by-annual-conferences), [Lewis Center](https://www.churchleadership.com/leading-ideas/twenty-five-percent-of-churches-disaffiliated-from-the-united-methodist-church/)) · RSCM America ([site](https://www.rscmamerica.org/)) · Elpus & Abril 2019 ([JRME](https://journals.sagepub.com/doi/10.1177/0022429419862837)) · GNU ([GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html), [selling exceptions](https://www.gnu.org/philosophy/selling-exceptions.html)) · maintainer funding ([The Register](https://www.theregister.com/2024/09/18/open_source_maintainers_underpaid/), [2024 funding report](https://opensourcefundingsurvey2024.com/), [Caleb Porzio](https://calebporzio.com/i-just-hit-dollar-100000yr-on-github-sponsors-heres-how-i-did-it)).
