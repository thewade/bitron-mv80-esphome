# Development

## Tests

Requirements: Bash, Python 3, and a C++17 compiler (`g++`). From the repository root, run:

```sh
tests/run.sh
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
