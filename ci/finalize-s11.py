#!/usr/bin/env python3
"""Reduce the S11 FRAME observation only from finalized presentation links."""
import json
from pathlib import Path
import sys


def finalize(root):
    path = root / 'recorder/observations.json'
    if not path.is_file():
        return
    observation = json.loads(path.read_text())
    events = []
    event_path = root / 'recorder/renderer-events.jsonl'
    if event_path.is_file():
        events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()]
    sequences = {row.get('detail', {}).get('fields', {}).get('sequence') for row in events
                 if row.get('detail', {}).get('name') == 's11.native-event'} - {None, 0}
    links_path = root / 'recorder/presentation-links.jsonl'
    links = [json.loads(line) for line in links_path.read_text().splitlines() if line.strip()] if links_path.is_file() else []
    calibration_path = root / 'recorder/capture-index-status.json'
    calibration = json.loads(calibration_path.read_text()) if calibration_path.is_file() else {}
    if calibration.get('clockCalibrated') is not True:
        links = []
    matches = {row.get('sequence') for row in links if row.get('status') == 'correlated'}
    late = {row.get("sequence") for row in links if row.get("status") == "measured-late"} & sequences
    complete = bool(sequences) and sequences <= matches
    for key in observation.get('assertions', {}):
        if key.endswith('-FRAME'):
            observation['assertions'][key] = {
                'verdict': 'FAIL' if late else 'PASS' if complete else 'UNVERIFIED',
                'actual': f'Native sequences={sorted(sequences)}; calibrated first-presentation joins={sorted(matches)}; late sequences={sorted(late)}; every sequence within one measured refresh={complete}.',
                'evidence': ['recorder/renderer-events.jsonl', 'recorder/presentation-links.jsonl', 'video/capture-index.jsonl'],
            }
    path.write_text(json.dumps(observation, indent=2) + '\n')

if __name__ == '__main__':
    finalize(Path(sys.argv[1]))
