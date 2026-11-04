#!/usr/bin/env python3
"""Record the Atom Echo's raw microphone stream to a 16 kHz mono WAV.

usage: capture.py <device-ip> <out.wav> [seconds]

Turn on the "Audio Capture" switch on the device first (it is off after every
reboot). The shared token is read from $CAPTURE_TOKEN or the capture_token key
in esphome/secrets.yaml.

Stops after `seconds` (default: until Ctrl-C). Name results samples/buzzer_*.wav
(must detect) or samples/negative_*.wav (must not) and run tests/run.sh.
A live level meter shows whether the mic hears anything.
"""
import array
import math
import os
import pathlib
import re
import socket
import sys
import time
import wave

PORT = 6055
RATE = 16000


def load_token():
    token = os.environ.get("CAPTURE_TOKEN")
    if token:
        return token
    secrets = pathlib.Path(__file__).resolve().parent.parent / "esphome" / "secrets.yaml"
    if secrets.exists():
        m = re.search(r"^capture_token:\s*[\"']?([^\"'\s]+)", secrets.read_text(), re.M)
        if m:
            return m.group(1)
    sys.exit("no token: set CAPTURE_TOKEN or capture_token in esphome/secrets.yaml")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    host, out = sys.argv[1], sys.argv[2]
    limit = float(sys.argv[3]) if len(sys.argv) > 3 else None

    token = load_token()
    sock = socket.create_connection((host, PORT), timeout=10)
    sock.sendall(token.encode())
    sock.settimeout(5)
    print(f"connected to {host}:{PORT}, recording to {out} (Ctrl-C to stop)")

    pcm = bytearray()
    start = last_print = time.time()
    try:
        while limit is None or time.time() - start < limit:
            try:
                data = sock.recv(8192)
            except socket.timeout:
                continue
            if not data:
                print("\ndevice closed the connection")
                break
            pcm += data
            now = time.time()
            if now - last_print >= 0.25:
                tail = bytes(pcm[-(RATE // 4) * 2:])
                s = array.array("h")
                s.frombytes(tail[: len(tail) // 2 * 2])
                if sys.byteorder == "big":
                    s.byteswap()
                peak = max((abs(v) for v in s), default=0)
                rms = math.sqrt(sum(v * v for v in s) / max(len(s), 1))
                db = 20 * math.log10(rms / 32768 + 1e-12)
                print(f"\r{len(pcm) / 2 / RATE:6.1f}s  rms {db:6.1f} dB  peak {peak:6d}", end="", flush=True)
                last_print = now
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()

    n = len(pcm) // 2
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(pcm[: n * 2]))
    wall = time.time() - start
    print(f"\nsaved {n / RATE:.1f}s of audio ({wall:.1f}s wall; a shortfall means dropped chunks)")


if __name__ == "__main__":
    main()
