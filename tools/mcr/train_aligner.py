#!/usr/bin/env python3
"""Score-informed glyph classification: learned-cost alignment decode.

Two inputs — the audio-derived event stream AND the piece's Byzantine notation
(glyph sequence + expected degrees + beats + lyrics word anchors). A GBM scores
arcs ((k',s') -> (k,s)) = "event k' realized slot s', and the next structural
event k realizes slot s"; Viterbi over the score sequence assigns every event
its glyph. Replaces note_align6's hand-tuned costs AND its manual pins with
learned costs (only piece start/end are assumed).

Training positives = consecutive claimed pairs of the chanter-verified
alignment; negatives = slot-shifted / pair-shifted / event-swapped corruptions.
Evaluation = GroupKFold over score lines: the decode that scores line L's
events used a model trained with all of line L's arcs held out.

Usage: train_aligner.py <workdir> [--no-word] [--models-out DIR]
"""
import json, sys, os
from collections import Counter, defaultdict
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcrlib import med_pitch, clean_stream, BREATH_GAP

MPS = 10.3
MAX_DK, MAX_DS = 6, 7          # max event/slot advance per arc (gold max: 4/5)
BAND = 0.15                    # |time-progress - beat-progress| node band
DUR_MARK = {'none': 1.0, 'klasma': 2.0, 'apli': 2.0, 'diple': 3.0}
# path-length normalization: arc cost = -logodds(p) (clipped) so that
# better-than-chance arcs REWARD claiming, plus explicit skip fees — without
# these the min-cost path simply claims as few events as possible.
ODDS_CLIP = 6.0
SKIP_EV, SKIP_SLOT = 1.4, 0.8
MINE_ROUNDS = 0    # hard-negative mining hurt (plausible arcs mislabeled): off

class Bag:
    """bootstrap ensemble of GBM arc scorers — single GBMs are unstable
    at this arc count (fold accuracy reshuffles with any feature change)"""
    def __init__(self, models):
        self.models = models
    def predict_proba(self, F):
        return np.mean([m.predict_proba(F) for m in self.models], axis=0)

