#!/usr/bin/env python3
"""Record a 24-hour session, managing the Audio Capture switch through HA."""
import json
import urllib.request

import capture
import review


def set_capture_switch(env, enabled):
    action = 'turn_on' if enabled else 'turn_off'
    request = urllib.request.Request(
        env['HA_URL'].rstrip('/') + '/api/services/switch/' + action,
        data=json.dumps({'entity_id': env['HA_CAPTURE_ENTITY']}).encode(),
        headers={'Authorization': 'Bearer ' + env['HA_TOKEN'],
                 'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def main():
    env = review.config()
    missing = [key for key in ('DEVICE_IP', 'HA_URL', 'HA_TOKEN', 'HA_CAPTURE_ENTITY')
               if not env.get(key)]
    if missing:
        raise ValueError('set ' + ', '.join(missing) + ' in .env or the environment')
    if not env['HA_CAPTURE_ENTITY'].startswith('switch.'):
        raise ValueError('HA_CAPTURE_ENTITY must be a switch entity ID')
    token = capture.load_token()
    try:
        set_capture_switch(env, True)
        print('Audio Capture enabled; press Ctrl-C to stop.')
        capture.record_chunked(env['DEVICE_IP'], str(review.ROOT / 'samples' / 'session'),
                               86400, 30 * 60, token)
    finally:
        set_capture_switch(env, False)
        print('Audio Capture disabled.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(f'Error: {error}') from error
