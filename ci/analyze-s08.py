#!/usr/bin/env python3
"""Classify finalized whole-desktop frames against two native-window baselines."""
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys

spec = importlib.util.spec_from_file_location('capture_index', Path(__file__).parent / 'recorders/index-video.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def classify(baseline_a, baseline_b, frame, main, excluded, display):
    if not baseline_a or not baseline_b or not frame or baseline_a[:2] != frame[:2] or baseline_b[:2] != frame[:2]:
        return 'unclassified'
    width, height, _ = frame
    dx, dy, dw, dh = display
    if dw <= 0 or dh <= 0:
        return 'unclassified'
    def pixel(image, x, y):
        channels = len(image[2]) // (width * height)
        offset = (y * width + x) * channels
        return image[2][offset:offset + 3]
    samples = []
    left, top, mw, mh = main
    ex, ey, ew, eh = excluded
    for logical_y in range(int(top + 60), int(top + mh - 16), 8):
        for logical_x in range(int(left + 16), int(left + mw - 16), 8):
            if ex - 8 <= logical_x <= ex + ew + 8 and ey - 8 <= logical_y <= ey + eh + 8:
                continue
            x, y = int((logical_x - dx) * width / dw), int((logical_y - dy) * height / dh)
            if not (0 <= x < width and 0 <= y < height):
                continue
            a, b, current = pixel(baseline_a, x, y), pixel(baseline_b, x, y), pixel(frame, x, y)
            if max(abs(i - j) for i, j in zip(a, b)) <= 3 and min(a) > 40:
                samples.append((sum(a) / 3, sum(current) / 3))
    if len(samples) < 200:
        return 'unclassified'
    unchanged = sum(abs(a - b) <= 12 for a, b in samples) / len(samples)
    ratio = statistics.median(b / a for a, b in samples)
    uniform = sum(abs(b - a * ratio) <= 8 for a, b in samples) / len(samples)
    if unchanged >= .95:
        return 'clear'
    if .15 <= ratio <= .94 and uniform >= .95:
        return 'scrim'
    return 'unclassified'


def analyze(root):
    video = root / 'video/desktop.mp4'
    result = dict(id='S08-A07', verdict='UNVERIFIED', captureScope='whole-desktop',
                  sourceVideo='video/desktop.mp4', sourceSha256=hashlib.sha256(video.read_bytes()).hexdigest() if video.is_file() else None,
                  method='native-window-two-baseline-stable-pixel-luminance-v1', framesAnalyzed=0,
                  classifiedFrames=0, scrimFrames=0, unclassifiedFrames=0)
    try:
        events = capture.read_json_lines(root / 'recorder/s08-case-events.jsonl')
        baseline = next(row for row in events if row.get('event') == 'scrim-baseline')
        start = next(row for row in events if row.get('event') == 'scrim-interval-start')
        stop = next(row for row in events if row.get('event') == 'scrim-interval-stop')
        if baseline['displayCount'] != 1 or baseline['windowID'] != start['windowID'] or baseline['mainBounds'] != start['mainBounds']:
            raise ValueError('Native window identity, bounds or single-display origin changed')
        images = [capture.read_png_rgb(root / name) for name in baseline['screens']]
        result['baselineSha256'] = [hashlib.sha256((root / name).read_bytes()).hexdigest() for name in baseline['screens']]
        index_status = json.loads((root / 'recorder/capture-index-status.json').read_text())
        if index_status.get('videoSha256') != result['sourceSha256']:
            raise ValueError('Decoded frame index does not match finalized video hash')
        rows = capture.read_json_lines(root / 'video/capture-index.jsonl')
        rows = [row for row in rows if row.get('clockMapping') == 'paired-realtime-monotonic'
                and start['monotonicSeconds'] * 1e9 <= row['timestampNanoseconds'] <= stop['monotonicSeconds'] * 1e9]
        for row in rows:
            measured = classify(*images, capture.read_png_rgb(root / row['relativePath']), start['mainBounds'], start['excludeBounds'], baseline['displayBounds'])
            result['framesAnalyzed'] += 1
            result['unclassifiedFrames'] += measured == 'unclassified'
            result['classifiedFrames'] += measured != 'unclassified'
            result['scrimFrames'] += measured == 'scrim'
        if result['framesAnalyzed'] and not result['unclassifiedFrames']:
            result['verdict'] = 'FAIL' if result['scrimFrames'] else 'PASS'
        result['actual'] = f"Measured frames={result['framesAnalyzed']}, scrim={result['scrimFrames']}, unclassified={result['unclassifiedFrames']}"
    except (OSError, KeyError, ValueError, StopIteration, TypeError) as error:
        result['actual'] = f'UNVERIFIED: baseline/capture calibration unavailable: {error}'
    return result

if __name__ == '__main__':
    root = Path(sys.argv[1])
    (root / 'recorder/s08-screen-analysis.json').write_text(json.dumps({'results': [analyze(root)]}, indent=2) + '\n')