def build_piece(wd, use_word=True):
    j = lambda f: json.load(open(os.path.join(wd, f)))
    mor = np.load(os.path.join(wd, 'moria_track.npy'))
    rms = np.load(os.path.join(wd, 'rms_track.npy'))
    ison = j('ison_timeline.json') if os.path.exists(os.path.join(wd, 'ison_timeline.json')) else None
    vn = clean_stream(j('voice_notes3.json'), mor, rms, ison)
    sl, interp, E = j('slots.json'), j('mcr_interpretation.json'), j('expected_degrees.json')
    S, K = len(sl['gi']), len(vn)
    med = np.array([np.nan if (m := med_pitch(mor, v[0], v[1])) is None else m for v in vn])
    t0 = np.array([v[0] for v in vn]); t1 = np.array([v[1] for v in vn])
    gap = np.array([v[3] for v in vn]); dur = t1 - t0
    gi, sub = np.array(sl['gi']), np.array(sl['sub'])
    w = np.array([interp[gi[s]]['beats'][min(sub[s], len(interp[gi[s]]['beats']) - 1)]
                  for s in range(S)])
    CW = np.concatenate([[0.0], np.cumsum(w)])
    Ea = np.array(E, dtype=float)
    line = np.array([interp[g]['line'] for g in gi])
    gorg = np.array([float(interp[g]['gorgon']) for g in gi])
    dmark = np.array([DUR_MARK.get(interp[g]['duration_mark'], 1.0) for g in gi])
    nsubs = np.array([float(interp[g]['sub_notes']) for g in gi])
    bars = j('barlines.json')
    first_slot = {}
    for s in range(S):
        first_slot.setdefault(int(gi[s]), s)
    is_bound = np.zeros(S)
    for b in bars:
        if b['next_glyph'] is not None and b['next_glyph'] in first_slot:
            is_bound[first_slot[b['next_glyph']]] = 1.0
    wt_slot = np.full(S, np.nan)
    if use_word and os.path.exists(os.path.join(wd, 'word_times.json')):
        wt, sn = j('word_times.json'), j('score_notes.json')
        for a, b in zip(sn['anchors'], wt):
            if a['gi'] in first_slot:
                wt_slot[first_slot[a['gi']]] = b['t0']
    # ison-change anchors: the score marks the level (red letters), the app's
    # ison timeline gives the time — unbiased sync points mid-melisma
    # (matching logic as note_align6)
    ISON_CP = {0xf043: 0, 0xf063: 0, 0xf056: 12, 0xf076: 12, 0xf042: 22,
               0xf04e: 30, 0xf06e: 30, 0xf06d: 42, 0xf04d: 42,
               0xf03f: 'M', 0xf02f: 'M'}
    it_slot = np.full(S, np.nan)
    if (os.path.exists(os.path.join(wd, 'ison_events_meta.json'))
            and os.path.exists(os.path.join(wd, 'red_special.json'))):
        sn_notes = j('score_notes.json')['notes']
        letters = []
        for m in j('red_special.json'):
            cp = int(m['cp'], 16)
            if cp not in ISON_CP:
                continue
            gj = min((jj for jj, g in enumerate(sn_notes) if g['line'] == m['line']),
                     key=lambda jj: abs((sn_notes[jj]['x0'] + sn_notes[jj]['x1']) / 2 - m['x']))
            letters.append((ISON_CP[cp], gj))
        li, cur = 0, None
        for t, lvl in j('ison_events_meta.json'):
            while li < len(letters) and letters[li][0] == cur and letters[li][0] != lvl:
                li += 1
            if li >= len(letters) or letters[li][0] != lvl:
                break
            if letters[li][1] in first_slot:
                it_slot[first_slot[letters[li][1]]] = t
            cur = lvl; li += 1
    smove = np.abs(np.diff(Ea, prepend=Ea[0]))          # |expected movement into s|
    CM = np.concatenate([[0.0], np.cumsum(smove)])
    spb = (t1[-1] - t0[0]) / max(CW[-1], 1.0)
    glyph = np.array([f"{interp[g]['name']}.{sb}" for g, sb in zip(gi, sub)])
    # nominal ladder position of each slot's expected degree, for the (noisy
    # but candidate-ranking) absolute-pitch deviation feature. A per-slot
    # ladder.json (moria per slot, genus-aware — soft-chromatic trochos etc.)
    # overrides the default diatonic construction.
    if os.path.exists(os.path.join(wd, 'ladder.json')):
        ladder = np.array(json.load(open(os.path.join(wd, 'ladder.json'))), dtype=float)
    else:
        LS = [12, 10, 8, 12, 12, 10, 8]
        lad = {0: 0.0}
        for d in range(0, int(Ea.max()) + 1):
            lad[d + 1] = lad[d] + LS[d % 7]
        for d in range(0, int(Ea.min()) - 1, -1):
            lad[d - 1] = lad[d] - LS[(d - 1) % 7]
        ladder = np.array([lad[int(e)] for e in Ea])
    # combined anchor times for the phase map (word + ison). Word anchors are
    # ASR-derived and occasionally scrambled (v6 kept a manual drop list) —
    # sanitize automatically: drop word anchors whose leave-one-out residual
    # vs their neighbours' beat-proportional interpolation is large. Ison
    # anchors are app telemetry: trusted, never dropped.
    cand = [(s, float(wt_slot[s]), 'word') for s in range(S) if not np.isnan(wt_slot[s])]
    cand += [(s, float(it_slot[s]), 'ison') for s in range(S) if not np.isnan(it_slot[s])]
    cand.sort()
    changed = True
    while changed and len(cand) > 2:
        changed = False
        worst, wi = 0.0, None
        for i in range(1, len(cand) - 1):
            if cand[i][2] == 'ison':
                continue
            (sa, ta, _), (s_, t_, _), (sb, tb, _) = cand[i - 1], cand[i], cand[i + 1]
            f = (CW[s_] - CW[sa]) / max(CW[sb] - CW[sa], 1e-6)
            r = abs(t_ - (ta + f * (tb - ta)))
            if r > worst:
                worst, wi = r, i
        if wi is not None and worst > 2.5:
            del cand[wi]; changed = True
    anchor_t = np.full(S, np.nan)
    for s, t, _ in cand:
        anchor_t[s] = t
    ison_t = it_slot
    P = dict(vn=vn, S=S, K=K, med=med, t0=t0, t1=t1, gap=gap, dur=dur,
             w=w, CW=CW, E=Ea, line=line, gorg=gorg, dmark=dmark,
             nsubs=nsubs, sub=sub, is_bound=is_bound, wt_slot=wt_slot,
             anchor_t=anchor_t, ison_t=ison_t, ladder=ladder, CM=CM, spb=spb,
             glyph=glyph)
    # absolute phase reference for every slot: anchor-interpolated expected
    # time (falls back to global tempo when no anchors)
    P['tmap'] = (slot_time_map(P) if not np.isnan(anchor_t).all()
                 else t0[0] + CW[:S] * spb)
    # within-bar counting: slot beat-offset from the last barline vs event
    # time since the last breath — shifted paths break this correspondence
    bar_phase = np.zeros(S)
    last_b = 0
    for s in range(S):
        if is_bound[s]:
            last_b = s
        bar_phase[s] = CW[s] - CW[last_b]
    t_breath = np.zeros(K)
    lastt = float(t0[0])
    for k in range(K):
        if gap[k] >= BREATH_GAP:
            lastt = float(t0[k])
        t_breath[k] = t0[k] - lastt
    P['bar_phase'], P['t_breath'] = bar_phase, t_breath
    # local tempo from the anchor map slope (captures rubato + melisma
    # stretch; global spb is badly wrong on freely-sung pieces)
    spb_loc = np.empty(S)
    for s in range(S):
        a, b = max(s - 4, 0), min(s + 4, S - 1)
        spb_loc[s] = (P['tmap'][b] - P['tmap'][a]) / max(CW[b] - CW[a], 1e-6)
    P['spb_loc'] = np.clip(spb_loc, 0.2, 5.0)
    return P

