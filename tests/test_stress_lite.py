"""Published Lite inputs retain the source maps and representative query cases."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from roboroute.dataset import load_dataset
from tools.benchmark import ROOT, fingerprint
from tools.mock_stress import FULL_DATASETS
from tools.reference_solver import solve_dataset
from tools.stress_dataset import INPUTS, flat_answers
from tools.stress_lite import QUERY_COUNTS, generate_all, select_queries


class LiteDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / 'docs/mock_stress/lite-manifest.json').read_text())
        cls.answers = {}
        for name in FULL_DATASETS:
            ds = load_dataset(ROOT / 'datasets' / (name + '_lite'))
            answers = solve_dataset(ds)
            if answers != flat_answers(ds):
                raise AssertionError(f'Independent oracles disagree: {name}')
            cls.answers[name] = answers

    def test_all_six_are_byte_identical_maps_and_subsets_with_provenance(self):
        for name, count, record in zip(FULL_DATASETS, QUERY_COUNTS, self.manifest['datasets']):
            with self.subTest(name=name):
                source = ROOT / 'datasets' / name
                path = ROOT / 'datasets' / (name + '_lite')
                full, lite = load_dataset(source), load_dataset(path)
                provenance = lite.metadata['stress_lite']
                indices = provenance['query_indices']
                self.assertEqual(indices, sorted(set(indices)))
                self.assertEqual(len(indices), count)
                self.assertLess(count, len(full.queries) / 10)
                self.assertEqual(lite.queries, [full.queries[index] for index in indices])
                self.assertEqual((source / 'map.csv').read_bytes(), (path / 'map.csv').read_bytes())
                self.assertEqual(provenance['source_sha256'], fingerprint(source, INPUTS))
                self.assertEqual(record['sha256'], fingerprint(path, INPUTS))
                digest = hashlib.sha256(''.join(f'{a}\n' for a in self.answers[name]).encode()).hexdigest()
                self.assertEqual(record['answers_sha256'], digest)

    def test_query_distributions_keep_the_stress_features(self):
        records = {r['dataset_id']: r['lite'] for r in self.manifest['datasets']}
        for name in (FULL_DATASETS[0], FULL_DATASETS[4]):
            record = records[name + '_lite']
            self.assertEqual(record['start_duplicate_fraction'], 0)
            self.assertEqual(record['goal_duplicate_fraction'], 0)
            self.assertEqual(record['unreachable'], 0)
        self.assertGreater(records[FULL_DATASETS[0] + '_lite']['detour_count'], 0)
        for name in (FULL_DATASETS[1], FULL_DATASETS[5]):
            record = records[name + '_lite']
            self.assertAlmostEqual(record['unreachable'] / record['query_count'], .15, delta=.01)
            self.assertEqual(record['detour_count'] + record['unreachable'], record['query_count'])
            self.assertGreater(record['start_duplicate_fraction'], .05)
            self.assertGreater(record['goal_duplicate_fraction'], .05)
        large_detour = records[FULL_DATASETS[5] + '_lite']
        self.assertGreater(large_detour['start_duplicate_fraction'], .45)
        self.assertGreater(large_detour['goal_duplicate_fraction'], .45)
        maze = records[FULL_DATASETS[2] + '_lite']
        self.assertGreater(maze['distance_reachable']['median'], 5000)
        self.assertGreater(maze['distance_reachable']['max'], 10000)
        islands = records[FULL_DATASETS[3] + '_lite']
        self.assertEqual(islands['component_count'], 4)
        self.assertAlmostEqual(islands['unreachable'] / islands['query_count'], .4, delta=.03)
        self.assertGreater(islands['same_cell'], 0)
        self.assertGreater(islands['detour_count'], 0)
        self.assertAlmostEqual(islands['start_duplicate_fraction'], .2, delta=.03)
        self.assertAlmostEqual(islands['goal_duplicate_fraction'], .2, delta=.03)

    def test_sampling_is_deterministic_and_does_not_overwrite(self):
        for name in FULL_DATASETS:
            ds = load_dataset(ROOT / 'datasets' / (name + '_lite'))
            # Resampling a whole subset must retain every row, without duplicates.
            self.assertEqual(select_queries(ds, self.answers[name], len(ds.queries)), list(range(len(ds.queries))))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                generate_all(Path(tmp))


if __name__ == '__main__':
    unittest.main()
