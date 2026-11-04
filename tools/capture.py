#!/usr/bin/env python3
"""Record the Atom Echo's raw microphone stream to a 16 kHz mono WAV.

usage: capture.py <device-ip> <out.wav> [seconds]
       capture.py <device-ip> <prefix> [seconds] --chunk <minutes>

Long-run mode (--chunk): writes <prefix>_YYYYmmdd_HHMMSS.wav every <minutes>,
streaming to disk, and reconnects (with a new file) after any drop. The start
time in each filename is local wall-clock time, so a position in a file is
filename time + offset, which lines up with Home Assistant event times.

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


def open_wav(path):
    w = wave.open(str(path), "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(RATE)
    return w


def level_line(tail, seconds):
    s = array.array("h")
    s.frombytes(tail[: len(tail) // 2 * 2])
    if sys.byteorder == "big":
        s.byteswap()
    peak = max((abs(v) for v in s), default=0)
    rms = math.sqrt(sum(v * v for v in s) / max(len(s), 1))
    db = 20 * math.log10(rms / 32768 + 1e-12)
    return f"\r{seconds:8.1f}s  rms {db:6.1f} dB  peak {peak:6d}"


def record_single(host, out, limit, token):
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
                print(level_line(bytes(pcm[-(RATE // 4) * 2:]), len(pcm) / 2 / RATE), end="", flush=True)
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


def record_chunked(host, prefix, limit, chunk_s, token):
    """Stream to disk in time-stamped files; every (re)connect starts a new file."""
    start = time.time()
    log = open(f"{prefix}.log", "a", buffering=1)

    def note(msg):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        log.write(line + "\n")
        print("\n" + line, flush=True)

    note(f"start {host}, chunk {chunk_s:.0f}s")
    try:
        while limit is None or time.time() - start < limit:
            try:
                sock = socket.create_connection((host, PORT), timeout=10)
                sock.sendall(token.encode())
                sock.settimeout(5)
            except OSError as e:
                note(f"connect failed ({e}); is the Audio Capture switch on? retrying")
                time.sleep(10)
                continue

            wav, frames, name = None, 0, None
            last_data = last_print = time.time()
            try:
                while limit is None or time.time() - start < limit:
                    try:
                        data = sock.recv(8192)
                    except socket.timeout:
                        if time.time() - last_data > 30:
                            note("no audio for 30 s")
                            break
                        continue
                    if not data:
                        note("device closed the connection")
                        break
                    last_data = time.time()
                    if wav is None:
                        name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.wav"
                        wav = open_wav(name)
                        frames = 0
                        note(f"recording {name}")
                    wav.writeframes(data[: len(data) // 2 * 2])
                    frames += len(data) // 2
                    if frames >= chunk_s * RATE:
                        wav.close()
                        wav = None
                    if last_data - last_print >= 1:
                        print(level_line(data, time.time() - start), end="", flush=True)
                        last_print = last_data
            finally:
                sock.close()
                if wav is not None:
                    wav.close()
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    note("stopped")


def main():
    args = sys.argv[1:]
    chunk = None
    if "--chunk" in args:
        i = args.index("--chunk")
        chunk = float(args[i + 1]) * 60
        del args[i : i + 2]
    if len(args) < 2:
        sys.exit(__doc__)
    host, out = args[0], args[1]
    limit = float(args[2]) if len(args) > 2 else None

    token = load_token()
    if chunk:
        record_chunked(host, out, limit, chunk, token)
    else:
        record_single(host, out, limit, token)


if __name__ == "__main__":
    main()
