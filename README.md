# Bitron MV80 ESPHome Buzzer Detector

ESPHome-based detector for the buzzer/ring signal from a Bitron MV80 intercom using the microphone in an M5Stack Atom Echo.

The detector samples the microphone at 16 kHz and analyzes overlapping 512-sample windows using Goertzel filters. Detection is based primarily on energy around:

- ~407 Hz
- ~703 Hz
- higher harmonics around ~2.1 / 2.8 kHz

A loudness gate, spectral ratios, score threshold, and short temporal filter are used to distinguish the intercom buzzer from normal room audio.

Diagnostic sensors expose the calculated RMS level, spectral ratios, and buzzer score in Home Assistant so the thresholds can be tuned from real recordings.

The Atom Echo's speaker remains available for Home Assistant audio/TTS; microphone capture is paused while the speaker is active.