from contextlib import redirect_stderr, redirect_stdout
from io import BytesIO, StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from request_logging import access_record
from tool import request_report as report


def record(**changes):
    value = {'event': 'http', 'method': 'GET', 'group': 'bookings',
             'status': 200, 'durationMs': 10, 'outcome': 'ok'}
    value.update(changes)
    return json.dumps(value).encode() + b'\n'


class RequestReportTests(unittest.TestCase):
    def test_exact_percentiles_status_zero_and_missing_metrics(self):
        data = b''.join(record(durationMs=n) for n in range(1, 101))
        data += record(group='admin/work-queue', status=503, outcome='database_busy', durationMs=None)
        data += b'{"event":"http","method":"OTHER","group":"other","status":0}\n'
        value = report.summarize(BytesIO(data))
        self.assertEqual(value['inputLines'], 102)
        self.assertEqual(value['rejectedLines'], 0)
        self.assertEqual(value['total']['handlerDurationMs'], {
            'samples': 100, 'missing': 2, 'p50': 50, 'p95': 95, 'p99': 99, 'max': 100})
        self.assertEqual(value['total']['statusCounts'], {'0': 1, '200': 100, '503': 1})
        self.assertEqual(value['total']['outcomeCounts'], {'database_busy': 1, 'ok': 100, 'unspecified': 1})
        self.assertIsNone(value['groups']['other']['handlerDurationMs']['p95'])
        self.assertEqual(value['groups']['bookings']['requests'], 100)

    def test_private_lines_unknown_fields_and_dynamic_labels_never_reappear(self):
        invalid = [b'SECRET traceback PRIVATE path\n', record(url='/PRIVATE?token=SECRET'),
                   record(group='PRIVATE'), record(method='SECRET'), record(outcome='SECRET'),
                   b'{"event":"http","method":"GET","group":"other","status":200,"status":500}\n',
                   b'\xffPRIVATE\n', b'[]\n', b'null\n']
        value = report.summarize(BytesIO(record() + b''.join(invalid)))
        self.assertEqual(value['rejectedLines'], len(invalid))
        self.assertEqual(value['total']['requests'], 1)
        self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertNotIn('SECRET', json.dumps(value))

    def test_invalid_metric_types_and_unhashable_labels_reject_entire_record(self):
        invalid = [record(durationMs=v) for v in [True, -1, '10', float('nan'), float('inf'), 86_400_001, {}, []]]
        invalid += [record(status=v) for v in [True, '200', 200.0, -1, 99, 600, None]]
        invalid += [record(**{field: []}) for field in ['method', 'group', 'outcome']]
        value = report.summarize(BytesIO(record() + b''.join(invalid)))
        self.assertEqual(value['total']['requests'], 1)
        self.assertEqual(value['rejectedLines'], len(invalid))

    def test_byte_line_count_and_line_length_limits_refuse_partial_results(self):
        for limit, value, data in [('MAX_BYTES', len(record()), record() * 2),
                                   ('MAX_LINES', 1, record() * 2),
                                   ('MAX_LINE_BYTES', 32, b'PRIVATE' * 100)]:
            with self.subTest(limit=limit), patch.object(report, limit, value):
                with self.assertRaisesRegex(report.ReportError, 'exceeds report limits'):
                    report.summarize(BytesIO(data))
        with patch.object(report, 'MAX_LINES', 1), patch.object(report, 'MAX_BYTES', len(record())):
            self.assertEqual(report.summarize(BytesIO(record()))['total']['requests'], 1)

    def test_empty_or_no_valid_input_is_an_error_not_a_healthy_zero_report(self):
        for data in [b'', b'PRIVATE\n', b'{"event":"other"}\n']:
            with self.subTest(data=data), self.assertRaisesRegex(report.ReportError, '^No valid HTTP'):
                report.summarize(BytesIO(data))

    def test_existing_logger_records_and_capped_duration_are_compatible(self):
        lines = [access_record('GET', '/api/sitters?phone=PRIVATE', 200, elapsed_seconds=.123, outcome='ok'),
                 access_record('POST', '/api/admin/work-queue/PRIVATE', 503, elapsed_seconds=100_000, outcome='database_busy'),
                 access_record('GET', '/api/me', 200, elapsed_seconds=float('nan'))]
        value = report.summarize(BytesIO(('\r\n'.join(lines)).encode()))
        self.assertEqual(value['total']['requests'], 3)
        self.assertEqual(value['total']['handlerDurationMs']['max'], 86_400_000)
        self.assertEqual(value['groups']['sitters']['handlerDurationMs']['p95'], 123)
        self.assertEqual(value['rejectedLines'], 0)

    def test_thresholds_include_transport_failure_and_refuse_incomplete_samples(self):
        lines = [access_record('GET','/api/sitters',s,elapsed_seconds=.1) for s in (0,503,200,404)]
        data = report.summarize(BytesIO(('\n'.join(lines)+'\n').encode()))
        assessment, code = report.assess(data, 'sitters', 4, 50, 100)
        self.assertEqual((code,assessment['failedRequests']), (0,2))
        assessment, code = report.assess(data, 'sitters', 4, 49.9, 99)
        self.assertEqual((code,assessment['exceeded']), (1,['failurePercent','handlerP95Ms']))
        self.assertEqual(report.assess(data, 'sitters', 5, 100, None)[1], 2)
        self.assertEqual(report.assess(data, 'support', 1, 100, None)[1], 2)
        data['rejectedLines'] = 1
        self.assertEqual(report.assess(data, None, 1, 100, None)[1],2)
        data['rejectedLines'] = 0
        data['total']['handlerDurationMs']['missing'] = 1
        self.assertEqual(report.assess(data,None,1,None,100)[1],2)

    def test_cli_read_only_file_stdin_and_sanitized_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'PRIVATE.log'
            original = record()
            path.write_bytes(original)
            output, error = StringIO(), StringIO()
            with redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(report.main([str(path)]), 0)
            self.assertEqual(json.loads(output.getvalue())['total']['requests'], 1)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(error.getvalue(), '')
            for args in [[str(path / 'SECRET')], ['--SECRET']]:
                output, error = StringIO(), StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    if args[0].startswith('--'):
                        with self.assertRaises(SystemExit) as caught:
                            report.main(args)
                        self.assertEqual(caught.exception.code, 2)
                    else:
                        self.assertEqual(report.main(args), 2)
                self.assertEqual(output.getvalue(), '')
                self.assertNotIn('PRIVATE', error.getvalue())
                self.assertNotIn('SECRET', error.getvalue())
        completed = subprocess.run([sys.executable, 'tool/request_report.py', '-'],
                                   input=record(), capture_output=True, check=True)
        self.assertEqual(json.loads(completed.stdout)['total']['requests'], 1)
        self.assertEqual(completed.stderr, b'')

    def test_cli_limit_and_read_failure_never_emit_partial_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'PRIVATE.log'
            path.write_bytes(record() * 2)
            for failure in ['limit', 'io']:
                output, error = StringIO(), StringIO()
                context = patch.object(report, 'MAX_LINES', 1) if failure == 'limit' else patch('builtins.open', side_effect=OSError('SECRET'))
                with context, redirect_stdout(output), redirect_stderr(error):
                    self.assertEqual(report.main([str(path)]), 2)
                self.assertEqual(output.getvalue(), '')
                self.assertNotIn('SECRET', error.getvalue())
                self.assertNotIn('PRIVATE', error.getvalue())


if __name__ == '__main__':
    unittest.main()
