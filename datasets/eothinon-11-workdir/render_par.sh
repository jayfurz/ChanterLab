#!/bin/bash
# parallel chunked render: 6 PIL workers -> NVENC chunks -> concat -> fade+audio mux
set -euo pipefail
cd "$(dirname "$0")"
N=7920; CH=6; STEP=$(( (N + CH - 1) / CH ))
export FFMPEG_BIN=/usr/bin/ffmpeg
rm -f chunk_*.mp4 concat_list.txt
pids=()
for i in $(seq 0 $((CH-1))); do
  a=$((i*STEP)); b=$(( (i+1)*STEP ))
  REEL_V2=1 REEL_LADDER=1 REEL_RANGE="$a:$b" REEL_OUT="chunk_$i.mp4" python3 render.py &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
for i in $(seq 0 $((CH-1))); do echo "file 'chunk_$i.mp4'" >> concat_list.txt; done
DUR=264.02
/usr/bin/ffmpeg -y -v error -f concat -safe 0 -i concat_list.txt -i master.wav \
  -map 0:v -map 1:a \
  -vf "fade=t=in:st=0:d=0.7,fade=t=out:st=$(python3 -c "print($DUR-2.2)"):d=2.2,format=yuv420p" \
  -c:v libx264 -preset medium -crf 18 -r 30 \
  -c:a aac -b:a 192k -ar 44100 -shortest -movflags +faststart \
  chant_reel_v3.6.mp4
rm -f chunk_*.mp4 concat_list.txt
echo "parallel render complete"
