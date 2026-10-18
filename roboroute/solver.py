"""Shortest-path algorithms used by the baseline and tooling."""
from __future__ import annotations
import heapq
from collections import deque

def _neighbors(grid, x, y):
    height, width = len(grid), len(grid[0])
    for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
        if 0 <= nx < width and 0 <= ny < height and not grid[ny][nx]: yield nx, ny

def dijkstra_distance(grid, start, goal):
    if start == goal: return 0
    heap=[(0, start)]; best={start: 0}
    while heap:
        distance, current=heapq.heappop(heap)
        if current == goal: return distance
        if distance != best[current]: continue
        for nxt in _neighbors(grid, *current):
            candidate=distance+1
            if candidate < best.get(nxt, float("inf")):
                best[nxt]=candidate; heapq.heappush(heap,(candidate,nxt))
    return -1

def shortest_path(grid, start, goal):
    """Return (distance, path), where path includes both endpoints."""
    queue=deque([start]); parent={start: None}
    while queue:
        current=queue.popleft()
        if current == goal:
            path=[]
            while current is not None: path.append(current); current=parent[current]
            path.reverse(); return len(path)-1, path
        for nxt in _neighbors(grid,*current):
            if nxt not in parent: parent[nxt]=current; queue.append(nxt)
    return -1, []

def solve_all_dijkstra(grid, queries):
    return [dijkstra_distance(grid, (sx,sy), (gx,gy)) for sx,sy,gx,gy in queries]
