#!/usr/bin/env python3
"""Reduce the S11 FRAME observation only from finalized presentation links."""
import json
from pathlib import Path
import sys


def finalize(root):
    path = root / 'recorder/observations.json'
    if not path.is_file():
        return
    observation = json.loads(path.read_text(encoding='utf-8-sig'))
    invalid = []

    def rows(path):
        records = []
        if path.is_file():
            for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('record must be an object')
                    records.append(row)
                except ValueError as error:
                    invalid.append({'path': str(path.relative_to(root)), 'line': number, 'error': str(error)})
        return records

    events = []
    event_path = root / 'recorder/renderer-events.jsonl'
    if event_path.is_file():
        events = rows(event_path)
    sequences = {row.get('detail', {}).get('fields', {}).get('sequence') for row in events
                 if row.get('detail', {}).get('name') == 's11.native-event'} - {None, 0}
    links_path = root / 'recorder/presentation-links.jsonl'
    links = rows(links_path)
    (root / 'recorder/s11-json-integrity.json').write_text(json.dumps({'valid': not invalid, 'errors': invalid}, indent=2) + '\n')
    calibration_path = root / 'recorder/capture-index-status.json'
    calibration = json.loads(calibration_path.read_text(encoding='utf-8-sig')) if calibration_path.is_file() else {}
    if calibration.get('clockCalibrated') is not True:
        links = []
    matches = {row.get('sequence') for row in links if row.get('status') == 'correlated'}
    late = {row.get("sequence") for row in links if row.get("status") == "measured-late"} & sequences
    complete = not invalid and bool(sequences) and sequences <= matches
    for key in observation.get('assertions', {}):
        if key.endswith('-FRAME'):
            observation['assertions'][key] = {
                'verdict': 'UNVERIFIED' if invalid else 'FAIL' if late else 'PASS' if complete else 'UNVERIFIED',
                'actual': f'JSON integrity errors={invalid}; Native sequences={sorted(sequences)}; calibrated first-presentation joins={sorted(matches)}; late sequences={sorted(late)}; every sequence within one measured refresh={complete}.',
                'evidence': ['recorder/renderer-events.jsonl', 'recorder/presentation-links.jsonl', 'video/capture-index.jsonl'],
            }
    path.write_text(json.dumps(observation, indent=2) + '\n')

if __name__ == '__main__':
    finalize(Path(sys.argv[1]))
