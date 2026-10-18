#!/usr/bin/env python3
"""Fail-closed benchmark. Only isolated, correct runs produce measured medians."""
from __future__ import annotations
from dataclasses import asdict
import hashlib
import json
import platform
from pathlib import Path
import shutil
from statistics import median
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roboroute.dataset import load_dataset
from tools.reference_solver import solve_dataset
from tools.isolated_runner import EnvironmentUnavailable, run_isolated
SCORING_METHOD = 'team-median-v1'


def benchmark(program, entry, dataset, *, memory_mib, repetitions=5, safety_stop=None, runner=None, expected_answers=None):
    if repetitions != 5:
        raise ValueError('Official benchmark requires exactly five runs.')
    runner = runner or run_isolated
    expected = solve_dataset(load_dataset(dataset)) if expected_answers is None else expected_answers
    runs = []
    for _ in range(repetitions):
        result = runner(program, entry, dataset, memory_mib=memory_mib, safety_stop=safety_stop)
        # Exactly one signed decimal integer per line, no skipped empty lines.
        if result.status == 'OK':
            try:
                lines = result.stdout.splitlines()
                import re
                valid = all(re.fullmatch(r'-?[0-9]+', line) for line in lines)
                actual = [int(line) for line in lines] if valid else None
            except ValueError:
                actual = None
            if actual != expected:
                result.status = 'WRONG_ANSWER'
        runs.append(asdict(result))
    status = ('OPERATOR_STOP' if any(r['status'] == 'OPERATOR_STOP' for r in runs)
              else next((r['status'] for r in runs if r['status'] != 'OK'), 'OK'))
    # An operator interruption is not a competition failure / zero point result.
    return {'status': status, 'runs': runs,
            'median_seconds': median(r['elapsed_seconds'] for r in runs) if status == 'OK' else None,
            'memory_peak_mib': max(r['memory_peak_mib'] for r in runs),
            'memory_metric': 'cgroup v2 memory.peak (includes descendants, cache and tmpfs; not RSS)'}


def fingerprint(directory, names=None):
    directory = Path(directory)
    files = [directory / n for n in names] if names else sorted(p for p in directory.rglob('*') if p.is_file())
    return {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def baseline_bundle(destination):
    destination.mkdir()
    shutil.copytree(ROOT / 'roboroute', destination / 'roboroute', ignore=shutil.ignore_patterns('__pycache__'))
    (destination / 'solution').mkdir()
    shutil.copyfile(ROOT / 'solution/main.py', destination / 'solution/main.py')
    return destination, Path('solution/main.py')


def evaluate(program, entry, datasets, memory_mib, safety_stop=None, *, team_id=None):
    """Interleave baseline/team runs to reduce systematic warm-cache ordering bias."""
    result = {'schema_version': 2, 'kind': 'benchmark-measurement', 'scoring_method': SCORING_METHOD,
              'team_id': team_id, 'status': 'INCOMPLETE', 'memory_limit_mib': memory_mib,
              'environment': {'python': sys.version, 'executable': str(Path(sys.executable).resolve()), 'kernel': platform.release()},
              'repetitions': 5, 'python': sys.version, 'executable': sys.executable,
              'program_sha256': fingerprint(program), 'datasets': []}
    try:
        with tempfile.TemporaryDirectory(prefix='roboroute-base-') as temporary:
            base, base_entry = baseline_bundle(Path(temporary) / 'program')
            result['baseline_sha256'] = fingerprint(base)
            for dataset in datasets:
                record = {'dataset_id': Path(dataset).resolve().name, 'dataset': str(Path(dataset).resolve()), 'sha256': fingerprint(dataset, ('map.csv', 'queries.csv', 'metadata.json'))}
                result['datasets'].append(record)
                expected = solve_dataset(load_dataset(dataset))
                calls = {'baseline': [], 'team': []}
                for repeat in range(5):
                    for name in (('baseline', 'team') if repeat % 2 == 0 else ('team', 'baseline')):
                        root, main = (base, base_entry) if name == 'baseline' else (program, entry)
                        run = run_isolated(root, main, dataset, memory_mib=memory_mib, safety_stop=safety_stop)
                        calls[name].append(run)
                        record[name] = {'runs': [asdict(r) for r in calls[name]]}
                        if run.status == 'OPERATOR_STOP':
                            raise EnvironmentUnavailable('Operator safety stop; scoring incomplete.')
                for name, root, main in [('baseline', base, base_entry), ('team', program, entry)]:
                    iterator = iter(calls[name])
                    record[name] = benchmark(root, main, dataset, memory_mib=memory_mib,
                                             runner=lambda *a, **kw: next(iterator), expected_answers=expected)
                if record['baseline']['status'] != 'OK':
                    raise EnvironmentUnavailable('Baseline failed; this dataset cannot be scored.')
                team = record['team']
                if team['status'] == 'OPERATOR_STOP':
                    raise EnvironmentUnavailable('Operator safety stop; scoring incomplete.')
                record['speedup'] = record['baseline']['median_seconds'] / team['median_seconds'] if team['status'] == 'OK' else None
            result['status'] = 'COMPLETE'
    except (EnvironmentUnavailable, OSError, ValueError) as error:
        result['error'] = str(error)
    return result

