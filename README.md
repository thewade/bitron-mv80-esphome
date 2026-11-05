# Bitron MV80 ESPHome Buzzer Detector

ESPHome-based detector for the buzzer/ring signal from a Bitron MV80 intercom using the microphone in an M5Stack Atom Echo.

The detector samples the microphone at 16 kHz and analyzes overlapping 512-sample windows using Goertzel filters. The buzzer is a set of narrow tones at ~406, ~703, ~2109 and ~2812 Hz that alternate every ~100 ms, so the detector averages power spectra over ~270 ms and measures how far each tone stands out above the spectrum around it ("prominence", in dB). A match needs the 703 Hz tone plus at least two of the other three to stand out by more than 16 dB (real presses score about 27-32 dB; household noise has reached about 12 dB), held for a few windows (with a short gap tolerance). This is independent of loudness, so it works whether the microphone hears the buzzer faintly (about -35 dB RMS from across the house) or loudly.

Diagnostic sensors expose the calculated RMS level, the per-tone prominences (the "407 Ratio", "703 Ratio" and "High Harmonic Ratio" sensors, now in dB), and the buzzer score (the weakest prominence that must pass, so a match is score > 16 dB).

The Atom Echo's speaker remains available for Home Assistant audio/TTS; microphone capture is paused while the speaker is active.

## Testing

The detector lives in `esphome/buzzer_detector.h` (shared by the firmware and tests). `tests/run.sh` compiles it into a host harness and runs it over `samples/buzzer*.wav` (must detect) and `samples/negative*.wav` plus synthetic noise/tones (must not detect). Add misses/false alarms as new sample WAVs. Build `tests/buzzer_test.cpp` directly and pass `--verbose` for per-window metrics.

### Recording samples from the device

The firmware serves its raw microphone stream (16 kHz mono PCM, exactly what the detector sees) on TCP port 6055 while a client is connected. Record it with:

    python3 tools/capture.py <device-ip> samples/buzzer_doorbell1.wav 10

For a long unattended run (hours or a day, about 115 MB/hour) use `python3 tools/capture.py <device-ip> samples/session --chunk 30`. It streams to `samples/session_YYYYmmdd_HHMMSS.wav` files every 30 minutes, reconnects with a new file after any drop, and keeps a `samples/session.log`. A position in a file is the filename's local time plus the offset, so it lines up with Home Assistant event times. These files are gitignored.

`samples/buzzer_phone.wav` is a phone recording of the buzzer at a different level and 48 kHz; it checks the detector is not tuned only to the device microphone. Name recordings `samples/buzzer_*.wav` (must detect) or `samples/negative_*.wav` (must not detect), then run `tests/run.sh`. Streaming is off after every reboot: turn on the "Audio Capture" switch first. A client must also send the shared token (`capture_token` in `esphome/secrets.yaml`, which is gitignored) or it is disconnected; the stream itself is unencrypted, so only use it on a trusted network.

## CI

`.github/workflows/ci.yml` runs the detector tests and compiles the firmware (with placeholder secrets) against the latest stable ESPHome on every push and pull request, and weekly. A `beta` build is also run but allowed to fail, as an early warning. It is free for public repositories; the toolchain is cached between runs.
