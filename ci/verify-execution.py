#!/usr/bin/env python3
"""Fail closed when a platform job produced no native case observations."""
import json
import os
from pathlib import Path


def execution_summary(root):
    finished = []
    events = root / 'events.jsonl'
    if events.is_file():
        for line in events.read_text(encoding='utf-8-sig').splitlines():
            row = json.loads(line)
            if row.get('event') == 'scenario-finished' and type(row.get('automationExit')) is int:
                finished.append({'spike': row.get('spike'), 'caseId': row.get('caseId'),
                                 'automationExit': row['automationExit']})
    rows = []
    for path in sorted((root / 'cells').glob('*/assertions.json')):
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        rows.extend(value.get('results', []))
    observed = sum(isinstance(row, dict) and row.get('laneVerdict', row.get('verdict')) in {'PASS', 'FAIL'}
                   for row in rows)
    errors = []
    if not finished:
        errors.append('No case completed execution; fallback emission is not execution.')
    if not observed:
        errors.append('Every assertion is fallback UNVERIFIED or no assertions were emitted.')
    return {'executedCases': finished, 'nativeAssertionObservations': observed, 'errors': errors}


def main():
    root = Path(os.environ.get('SHELL_EVIDENCE_DIR', 'evidence'))
    try:
        summary = execution_summary(root)
    except (OSError, ValueError, TypeError) as error:
        summary = {'errors': [str(error)]}
    root.mkdir(parents=True, exist_ok=True)
    (root / 'execution-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return int(bool(summary['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
