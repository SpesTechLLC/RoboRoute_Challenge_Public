"""Terminal rendering helpers, deliberately dependency-free."""
from __future__ import annotations
import shutil
from collections import deque

RESET="\033[0m"; COLORS={"wall":"\033[38;5;240m","start":"\033[1;32m","goal":"\033[1;31m","path":"\033[1;33m", "visited":"\033[38;5;67m", "frontier":"\033[1;36m"}

def viewport_for_path(grid, path, max_width=80, max_height=35, margin=2):
    """Return an inclusive viewport.  A large path gets a whole-map view."""
    width,height=len(grid[0]),len(grid)
    if not path: return (0,0,min(width,max_width),min(height,max_height), width>max_width or height>max_height)
    xs,ys=zip(*path); left=max(0,min(xs)-margin); right=min(width,max(xs)+margin+1); top=max(0,min(ys)-margin); bottom=min(height,max(ys)+margin+1)
    too_large=right-left>max_width or bottom-top>max_height
    return (0,0,width,height,True) if too_large else (left,top,right,bottom,False)

def viewport_for_points(grid, points, max_width=80, max_height=35, margin=2):
    """Viewport covering points even when a query has no route."""
    width,height=len(grid[0]),len(grid)
    xs,ys=zip(*points); left=max(0,min(xs)-margin); right=min(width,max(xs)+margin+1); top=max(0,min(ys)-margin); bottom=min(height,max(ys)+margin+1)
    too_large=right-left>max_width or bottom-top>max_height
    return (0,0,width,height,True) if too_large else (left,top,right,bottom,False)

def render_overview(grid, max_width=None, max_height=None):
    terminal=shutil.get_terminal_size((100,40)); max_width=max_width or max(20,terminal.columns); max_height=max_height or max(8,terminal.lines-4)
    height,width=len(grid),len(grid[0]); sx=max(1,(width+max_width-1)//max_width); sy=max(1,(height+max_height-1)//max_height)
    shades=" ░▒▓█"; lines=[]
    for y in range(0,height,sy):
        line=""
        for x in range(0,width,sx):
            cells=[grid[yy][xx] for yy in range(y,min(y+sy,height)) for xx in range(x,min(x+sx,width))]
            line+=shades[round(sum(cells)/len(cells)*4)]
        lines.append(line)
    return "\n".join(lines)

def render_query(grid, start, goal, path, max_width=80, max_height=35):
    left,top,right,bottom,downsample=viewport_for_path(grid,path,max_width,max_height) if path else viewport_for_points(grid,(start,goal),max_width,max_height)
    if downsample:
        return "Path does not fit at full scale; overview follows:\n"+render_overview(grid,max_width,max_height)
    path_set=set(path); lines=[]
    for y in range(top,bottom):
        row=[]
        for x in range(left,right):
            point=(x,y)
            if point==start: row.append(COLORS["start"]+"S"+RESET)
            elif point==goal: row.append(COLORS["goal"]+"G"+RESET)
            elif point in path_set: row.append(COLORS["path"]+"·"+RESET)
            elif grid[y][x]: row.append(COLORS["wall"]+"█"+RESET)
            else: row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)

def bfs_frames(grid, start, goal, every=1):
    """Yield BFS snapshots as (visited, frontier); final snapshot reaches goal."""
    queue=deque([start]); discovered={start}; visited=set(); step=0
    while queue:
        current=queue.popleft(); visited.add(current); step+=1
        if step % every == 0 or current == goal:
            yield frozenset(visited), frozenset(queue)
        if current == goal: return
        x,y=current
        for nx,ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if 0 <= ny < len(grid) and 0 <= nx < len(grid[0]) and not grid[ny][nx] and (nx,ny) not in discovered:
                discovered.add((nx,ny)); queue.append((nx,ny))
    if step % every:
        yield frozenset(visited), frozenset()

def render_search_frame(grid, start, goal, visited, frontier, viewport):
    """Render one BFS state in an already selected full-scale viewport."""
    left,top,right,bottom,downsample=viewport
    if downsample: return "Search area is too large to animate; use a smaller query."
    lines=[]
    for y in range(top,bottom):
        row=[]
        for x in range(left,right):
            point=(x,y)
            if point == start: row.append(COLORS["start"]+"S"+RESET)
            elif point == goal: row.append(COLORS["goal"]+"G"+RESET)
            elif point in frontier: row.append(COLORS["frontier"]+"▒"+RESET)
            elif point in visited: row.append(COLORS["visited"]+"░"+RESET)
            elif grid[y][x]: row.append(COLORS["wall"]+"█"+RESET)
            else: row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)