FEAT_NAMES = ['obs', 'exp', 'adiff', 'obs_miss', 'dks', 'dss', 'skip_move',
              'lg_spb', 'lg_rel', 'lg_durfit', 'gap_k', 'breath_k', 'cross_bar',
              'gorg_s', 'sub_s', 'nsubs_s', 'w_s', 'dmark_s', 'word_dt',
              'word_anch', 'dur_k', 'dur_kp',
              'lg_ioi_fit', 'pitch_dev', 'bound_s',
              'lg_phase_fit', 'breath_bound', 'lg_rel_loc', 'lg_durfit_loc']
# NOTE: absolute tmap_dt features were removed — the anchor time map mis-
# stretches across melismas and the model over-trusted it (CV ablation:
# .714 -> .753 without them). The map still gates the node band + lg_ioi_fit.

def featurize(P, kp, sp, k, s):
    """vectorized arc features; all args int arrays of equal length"""
    kp, sp, k, s = (np.asarray(a) for a in (kp, sp, k, s))
    obs = (P['med'][k] - P['med'][kp]) / MPS
    miss = np.isnan(obs)
    exp = P['E'][s] - P['E'][sp]
    adiff = np.abs(np.nan_to_num(obs) - exp)
    ioi = P['t0'][k] - P['t0'][kp]
    B = P['CW'][s] - P['CW'][sp]
    lg_spb = np.log(np.maximum(ioi, 0.02) / np.maximum(B, 0.25))
    lg_rel = lg_spb - np.log(P['spb'])
    lg_durfit = np.log(np.maximum(P['dur'][k], 0.02)
                       / np.maximum(P['w'][s] * P['spb'], 0.05))
    skip_move = P['CM'][s] - P['CM'][sp + 1]            # movement in skipped slots
    cross = np.array([P['is_bound'][a + 1:b + 1].sum() for a, b in zip(sp, s)])
    wdt = P['t0'][k] - P['wt_slot'][s]
    wanch = ~np.isnan(wdt)
    wdt = np.clip(np.nan_to_num(wdt), -4, 4)
    F = np.column_stack([
        np.nan_to_num(obs), exp, adiff, miss.astype(float),
        (k - kp - 1), (s - sp - 1), skip_move,
        lg_spb, lg_rel, lg_durfit,
        P['gap'][k], (P['gap'][k] >= BREATH_GAP).astype(float), cross,
        P['gorg'][s], P['sub'][s].astype(float), P['nsubs'][s], P['w'][s],
        P['dmark'][s], wdt, wanch.astype(float), P['dur'][k], P['dur'][kp],
        np.log(np.maximum(ioi, 0.02)
               / np.maximum(P['tmap'][s] - P['tmap'][sp], 0.05)),
        np.clip(np.nan_to_num(P['med'][k] - P['ladder'][s]), -25, 25),
        P['is_bound'][s],
        np.log((P['t_breath'][k] + 0.1)
               / (P['bar_phase'][s] * P['spb_loc'][s] + 0.1)),
        (P['gap'][k] >= BREATH_GAP).astype(float) * P['is_bound'][s],
        lg_spb - np.log(P['spb_loc'][s]),
        np.log(np.maximum(P['dur'][k], 0.02)
               / np.maximum(P['w'][s] * P['spb_loc'][s], 0.05))])
    return F.astype(np.float32)

