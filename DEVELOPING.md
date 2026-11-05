# Development

## Tests

Requirements: Bash, Python 3, and a C++17 compiler (`g++`). From the repository root, run:

```sh
tests/run.sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

The script builds a temporary host harness for `esphome/buzzer_detector.h`, runs the sample recordings and synthetic cases, and removes its temporary files afterward. Recordings named `samples/buzzer*.wav` must trigger detection; `samples/negative*.wav` must not. Synthetic cases cover noise, individual tones, and buzzer signals, including recordings with reduced level and added noise.

Run the tests before flashing firmware. Only commit recordings that are suitable for public distribution; local session recordings are gitignored.

## CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on pushes, pull requests, manual dispatch, and Mondays at 09:00 UTC. It runs the host tests and compiles the firmware against the `latest` and `beta` ESPHome container images. The stable build must pass; beta failures are allowed. CI generates placeholder secrets and caches the ESPHome toolchain. It does not flash a device.

## Local configuration

Firmware credentials belong in the gitignored `esphome/secrets.yaml`.

For the flash helper, create a `.env` file in the repository root. It is gitignored and sourced as a Bash file, so use shell assignments and quote values as needed.

| Variable | Purpose |
| --- | --- |
| `DEVICE_IP` | Device address for OTA flashing; required. |

## Tools

### Build and flash

Requires Docker and an OTA-reachable device with this firmware already installed.

```sh
tools/flash.sh
```

The helper loads `.env`, pulls the latest stable ESPHome image, compiles and OTA-flashes the firmware. Audio Capture stays off after reboot; enable it manually when you want to record.

Use `--no-pull` to reuse the local image. Full build output is written to `/tmp/flash.log`. Compilation can take several minutes.

### Record test samples

Requires Python 3 and access to the device's TCP port 6055. Enable the device's **Audio Capture** switch first; it resets to off after each reboot. The tool reads the shared token from `CAPTURE_TOKEN` or `capture_token` in `esphome/secrets.yaml`.

```sh
python3 tools/capture.py <device-ip> samples/buzzer_new.wav 10
```

The tool records 16 kHz mono PCM as WAV. Use `samples/negative_new.wav` for a recording that should not trigger detection, then run the tests.

For a longer recording with a new file every 30 minutes:

```sh
python3 tools/capture.py <device-ip> samples/session --chunk 30 86400
```

This records for up to 24 hours, reconnects after connection drops, and writes timestamped WAV files plus `samples/session.log`. Omit the duration to record until interrupted. Session files are gitignored. Streaming is unencrypted; use a trusted network.

### Review Home Assistant events and recordings

`tools/review.py` uses Python 3's standard library. For event queries, add `HA_URL`,
`HA_TOKEN` (a long-lived access token), and `HA_ENTITY` (the detection binary sensor
entity ID) to the local `.env`, or set them in the environment. Environment values
take precedence. Simple shell assignments are supported; shell expressions are not
executed. `--entity` overrides `HA_ENTITY`. These are Home Assistant entity IDs,
not device IDs. If needed for manual capture-switch control, keep its entity ID
in `.env` as `HA_CAPTURE_ENTITY`; the tools do not change that switch.

All event timestamps must include a UTC offset to avoid timezone ambiguity:

```sh
python3 tools/review.py events --start 2026-11-05T15:00:00-05:00 --end 2026-11-05T16:00:00-05:00
python3 tools/review.py clip --at 2026-11-05T15:42:18-05:00 --label false-positive --detector
```

Event queries print detection transitions and cache responses in the gitignored
`.review-cache/` directory. Use `--refresh` for recent ranges whose history may
still change. A missed detection needs a supplied time because HA has no event.

Clipping scans `samples/` by default (`--sessions` selects another directory).
Labels are `correct`, `false-positive`, and `missed`. The default window is five
seconds before and after the event; adjust `--before` and `--after` as needed.
The tool writes a WAV and JSON label/source metadata to gitignored
`samples/review/`. `--output` selects another path; existing outputs are refused.
`--detector` builds the host harness temporarily and prints a compact summary
(requires `g++`). Labels do not automatically add recordings to the test suite.

New captures write a `.timing.jsonl` sidecar beside each WAV, mapping frame ranges
to UTC receive times. Keep the sidecar with the recording. Review uses these
ranges rather than assuming the sample clock tracks elapsed wall time across
missing audio. Receive times include device/network buffering; allow a margin
around events. Gaps are omitted from clips, not filled with silence, and source
ranges are recorded in the clip metadata. Overlapping captures may both contribute.

For old timestamped session files without sidecars, specify the recording's UTC
offset, for example `--legacy-offset=-05:00`. Alignment is approximate and can drift
when audio was dropped; widen the clip window as needed. Exact timing cannot be
recovered from old WAVs alone. Sidecars, cached history, and review clips stay local.
