#!/usr/bin/env bash
# encode-voices.sh — compress generate-voices.mjs's WAV output to the Ogg/Opus
# files the app actually fetches (GitHub issue #66's "Voices" instrument).
#
# Why Opus: Chromium/Firefox/Safari all decode Ogg Opus via the standard
# fetch()+AudioContext.decodeAudioData() path Tone.js/Tone.Sampler uses, and
# at this bitrate a mono sustained pad tone is essentially transparent while
# costing a fraction of raw WAV. Bitrate/headroom were picked empirically:
# `ffmpeg ... -af astats -f null -` on each encoded file was used to check
# "Peak level dB" — a plain-sawtooth-ish additive source with sharp harmonics
# rings a couple dB above its source peak under lossy MDCT compression.
# generate-voices.mjs normalizes to 0.65 peak (loud enough that Voices mode
# isn't badly quieter than Synth at the same 0.25 per-part gain — an earlier
# 0.4 target was too conservative and made Voices sound washed out next to
# the synth in an A/B) and this script uses 128kbps, which keeps the
# occasional overshoot to a fraction of a dB — nowhere near enough to matter
# once it's summed through the app's own Gain(0.25) + Limiter(-1) chain, but
# re-check astats if you push the peak target any higher.
#
# Run from this directory after `node generate-voices.mjs`:
#   ./encode-voices.sh
# Produces voices/ah_<midi>.ogg (deletes the .wav intermediates once done —
# those are NOT shipped; only the .ogg files are fetched by the app).

set -euo pipefail
cd "$(dirname "$0")/voices"

for f in ah_*.wav; do
  base="${f%.wav}"
  ffmpeg -y -loglevel error -i "$f" -c:a libopus -b:a 128k -vbr on -compression_level 10 "${base}.ogg"
  echo "encoded ${base}.ogg"
done

echo "--- peak check (should be comfortably < 0 dB; the app sums 4 of these" \
     "through a 0.25 gain + limiter, so a note or two nudging just over 0dB" \
     "here is not itself a bug, but keep it the exception, not the rule) ---"
for f in ah_*.ogg; do
  peak=$(ffmpeg -loglevel info -i "$f" -af astats -f null - 2>&1 | grep "Peak level dB" | tail -1)
  echo "$f: $peak"
done

echo "--- total payload ---"
du -cb ah_*.ogg | tail -1

rm -f ah_*.wav
echo "removed .wav intermediates — voices/ now holds only what ships."
