#!/usr/bin/env bash
# Builds the detector test harness and runs it against samples/ plus
# synthetic negative cases. Add real recordings as samples/buzzer*.wav
# (must detect) or samples/negative*.wav (must not detect).
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

g++ -O2 -Wall -Wextra -std=c++17 -o "$tmp/buzzer_test" tests/buzzer_test.cpp

python3 - "$tmp" <<'EOF'
import math, random, struct, sys, wave
out = sys.argv[1]
def write(name, samples):
    with wave.open(f"{out}/{name}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, int(s)))) for s in samples))
n = 16000 * 3
random.seed(1)
write("silence", [0] * n)
write("noise", [random.gauss(0, 3000) for _ in range(n)])
write("tone_1k", [8000 * math.sin(2 * math.pi * 1000 * i / 16000) for i in range(n)])
def tone(f, a): return [a * math.sin(2 * math.pi * f * i / 16000) for i in range(n)]
write("tone_407", tone(406.25, 8000))
write("tone_2109", tone(2109, 8000))
write("tones_407_703", [a + b for a, b in zip(tone(406.25, 8000), tone(703, 4000))])
write("harmonics_407", [sum(math.sin(2 * math.pi * 406.25 * k * i / 16000) / k for k in range(1, 8)) * 5000 for i in range(n)])
write("voice_like", [sum(math.sin(2 * math.pi * 200 * k * i / 16000) / k for k in range(1, 15)) * 3000
                     * (1 + math.sin(2 * math.pi * 4 * i / 16000)) for i in range(n)])

# Positive: the four buzzer tones, alternating in ~100 ms phases like the real thing.
def phase(i):
    on_a = (i // 1600) % 2 == 0
    fs = (406.25, 703.125) if on_a else (2109.375, 2812.5)
    return sum(4000 * math.sin(2 * math.pi * f * i / 16000) for f in fs) + 2500 * math.sin(2 * math.pi * 406.25 * i / 16000)
write("synthetic_buzz", [phase(i) for i in range(n)])

# Robustness: the real buzzer at low level with added noise must still be detected.
with wave.open("samples/buzzer.wav") as r:
    rate, raw = r.getframerate(), r.readframes(r.getnframes())
src = struct.unpack("<%dh" % (len(raw) // 2), raw)
for gain, noise in ((0.25, 300), (0.1, 150)):
    with wave.open(f"{out}/robust_g{gain}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, int(v * gain + random.gauss(0, noise))))) for v in src))
EOF

fail=0
for f in samples/buzzer*.wav; do
  "$tmp/buzzer_test" "$f" --expect-detect || fail=1
done
for f in "$tmp"/robust_*.wav "$tmp"/synthetic_*.wav; do
  "$tmp/buzzer_test" "$f" --expect-detect || fail=1
done
for f in samples/negative*.wav "$tmp"/*.wav; do
  [ -e "$f" ] || continue
  case "$f" in */robust_*|*/synthetic_*) continue;; esac
  "$tmp/buzzer_test" "$f" --expect-none || fail=1
done
# Optional local-only raw capture (gitignored): 15 min with four presses.
if [ -e samples/session1.wav ]; then
  "$tmp/buzzer_test" samples/session1.wav --expect-count 4 || fail=1
fi
# Optional local-only false positives cut from long captures (gitignored).
for f in samples/session_fp*.wav; do
  [ -e "$f" ] || continue
  "$tmp/buzzer_test" "$f" --expect-none || fail=1
done
exit $fail
