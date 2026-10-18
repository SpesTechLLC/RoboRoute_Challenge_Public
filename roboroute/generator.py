"""Deterministic map and query generators."""
from __future__ import annotations

import random
from collections import deque

from .dataset import Query


def generate_map(width: int, height: int, map_type: str, rng: random.Random) -> list[list[int]]:
    if width < 3 or height < 3:
        raise ValueError("width and height must both be at least 3.")
    if map_type == "open":
        grid = [[0] * width for _ in range(height)]
        for _ in range(max(1, width * height // 100)):
            grid[rng.randrange(height)][rng.randrange(width)] = 1
    elif map_type == "random":
        grid = [[0] * width for _ in range(height)]
        for _ in range(max(3, width * height // 180)):
            x, y = rng.randrange(width), rng.randrange(height)
            rw, rh = rng.randint(1, max(1, width // 10)), rng.randint(1, max(1, height // 8))
            for yy in range(y, min(height, y + rh)):
                for xx in range(x, min(width, x + rw)):
                    grid[yy][xx] = 1
    elif map_type == "rooms":
        grid = [[1] * width for _ in range(height)]
        rooms = []
        for _ in range(max(3, min(12, width * height // 250))):
            rw, rh = rng.randint(3, max(3, width // 3)), rng.randint(3, max(3, height // 3))
            x, y = rng.randint(0, max(0, width - rw)), rng.randint(0, max(0, height - rh))
            rooms.append((x, y, rw, rh))
            for yy in range(y, y + rh):
                for xx in range(x, x + rw): grid[yy][xx] = 0
        centers = [(x + rw // 2, y + rh // 2) for x, y, rw, rh in rooms]
        for (x1, y1), (x2, y2) in zip(centers, centers[1:]):
            for x in range(min(x1, x2), max(x1, x2) + 1): grid[y1][x] = 0
            for y in range(min(y1, y2), max(y1, y2) + 1): grid[y][x2] = 0
    elif map_type == "maze":
        grid = [[1] * width for _ in range(height)]
        stack = [(1, 1)]; grid[1][1] = 0
        while stack:
            x, y = stack[-1]
            candidates = [(x + dx, y + dy, dx, dy) for dx, dy in ((2,0),(-2,0),(0,2),(0,-2))
                          if 0 < x + dx < width - 1 and 0 < y + dy < height - 1 and grid[y + dy][x + dx]]
            if not candidates: stack.pop(); continue
            nx, ny, dx, dy = rng.choice(candidates)
            grid[y + dy // 2][x + dx // 2] = 0; grid[ny][nx] = 0; stack.append((nx, ny))
    elif map_type == "islands":
        grid = [[1] * width for _ in range(height)]
        for _ in range(max(3, width * height // 300)):
            rw, rh = rng.randint(2, max(2, width // 5)), rng.randint(2, max(2, height // 4))
            x, y = rng.randint(0, width-rw), rng.randint(0, height-rh)
            for yy in range(y, y+rh):
                for xx in range(x, x+rw): grid[yy][xx] = 0
    else: raise ValueError(f"Unknown map type: {map_type}")
    return grid


def _free(grid): return [(x, y) for y, row in enumerate(grid) for x, value in enumerate(row) if not value]
def _nearby(grid, start, radius):
    sx, sy = start; return [(x,y) for x,y in _free(grid) if 0 < abs(x-sx)+abs(y-sy) <= radius]

def generate_queries(grid: list[list[int]], count: int, query_type: str, rng: random.Random) -> list[Query]:
    free = _free(grid)
    if len(free) < 2: raise ValueError("Map must contain at least two free cells.")
    def random_pair():
        start, goal = rng.sample(free, 2); return (*start, *goal)
    def biased(side: str):
        popular = rng.sample(free, min(3, len(free)))
        result=[]
        for _ in range(count):
            fixed = rng.choices(popular, weights=[15,10,7], k=1)[0] if rng.random() < .32 else rng.choice(free)
            other = rng.choice(free)
            result.append((*other, *fixed) if side == "goal" else (*fixed, *other))
        return result
    if query_type == "random": return [random_pair() for _ in range(count)]
    if query_type == "repeated_goal": return biased("goal")
    if query_type == "repeated_start": return biased("start")
    if query_type in ("local", "long_distance"):
        result=[]; min_dist = (len(grid)+len(grid[0])) // 3
        for _ in range(count):
            start = rng.choice(free)
            candidates = _nearby(grid, start, max(3, min(len(grid),len(grid[0]))//4)) if query_type == "local" else [p for p in free if abs(p[0]-start[0])+abs(p[1]-start[1]) >= min_dist]
            goal = rng.choice(candidates or [p for p in free if p != start]); result.append((*start, *goal))
        return result
    if query_type == "mixed":
        # Generate each group in batches: a one-query repeated_goal batch would
        # not actually repeat anything, so it would hide the intended pattern.
        weights = [("random", 45), ("repeated_goal", 18), ("repeated_start", 12),
                   ("local", 15), ("long_distance", 10)]
        remaining = count
        result = []
        for index, (kind, weight) in enumerate(weights):
            amount = remaining if index == len(weights) - 1 else count * weight // 100
            remaining -= amount
            result.extend(generate_queries(grid, amount, kind, rng))
        rng.shuffle(result)
        return result
    raise ValueError(f"Unknown query type: {query_type}")