def training_arcs(P, gold):
    """positives from consecutive gold pairs + corrupted negatives"""
    rows, y, grp = [], [], []
    S = P['S']
    for (kp, sp), (k, s) in zip(gold, gold[1:]):
        cands = [(kp, sp, k, s, 1)]
        for d in (-3, -2, -1, 1, 2, 3):                 # endpoint slot shift
            s2 = s + d
            if sp < s2 < sp + MAX_DS + 1 and 0 <= s2 < S:
                cands.append((kp, sp, k, s2, 0))
        for d in (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5):   # pair shift (drift arcs)
            sp2, s2 = sp + d, s + d
            if 0 <= sp2 < s2 < S and s2 - sp2 <= MAX_DS:
                cands.append((kp, sp2, k, s2, 0))
        for k2 in (k - 1, k + 1):                       # wrong onset
            if kp < k2 < P['K'] and (k2, s) != (k, s):
                cands.append((kp, sp, k2, s, 0))
        for k2, d in ((k - 1, 1), (k + 1, -1), (k - 1, -2), (k + 1, 2)):
            s2 = s + d                                   # combined corruption
            if kp < k2 < P['K'] and sp < s2 < sp + MAX_DS + 1 and 0 <= s2 < S:
                cands.append((kp, sp, k2, s2, 0))
        for c in cands:
            rows.append(c[:4]); y.append(c[4]); grp.append(P['line'][s])
    kp, sp, k, s = (np.array([r[i] for r in rows]) for i in range(4))
    return featurize(P, kp, sp, k, s), np.array(y), np.array(grp)

def slot_time_map(P):
    """piecewise-linear slot->expected-time through the word anchors
    (beat-proportional between anchors); falls back to global tempo"""
    S = P['S']
    anch = [(0, float(P['t0'][0]))]
    for s in range(S):
        if not np.isnan(P['anchor_t'][s]):
            t = float(P['anchor_t'][s])
            if t > anch[-1][1] + 1e-3 and s > anch[-1][0]:
                anch.append((s, t))
    anch.append((S - 1, float(P['t1'][-1])))
    tmap = np.empty(S)
    for (sa, ta), (sb, tb) in zip(anch, anch[1:]):
        for s in range(sa, sb + 1):
            f = (P['CW'][s] - P['CW'][sa]) / max(P['CW'][sb] - P['CW'][sa], 1e-6)
            tmap[s] = ta + f * (tb - ta)
    return tmap

BAND_EARLY, BAND_LATE = 5.0, 9.0   # s around the word-anchor time map

def decode_marginal(P, model):
    """forward-backward over the same graph -> per-event slot posteriors.
    Returns (assignment {k: s}, confidence {k: p}); an event is claimed when
    its total claim mass exceeds 0.5, at its argmax slot."""
    S, K = P['S'], P['K']
    nodes, arcs_at, starts, ends = _graph(P, model)
    out_at = defaultdict(list)
    for i, lst in arcs_at.items():
        for pj, c in lst:
            out_at[pj].append((i, c))
    NEG = -1e18
    alpha = np.full(len(nodes), NEG)
    for i, c in starts:
        alpha[i] = -c
    order = sorted(range(len(nodes)), key=lambda i: nodes[i][0])
    for i in order:
        for pj, c in arcs_at[i]:
            if alpha[pj] > NEG / 2:
                alpha[i] = np.logaddexp(alpha[i], alpha[pj] - c)
    beta = np.full(len(nodes), NEG)
    for i, c in ends:
        beta[i] = -c
    for i in reversed(order):
        for jj, c in out_at[i]:
            if beta[jj] > NEG / 2:
                beta[i] = np.logaddexp(beta[i], beta[jj] - c)
    lz = NEG
    for i, c in ends:
        if alpha[i] > NEG / 2:
            lz = np.logaddexp(lz, alpha[i] - c)
    marg = defaultdict(dict)
    for i, (k, s) in enumerate(nodes):
        if alpha[i] > NEG / 2 and beta[i] > NEG / 2:
            marg[k][s] = np.exp(alpha[i] + beta[i] - lz)
    asn, conf = {}, {}
    for k, d in marg.items():
        tot = sum(d.values())
        if tot > 0.5:
            s, p = max(d.items(), key=lambda x: x[1])
            asn[k] = s
            conf[k] = p
    return asn, conf

