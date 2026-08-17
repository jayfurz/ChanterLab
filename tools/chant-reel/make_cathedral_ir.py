#!/usr/bin/env python3
"""Synthesize a stereo cathedral impulse response (octave-band RT60-shaped noise,
sparse early reflections, 65ms predelay). Usage: make_cathedral_ir.py out.wav"""
import sys
import numpy as np, wave
from scipy import signal
sr = 44100; np.random.seed(1453)
dur = 6.0; n = int(sr*dur); t = np.arange(n)/sr
bands = [(88,177,5.4),(177,354,5.1),(354,707,4.7),(707,1414,4.1),
         (1414,2828,3.3),(2828,5657,2.3),(5657,11314,1.4),(11314,20000,0.9)]
tail = np.zeros((n,2))
for lo,hi,rt60 in bands:
    sos = signal.butter(4, [lo/(sr/2), min(hi/(sr/2),0.99)], btype='band', output='sos')
    for ch in range(2):
        tail[:,ch] += signal.sosfilt(sos, np.random.randn(n)) * 10**(-3*t/rt60)
er = np.zeros((n,2))
for i,(tt,amp) in enumerate([(0.019,0.32),(0.027,0.28),(0.036,0.24),(0.047,0.20),(0.059,0.17),(0.071,0.14),(0.083,0.11)]):
    for ch in range(2):
        er[int((tt + (0.0013 if ch else 0)*(1 if i%2 else -1))*sr), ch] += amp*(1 if (i+ch)%2 else -1)
er = signal.fftconvolve(er, np.hanning(60)[:,None]*np.random.randn(60,1)*0.2, mode='full', axes=0)[:n]
pre = int(0.065*sr)
ir = np.zeros((n+pre,2)); ir[:n] += er*0.8
fade = np.ones(n); fi = int(0.030*sr); fade[:fi] = np.linspace(0,1,fi)**2
ir[pre:pre+n] += tail*fade[:,None]*0.9
ir = ir/np.max(np.abs(ir))*0.22
o = wave.open(sys.argv[1],'wb'); o.setnchannels(2); o.setsampwidth(2); o.setframerate(sr)
o.writeframes((np.clip(ir,-1,1)*32767).astype(np.int16).tobytes()); o.close()
print('IR ->', sys.argv[1])
