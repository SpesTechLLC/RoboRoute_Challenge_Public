"""Stress data properties and oracle checks; no changes to runner/scoring."""
from pathlib import Path
import tempfile
import unittest

from roboroute.dataset import load_dataset
from roboroute.solver import solve_all_dijkstra
from tools import stress_dataset as stress
from tools.stress_search_profile import search


class StressDatasetTests(unittest.TestCase):
    def config(self, kind, **updates):
        return dict(kind=kind, width=61, height=61, queries=40, seed=1234,
                    profile='public', **updates)

    def test_all_structures_regenerate_and_agree_with_dijkstra(self):
        for kind in stress.KINDS:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                dataset = stress.generate(Path(tmp)/'data', self.config(kind))
                report = stress.validate(dataset, Path(tmp)/'evidence')
                self.assertTrue(all(report['constraints'].values()))
                ds = load_dataset(dataset)
                expected = [int(line) for line in (Path(tmp)/'evidence/answers.txt').read_text().splitlines()]
                self.assertEqual(expected, solve_all_dijkstra(ds.grid, ds.queries))
                # All three search instruments must agree, including unreachable
                # and same-cell cases. These are operation counts, not rankings.
                for query, answer in zip(ds.queries, expected):
                    for algorithm in ('bfs', 'bidirectional_bfs', 'astar'):
                        self.assertEqual(search(ds, query, algorithm)[0], answer)

    def test_detour_rejects_naive_manhattan_even_with_few_obstacles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = stress.generate(Path(tmp)/'data', self.config('stress_detour'))
            report = stress.validate(path, Path(tmp)/'evidence')
            self.assertLess(report['obstacle_fraction'], .05)
            self.assertGreaterEqual(report['substantial_detour_count'], 30)
            self.assertGreater(report['unreachable'], 0)

    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = stress.generate(Path(tmp)/'data', self.config('stress_open_unique'))
            before = stress.fingerprint(path, stress.INPUTS)
            with self.assertRaises(ValueError):
                stress.generate(path, self.config('stress_open_unique'))
            self.assertEqual(before, stress.fingerprint(path, stress.INPUTS))

    def test_only_public_generation_is_supported(self):
        config = self.config('stress_detour')
        config['profile'] = 'evaluation'
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            stress.generate(Path(tmp)/'unsafe', config)

    def test_incomplete_or_partial_results_are_not_calibration_evidence(self):
        def side():
            return dict(status='OK', runs=[dict(status='OK') for _ in range(5)])
        result = dict(status='COMPLETE', datasets=[dict(baseline=side(), team=side())])
        self.assertTrue(stress.accepted_measurement(result))
        result['status'] = 'INCOMPLETE'
        self.assertFalse(stress.accepted_measurement(result))
        result['status'] = 'COMPLETE'
        result['datasets'][0]['team']['runs'][0]['status'] = 'LEFTOVER_PROCESSES'
        self.assertFalse(stress.accepted_measurement(result))
        result['datasets'][0]['team']['runs'].pop(0)
        self.assertFalse(stress.accepted_measurement(result))

    def test_calibration_changes_queries_before_size_and_stays_within_limits(self):
        config = self.config('stress_open_unique')
        updated = stress.adjusted_config(config, 2, (10, 20))
        self.assertEqual(updated['queries'], 300)
        self.assertEqual(updated['width'], config['width'])
        self.assertEqual(updated['height'], config['height'])
        config.update(queries=2000)
        enlarged = stress.adjusted_config(config, 5, (10, 20))
        self.assertGreater(enlarged['width'], config['width'])
        self.assertEqual(enlarged['queries'], 2000)
        shrunk = stress.adjusted_config(dict(config, queries=24), 40, (10, 20))
        self.assertLess(shrunk['width'], config['width'])
        self.assertGreaterEqual(shrunk['width'], 31)


if __name__ == '__main__':
    unittest.main()
