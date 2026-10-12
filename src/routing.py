"""
Terrain-aware route planning over a DEM: grid A* on a cost raster built from
slope, with an adjustable trade-off between travel time and slope risk.

Cost model (illustrative, not calibrated to any real vehicle):
  * speed falls off exponentially with slope:  v = V0 * exp(-slope / SLOPE_SCALE_DEG)
  * slopes steeper than MAX_SLOPE_DEG are impassable
  * time_per_m = 1 / v
  * risk_per_m = (slope / MAX_SLOPE_DEG) ** 2   -- grows fast near the limit
  * cell cost  = w_time * time_per_m + w_risk * risk_per_m
  * moving between two adjacent cells costs (cell size) * mean of the two cells' costs

A* runs on an 8-connected grid with heapq. The heuristic is octile distance
times w_time * (smallest time_per_m on the grid). Every step costs at least
that much per meter (risk is >= 0), and octile distance never overestimates
8-connected grid distance, so the heuristic is admissible; it is also
consistent, so a closed set is safe.

Run `python src/routing.py [school_id]` to route across a live-fetched campus
DEM under three weightings and print the Pareto comparison.
"""

import heapq
import math
import sys
from dataclasses import dataclass, field

import numpy as np

V0_MPS = 1.4  # flat-ground speed, roughly walking pace
SLOPE_SCALE_DEG = 12.0
MAX_SLOPE_DEG = 25.0

_NEIGHBORS = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]


@dataclass
class CostRasters:
    time_per_m: np.ndarray  # seconds per meter; inf where impassable
    risk_per_m: np.ndarray  # dimensionless risk per meter; inf where impassable
    cell_m: float


@dataclass
class Route:
    path: list  # [(row, col), ...] start to goal
    distance_m: float
    time_s: float
    risk: float
    max_slope_deg: float
    cost: float
    expanded: int
    weights: tuple = field(default=(1.0, 0.0))
    dominated: bool = False


def cost_rasters(slope_deg, cell_m):
    """Per-cell time and risk rates from a slope raster (degrees). NaN slope counts as impassable."""
    slope = np.asarray(slope_deg, dtype=np.float64)
    blocked = np.isnan(slope) | (slope > MAX_SLOPE_DEG)
    safe = np.where(blocked, 0.0, slope)
    time_per_m = 1.0 / (V0_MPS * np.exp(-safe / SLOPE_SCALE_DEG))
    risk_per_m = (safe / MAX_SLOPE_DEG) ** 2
    time_per_m[blocked] = np.inf
    risk_per_m[blocked] = np.inf
    return CostRasters(time_per_m, risk_per_m, float(cell_m))


def octile(dr, dc):
    """Shortest 8-connected distance in cell units between cells dr, dc apart on an open grid."""
    dr, dc = abs(dr), abs(dc)
    return (dr + dc) + (math.sqrt(2) - 2) * min(dr, dc)


def _rate(rasters, w_time, w_risk):
    """Combined cost per meter; inf wherever the cell is impassable (avoids inf * 0 = nan)."""
    blocked = ~np.isfinite(rasters.time_per_m)
    rate = w_time * np.where(blocked, 0.0, rasters.time_per_m) + w_risk * np.where(blocked, 0.0, rasters.risk_per_m)
    rate[blocked] = np.inf
    return rate


def astar(rasters, start, goal, w_time=1.0, w_risk=0.0):
    """
    Cheapest 8-connected path from start to goal ((row, col) tuples) under
    cost = w_time * time + w_risk * risk. Returns a Route, or None if the goal
    is unreachable. w_time must be >= 0 and w_risk >= 0, not both zero.
    """
    if w_time < 0 or w_risk < 0 or (w_time == 0 and w_risk == 0):
        raise ValueError("weights must be non-negative and not both zero")
    t, cell = rasters.time_per_m, rasters.cell_m
    rate = _rate(rasters, w_time, w_risk)
    rows, cols = rate.shape
    if not (np.isfinite(rate[start]) and np.isfinite(rate[goal])):
        return None

    finite_t = t[np.isfinite(t)]
    h_scale = w_time * float(finite_t.min()) * cell if finite_t.size else 0.0

    def h(node):
        return h_scale * octile(node[0] - goal[0], node[1] - goal[1])

    best = {start: 0.0}
    parent = {}
    heap = [(h(start), 0.0, start)]
    closed = set()
    expanded = 0
    while heap:
        _, g, node = heapq.heappop(heap)
        if node in closed:
            continue
        closed.add(node)
        expanded += 1
        if node == goal:
            return _summarize(rasters, _backtrack(parent, node), g, expanded, (w_time, w_risk))
        r, c = node
        for dr, dc in _NEIGHBORS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < rows and 0 <= nc < cols) or (nr, nc) in closed:
                continue
            if not np.isfinite(rate[nr, nc]):
                continue
            step = cell * (math.sqrt(2) if dr and dc else 1.0)
            ng = g + step * 0.5 * (rate[r, c] + rate[nr, nc])
            if ng < best.get((nr, nc), math.inf):
                best[(nr, nc)] = ng
                parent[(nr, nc)] = node
                heapq.heappush(heap, (ng + h((nr, nc)), ng, (nr, nc)))
    return None


