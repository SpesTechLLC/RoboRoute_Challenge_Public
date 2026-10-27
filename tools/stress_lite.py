#!/usr/bin/env python3
"""Reproduce public Lite inputs by stratified sampling of the six Full inputs."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roboroute.dataset import load_dataset, write_dataset
from tools.benchmark import fingerprint
from tools.mock_stress import FULL_DATASETS
from tools.reference_solver import solve_dataset
from tools.stress_dataset import INPUTS, components, flat_answers, save_json

VERSION = 1
QUERY_COUNTS = (16, 20, 24, 40, 128, 128)


def strata(dataset, answers):
    """Keep unreachable, same-cell, direct and detour cases, plus distance quartiles."""
    classes = defaultdict(list)
    for index, (query, answer) in enumerate(zip(dataset.queries, answers)):
        sx, sy, gx, gy = query
        manhattan = abs(sx - gx) + abs(sy - gy)
        kind = ('unreachable' if answer < 0 else 'same_cell' if answer == 0
                else 'detour' if answer > manhattan else 'direct')
        classes[kind].append(index)
    buckets = {}
    for kind, indices in sorted(classes.items()):
        indices.sort(key=lambda index: (answers[index], index))
        # Splitting rare exceptions into four buckets would overrepresent them.
        bins = 4 if kind in ('direct', 'detour') and len(indices) >= 8 else 1
        for rank, index in enumerate(indices):
            buckets.setdefault((kind, rank * bins // len(indices)), []).append(index)
    return buckets


def select_queries(dataset, answers, count):
    buckets = strata(dataset, answers)
    if len(answers) != len(dataset.queries) or not len(buckets) <= count <= len(answers):
        raise ValueError('Require matching answers and enough queries for every stratum.')
    # At least one case from every nonempty stratum, then proportional allocation.
    ideal = {key: count * len(rows) / len(answers) for key, rows in buckets.items()}
    quotas = {key: 1 for key in buckets}
    while sum(quotas.values()) < count:
        key = max((key for key in buckets if quotas[key] < len(buckets[key])),
                  key=lambda key: (ideal[key] - quotas[key], key))
        quotas[key] += 1
    source_starts = len({q[:2] for q in dataset.queries}) / len(answers)
    source_goals = len({q[2:] for q in dataset.queries}) / len(answers)
    starts, goals, selected = set(), set(), []
    chosen = {key: 0 for key in buckets}
    available = {key: set(rows) for key, rows in buckets.items()}
    for step in range(1, count + 1):
        key = max((key for key in buckets if chosen[key] < quotas[key]),
                  key=lambda key: (step * quotas[key] / count - chosen[key], key))
        rank = {index: pos for pos, index in enumerate(buckets[key])}
        target_rank = (chosen[key] + .5) * len(rank) / quotas[key] - .5

        def cost(index):
            query = dataset.queries[index]
            # Prefer shared endpoints where the original distribution repeats them.
            start_error = abs(len(starts) + (query[:2] not in starts) - max(1, round(step * source_starts)))
            goal_error = abs(len(goals) + (query[2:] not in goals) - max(1, round(step * source_goals)))
            return start_error + goal_error, abs(rank[index] - target_rank), index

        index = min(available[key], key=cost)
        available[key].remove(index)
        chosen[key] += 1
        selected.append(index)
        starts.add(dataset.queries[index][:2])
        goals.add(dataset.queries[index][2:])
    return sorted(selected)


def describe(dataset, answers):
    n = len(answers)
    reachable = [a for a in answers if a >= 0]
    _, groups = components(dataset.grid)
    return dict(width=dataset.width, height=dataset.height, query_count=n,
                component_count=len(groups), unreachable=answers.count(-1),
                same_cell=answers.count(0),
                detour_count=sum(a > abs(q[0] - q[2]) + abs(q[1] - q[3])
                                 for q, a in zip(dataset.queries, answers)),
                start_duplicate_fraction=1 - len({q[:2] for q in dataset.queries}) / n,
                goal_duplicate_fraction=1 - len({q[2:] for q in dataset.queries}) / n,
                repeated_pairs=n - len(set(dataset.queries)),
                distance_reachable=dict(min=min(reachable), median=median(reachable), max=max(reachable)))


def generate_all(output):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError(f'Refusing to overwrite {output}')
    output.mkdir(parents=True)
    manifest = dict(schema_version=VERSION, selection='reachability/path-type/distance-quartiles/endpoint-reuse',
                    generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    python=sys.version, datasets=[])
    for name, count in zip(FULL_DATASETS, QUERY_COUNTS):
        source = ROOT / 'datasets' / name
        dataset = load_dataset(source)
        answers = solve_dataset(dataset)
        indices = select_queries(dataset, answers, count)
        destination = output / (name + '_lite')
        write_dataset(destination, dataset.grid, [dataset.queries[index] for index in indices], dataset.metadata['seed'])
        # Retain the source map's exact bytes as well as its geometry.
        shutil.copyfile(source / 'map.csv', destination / 'map.csv')
        metadata = json.loads((destination / 'metadata.json').read_text())
        metadata['stress_lite'] = dict(version=VERSION, source_dataset=name,
                                       source_sha256=fingerprint(source, INPUTS), query_indices=indices)
        save_json(destination / 'metadata.json', metadata)
        lite = load_dataset(destination)
        expected = [answers[index] for index in indices]
        if flat_answers(lite) != expected:
            raise ValueError(f'Independent flat BFS disagrees: {name}')
        if set(strata(dataset, answers)) != set(strata(lite, expected)):
            raise ValueError(f'Lite lost a query stratum: {name}')
        manifest['datasets'].append(dict(dataset_id=destination.name,
                                        source=describe(dataset, answers), lite=describe(lite, expected),
                                        sha256=fingerprint(destination, INPUTS),
                                        answers_sha256=hashlib.sha256(''.join(f'{a}\n' for a in expected).encode()).hexdigest(),
                                        query_indices=indices))
        print(f'Validated {destination.name}: {count}/{len(answers)} queries', flush=True)
    save_json(output / 'manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing directories are never overwritten')
    args = parser.parse_args()
    try:
        generate_all(args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
