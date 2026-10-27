"""Aggregate scoring, CLI compatibility and the reused benchmark's failure paths."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import mock_stress as stress, rr_cli
from tools.isolated_runner import EnvironmentUnavailable, RunResult


def measurement(mode='full'):
    baseline = (2., 8., 1., 16., 4., 9.)
    speedups = (4., 1., .25, 2., .5, 1.)  # Product=1; time ratio is different.

    def side(seconds, peak):
        return dict(status='OK', median_seconds=seconds, memory_peak_mib=peak,
                    runs=[dict(status='OK', elapsed_seconds=seconds * factor, memory_peak_mib=peak)
                          for factor in (.8, 1.2, 1., .9, 1.1)])

    return dict(status='COMPLETE', datasets=[
        dict(dataset_id=name, baseline=side(b, 10), team=side(b / s, 20 + index), speedup=s)
        for index, (name, b, s) in enumerate(zip(stress.MODES[mode], baseline, speedups))])


class AggregateTests(unittest.TestCase):
    def test_geometric_mean_and_time_ratio_are_distinct(self):
        result = stress.summarize(measurement(), 'full')
        summary = result['summary']
        self.assertEqual(summary['status'], 'VALID')
        self.assertEqual(summary['correct_datasets'], 6)
        self.assertAlmostEqual(summary['geometric_mean_speedup'], 1.)
        self.assertAlmostEqual(summary['total_time_ratio'], 40 / 37.5)
        self.assertEqual(summary['team_memory_peak_mib'], 25)
        self.assertFalse(result['official_score'])

    def test_any_one_bad_run_invalidates_both_aggregate_metrics(self):
        for status in ('WRONG_ANSWER', 'MEMORY_EXCEEDED', 'RUNTIME_ERROR', 'OUTPUT_LIMIT', 'LEFTOVER_PROCESSES'):
            with self.subTest(status=status):
                raw = measurement()
                raw['datasets'][3]['team'].update(status=status, median_seconds=None)
                raw['datasets'][3]['team']['runs'][2]['status'] = status
                result = stress.summarize(raw, 'full')
                summary = result['summary']
                self.assertEqual(result['status'], 'COMPLETE')
                self.assertEqual(summary['status'], 'INVALID')
                self.assertEqual(summary['correct_datasets'], 5)
                self.assertIsNone(summary['geometric_mean_speedup'])
                self.assertIsNone(summary['total_time_ratio'])
                self.assertIn(status, summary['reasons'][0])
                self.assertIn('3回目', summary['reasons'][0])
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(stress.display_stress(result), 1)
                self.assertIn(status, output.getvalue())

    def test_all_five_runs_must_pass_even_if_side_claims_ok(self):
        raw = measurement()
        raw['datasets'][0]['team']['runs'][0]['status'] = 'WRONG_ANSWER'
        self.assertFalse(stress.summarize(raw, 'full')['summary']['valid'])

    def test_environment_failure_is_incomplete_not_invalid(self):
        raw = measurement()
        raw.update(status='INCOMPLETE', error='namespace unavailable')
        result = stress.summarize(raw, 'full')
        self.assertEqual(result['summary']['status'], 'INCOMPLETE')
        self.assertIsNone(result['summary']['geometric_mean_speedup'])
        self.assertIn('namespace unavailable', result['summary']['reasons'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(stress.display_stress(result), 2)

    def test_missing_duplicate_or_bad_baseline_records_are_incomplete(self):
        bad = []
        missing = measurement()
        missing['datasets'].pop()
        bad.append(missing)
        duplicate = measurement()
        duplicate['datasets'][5]['dataset_id'] = stress.FULL_DATASETS[0]
        bad.append(duplicate)
        baseline = measurement()
        baseline['datasets'][0]['baseline']['runs'][4]['status'] = 'RUNTIME_ERROR'
        bad.append(baseline)
        for raw in bad:
            self.assertEqual(stress.summarize(raw, 'full')['summary']['status'], 'INCOMPLETE')

    def test_partial_runs_are_printable_and_unmeasured_peak_is_not_zero(self):
        raw = dict(status='INCOMPLETE', datasets=[], error='worker failed')
        result = stress.summarize(raw, 'lite')
        self.assertIsNone(result['summary']['team_memory_peak_mib'])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(stress.display_stress(result), 2)
        partial = dict(dataset_id=stress.MODES['lite'][0], team=dict(runs=[
            dict(status='OK', memory_peak_mib=42, elapsed_seconds=1.)]))
        raw['datasets'].append(partial)
        result = stress.summarize(raw, 'lite')
        self.assertFalse(partial['correct'])
        self.assertEqual(result['summary']['team_memory_peak_mib'], 42)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(stress.display_stress(result), 2)

    def test_invalid_timings_do_not_produce_speedup(self):
        for value in (0, -1, None, math.inf, math.nan):
            raw = measurement()
            raw['datasets'][0]['team']['median_seconds'] = value
            result = stress.summarize(raw, 'full')
            self.assertEqual(result['summary']['status'], 'INCOMPLETE')
            self.assertIsNone(result['summary']['geometric_mean_speedup'])


class ReusedBenchmarkTests(unittest.TestCase):
    def evaluate(self, failure=None):
        calls = []

        def runner(program, entry, dataset, *, memory_mib, safety_stop):
            calls.append((Path(program), Path(entry), Path(dataset).name, memory_mib, safety_stop))
            is_team = Path(program) == self.program
            status = failure if is_team and len(calls) == 2 and failure else 'OK'
            if status == 'ENVIRONMENT':
                raise EnvironmentUnavailable('bootstrap failed')
            out = '999\n' if status == 'WRONG_ANSWER' else '7\n'
            return RunResult('OK' if status == 'WRONG_ANSWER' else status,
                             1. if is_team else 2., 12., 10., memory_mib,
                             1 if status == 'RUNTIME_ERROR' else 0, out, '', {})

        with tempfile.TemporaryDirectory() as tmp:
            self.program = Path(tmp) / 'work'
            self.program.mkdir()
            (self.program / 'main.py').write_text('print(7)\n')
            with patch('tools.benchmark.run_isolated', side_effect=runner), \
                 patch('tools.benchmark.solve_dataset', return_value=[7]):
                result = stress.evaluate_stress(self.program, 'full', safety_stop=60, team_id='test')
        return result, calls

    def test_reuses_five_run_interleaving_and_128_mib(self):
        result, calls = self.evaluate()
        self.assertTrue(result['summary']['valid'])
        self.assertEqual(len(calls), 60)
        self.assertTrue(all(call[3:] == (128, 60) for call in calls))
        for index, name in enumerate(stress.FULL_DATASETS):
            segment = calls[index * 10:(index + 1) * 10]
            self.assertTrue(all(call[2] == name for call in segment))
            self.assertEqual([call[0] == self.program for call in segment],
                             [False, True, True, False, False, True, True, False, False, True])
        self.assertAlmostEqual(result['summary']['geometric_mean_speedup'], 2.)
        self.assertEqual(result['repetitions'], 5)
        self.assertEqual(result['memory_limit_mib'], 128)

    def test_participant_failures_still_measure_all_six(self):
        for status in ('WRONG_ANSWER', 'MEMORY_EXCEEDED', 'RUNTIME_ERROR'):
            with self.subTest(status=status):
                result, calls = self.evaluate(status)
                self.assertEqual(len(calls), 60)
                self.assertEqual(result['summary']['status'], 'INVALID')
                self.assertEqual(result['summary']['correct_datasets'], 5)
                self.assertIn(status, result['summary']['reasons'][0])

    def test_bootstrap_failure_and_operator_stop_are_incomplete(self):
        for status in ('ENVIRONMENT', 'OPERATOR_STOP'):
            result, calls = self.evaluate(status)
            self.assertEqual(result['summary']['status'], 'INCOMPLETE')
            self.assertEqual(len(calls), 2)
            self.assertIsNone(result['summary']['geometric_mean_speedup'])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / 'existing-work'
        self.work.mkdir()
        (self.work / 'main.py').write_text('print(7)\n')
        self.output = self.root / 'result.json'

    def run_cli(self, arguments):
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            code = rr_cli.main(arguments)
        return code, output.getvalue()

    def test_both_modes_use_existing_work_and_save_json(self):
        for mode in ('lite', 'full'):
            result = stress.summarize(measurement(mode), mode)
            with patch.object(rr_cli, 'evaluate_stress', return_value=result) as evaluate:
                code, output = self.run_cli(['--_worker', 'mock-stress', '--' + mode,
                                             '--work', str(self.work), '--result', str(self.output), '--team', 'team01'])
            self.assertEqual(code, 0)
            self.assertIn('180秒', output)
            self.assertIn('幾何平均', output)
            evaluate.assert_called_once_with(self.work, mode, None, team_id='team01')
            self.assertEqual(json.loads(self.output.read_text())['summary']['status'], 'VALID')
            self.assertEqual((self.work / 'main.py').read_text(), 'print(7)\n')

    def test_mode_is_explicit_and_mutually_exclusive(self):
        for flags in ([], ['--lite', '--full']):
            with self.assertRaises(SystemExit) as error:
                self.run_cli(['mock-stress', *flags])
            self.assertEqual(error.exception.code, 2)

    def test_service_forwarding_and_default_mode_filename(self):
        result = stress.summarize(measurement('lite'), 'lite')

        def service(arguments):
            self.assertEqual(arguments[:3], ['mock-stress', '--work', str(self.work)])
            self.assertIn('--lite', arguments)
            self.assertIn('--team', arguments)
            self.assertIn('--safety-stop', arguments)
            dest = Path(arguments[arguments.index('--result') + 1])
            self.assertTrue(dest.name.startswith('mock-stress-lite-'))
            self.assertEqual(json.loads(dest.read_text())['summary']['status'], 'INCOMPLETE')
            dest.write_text(json.dumps(result))
            return 0

        with patch.object(rr_cli, 'ROOT', self.root), patch.object(rr_cli, '_inside_delegation', return_value=False), \
             patch.object(rr_cli, 'run_service', side_effect=service):
            code, _ = self.run_cli(['mock-stress', '--lite', '--work', str(self.work),
                                    '--team', 'team01', '--safety-stop', '60'])
        self.assertEqual(code, 0)
        self.assertEqual(len(list((self.root / 'results').glob('mock-stress-lite-*.json'))), 1)

    def test_failed_service_and_exceptions_save_incomplete(self):
        with patch.object(rr_cli, '_inside_delegation', return_value=False), \
             patch.object(rr_cli, 'run_service', return_value=9):
            code, output = self.run_cli(['mock-stress', '--full', '--work', str(self.work), '--result', str(self.output)])
        self.assertEqual(code, 2)
        self.assertIn('INCOMPLETE', output)
        self.assertEqual(json.loads(self.output.read_text())['summary']['status'], 'INCOMPLETE')
        with patch.object(rr_cli, 'evaluate_stress', side_effect=EnvironmentUnavailable('no cgroup')):
            code, _ = self.run_cli(['--_worker', 'mock-stress', '--lite', '--work', str(self.work), '--result', str(self.output)])
        saved = json.loads(self.output.read_text())
        self.assertEqual(code, 2)
        self.assertEqual(saved['summary']['status'], 'INCOMPLETE')
        self.assertIn('no cgroup', saved['summary']['reasons'])

    def test_existing_mock_and_bench_routing_is_unchanged(self):
        for command in ('mock', 'bench'):
            raw = measurement()
            with patch.object(rr_cli, 'evaluate', return_value=deepcopy(raw)) as evaluate, \
                 patch.object(rr_cli, 'dataset_path', return_value=rr_cli.ROOT / 'datasets/practice'):
                code, output = self.run_cli(['--_worker', command, '--work', str(self.work), '--result', str(self.output)])
            self.assertEqual(code, 0)
            self.assertNotIn('幾何平均', output)
            expected = ([rr_cli.ROOT / 'datasets' / name for name in rr_cli.MOCK_DATASETS]
                        if command == 'mock' else [rr_cli.ROOT / 'datasets/practice'])
            self.assertEqual(evaluate.call_args.args[2], expected)
            self.assertNotIn('summary', json.loads(self.output.read_text()))


if __name__ == '__main__':
    unittest.main()
