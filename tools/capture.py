#!/usr/bin/env python3
"""Record the Atom Echo's raw microphone stream to a 16 kHz mono WAV.

usage: capture.py <device-ip> <out.wav> [seconds]
       capture.py <device-ip> <prefix> [seconds] --chunk <minutes>

Long-run mode (--chunk): writes <prefix>_YYYYmmdd_HHMMSS.wav every <minutes>,
streaming to disk, and reconnects (with a new file) after any drop. The start
time in each filename is local wall-clock time. A .timing.jsonl sidecar maps
sample ranges to UTC receive times for review.py; filenames alone can drift.

Turn on the "Audio Capture" switch on the device first (it is off after every
reboot). The shared token is read from $CAPTURE_TOKEN or the capture_token key
in esphome/secrets.yaml.

Stops after `seconds` (default: until Ctrl-C). Name results samples/buzzer_*.wav
(must detect) or samples/negative_*.wav (must not) and run tests/run.sh.
A live level meter shows whether the mic hears anything.
"""
import array
import math
import json
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


class TimedWriter:
    """Preserve byte alignment and map each block to its wall-clock receive time."""
    def __init__(self, path):
        self.wav = open_wav(path)
        self.timing = open(pathlib.Path(path).with_suffix('.timing.jsonl'), 'w', buffering=1)
        self.frames = 0
        self.pending = b''

    def write(self, data, received_at):
        data = self.pending + data
        size = len(data) // 2 * 2
        self.pending = data[size:]
        if not size:
            return
        first = self.frames
        self.wav.writeframes(data[:size])
        self.frames += size // 2
        self.timing.write(json.dumps({'first_frame': first, 'end_frame': self.frames,
                                      'received_at': received_at}) + '\n')

    def close(self):
        self.wav.close()
        self.timing.close()


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

    writer = TimedWriter(out)
    start = last_print = time.monotonic()
    try:
        while limit is None or time.monotonic() - start < limit:
            try:
                data = sock.recv(8192)
            except socket.timeout:
                continue
            received_at = time.time()
            if not data:
                print("\ndevice closed the connection")
                break
            writer.write(data, received_at)
            now = time.monotonic()
            if now - last_print >= 0.25:
                print(level_line(data[:len(data)//2*2], writer.frames / RATE), end="", flush=True)
                last_print = now
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        writer.close()
    print(f"\nsaved {writer.frames / RATE:.1f}s of audio; timing sidecar written")


def record_chunked(host, prefix, limit, chunk_s, token):
    """Stream to disk in time-stamped files; every (re)connect starts a new file."""
    start = time.monotonic()
    log = open(f"{prefix}.log", "a", buffering=1)

    def note(msg):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        log.write(line + "\n")
        print("\n" + line, flush=True)

    note(f"start {host}, chunk {chunk_s:.0f}s")
    try:
        while limit is None or time.monotonic() - start < limit:
            try:
                sock = socket.create_connection((host, PORT), timeout=10)
                sock.sendall(token.encode())
                sock.settimeout(5)
            except OSError as e:
                note(f"connect failed ({e}); is the Audio Capture switch on? retrying")
                time.sleep(10)
                continue

            wav, frames, name = None, 0, None
            pending = b''
            last_data = last_print = time.time()
            try:
                while limit is None or time.monotonic() - start < limit:
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
                        if pathlib.Path(name).exists():
                            name = name[:-4] + f"_{time.time_ns()}.wav"
                        wav = TimedWriter(name)
                        wav.pending = pending
                        frames = 0
                        note(f"recording {name}")
                    wav.write(data, last_data)
                    frames = wav.frames
                    if frames >= chunk_s * RATE:
                        pending = wav.pending
                        wav.close()
                        wav = None
                    if last_data - last_print >= 1:
                        print(level_line(data[:len(data)//2*2], time.monotonic() - start), end="", flush=True)
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
