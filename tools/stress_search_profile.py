#!/usr/bin/env python3
"""Compare search expansions on deterministic query samples (not timing/scoring)."""
from __future__ import annotations

import argparse
from collections import deque
import heapq
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roboroute.dataset import load_dataset
from tools.stress_dataset import adjacent, describe, save_json


def search(dataset, query, algorithm):
    w, h = dataset.width, dataset.height
    sx, sy, gx, gy = query
    start, goal = sy*w+sx, gy*w+gx
    free = [not cell for row in dataset.grid for cell in row]
    seen = [-1] * (w*h)
    seen[start] = 0
    expanded = 0
    if algorithm == 'bidirectional_bfs':
        if start == goal:
            return 0, 1
        back = [-1] * (w*h)
        back[goal] = 0
        front, rear = [start], [goal]
        while front and rear:
            if len(front) > len(rear):
                front, rear, seen, back = rear, front, back, seen
            following, meetings = [], []
            for p in front:
                expanded += 1
                for q in adjacent(p, w, h):
                    if not free[q] or seen[q] >= 0:
                        continue
                    seen[q] = seen[p] + 1
                    following.append(q)
                    if back[q] >= 0:
                        meetings.append(seen[q] + back[q])
            if meetings:
                return min(meetings), expanded
            front = following
        return -1, expanded
    if algorithm == 'bfs':
        queue = deque([start])
        while queue:
            p = queue.popleft()
            expanded += 1
            if p == goal:
                return seen[p], expanded
            for q in adjacent(p, w, h):
                if free[q] and seen[q] < 0:
                    seen[q] = seen[p] + 1
                    queue.append(q)
        return -1, expanded
    if algorithm != 'astar':
        raise ValueError(algorithm)

    def heuristic(p):
        return abs(p % w-gx) + abs(p // w-gy)

    queue = [(heuristic(start), 0, start)]
    while queue:
        _, distance, p = heapq.heappop(queue)
        if seen[p] != distance:
            continue
        expanded += 1
        if p == goal:
            return distance, expanded
        for q in adjacent(p, w, h):
            if free[q] and (seen[q] < 0 or distance + 1 < seen[q]):
                seen[q] = distance + 1
                heapq.heappush(queue, (distance + 1 + heuristic(q), distance + 1, q))
    return -1, expanded


def profile(dataset, answers, count=16):
    if count < 1 or len(answers) != len(dataset.queries):
        raise ValueError('Positive count and one answer per query required.')
    # Distance quantiles avoid picking only easy first queries or only the maximum.
    reachable = sorted((a, i) for i, a in enumerate(answers) if a >= 0)
    unreachable = [i for i, a in enumerate(answers) if a < 0]
    count = min(count, len(reachable))
    indices = [reachable[i*(len(reachable)-1)//max(1, count-1)][1] for i in range(count)]
    indices += unreachable[:4]
    rows = []
    for index in indices:
        row = dict(query_index=index, expected=answers[index], expansions={})
        for algorithm in ('bfs', 'bidirectional_bfs', 'astar'):
            answer, expansions = search(dataset, dataset.queries[index], algorithm)
            if answer != answers[index]:
                raise ValueError(f'{algorithm} disagrees at query {index}')
            row['expansions'][algorithm] = expansions
        rows.append(row)
    return dict(dataset=dataset.path.name, metric='popped/expanded cells; bidirectional BFS completes meeting layer',
                notes='Operation counts only. No component precheck/cache. A* ties use (f,g,flat_index). Not runtime rankings.',
                sampling='16 reachable distance quantiles (or fewer) + first 4 unreachable queries', rows=rows,
                summaries={algorithm: describe([row['expansions'][algorithm] for row in rows])
                           for algorithm in ('bfs', 'bidirectional_bfs', 'astar')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--answers', type=Path, required=True, help='answers.txt from stress_dataset validate')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    answers = [int(line) for line in args.answers.read_text().splitlines()]
    save_json(args.output, profile(dataset, answers))
    print(f'Validated sampled search counts: {args.output}')


if __name__ == '__main__':
    main()
