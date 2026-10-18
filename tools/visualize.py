#!/usr/bin/env python3
"""Display a RoboRoute map or one query's shortest path in a terminal."""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from roboroute.dataset import load_dataset
from roboroute.solver import shortest_path
from roboroute.visualization import bfs_frames, render_overview, render_query, render_search_frame, viewport_for_points

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("dataset"); parser.add_argument("--query",type=int); parser.add_argument("--overview",action="store_true"); parser.add_argument("--animate",action="store_true",help="animate BFS exploration for --query"); parser.add_argument("--delay",type=float,default=0.04,help="seconds between animation frames (default: 0.04)"); parser.add_argument("--steps-per-frame",type=int,default=8,help="BFS nodes processed per frame (default: 8)"); args=parser.parse_args()
    try: dataset=load_dataset(args.dataset)
    except ValueError as error: print(f"ERROR: {error}",file=sys.stderr); return 2
    if args.overview or args.query is None:
        print(f"Dataset : {dataset.path.name}\nMap     : {dataset.width} x {dataset.height}\nLegend  : space=free, █=obstacle\n")
        print(render_overview(dataset.grid)); return 0
    if not 0 <= args.query < len(dataset.queries): print(f"ERROR: Query index must be between 0 and {len(dataset.queries)-1}.",file=sys.stderr); return 2
    if args.animate and (args.delay < 0 or args.steps_per_frame < 1): print("ERROR: --delay must be non-negative and --steps-per-frame must be at least 1.", file=sys.stderr); return 2
    sx,sy,gx,gy=dataset.queries[args.query]; distance,path=shortest_path(dataset.grid,(sx,sy),(gx,gy))
    print(f"Dataset : {dataset.path.name}\nQuery   : #{args.query}\n\nStart   : ({sx}, {sy})\nGoal    : ({gx}, {gy})\nDistance: {distance}\nReachable: {'YES' if distance >= 0 else 'NO'}\nLegend  : S=start, G=goal, ·=path, █=obstacle\n")
    if args.animate:
        viewport=viewport_for_points(dataset.grid, ((sx,sy),(gx,gy)))
        if viewport[-1]:
            print("Animation skipped: Start and Goal do not fit in a single terminal viewport.\n" + render_query(dataset.grid,(sx,sy),(gx,gy),path)); return 0
        try:
            for visited,frontier in bfs_frames(dataset.grid,(sx,sy),(gx,gy),args.steps_per_frame):
                print("\033[H\033[2J", end="")
                print(f"Dataset : {dataset.path.name} | Query: #{args.query} | BFS visited: {len(visited)}\nLegend: S=start, G=goal, ▒=frontier, ░=visited, █=obstacle\n")
                print(render_search_frame(dataset.grid,(sx,sy),(gx,gy),visited,frontier,viewport), flush=True)
                time.sleep(args.delay)
        except KeyboardInterrupt: print("\nAnimation stopped."); return 130
        print("\nShortest path:\n" + render_query(dataset.grid,(sx,sy),(gx,gy),path)); return 0
    print(render_query(dataset.grid,(sx,sy),(gx,gy),path)); return 0
if __name__ == "__main__": raise SystemExit(main())