def _backtrack(parent, node):
    path = [node]
    while node in parent:
        node = parent[node]
        path.append(node)
    return path[::-1]


def _summarize(rasters, path, cost, expanded, weights):
    dist = time_s = risk = 0.0
    for (r0, c0), (r1, c1) in zip(path, path[1:]):
        step = rasters.cell_m * (math.sqrt(2) if r0 != r1 and c0 != c1 else 1.0)
        dist += step
        time_s += step * 0.5 * (rasters.time_per_m[r0, c0] + rasters.time_per_m[r1, c1])
        risk += step * 0.5 * (rasters.risk_per_m[r0, c0] + rasters.risk_per_m[r1, c1])
    # Recover each cell's slope from its risk rate: risk = (slope / MAX)^2
    worst = max(math.sqrt(rasters.risk_per_m[p]) * MAX_SLOPE_DEG for p in path)
    return Route(path, dist, time_s, risk, worst, cost, expanded, weights)


def dijkstra_cost(rasters, start, goal, w_time=1.0, w_risk=0.0):
    """Plain Dijkstra (no heuristic) returning just the optimal cost; reference for checking astar."""
    rate = _rate(rasters, w_time, w_risk)
    rows, cols = rate.shape
    dist = {start: 0.0}
    heap = [(0.0, start)]
    while heap:
        g, node = heapq.heappop(heap)
        if g > dist.get(node, math.inf):
            continue
        if node == goal:
            return g
        r, c = node
        for dr, dc in _NEIGHBORS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and np.isfinite(rate[nr, nc]):
                step = rasters.cell_m * (math.sqrt(2) if dr and dc else 1.0)
                ng = g + step * 0.5 * (rate[r, c] + rate[nr, nc])
                if ng < dist.get((nr, nc), math.inf):
                    dist[(nr, nc)] = ng
                    heapq.heappush(heap, (ng, (nr, nc)))
    return None


def compare_weightings(rasters, start, goal, weightings=((1.0, 0.0), (1.0, 50.0), (0.0, 1.0))):
    """
    Route under each (w_time, w_risk) and mark which results are Pareto-dominated
    on (time, risk). A route is dominated if another is no worse on both and
    strictly better on at least one.
    """
    routes = [r for w in weightings if (r := astar(rasters, start, goal, *w)) is not None]
    eps = 1e-9
    for a in routes:
        a.dominated = any(
            b is not a
            and b.time_s <= a.time_s + eps and b.risk <= a.risk + eps
            and (b.time_s < a.time_s - eps or b.risk < a.risk - eps)
            for b in routes
        )
    return routes


def main():
    import pandas as pd

    import config
    from geo_utils import square_bbox_around
    from terrain import composite_dem, slope_degrees

    school_id = sys.argv[1] if len(sys.argv) > 1 else None
    schools = pd.read_csv(config.MEASUREMENTS_CSV, dtype={"school_id": str})
    row = schools[schools.school_id == school_id].iloc[0] if school_id else schools.iloc[0]
    bbox = square_bbox_around(row.location_lat, row.location_lon, config.DEFAULT_CROP_METERS / 2)
    dem = composite_dem(bbox)
    slope = slope_degrees(dem.array, dem.dx_m, dem.dy_m)
    rasters = cost_rasters(slope, (dem.dx_m + dem.dy_m) / 2)
    rows, cols = slope.shape
    start, goal = (rows - 1, 0), (0, cols - 1)  # SW corner to NE corner
    print(f"{row.school_name}: {rows}x{cols} DEM, {rasters.cell_m:.1f} m cells, "
          f"elevation {np.nanmin(dem.array):.1f}-{np.nanmax(dem.array):.1f} m, route SW -> NE corner")
    print(f"{'w_time':>6} {'w_risk':>6} {'dist_m':>8} {'time_s':>8} {'risk':>7} {'max_slope':>9} {'expanded':>8}  pareto")
    for r in compare_weightings(rasters, start, goal):
        print(f"{r.weights[0]:>6g} {r.weights[1]:>6g} {r.distance_m:>8.1f} {r.time_s:>8.1f} {r.risk:>7.3f} "
              f"{r.max_slope_deg:>8.1f}° {r.expanded:>8}  {'dominated' if r.dominated else 'optimal'}")


if __name__ == "__main__":
    main()
