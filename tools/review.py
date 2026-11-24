#!/usr/bin/env python3
"""Find HA detections and extract local review clips. Python standard library only."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import urllib.parse
import urllib.request
import wave

ROOT = Path(__file__).resolve().parent.parent


def timestamp(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamps must include a UTC offset, e.g. 2026-11-05T15:42:18-05:00')
    return parsed.timestamp()


def config():
    values = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            parts = shlex.split(line, comments=True)
            if parts and parts[0] == 'export':
                parts.pop(0)
            if len(parts) == 1 and '=' in parts[0]:
                key, value = parts[0].split('=', 1)
                values[key] = value
    values.update(os.environ)
    return values


def events(args):
    start, end = timestamp(args.start), timestamp(args.end)
    if end <= start:
        raise ValueError('end must be after start')
    env = config()
    entity = args.entity or env.get('HA_ENTITY')
    if not entity:
        raise ValueError('set HA_ENTITY in .env or use --entity')
    base = env['HA_URL'].rstrip('/')
    key = hashlib.sha256(json.dumps([base, entity, start, end]).encode()).hexdigest()
    cache = ROOT / '.review-cache' / (key + '.json')
    if cache.exists() and not args.refresh:
        history = json.loads(cache.read_text())
    else:
        query = urllib.parse.urlencode({'filter_entity_id': entity,
                                      'end_time': args.end, 'minimal_response': 'true'})
        url = base + '/api/history/period/' + urllib.parse.quote(args.start, safe='') + '?' + query
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + env['HA_TOKEN']})
        with urllib.request.urlopen(request, timeout=30) as response:
            history = json.load(response)
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(history))
    count = 0
    for states in history:
        previous = None
        for state in states:
            when = state.get('last_changed') or state.get('last_updated')
            current = state['state']
            if when and start <= timestamp(when) < end and current == 'on' and previous != 'on':
                print(when)
                count += 1
            previous = current
    print(f'{count} detection transition(s); cached locally')


def segments(path, legacy_zone):
    """Yield (first frame, last frame, estimated wall start, wall end)."""
    with wave.open(str(path)) as wav:
        rate, total = wav.getframerate(), wav.getnframes()
    timing = path.with_suffix('.timing.jsonl')
    if timing.exists():
        for line in timing.read_text().splitlines():
            entry = json.loads(line)
            first, last = entry['first_frame'], min(entry['end_frame'], total)
            if last > first:
                end = entry['received_at']
                yield first, last, end - (last - first) / rate, end, 'receive-time estimate'
    else:
        if not legacy_zone:
            return
        # Explicit offset makes legacy filenames independent of the host timezone.
        name = path.stem
        parsed = dt.datetime.strptime(name[-15:], '%Y%m%d_%H%M%S')
        start = timestamp(parsed.isoformat() + legacy_zone)
        yield 0, total, start, start + total / rate, 'legacy estimate; dropped-audio drift unknown'


def clip(args):
    target = timestamp(args.at)
    low, high = target - args.before, target + args.after
    selected = []
    for path in sorted(Path(args.sessions).glob('*.wav')):
        if path.stem.startswith('session_fp'):
            continue
        try:
            with wave.open(str(path)) as wav:
                rate = wav.getframerate()
            for first, last, start, end, quality in segments(path, args.legacy_offset):
                if start < high and end > low:
                    a = max(first, first + int((low - start) * rate))
                    b = min(last, first + int((high - start) * rate))
                    if b > a:
                        selected.append((max(low, start), path, a, b, quality))
        except ValueError:
            continue  # Non-session filename without timing metadata.
    if not selected:
        raise ValueError('no matching audio; legacy sessions require --legacy-offset ±HH:MM')
    selected.sort(key=lambda item: (item[0], str(item[1]), item[2]))
    output = Path(args.output) if args.output else ROOT / 'samples' / 'review' / (args.label + '_' + dt.datetime.fromtimestamp(target, dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.wav')
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.with_suffix('.json').exists():
        raise ValueError('output already exists; choose another --output')
    sources, params = [], None
    with wave.open(str(output), 'wb') as dest:
        for wall, path, first, last, quality in selected:
            with wave.open(str(path)) as src:
                current = (src.getnchannels(), src.getsampwidth(), src.getframerate())
                if params is None:
                    params = current
                    dest.setnchannels(params[0]); dest.setsampwidth(params[1]); dest.setframerate(params[2])
                if current != params:
                    raise ValueError('matching files have incompatible audio formats')
                src.setpos(first)
                dest.writeframes(src.readframes(last - first))
            sources.append({'file': str(path), 'first_frame': first, 'end_frame': last,
                            'estimated_start': wall, 'alignment': quality})
    output.with_suffix('.json').write_text(json.dumps({'event': args.at, 'label': args.label,
        'before': args.before, 'after': args.after, 'sources': sources,
        'note': 'Receive times include network/device buffering; gaps are omitted, not silence-filled.'}, indent=2) + '\n')
    print(f'Clip: {output}\nLabel: {args.label}\nAlignment: ' + ', '.join(sorted({x['alignment'] for x in sources})))
    if args.detector:
        with tempfile.TemporaryDirectory() as directory:
            binary = str(Path(directory) / 'buzzer_test')
            subprocess.run(['g++', '-O2', '-std=c++17', '-o', binary, str(ROOT / 'tests/buzzer_test.cpp')], check=True, capture_output=True)
            result = subprocess.run([binary, str(output)], check=True, capture_output=True, text=True)
            lines = result.stdout.splitlines()
            print('\n'.join(lines[:8]))
            if len(lines) > 8:
                print(f'... {len(lines) - 8} more lines omitted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    event = sub.add_parser('events', help='list HA off-to-on transitions, with a local cache')
    event.add_argument('--start', required=True); event.add_argument('--end', required=True)
    event.add_argument('--entity'); event.add_argument('--refresh', action='store_true')
    event.set_defaults(run=events)
    sample = sub.add_parser('clip', help='extract and label audio around a supplied event time')
    sample.add_argument('--at', required=True)
    sample.add_argument('--label', choices=['correct', 'false-positive', 'missed'], required=True)
    sample.add_argument('--sessions', default=str(ROOT / 'samples'))
    sample.add_argument('--before', type=float, default=5); sample.add_argument('--after', type=float, default=5)
    sample.add_argument('--legacy-offset', help='recording timezone offset, e.g. --legacy-offset=-05:00')
    sample.add_argument('--output'); sample.add_argument('--detector', action='store_true')
    sample.set_defaults(run=clip)
    args = parser.parse_args()
    try:
        if hasattr(args, 'before') and (args.before < 0 or args.after <= 0):
            raise ValueError('before must be nonnegative and after must be positive')
        args.run(args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        # HTTP exceptions omit request headers, including the authorization token.
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