def with_anchors(P, extra, base='all'):
    """clone P with extra {slot: time} anchors; rebuild the phase map and the
    local-tempo curve (the two derived fields the anchors feed).
    base='ison' starts from the trusted ison anchors only — used after pass 1,
    when dense confident claims replace the ASR word anchors entirely."""
    P2 = dict(P)
    at = (P['ison_t'] if base == 'ison' else P['anchor_t']).copy()
    for s, t in extra.items():
        if np.isnan(at[s]):
            at[s] = t
    P2['anchor_t'] = at
    P2['tmap'] = slot_time_map(P2)
    S = P['S']
    spb_loc = np.empty(S)
    for s in range(S):
        a, b = max(s - 4, 0), min(s + 4, S - 1)
        spb_loc[s] = (P2['tmap'][b] - P2['tmap'][a]) / max(P['CW'][b] - P['CW'][a], 1e-6)
    P2['spb_loc'] = np.clip(spb_loc, 0.2, 5.0)
    return P2

def decode_em(P, model, rounds=2, conf_thresh=0.9):
    """marginal decode -> high-confidence claims become new time anchors ->
    denser melisma-aware phase map -> re-decode. Fully automatic (no labels)."""
    asn, conf = decode_marginal(P, model)
    for _ in range(rounds - 1):
        extra = {s: float(P['t0'][k]) for k, s in asn.items()
                 if conf.get(k, 0) >= conf_thresh}
        # keep the word anchors: rebasing on ison+claims only loses the map
        # in regions with no confident claims (CV: .761 -> .702)
        asn, conf = decode_marginal(with_anchors(P, extra), model)
    return asn, conf

def _graph(P, model):
    """shared graph construction for viterbi + marginal decodes"""
    S, K = P['S'], P['K']
    dt = P['t0'][:, None] - P['tmap'][None, :]
    in_band = (dt >= -BAND_EARLY) & (dt <= BAND_LATE)
    in_band[:26, :3] = True                              # start region
    in_band[-8:, S - 4:] = True                          # end region
    nodes = [(k, s) for k in range(K) for s in range(S) if in_band[k, s]]
    nid = {n: i for i, n in enumerate(nodes)}
    A_kp, A_sp, A_k, A_s = [], [], [], []
    for (k, s) in nodes:
        for kp in range(max(0, k - MAX_DK), k):
            for sp in range(max(0, s - MAX_DS), s):
                if in_band[kp, sp]:
                    A_kp.append(kp); A_sp.append(sp); A_k.append(k); A_s.append(s)
    F = featurize(P, A_kp, A_sp, A_k, A_s)
    p = model.predict_proba(F)[:, 1]
    odds = np.clip(np.log(np.clip(p, 1e-9, 1) / np.clip(1 - p, 1e-9, 1)),
                   -ODDS_CLIP, ODDS_CLIP)
    cost = (-odds + SKIP_EV * (np.array(A_k) - np.array(A_kp) - 1)
            + SKIP_SLOT * (np.array(A_s) - np.array(A_sp) - 1))
    arcs_at = defaultdict(list)
    for i in range(len(A_k)):
        arcs_at[nid[(A_k[i], A_s[i])]].append((nid[(A_kp[i], A_sp[i])], cost[i]))
    starts = [(i, 0.15 * k + 0.6 * s) for i, (k, s) in enumerate(nodes)
              if s <= 2 and k <= 25]
    ends = [(i, 0.15 * (K - 1 - k) + 0.6 * (S - 1 - s))
            for i, (k, s) in enumerate(nodes) if s >= S - 4]
    return nodes, arcs_at, starts, ends

