#!/usr/bin/env python3
"""Generate a deterministic RoboRoute dataset."""
from __future__ import annotations
import argparse, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roboroute.dataset import write_dataset, validate_limits
from roboroute.generator import generate_map, generate_queries

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--output", required=True); parser.add_argument("--width",type=int,required=True); parser.add_argument("--height",type=int,required=True); parser.add_argument("--queries",type=int,required=True); parser.add_argument("--map-type",choices=["open","random","rooms","maze","islands"],required=True); parser.add_argument("--query-type",choices=["random","repeated_goal","repeated_start","local","long_distance","mixed"],required=True); parser.add_argument("--seed",type=int,required=True)
    args=parser.parse_args()
    try:
        validate_limits(args.width, args.height, args.queries)
        rng=random.Random(args.seed); grid=generate_map(args.width,args.height,args.map_type,rng); queries=generate_queries(grid,args.queries,args.query_type,rng); write_dataset(args.output,grid,queries,args.seed)
        print(f"Generated {args.output}: {args.width}x{args.height}, {args.queries} queries")
    except ValueError as error: parser.error(str(error))
if __name__ == "__main__": main()
