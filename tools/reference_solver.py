#!/usr/bin/env python3
"""Correct reference solver (BFS for an unweighted grid)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roboroute.dataset import load_dataset
from roboroute.solver import shortest_path

def solve_dataset(dataset): return [shortest_path(dataset.grid,(sx,sy),(gx,gy))[0] for sx,sy,gx,gy in dataset.queries]
def main():
    if len(sys.argv)!=2: print("Usage: python tools/reference_solver.py DATASET_DIRECTORY",file=sys.stderr); return 2
    try: print(*solve_dataset(load_dataset(sys.argv[1])),sep="\n")
    except ValueError as error: print(f"ERROR: {error}",file=sys.stderr); return 2
    return 0
if __name__ == "__main__": raise SystemExit(main())
