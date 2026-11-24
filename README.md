# Bitron MV80 ESPHome Buzzer Detector

Detect a Bitron MV80 intercom buzzer in Home Assistant using the microphone in an M5Stack Atom Echo. No wiring to the intercom is required.

The Atom Echo also remains available for Home Assistant audio and text-to-speech. Buzzer monitoring pauses during playback and resumes afterward.

## Setup

Create a YAML file in your ESPHome configuration directory (typically
`/config/esphome` in Home Assistant):

```yaml
substitutions:
  capture_token: !secret capture_token

packages:
  intercom: github://thewade/bitron-mv80-esphome/esphome/packages/m5stack-atom-echo.yaml@main

api:
  encryption:
    key: !secret m5stack_atom_echo__encryption_key

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
```

ESPHome downloads the package and required external component from GitHub when
it builds; no header files need to be copied. You can also copy
[`esphome/m5stack-atom-echo.yaml`](esphome/m5stack-atom-echo.yaml) directly.

Add these entries to your ESPHome `secrets.yaml`:

```yaml
wifi_ssid: "your Wi-Fi name"
wifi_password: "your Wi-Fi password"
m5stack_atom_echo__encryption_key: "your ESPHome API encryption key"
capture_token: "your random capture token"
```

Use an ESPHome-generated API encryption key and a random capture token, then
install the device through the ESPHome dashboard. Audio Capture is optional,
off by default, and streams unencrypted audio when enabled; use a trusted network.

## Optional detector tuning

Defaults work without any additional configuration. To override one or more
settings, add them under `substitutions` in your device YAML, for example:

```yaml
substitutions:
  capture_token: !secret capture_token
  buzzer_min_prominence_db: "18.0"
```

| Substitution | Default | Effect |
| --- | ---: | --- |
| `buzzer_min_prominence_db` | 16.0 | Minimum score in dB. Raising it can reduce false positives but may miss buzzers. |
| `buzzer_min_2812_prominence_db` | 6.0 | Minimum 2812 Hz prominence in dB, required in addition to the score. |
| `buzzer_hit_count_on` | 3 | Number of matching analysis windows needed to detect a buzzer. |
| `buzzer_hit_gap_reset_ms` | 500 | Maximum gap in milliseconds between matching windows before confirmation resets. |

Both prominence thresholds must be non-negative; the count and gap must be
positive integers. Changing a setting requires rebuilding and installing the
firmware; invalid values are rejected during compilation. Matching windows are
about 16 ms apart, so a shorter gap prevents confirmation when the count exceeds
one. Tune cautiously: more restrictive settings can miss real presses, and
less restrictive settings can cause false detections. No maximum buzzer duration
is imposed.

## Development

See [DEVELOPING.md](DEVELOPING.md) for testing, CI, and development tools.
