"""Offline capture/review regression tests; no device or HA credentials required."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
import wave
from unittest.mock import MagicMock, patch


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / 'tools' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


capture, review = module('capture'), module('review')
with patch.dict(sys.modules, {'capture': capture, 'review': review}):
    record = module('record')


class RecordingSessionTests(unittest.TestCase):
    def test_startup_connection_refusal_retries_quickly(self):
        sock = MagicMock()
        sock.recv.side_effect = [b'\x01\x02', KeyboardInterrupt]
        with tempfile.TemporaryDirectory() as directory:
            prefix = str(Path(directory) / 'session')
            with patch.object(capture.socket, 'create_connection',
                              side_effect=[ConnectionRefusedError('not ready'), sock]), \
                 patch.object(capture.time, 'sleep') as sleep, \
                 contextlib.redirect_stdout(io.StringIO()):
                capture.record_chunked('device', prefix, None, 1800, 'token')
            sleep.assert_called_once_with(1)
            wavs = list(Path(directory).glob('session_*.wav'))
            self.assertEqual(len(wavs), 1)
            with wave.open(str(wavs[0])) as wav:
                self.assertEqual(wav.readframes(1), b'\x01\x02')

    def test_startup_retry_backs_off_when_device_remains_unavailable(self):
        elapsed = [0]

        def sleep(seconds):
            elapsed[0] += seconds

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(capture.socket, 'create_connection',
                          side_effect=ConnectionRefusedError('not ready')), \
             patch.object(capture.time, 'monotonic', side_effect=lambda: elapsed[0]), \
             patch.object(capture.time, 'sleep', side_effect=sleep) as pauses, \
             contextlib.redirect_stdout(io.StringIO()):
            capture.record_chunked('device', str(Path(directory) / 'session'), 12, 1800, 'token')
        self.assertEqual([call.args[0] for call in pauses.call_args_list], [1] * 10 + [10])

    def test_connection_failures_after_success_keep_existing_retry_delay(self):
        sock = MagicMock()
        sock.recv.return_value = b''
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(capture.socket, 'create_connection',
                          side_effect=[sock, ConnectionRefusedError('down'), KeyboardInterrupt]), \
             patch.object(capture.time, 'sleep') as pauses, \
             contextlib.redirect_stdout(io.StringIO()):
            capture.record_chunked('device', str(Path(directory) / 'session'), None, 1800, 'token')
        self.assertEqual([call.args[0] for call in pauses.call_args_list], [2, 10])

    def test_session_manages_switch_and_records(self):
        env = {'DEVICE_IP': 'device', 'HA_URL': 'http://example.invalid/',
               'HA_TOKEN': 'private', 'HA_CAPTURE_ENTITY': 'switch.capture'}
        calls = []

        def request(req, timeout):
            calls.append((req.full_url, json.loads(req.data), req.get_method(),
                          req.get_header('Authorization'), timeout))
            return io.BytesIO(b'[]')

        def recording(host, prefix, limit, chunk, token):
            calls.append((host, prefix, limit, chunk, token))

        with patch.object(review, 'config', return_value=env), \
             patch.object(capture, 'load_token', return_value='capture-token'), \
             patch.object(capture, 'record_chunked', side_effect=recording), \
             patch.object(record.urllib.request, 'urlopen', side_effect=request), \
             contextlib.redirect_stdout(io.StringIO()):
            record.main()
        self.assertEqual(calls, [
            ('http://example.invalid/api/services/switch/turn_on',
             {'entity_id': 'switch.capture'}, 'POST', 'Bearer private', 30),
            ('device', str(review.ROOT / 'samples' / 'session'), 86400, 1800, 'capture-token'),
            ('http://example.invalid/api/services/switch/turn_off',
             {'entity_id': 'switch.capture'}, 'POST', 'Bearer private', 30),
        ])

    def test_reads_dotenv_and_respects_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text(
                'DEVICE_IP=file-device\nHA_URL="http://example.invalid"\n'
                'HA_TOKEN=private\nHA_CAPTURE_ENTITY=switch.capture\n')
            with patch.object(review, 'ROOT', root), \
                 patch.dict(os.environ, {'DEVICE_IP': 'env-device'}, clear=True), \
                 patch.object(capture, 'load_token', return_value='token'), \
                 patch.object(capture, 'record_chunked') as recording, \
                 patch.object(record, 'set_capture_switch') as switch, \
                 contextlib.redirect_stdout(io.StringIO()):
                record.main()
            self.assertEqual(recording.call_args.args,
                             ('env-device', str(root / 'samples' / 'session'), 86400, 1800, 'token'))
            self.assertEqual([call.args[1] for call in switch.call_args_list], [True, False])

    def test_switch_is_turned_off_if_recording_fails(self):
        env = {'DEVICE_IP': 'device', 'HA_URL': 'http://example.invalid',
               'HA_TOKEN': 'private', 'HA_CAPTURE_ENTITY': 'switch.capture'}
        with patch.object(review, 'config', return_value=env), \
             patch.object(capture, 'load_token', return_value='token'), \
             patch.object(capture, 'record_chunked', side_effect=OSError('disk error')), \
             patch.object(record, 'set_capture_switch') as switch, \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, 'disk error'):
                record.main()
        self.assertEqual([call.args[1] for call in switch.call_args_list], [True, False])

    def test_missing_settings_do_not_touch_switch(self):
        with patch.object(review, 'config', return_value={}), \
             patch.object(record, 'set_capture_switch') as switch:
            with self.assertRaisesRegex(ValueError, 'DEVICE_IP.*HA_URL.*HA_TOKEN.*HA_CAPTURE_ENTITY'):
                record.main()
        switch.assert_not_called()


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
