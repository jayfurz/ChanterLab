#!/usr/bin/env python3
"""Segment a mono chant recording into note events.
Autocorrelation f0 @10ms hop -> note boundaries at sustained pitch change (>=80c for 70ms),
unvoiced gaps (>=140ms), energy re-articulation dips (>=7dB); octave-glitch guard; merge pass.
Usage: voice_segment.py in.wav out.json   ->  [[t0,t1,cents_rel_55Hz,gap_before_s],...]"""
import sys, json
import numpy as np, wave
from scipy.signal import medfilt

inp, out = sys.argv[1], sys.argv[2]
w = wave.open(inp,'rb'); sr = w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)/32768.0
w.close()
hop, win = int(sr*0.01), 2048
nfr = (len(x)-win)//hop
f0 = np.zeros(nfr); rms = np.zeros(nfr)
lo, hi = int(sr/370), int(sr/90)
for i in range(nfr):
    fr = x[i*hop:i*hop+win]
    r = np.sqrt(np.mean(fr**2)); rms[i] = r
    if r < 0.008: continue
    fr = fr - fr.mean()
    ac = np.correlate(fr, fr, 'full')[win-1:]
    if ac[0] <= 0: continue
    ac /= ac[0]
    pk = int(np.argmax(ac[lo:hi])) + lo
    if 1 <= pk < len(ac)-1 and ac[pk] > 0.45:
        a,b,c = ac[pk-1], ac[pk], ac[pk+1]
        f0[i] = sr/(pk + 0.5*(a-c)/(a-2*b+c+1e-12))
cents = np.where(f0>0, 1200*np.log2(np.maximum(f0,1)/55.0), np.nan)
cents = medfilt(np.where(np.isnan(cents), 0, cents), 7); cents[cents==0]=np.nan
db = 20*np.log10(np.maximum(rms,1e-6))
notes=[]; cur=None; dev=0; last_end=-999
def close(endfr):
    global cur
    if cur and (endfr-cur['s'])>=10:
        notes.append([cur['s']*hop/sr, endfr*hop/sr, float(np.median(cur['v'])), cur['gap']])
        return endfr
for i in range(nfr):
    c = cents[i]
    if np.isnan(c):
        if cur:
            cur['sil'] += 1
            if cur['sil'] >= 14:
                e = close(i-cur['sil'])
                if e: last_end = e
                cur=None
        continue
    if cur is None:
        gap = (i-last_end)*hop/sr if last_end>0 else 9.9
        cur = {'s':i,'v':[c],'sil':0,'gap':round(min(gap,9.9),2),'dip':False}; dev=0; continue
    cur['sil']=0
    med = np.median(cur['v'][-40:]); d = c-med
    if abs(abs(d)-1200)<150 and dev<3: continue
    if abs(d)>80:
        dev+=1
        if dev>=7:
            e=close(i-dev+1)
            if e is not None: last_end=e
            cur={'s':i-dev+1,'v':[c],'sil':0,'gap':0.0,'dip':False}; dev=0
        continue
    dev=0
    if len(cur['v'])>12:
        pk=np.max(db[max(0,i-30):i+1])
        if db[i]<pk-7.0: cur['dip']=True
        elif cur['dip'] and db[i]>pk-2.5:
            e=close(i)
            if e is not None: last_end=e
            cur={'s':i,'v':[c],'sil':0,'gap':0.0,'dip':False}; continue
    cur['v'].append(c)
close(nfr)
merged=[notes[0]]
for n in notes[1:]:
    p=merged[-1]
    if n[0]-p[1]<0.06 and abs(n[2]-p[2])<60 and n[3]<0.14: p[1]=n[1]
    else: merged.append(n)
json.dump([[round(a,3),round(b,3),round(c,1),g] for a,b,c,g in merged], open(out,'w'))
print(len(merged), 'notes ->', out)
