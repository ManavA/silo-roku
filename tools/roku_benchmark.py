#!/usr/bin/env python3
"""Summarize paired native Roku timing evidence without hiding failed trials.

Input reports contain scenario, conditions (device/server/cache/item setup), and
samples_ms (positive elapsed milliseconds, or null for an unsuccessful trial).
Keep private hosts, item identifiers, credentials and signed URLs out of reports.
Capture native readiness separately from screenshot/artwork completion. A native
Video play state plus advancing position establishes playback startup, not
physical HDR, audible audio or long-session stability.
"""
import argparse
import json
import math
import statistics
from pathlib import Path


def summarize(samples):
    if not isinstance(samples, list) or not samples:
        raise ValueError('at least one timing trial is required')
    valid = []
    for value in samples:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('timings must be positive finite milliseconds or null')
        valid.append(value)
    return {'trials': len(samples), 'successes': len(valid),
            'failures': len(samples) - len(valid),
            'median_ms': statistics.median(valid) if valid else None,
            'min_ms': min(valid) if valid else None,
            'max_ms': max(valid) if valid else None}


def compare(before, after):
    for key in ('scenario', 'conditions'):
        if not before.get(key) or before.get(key) != after.get(key):
            raise ValueError('comparison requires matching ' + key)
    baseline = summarize(before['samples_ms'])
    candidate = summarize(after['samples_ms'])
    delta = percent = None
    if baseline['median_ms'] is not None and candidate['median_ms'] is not None:
        delta = candidate['median_ms'] - baseline['median_ms']
        percent = delta / baseline['median_ms'] * 100
    return {'scenario': before['scenario'], 'before': baseline, 'after': candidate,
            'median_delta_ms': delta, 'median_delta_percent': percent,
            'failure_delta': candidate['failures'] - baseline['failures']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    try:
        result = compare(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
