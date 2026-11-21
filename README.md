# Bitron MV80 ESPHome Buzzer Detector

Detect a Bitron MV80 intercom buzzer in Home Assistant using the microphone in an M5Stack Atom Echo. No wiring to the intercom is required.

The Atom Echo also remains available for Home Assistant audio and text-to-speech. Buzzer monitoring pauses during playback and resumes afterward.

## Setup

Copy [`esphome/m5stack-atom-echo.yaml`](esphome/m5stack-atom-echo.yaml) to
your ESPHome configuration directory (typically `/config/esphome` in Home
Assistant). ESPHome downloads the required external component from GitHub
when it builds; no header files need to be copied.

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

## Development

See [DEVELOPING.md](DEVELOPING.md) for testing, CI, and development tools.
