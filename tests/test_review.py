"""Offline capture/review regression tests; no device or HA credentials required."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
import wave
from unittest.mock import patch


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


capture, review = module('capture'), module('review')


class ReviewTests(unittest.TestCase):
    def test_gap_and_odd_tcp_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session.wav'
            writer = capture.TimedWriter(path)
            writer.write(b'\x01', 1000)
            writer.write(b'\x02' * 31999, 1001)  # one second, including pending byte
            writer.write(b'\x03\x04' * 16000, 1011)  # ten seconds later
            writer.close()
            with wave.open(str(path)) as src:
                self.assertEqual(src.getnframes(), 32000)
                self.assertEqual(src.readframes(1), b'\x01\x02')
            spans = list(review.segments(path, None))
            self.assertEqual([(s[2], s[3]) for s in spans], [(1000, 1001), (1010, 1011)])
            output = Path(directory) / 'clip.wav'
            args = types.SimpleNamespace(at='1970-01-01T00:16:50.500+00:00', before=.25,
                after=.25, sessions=directory, legacy_offset=None, output=str(output),
                label='false-positive', detector=False)
            with contextlib.redirect_stdout(io.StringIO()):
                review.clip(args)
            with wave.open(str(output)) as src:
                self.assertEqual(src.getnframes(), 8000)
                self.assertEqual(src.readframes(1), b'\x03\x04')
            self.assertEqual(json.loads(output.with_suffix('.json').read_text())['label'], 'false-positive')

    def test_legacy_requires_explicit_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'session_20261105_120000.wav'
            writer = capture.TimedWriter(path); writer.write(b'\0\0' * 16000, 1); writer.close()
            path.with_suffix('.timing.jsonl').unlink()
            self.assertEqual(list(review.segments(path, None)), [])
            self.assertEqual(list(review.segments(path, '-05:00'))[0][2], review.timestamp('2026-11-05T17:00:00Z'))

    def test_event_cache_filters_initial_state_and_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            args = types.SimpleNamespace(start='2026-11-05T12:00:00Z', end='2026-11-05T13:00:00Z', entity=None, refresh=False)
            states = [[{'state': state, 'last_changed': when} for state, when in [
                ('on', '2026-11-05T11:59:00Z'), ('off', '2026-11-05T12:01:00Z'),
                ('on', '2026-11-05T12:02:00Z'), ('on', '2026-11-05T12:02:00Z')]]]
            response = io.BytesIO(json.dumps(states).encode())
            with patch.object(review, 'ROOT', Path(directory)), patch.object(review, 'config', return_value={
                'HA_URL': 'http://example.invalid', 'HA_TOKEN': 'private', 'HA_ENTITY': 'binary_sensor.test'}), patch.object(review.urllib.request, 'urlopen', return_value=response) as fetch:
                for _ in range(2):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        review.events(args)
                    self.assertIn('1 detection transition(s)', out.getvalue())
                    self.assertNotIn('private', out.getvalue())
                self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