def decode(P, model):
    """Viterbi over (event, slot) nodes with learned arc costs"""
    nodes, arcs_at, starts, ends = _graph(P, model)
    D = np.full(len(nodes), np.inf)
    Ptr = np.full(len(nodes), -1, dtype=int)
    for i, c in starts:
        D[i] = c
    order = sorted(range(len(nodes)), key=lambda i: nodes[i][0])
    for i in order:
        for pj, c in arcs_at[i]:
            if D[pj] + c < D[i]:
                D[i] = D[pj] + c; Ptr[i] = pj
    best, barg = np.inf, -1
    for i, c in ends:
        if np.isfinite(D[i]) and D[i] + c < best:
            best, barg = D[i] + c, i
    path = []
    while barg != -1:
        path.append(nodes[barg]); barg = Ptr[barg]
    path.reverse()
    return {k: s for k, s in path}

def main():
    wd = sys.argv[1] if len(sys.argv) > 1 else '.'
    use_word = '--no-word' not in sys.argv
    out_dir = sys.argv[sys.argv.index('--models-out') + 1] if '--models-out' in sys.argv \
        else os.path.join(wd, 'models')
    P = build_piece(wd, use_word=use_word)
    claims = json.load(open(os.path.join(wd, 'slot_claims.json')))
    gold = sorted(((k, s) for s, k in enumerate(claims) if k is not None),
                  key=lambda p: p[1])
    orn = json.load(open(os.path.join(wd, 'ornaments.json')))
    gold_ev = dict(gold)
    print(f"piece: {P['K']} events, {P['S']} slots, {len(gold)} gold claims, "
          f"word anchors {'on' if use_word else 'OFF'}")

    X, y, grp = training_arcs(P, gold)
    print(f"training arcs: {len(y)} ({int(y.sum())} positive)")
    # gold nodes must sit inside the decode band or accuracy is capped
    if not np.isnan(P['wt_slot']).all():
        tmap = slot_time_map(P)
        out_band = sum(not (-BAND_EARLY <= P['t0'][k] - tmap[s] <= BAND_LATE)
                       for k, s in gold)
    else:
        tspan = (P['t0'][0], P['t1'][-1])
        tp_ = (P['t0'] - tspan[0]) / (tspan[1] - tspan[0])
        sp_ = P['CW'][:P['S']] / P['CW'][-1]
        out_band = sum(abs(tp_[k] - sp_[s]) > BAND for k, s in gold)
    print(f"gold nodes outside decode band: {out_band}/{len(gold)}")

    def fit(tr, X_extra=None, n_bag=7):
        Xt, yt = X[tr], y[tr]
        if X_extra is not None and len(X_extra):
            Xt = np.vstack([Xt, X_extra])
            yt = np.concatenate([yt, np.zeros(len(X_extra), dtype=y.dtype)])
        models = []
        rng = np.random.default_rng(0)
        for b in range(n_bag):
            idx = rng.choice(len(yt), len(yt), replace=True) if b else np.arange(len(yt))
            m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06,
                                               max_leaf_nodes=15, min_samples_leaf=10,
                                               l2_regularization=2.0,
                                               class_weight='balanced')
            m.fit(Xt[idx], yt[idx])
            models.append(m)
        return Bag(models)

    gold_arcs = set(zip([g[0] for g in gold], [g[1] for g in gold],
                        [g[0] for g in gold[1:]] + [-1],
                        [g[1] for g in gold[1:]] + [-1]))

    def mine(asn, train_lines):
        """decoded arcs on TRAIN lines that aren't gold -> hard negatives"""
        path = sorted(asn.items())
        arcs = [(kp, sp, k, s) for (kp, sp), (k, s) in zip(path, path[1:])
                if (kp, sp, k, s) not in gold_arcs
                and P['line'][s] in train_lines and s - sp <= MAX_DS and k - kp <= MAX_DK]
        if not arcs:
            return np.empty((0, X.shape[1]), dtype=X.dtype)
        kp, sp, k, s = (np.array([a[i] for a in arcs]) for i in range(4))
        return featurize(P, kp, sp, k, s)

    # ---- grouped-CV decode ----
    hit_slot = hit_glyph = tot = 0
    unclaimed_gold = 0
    orn_tp = orn_fp = orn_fn = 0
    per_fold = []
    conf_recs = []      # (confidence, glyph-correct) pooled out-of-fold
    for fold, (tr, te) in enumerate(GroupKFold(n_splits=6).split(X, y, grp)):
        test_lines = set(grp[te])
        train_lines = set(grp[tr])
        m = fit(tr)
        hard = None
        for _ in range(MINE_ROUNDS):                    # hard-negative rounds
            asn = decode(P, m)
            mined = mine(asn, train_lines)
            hard = mined if hard is None else np.vstack([hard, mined])
            if not len(mined):
                break
            m = fit(tr, hard)
        asn, conf = decode_em(P, m, rounds=3)
        f_hit = f_tot = 0
        for k, s in gold:
            if P['line'][s] not in test_lines:
                continue
            tot += 1; f_tot += 1
            ps = asn.get(k)
            ok = False
            if ps is None:
                unclaimed_gold += 1
            else:
                hit_slot += (ps == s)
                ok = P['glyph'][ps] == P['glyph'][s]
                hit_glyph += ok; f_hit += ok
            conf_recs.append((conf.get(k, 0.0), bool(ok)))
        # melisma layer: decoder-unclaimed events vs ornament labels (test
        # lines; gold-structural events excluded — their misses are counted
        # in unclaimed_gold)
        for k in range(P['K']):
            if k in gold_ev:
                continue
            near = min(gold, key=lambda g: abs(P['t0'][g[0]] - P['t0'][k]))
            if P['line'][near[1]] not in test_lines:
                continue
            is_orn = any(min(P['t1'][k], o1) - max(P['t0'][k], o0) > 0.05
                         for o0, o1, _ in orn)
            pred_orn = k not in asn
            if is_orn and pred_orn: orn_tp += 1
            elif pred_orn and not is_orn: orn_fp += 1
            elif is_orn and not pred_orn: orn_fn += 1
        per_fold.append(f_hit / max(f_tot, 1))
        print(f"fold {fold}: glyph acc {per_fold[-1]:.3f} (n={f_tot})")

    print(f"\n== score-informed decode, grouped CV ==")
    print(f"glyph accuracy       {hit_glyph / tot:.3f}   ({hit_glyph}/{tot})")
    print(f"exact-slot accuracy  {hit_slot / tot:.3f}")
    print(f"gold events left unclaimed by decode: {unclaimed_gold}")
    print(f"melisma/ornament: precision {orn_tp / max(orn_tp + orn_fp, 1):.2f} "
          f"recall {orn_tp / max(orn_tp + orn_fn, 1):.2f} "
          f"({orn_tp}tp/{orn_fp}fp/{orn_fn}fn)")
    gates = {}
    print("confidence gating (accuracy on the events the model trusts):")
    for th in (0.5, 0.7, 0.8, 0.9):
        sel = [ok for c, ok in conf_recs if c >= th]
        if sel:
            gates[th] = {'coverage': len(sel) / tot, 'accuracy': float(np.mean(sel))}
            print(f"  conf>={th}: coverage {len(sel) / tot:.2f} "
                  f"accuracy {np.mean(sel):.3f} (n={len(sel)})")

    # ---- final model on all arcs + full decode artifact ----
    os.makedirs(out_dir, exist_ok=True)
    import joblib
    m = fit(np.arange(len(y)))
    asn, conf = decode_em(P, m, rounds=3)
    joblib.dump(m, os.path.join(out_dir, 'aligner_gbm.joblib'))
    json.dump({'features': FEAT_NAMES, 'use_word': use_word,
               'cv_glyph_acc': hit_glyph / tot, 'cv_slot_acc': hit_slot / tot,
               'per_fold': per_fold, 'confidence_gates': gates},
              open(os.path.join(out_dir, 'report_aligner.json'), 'w'), indent=1)
    json.dump({str(k): {'slot': int(s), 'glyph': str(P['glyph'][s]),
                        'conf': round(float(conf.get(k, 0.0)), 3)}
               for k, s in sorted(asn.items())},
              open(os.path.join(out_dir, 'aligned_full.json'), 'w'), indent=1)
    full_acc = np.mean([asn.get(k) == s for k, s in gold])
    print(f"full-data decode (resubstitution): slot acc {full_acc:.3f}; "
          f"saved -> {out_dir}/")

if __name__ == '__main__':
    main()
