#!/usr/bin/env python3
"""Reproducible day-two candidates; does not change competition or runner code."""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
from statistics import median
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from roboroute.dataset import load_dataset, validate_limits, write_dataset
from roboroute.generator import generate_map, generate_queries
from tools.benchmark import baseline_bundle, evaluate, fingerprint
from tools.reference_solver import solve_dataset

VERSION = 1
KINDS = ('stress_open_unique', 'stress_detour', 'stress_maze_long', 'stress_islands_mixed')
PUBLIC = [dict(kind=k, width=w, height=h, queries=24, seed=s, profile='public')
          for k, w, h, s in zip(KINDS, (181, 181, 251, 241), (181, 181, 251, 221),
                                (2026102501, 2026102502, 2026102503, 2026102504))]
INPUTS = ('map.csv', 'queries.csv', 'metadata.json')


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def components(grid):
    """Independent flat-index flood fill, also used to guarantee query mixtures."""
    h, w = len(grid), len(grid[0])
    labels = [-1] * (w * h)
    groups = []
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            origin = y * w + x
            if cell or labels[origin] >= 0:
                continue
            label = len(groups)
            labels[origin] = label
            group, queue = [], deque([origin])
            while queue:
                p = queue.popleft()
                group.append((p % w, p // w))
                for q in adjacent(p, w, h):
                    if labels[q] < 0 and not grid[q // w][q % w]:
                        labels[q] = label
                        queue.append(q)
            groups.append(group)
    return labels, groups


def adjacent(p, w, h):
    if p % w:
        yield p - 1
    if p % w < w - 1:
        yield p + 1
    if p >= w:
        yield p - w
    if p < w * (h - 1):
        yield p + w


def flat_answers(dataset):
    """Second oracle: array distances, independent of roboroute.solver helpers."""
    w, h = dataset.width, dataset.height
    labels, _ = components(dataset.grid)
    answers = []
    for sx, sy, gx, gy in dataset.queries:
        start, goal = sy * w + sx, gy * w + gx
        if labels[start] != labels[goal]:
            answers.append(-1)
            continue
        distances = [-1] * (w * h)
        distances[start] = 0
        queue = deque([start])
        while queue:
            p = queue.popleft()
            if p == goal:
                break
            for q in adjacent(p, w, h):
                if distances[q] < 0 and not dataset.grid[q // w][q % w]:
                    distances[q] = distances[p] + 1
                    queue.append(q)
        answers.append(distances[goal])
    return answers


def build(config):
    if config.get('version', VERSION) != VERSION:
        raise ValueError('Unsupported stress generator version.')
    kind = config['kind']
    w, h, n = (config[key] for key in ('width', 'height', 'queries'))
    validate_limits(w, h, n)
    if min(w, h) < 31 or kind not in KINDS:
        raise ValueError('Stress candidates require dimensions >=31 and a supported kind.')
    if type(config['seed']) is not int or config.get('profile') != 'public':
        raise ValueError('An integer seed and public profile are required.')
    rng = random.Random(config['seed'])
    if kind == 'stress_open_unique':
        grid = generate_map(w, h, 'open', rng)
        free = [(x, y) for y in range(h) for x in range(w) if not grid[y][x]]
        used_s, used_g, queries = set(), set(), []
        threshold = (w + h) * .45
        for _ in range(n):
            for _attempt in range(100000):
                s, g = rng.sample(free, 2)
                if s not in used_s and g not in used_g and abs(s[0]-g[0])+abs(s[1]-g[1]) >= threshold:
                    break
            else:
                raise ValueError('Cannot satisfy unique long-distance queries; enlarge map or reduce queries.')
            used_s.add(s)
            used_g.add(g)
            queries.append((*s, *g))
    elif kind == 'stress_detour':
        # One thin wall with a single bottom/top opening; a sealed corner pocket.
        grid = [[0] * w for _ in range(h)]
        wall = w // 2 + rng.randint(-max(1, w//20), max(1, w//20))
        for y in range(h - 2):
            grid[y][wall] = 1
        pocket = max(5, min(w, h) // 12)
        for y in range(pocket + 1):
            grid[y][w - pocket - 1] = 1
        for x in range(w - pocket - 1, w):
            grid[pocket][x] = 1
        queries = []
        for i in range(n):
            if i < max(1, n * 15 // 100):
                s = (rng.randrange(w-pocket, w), rng.randrange(pocket))
                g = (rng.randrange(wall), rng.randrange(h))
            else:
                s = (wall - rng.randint(1, min(9, wall)), rng.randrange(max(1, h//3)))
                g = (wall + rng.randint(1, min(9, w-pocket-2-wall)), rng.randrange(max(1, h//3)))
            if rng.random() < .5:
                s, g = g, s
            queries.append((*s, *g))
        rng.shuffle(queries)
    elif kind == 'stress_maze_long':
        grid = generate_map(w, h, 'maze', rng)
        queries = generate_queries(grid, n, 'long_distance', rng)
    else:
        # Reuse open maps within four quadrants, then add an uninterrupted separator.
        # Large components keep unreachable BFS/Dijkstra queries expensive.
        grid = [[1] * w for _ in range(h)]
        mx, my = w//2 + rng.randint(-w//12, w//12), h//2 + rng.randint(-h//12, h//12)
        for x0, x1 in ((0, mx), (mx+1, w)):
            for y0, y1 in ((0, my), (my+1, h)):
                tile = generate_map(x1-x0, y1-y0, 'open', rng)
                for yy, row in enumerate(tile):
                    grid[y0+yy][x0:x1] = row
        _, groups = components(grid)
        groups = sorted(groups, key=len, reverse=True)[:4]
        if len(groups) != 4:
            raise ValueError('Four large components required.')
        popular = [rng.sample(group, 3) for group in groups]
        queries = []
        for i in range(n):
            a = rng.randrange(4)
            b = (a + rng.randrange(1, 4)) % 4 if i % 10 < 4 else a
            s, g = rng.choice(groups[a]), rng.choice(groups[b])
            if i % 5 == 0:
                s = rng.choice(popular[a])
            if i % 5 == 1:
                g = rng.choice(popular[b])
            if i % 40 == 39:
                g = s  # Explicit same-cell correctness cases.
            queries.append((*s, *g))
        rng.shuffle(queries)
    return grid, queries


def guard_destination(output):
    resolved = Path(output).resolve()
    if resolved.exists():
        raise ValueError(f'Refusing to overwrite {resolved}')
    return resolved


def generate(output, config):
    output = guard_destination(output)
    grid, queries = build(config)
    write_dataset(output, grid, queries, config['seed'])
    metadata = json.loads((output / 'metadata.json').read_text())
    metadata['stress_generator'] = {'version': VERSION, **config}
    save_json(output / 'metadata.json', metadata)
    load_dataset(output)
    return output


def describe(values):
    if not values:
        return None
    return dict(min=min(values), median=median(values), max=max(values), mean=sum(values)/len(values))


def validate(directory, evidence):
    ds = load_dataset(directory)  # All size, byte, metadata and endpoint limits.
    reference = solve_dataset(ds)
    independent = flat_answers(ds)
    if reference != independent:
        raise ValueError('Reference BFS and independent flat BFS disagree.')
    labels, groups = components(ds.grid)
    starts = [(q[0], q[1]) for q in ds.queries]
    goals = [(q[2], q[3]) for q in ds.queries]
    manhattan = [abs(sx-gx)+abs(sy-gy) for sx, sy, gx, gy in ds.queries]
    pairs = [(answer, m) for answer, m in zip(reference, manhattan) if answer >= 0]
    if any(answer < m or (answer - m) % 2 for answer, m in pairs):
        raise ValueError('Distance violates Manhattan lower bound/parity.')
    for q, answer in zip(ds.queries, reference):
        sx, sy, gx, gy = q
        if (labels[sy*ds.width+sx] == labels[gy*ds.width+gx]) != (answer >= 0):
            raise ValueError('Reachability and component labels disagree.')
    config = ds.metadata.get('stress_generator')
    if config is None:
        raise ValueError('Missing reproducible generation config.')
    with tempfile.TemporaryDirectory(prefix='rr-reproduce-') as temporary:
        # Regeneration is byte checked, including metadata, never an inferred claim.
        rebuilt = generate(Path(temporary)/'rebuilt', config)
        reproduced = fingerprint(rebuilt, INPUTS) == fingerprint(directory, INPUTS)
    if not reproduced:
        raise ValueError('Byte-for-byte regeneration failed.')
    n = len(reference)
    substantial = sum(a-m >= ds.height//2 and a >= 2*m for a, m in pairs)
    checks = dict(loader_limits_metadata_endpoints=True, independent_oracle=True,
                  component_reachability=True, manhattan_lower_bound_parity=True, byte_reproduction=True)
    kind = config['kind']
    if kind == 'stress_detour':
        checks['sufficient_detours'] = substantial >= n * .65 and 0 < reference.count(-1) < n
    elif kind == 'stress_open_unique':
        checks['unique_endpoints_and_long_queries'] = len(set(starts)) == len(set(goals)) == n and min(manhattan) >= (ds.width+ds.height)*.44
        checks['connected_open_map'] = len(groups) == 1 and reference.count(-1) == 0
    elif kind == 'stress_maze_long':
        checks['long_winding_paths'] = len(groups) == 1 and median(reference) >= ds.width+ds.height
    else:
        checks['mixed_reachability_and_repetition'] = len(groups) >= 4 and 0 < reference.count(-1) < n and len(set(starts)) < n and len(set(goals)) < n
    if not all(checks.values()):
        raise ValueError(f'Structural acceptance failed: {checks}')
    evidence = Path(evidence)
    evidence.mkdir(parents=True, exist_ok=True)
    answer_path = evidence / 'answers.txt'
    answer_path.write_text(''.join(f'{a}\n' for a in reference), encoding='utf-8')
    report = dict(schema_version=VERSION, dataset=str(Path(directory).resolve()), config=config,
                  constraints=checks, width=ds.width, height=ds.height, query_count=n,
                  obstacle_fraction=sum(map(sum, ds.grid))/(ds.width*ds.height),
                  free_cells=sum(map(len, groups)), component_count=len(groups),
                  component_sizes=sorted(map(len, groups), reverse=True),
                  reachable=n-reference.count(-1), unreachable=reference.count(-1),
                  same_cell=sum(m == 0 for m in manhattan),
                  unique_starts=len(set(starts)), unique_goals=len(set(goals)),
                  start_duplicate_fraction=1-len(set(starts))/n,
                  goal_duplicate_fraction=1-len(set(goals))/n,
                  endpoint_duplicate_fraction=1-len(set(starts+goals))/(2*n),
                  repeated_pairs=n-len(set(ds.queries)),
                  manhattan=describe(manhattan), distance_reachable=describe([a for a, _ in pairs]),
                  excess_reachable=describe([a-m for a, m in pairs]),
                  ratio_reachable_nonzero=describe([a/m for a, m in pairs if m]),
                  detour_count=sum(a>m for a, m in pairs), substantial_detour_count=substantial,
                  substantial_detour_definition='distance - Manhattan >= height//2 AND distance >= 2*Manhattan',
                  branching_cells=sum(sum(1 for q in adjacent(y*ds.width+x, ds.width, ds.height)
                                          if not ds.grid[q//ds.width][q%ds.width]) >= 3
                                      for y, row in enumerate(ds.grid) for x, cell in enumerate(row) if not cell),
                  file_bytes={name: (Path(directory)/name).stat().st_size for name in INPUTS},
                  sha256=fingerprint(directory, INPUTS),
                  answers_sha256=hashlib.sha256(answer_path.read_bytes()).hexdigest(),
                  generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  python=sys.version)
    save_json(evidence / 'validation.json', report)
    return report


def accepted_measurement(result):
    return result.get('status') == 'COMPLETE' and len(result.get('datasets', [])) == 1 and all(
        result['datasets'][0].get(side, {}).get('status') == 'OK'
        and len(result['datasets'][0][side].get('runs', [])) == 5
        and all(run['status'] == 'OK' for run in result['datasets'][0][side]['runs'])
        for side in ('baseline', 'team'))


def adjusted_config(config, seconds, target):
    """Tune Q first; resize only if Q hits a bound. Never exceed input limits."""
    updated = dict(config)
    goal = sum(target) / 2
    desired = round(config['queries'] * goal / seconds)
    updated['queries'] = max(24, min(2000, desired))
    if desired > 2000 and config['queries'] == 2000:
        scale = math.sqrt(goal / seconds)
        for dimension in ('width', 'height'):
            updated[dimension] = min(300, max(31, round(config[dimension] * scale)))
    elif desired < 24 and config['queries'] == 24:
        scale = math.sqrt(goal / seconds)
        for dimension in ('width', 'height'):
            updated[dimension] = min(300, max(31, round(config[dimension] * scale)))
    return updated


def tune(output, configs, target):
    """Pilot then adapt by measured medians using the UNMODIFIED isolated evaluator.

    'team' in the evaluator JSON is the trusted reference BFS probe, never a team
    submission. Only COMPLETE / all ten OK measurements inform calibration.
    """
    output = guard_destination(output)
    output.mkdir(parents=True)
    history = []
    save_json(output/'requested-configs.json', configs)
    with tempfile.TemporaryDirectory(prefix='rr-stress-probe-') as temporary:
        probe, _ = baseline_bundle(Path(temporary)/'probe')
        shutil.copyfile(ROOT/'tools/reference_solver.py', probe/'main.py')
        for initial in configs:
            config = dict(initial)
            # Every profile starts with a small pilot, regardless of supplied count.
            config['queries'] = min(24, config['queries'])
            attempts = []
            for attempt in range(4):
                path = generate(output/'calibration'/config['kind']/f'attempt-{attempt:02}', config)
                print(f"Measuring {config['kind']} {config['width']}x{config['height']} q={config['queries']}", flush=True)
                result = evaluate(probe, 'main.py', [path], 128, safety_stop=60,
                                  team_id='TRUSTED_REFERENCE_BFS_CALIBRATION_ONLY')
                save_json(path.parent/f'{path.name}-benchmark.json', result)
                item = dict(config=dict(config), benchmark=str(path.parent/f'{path.name}-benchmark.json'),
                            accepted=accepted_measurement(result))
                attempts.append(item)
                if not item['accepted']:
                    item['reason'] = result.get('error', 'Not all baseline/probe runs OK')
                    # Still produce and fully validate the candidate, never guess a time.
                    break
                seconds = result['datasets'][0]['baseline']['median_seconds']
                item['baseline_median_seconds'] = seconds
                print(f'  baseline median={seconds:.6f}s; all 5+5 OK', flush=True)
                if target[0] <= seconds <= target[1]:
                    break
                updated = adjusted_config(config, seconds, target)
                if updated == config:
                    break
                if attempt < 3:
                    config = updated
            destination = output/config['kind']
            shutil.copytree(path, destination)
            report = validate(destination, output/'evidence'/config['kind'])
            final = dict(kind=config['kind'], attempts=attempts, sha256=report['sha256'],
                         selected_config=config, timing_status='PENDING',
                         note='No official scoring changes. team field is trusted reference BFS.')
            last = attempts[-1]
            if last['accepted']:
                final['timing_status'] = 'MEASURED'
                final['baseline_median_seconds'] = last['baseline_median_seconds']
                final['target_met'] = target[0] <= last['baseline_median_seconds'] <= target[1]
            history.append(final)
            save_json(output/'calibration.json', dict(target_seconds=target, datasets=history))
            print(f'Validated {destination}', flush=True)
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    gen = commands.add_parser('generate')
    gen.add_argument('--output', type=Path, required=True)
    gen.add_argument('--kind', choices=KINDS, required=True)
    for key in ('width', 'height', 'queries', 'seed'):
        gen.add_argument('--'+key, type=int, required=True)
    check = commands.add_parser('validate')
    check.add_argument('--dataset', type=Path, required=True)
    check.add_argument('--evidence', type=Path, required=True)
    calibration = commands.add_parser('tune')
    calibration.add_argument('--output', type=Path, required=True)
    calibration.add_argument('--config', type=Path, help='JSON list; absent = public pilot configs')
    calibration.add_argument('--target-min', type=float, default=10)
    calibration.add_argument('--target-max', type=float, default=20)
    args = parser.parse_args()
    try:
        if args.command == 'generate':
            config = {k: getattr(args, k) for k in ('kind', 'width', 'height', 'queries', 'seed')}
            config['profile'] = 'public'
            generate(args.output, config)
            print(f'Generated {args.output}; run validate before use.')
        elif args.command == 'validate':
            print(json.dumps(validate(args.dataset, args.evidence), ensure_ascii=False, indent=2))
        else:
            if not 0 < args.target_min <= args.target_max < 60 or not all(map(math.isfinite, (args.target_min, args.target_max))):
                raise ValueError('Require 0 < target-min <= target-max < 60 (operator calibration guard).')
            configs = json.loads(args.config.read_text()) if args.config else PUBLIC
            if not configs or len({c['kind'] for c in configs}) != len(configs):
                raise ValueError('Config must contain distinct candidate kinds.')
            tune(args.output, configs, (args.target_min, args.target_max))
    except (ValueError, OSError) as error:
        parser.exit(2, f'ERROR: {error}\n')


if __name__ == '__main__':
    main()
