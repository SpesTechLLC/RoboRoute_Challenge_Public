"""Dataset loading and validation."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

MAX_WIDTH = 300
MAX_HEIGHT = 300
MAX_QUERIES = 2000


def validate_limits(width, height, query_count):
    for label, value, maximum in (('width', width, MAX_WIDTH), ('height', height, MAX_HEIGHT), ('query_count', query_count, MAX_QUERIES)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError(f'{label} must be an integer in [1, {maximum}].')


Point = tuple[int, int]
Query = tuple[int, int, int, int]


@dataclass(frozen=True)
class Dataset:
    path: Path
    grid: list[list[int]]
    queries: list[Query]
    metadata: dict

    @property
    def width(self) -> int:
        return len(self.grid[0])

    @property
    def height(self) -> int:
        return len(self.grid)


def load_dataset(directory: str | Path) -> Dataset:
    """Load a dataset directory, reporting friendly validation errors."""
    path = Path(directory)
    required = ("map.csv", "queries.csv", "metadata.json")
    for name in required:
        file_path = path / name
        if not file_path.is_file():
            raise ValueError(f"{name} was not found. Expected: {file_path}")

    if (path / 'metadata.json').stat().st_size > 65536:
        raise ValueError('metadata.json exceeds 64 KiB.')
    with (path / 'metadata.json').open(encoding='utf-8') as file:
        metadata = json.load(file)
    if not isinstance(metadata, dict):
        raise ValueError('metadata.json must be an object.')
    validate_limits(metadata.get('width'), metadata.get('height'), metadata.get('query_count'))
    if any((path / name).stat().st_size > 4 * 1024 * 1024 for name in ('map.csv', 'queries.csv')):
        raise ValueError('Input CSV exceeds 4 MiB.')
    grid = []
    with (path / "map.csv").open(newline="", encoding="utf-8") as file:
        for row in csv.reader(file):
            if not row:
                continue
            if len(grid) >= MAX_HEIGHT or len(row) > MAX_WIDTH:
                raise ValueError('map.csv exceeds the map dimensions limit.')
            grid.append([int(cell) for cell in row])
    if not grid or not grid[0] or any(len(row) != len(grid[0]) for row in grid):
        raise ValueError("map.csv must be a non-empty rectangular grid.")
    if any(cell not in (0, 1) for row in grid for cell in row):
        raise ValueError("map.csv may contain only 0 (free) and 1 (obstacle).")

    with (path / "queries.csv").open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        expected = ["start_x", "start_y", "goal_x", "goal_y"]
        if reader.fieldnames != expected:
            raise ValueError("queries.csv header must be: " + ",".join(expected))
        queries = []
        for row in reader:
            if len(queries) >= MAX_QUERIES:
                raise ValueError('queries.csv exceeds 2000 queries.')
            if None in row or any(row.get(key) is None for key in expected):
                raise ValueError('Each query must have exactly four integers.')
            queries.append(tuple(int(row[key]) for key in expected))
    dataset = Dataset(path, grid, queries, metadata)
    if metadata.get("width") != dataset.width or metadata.get("height") != dataset.height:
        raise ValueError("metadata.json dimensions do not match map.csv.")
    if metadata.get("query_count") != len(queries):
        raise ValueError("metadata.json query_count does not match queries.csv.")
    for index, (sx, sy, gx, gy) in enumerate(queries):
        for x, y, label in ((sx, sy, "start"), (gx, gy, "goal")):
            if not (0 <= x < dataset.width and 0 <= y < dataset.height):
                raise ValueError(f"Query {index} {label} is outside the map.")
            if grid[y][x]:
                raise ValueError(f"Query {index} {label} is on an obstacle.")
    return dataset


def write_dataset(directory: str | Path, grid: list[list[int]], queries: list[Query], seed: int) -> None:
    if not grid or not grid[0]:
        raise ValueError('A non-empty grid is required.')
    validate_limits(len(grid[0]), len(grid), len(queries))
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    with (path / "map.csv").open("w", newline="", encoding="utf-8") as file:
        csv.writer(file).writerows(grid)
    with (path / "queries.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["start_x", "start_y", "goal_x", "goal_y"])
        writer.writerows(queries)
    metadata = {"format_version": 1, "width": len(grid[0]), "height": len(grid),
                "query_count": len(queries), "seed": seed}
    (path / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
