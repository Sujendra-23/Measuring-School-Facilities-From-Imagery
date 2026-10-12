"""
Spatial index vs linear scan on synthetic campuses.

Campuses are random 100-800 m squares scattered over a ~1000 km box around
the continental US. Both sides use the identical exact-distance function, so
the only difference is how many geometries each one has to test. Results of
the two are compared for equality on every query before timing is reported.

Run from the repo root:  python benchmarks/bench_spatial_index.py
"""

import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402
import shapely  # noqa: E402
from geo_utils import meters_to_degrees  # noqa: E402
from shapely.geometry import box  # noqa: E402
from spatial_index import CampusIndex, _M_PER_DEG, distance_m, nearest_school_linear, schools_within_linear  # noqa: E402

SIZES = [1_000, 10_000, 50_000]
N_QUERIES = {1_000: 200, 10_000: 100, 50_000: 20}  # linear scan at 50k is slow, so fewer queries
RADIUS_KM = 25


def make_campuses(n, rng):
    campuses = []
    for i in range(n):
        lat, lon = rng.uniform(30, 48), rng.uniform(-120, -75)
        d_lat, d_lon = meters_to_degrees(rng.uniform(50, 400), lat)
        campuses.append((box(lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat), {"school_id": f"S{i}"}))
    return campuses


def within_vectorized_scan(geoms, bounds, lat, lon, radius_km):
    """A stronger linear baseline: numpy bounding-box filter over all N, exact distance only on the survivors."""
    r_m = radius_km * 1000
    d_lat = r_m / _M_PER_DEG
    d_lon = d_lat / np.cos(np.radians(lat))
    keep = np.nonzero((bounds[:, 0] <= lon + d_lon) & (bounds[:, 2] >= lon - d_lon)
                      & (bounds[:, 1] <= lat + d_lat) & (bounds[:, 3] >= lat - d_lat))[0]
    hits = [(i, distance_m(geoms[i], lat, lon)) for i in keep]
    return sorted([h for h in hits if h[1] <= r_m], key=lambda h: h[1])


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t0


def main():
    rng = random.Random(0)
    print(f"python {sys.version.split()[0]}; within-radius queries use {RADIUS_KM} km; times are mean per query\n")
    print("within-radius baselines: 'scan' = Python loop over every geometry; 'np scan' = numpy bbox filter then exact check\n")
    print(f"{'N':>7} {'build s':>8} | {'within: scan ms':>15} {'np scan ms':>10} {'index ms':>9} {'x vs scan':>9} {'x vs np':>8} | "
          f"{'nearest: scan ms':>16} {'index ms':>9} {'speedup':>8} | queries")
    for n in SIZES:
        campuses = make_campuses(n, rng)
        index, build_s = timed(lambda: CampusIndex(campuses))
        queries = [(rng.uniform(30, 48), rng.uniform(-120, -75)) for _ in range(N_QUERIES[n])]

        geoms = [g for g, _ in campuses]
        bounds = shapely.bounds(np.array(geoms, dtype=object))
        t_scan_w, t_np_w, t_idx_w, t_scan_n, t_idx_n = [], [], [], [], []
        for lat, lon in queries:
            fast, t = timed(lambda: index.schools_within(lat, lon, RADIUS_KM)); t_idx_w.append(t)
            slow, t = timed(lambda: schools_within_linear(campuses, lat, lon, RADIUS_KM)); t_scan_w.append(t)
            assert [p["school_id"] for p, _ in fast] == [p["school_id"] for p, _ in slow]
            vec, t = timed(lambda: within_vectorized_scan(geoms, bounds, lat, lon, RADIUS_KM)); t_np_w.append(t)
            assert [campuses[i][1]["school_id"] for i, _ in vec] == [p["school_id"] for p, _ in slow]
            fast, t = timed(lambda: index.nearest_school(lat, lon)); t_idx_n.append(t)
            slow, t = timed(lambda: nearest_school_linear(campuses, lat, lon)); t_scan_n.append(t)
            assert fast[0]["school_id"] == slow[0]["school_id"]

        ms = lambda xs: statistics.mean(xs) * 1000
        print(f"{n:>7} {build_s:>8.3f} | {ms(t_scan_w):>15.2f} {ms(t_np_w):>10.3f} {ms(t_idx_w):>9.3f} "
              f"{ms(t_scan_w) / ms(t_idx_w):>8.0f}x {ms(t_np_w) / ms(t_idx_w):>7.1f}x | "
              f"{ms(t_scan_n):>16.2f} {ms(t_idx_n):>9.3f} {ms(t_scan_n) / ms(t_idx_n):>7.0f}x | {len(queries)}")


if __name__ == "__main__":
    main()
