"""Offline, bounded aggregation of Momiq's private-safe HTTP JSON lines."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from request_logging import ADMIN_GROUPS, CLIENT_GROUPS, METHODS, OUTCOMES

MAX_BYTES = 32 * 1024 * 1024
MAX_LINES = 100_000
MAX_LINE_BYTES = 4096
GROUPS = CLIENT_GROUPS | {'other', 'admin-assets', 'admin/other'} | {
    'admin/' + group for group in ADMIN_GROUPS
}
REQUIRED = {'event', 'method', 'group', 'status'}
ALLOWED = REQUIRED | {'durationMs', 'outcome'}


class ReportError(ValueError):
    """No input content or local paths belong in an error message."""


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate field')
        value[key] = item
    return value


def _record(line):
    try:
        value = json.loads(line.decode('utf-8'), object_pairs_hook=_unique_object)
        if not isinstance(value, dict) or not REQUIRED <= value.keys() <= ALLOWED:
            return None
        if value['event'] != 'http':
            return None
        if value['method'] not in METHODS | {'OTHER'} or value['group'] not in GROUPS:
            return None
        status = value['status']
        if type(status) is not int or not (status == 0 or 100 <= status <= 599):
            return None
        if 'outcome' in value and value['outcome'] not in OUTCOMES:
            return None
        elapsed = value.get('durationMs')
        if elapsed is not None and (type(elapsed) not in (int, float)
                                   or not math.isfinite(elapsed) or not 0 <= elapsed <= 86_400_000):
            return None
        return value
    except (ValueError, TypeError, RecursionError, OverflowError):
        return None


class _Bucket:
    def __init__(self):
        self.count = 0
        self.statuses = Counter()
        self.outcomes = Counter()
        self.methods = Counter()
        self.durations = []

    def add(self, record):
        self.count += 1
        self.statuses[str(record['status'])] += 1
        self.outcomes[record.get('outcome', 'unspecified')] += 1
        self.methods[record['method']] += 1
        if record.get('durationMs') is not None:
            self.durations.append(record['durationMs'])

    def document(self):
        samples = sorted(self.durations)
        count = len(samples)
        def percentile(fraction):
            return samples[math.ceil(count * fraction) - 1] if count else None
        return {
            'requests': self.count,
            'statusCounts': dict(sorted(self.statuses.items())),
            'outcomeCounts': dict(sorted(self.outcomes.items())),
            'methodCounts': dict(sorted(self.methods.items())),
            'handlerDurationMs': {
                'samples': count, 'missing': self.count - count,
                'p50': percentile(.50), 'p95': percentile(.95), 'p99': percentile(.99),
                'max': samples[-1] if count else None,
            },
        }


def summarize(stream):
    """Read binary JSON lines. Reject limits atomically; never return a partial report."""
    total = _Bucket()
    groups = {}
    lines = size = rejected = 0
    while True:
        line = stream.readline(MAX_LINE_BYTES + 1)
        if not line:
            break
        lines += 1
        size += len(line)
        if len(line) > MAX_LINE_BYTES or lines > MAX_LINES or size > MAX_BYTES:
            raise ReportError('Input exceeds report limits; use a smaller log slice.')
        record = _record(line)
        if record is None:
            rejected += 1
            continue
        total.add(record)
        groups.setdefault(record['group'], _Bucket()).add(record)
    if not total.count:
        raise ReportError('No valid HTTP diagnostic records found.')
    return {
        'schemaVersion': 1,
        'scope': 'supplied-log-lines',
        'percentileMethod': 'nearest-rank',
        'inputLines': lines,
        'rejectedLines': rejected,
        'total': total.document(),
        'groups': {name: bucket.document() for name, bucket in sorted(groups.items())},
    }


def assess(report, group, min_requests, max_failure_percent, max_p95_ms):
    bucket = report['total'] if group is None else report['groups'].get(group)
    result = {'group':group, 'minRequests':min_requests,
              'maxFailurePercent':max_failure_percent, 'maxP95Ms':max_p95_ms}
    if report['rejectedLines'] or not bucket or bucket['requests'] < min_requests:
        return {**result, 'status':'insufficient'}, 2
    duration = bucket['handlerDurationMs']
    if max_p95_ms is not None and duration['missing']:
        return {**result, 'status':'insufficient'}, 2
    failures = sum(count for code, count in bucket['statusCounts'].items()
                   if int(code) == 0 or 500 <= int(code) <= 599)
    count = bucket['requests']
    exceeded = []
    if max_failure_percent is not None and failures*100 > max_failure_percent*count:
        exceeded.append('failurePercent')
    if max_p95_ms is not None and duration['p95'] > max_p95_ms:
        exceeded.append('handlerP95Ms')
    return {**result, 'status':'exceeded' if exceeded else 'within',
            'exceeded':exceeded, 'failedRequests':failures, 'requests':count,
            'handlerP95Ms':duration['p95']}, int(bool(exceeded))


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Invalid arguments; use --help.\n')


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument('input', help='JSON-lines log file, or - for binary stdin')
    parser.add_argument('--group', choices=sorted(GROUPS))
    parser.add_argument('--min-requests', type=int)
    parser.add_argument('--max-failure-percent', type=float, help='Status 0 and HTTP 5xx')
    parser.add_argument('--max-p95-ms', type=float)
    args = parser.parse_args(argv)
    checking = args.max_failure_percent is not None or args.max_p95_ms is not None
    if not checking and (args.group is not None or args.min_requests is not None):
        parser.error('A threshold is required')
    if ((args.max_failure_percent is not None and not 0 <= args.max_failure_percent <= 100)
            or (args.max_p95_ms is not None and not 0 <= args.max_p95_ms <= 86_400_000)
            or (args.min_requests is not None and not 1 <= args.min_requests <= MAX_LINES)):
        parser.error('Invalid threshold')
    status = 0
    try:
        if args.input == '-':
            report = summarize(sys.stdin.buffer)
        else:
            with open(args.input, 'rb') as stream:
                report = summarize(stream)
        if checking:
            report['assessment'], status = assess(report, args.group, args.min_requests or 1,
                                                   args.max_failure_percent, args.max_p95_ms)
        print(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False))
    except ReportError as error:
        print(str(error), file=sys.stderr)
        return 2
    except OSError:
        print('Cannot read diagnostics or write report.', file=sys.stderr)
        return 2
    return status


if __name__ == '__main__':
    sys.exit(main())
