#!/usr/bin/env python3
"""Baseline RoboRoute solver: run Dijkstra independently for every query."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roboroute.dataset import load_dataset
from roboroute.solver import solve_all_dijkstra

def main():
    if len(sys.argv) != 2:
        print("Usage: python solution/main.py DATASET_DIRECTORY", file=sys.stderr); return 2
    try: dataset=load_dataset(sys.argv[1])
    except ValueError as error: print(f"ERROR: {error}",file=sys.stderr); return 2
    print(*solve_all_dijkstra(dataset.grid,dataset.queries),sep="\n")
    return 0
if __name__ == "__main__": raise SystemExit(main())
