"""Routing tests on grids small enough to solve by hand."""

import math
import random

import numpy as np
import pytest

from routing import (
    MAX_SLOPE_DEG, V0_MPS, astar, compare_weightings, cost_rasters, dijkstra_cost, octile,
)

CELL = 10.0


def rasters_for(slope):
    return cost_rasters(np.asarray(slope, dtype=float), CELL)


def test_octile_known_values():
    assert octile(0, 0) == 0
    assert octile(0, 5) == 5
    assert octile(3, 3) == pytest.approx(3 * math.sqrt(2))
    assert octile(2, 5) == pytest.approx(2 * math.sqrt(2) + 3)


def test_flat_grid_diagonal():
    route = astar(rasters_for(np.zeros((5, 5))), (0, 0), (4, 4))
    assert route.distance_m == pytest.approx(4 * math.sqrt(2) * CELL)
    assert route.time_s == pytest.approx(route.distance_m / V0_MPS)
    assert route.risk == 0 and route.max_slope_deg == 0
    assert route.path[0] == (0, 0) and route.path[-1] == (4, 4) and len(route.path) == 5


def test_flat_grid_straight_line_and_trivial_route():
    r = rasters_for(np.zeros((5, 5)))
    assert astar(r, (0, 0), (0, 4)).distance_m == pytest.approx(4 * CELL)
    same = astar(r, (2, 2), (2, 2))
    assert same.path == [(2, 2)] and same.distance_m == 0


def test_wall_with_one_gap_forces_detour():
    slope = np.zeros((5, 5))
    slope[:, 2] = 90  # impassable wall down the middle column
    slope[4, 2] = 0   # ...with a gap in the bottom row
    route = astar(rasters_for(slope), (0, 0), (0, 4))
    assert (4, 2) in route.path
    # (0,0)->(4,2) and (4,2)->(0,4) are each two diagonals plus two straights
    assert route.distance_m == pytest.approx(2 * (2 * math.sqrt(2) + 2) * CELL)


def test_unreachable_goal_returns_none():
    slope = np.zeros((5, 5))
    slope[:, 2] = 90
    assert astar(rasters_for(slope), (0, 0), (0, 4)) is None
    assert astar(rasters_for(slope), (0, 0), (0, 2)) is None  # goal itself impassable


def test_slope_above_limit_is_impassable_below_is_not():
    just_under = np.zeros((3, 3))
    just_under[:, 1] = MAX_SLOPE_DEG - 0.01
    assert astar(rasters_for(just_under), (0, 0), (0, 2)) is not None
    just_over = np.zeros((3, 3))
    just_over[:, 1] = MAX_SLOPE_DEG + 0.01
    assert astar(rasters_for(just_over), (0, 0), (0, 2)) is None


def test_invalid_weights_rejected():
    r = rasters_for(np.zeros((3, 3)))
    for w in [(0, 0), (-1, 1), (1, -1)]:
        with pytest.raises(ValueError):
            astar(r, (0, 0), (2, 2), *w)


HUMP_DEG = 5.0


def hump_grid():
    """9x9 open grid with a gentle 5 degree band across columns 3-5 in rows 2-6 (rows 0-1 and 7-8 are flat)."""
    slope = np.zeros((9, 9))
    slope[2:7, 3:6] = HUMP_DEG
    return rasters_for(slope)


def test_time_vs_risk_weighting_picks_different_known_routes():
    r = hump_grid()
    start, goal = (4, 0), (4, 8)

    fast = astar(r, start, goal, w_time=1, w_risk=0)
    # time-optimal: straight across the hump, 80 m, risk = 30 m of band at (5/25)^2 = 0.04/m
    assert fast.distance_m == pytest.approx(8 * CELL)
    assert fast.risk == pytest.approx(30 * (HUMP_DEG / MAX_SLOPE_DEG) ** 2)
    flat_tpm = 1 / V0_MPS
    hump_tpm = flat_tpm * math.exp(HUMP_DEG / 12.0)
    expected_time = 10 * (2 * flat_tpm + 0.5 * (flat_tpm + hump_tpm) * 2 + 2 * hump_tpm + 2 * flat_tpm)
    assert fast.time_s == pytest.approx(expected_time)

    safe = astar(r, start, goal, w_time=1, w_risk=50)
    # risk-averse: goes around the band through rows 0-1/7-8 at zero risk, 6 diagonals + 2 straights
    assert safe.risk == 0
    assert safe.distance_m == pytest.approx((6 * math.sqrt(2) + 2) * CELL)
    assert safe.time_s > fast.time_s  # the detour costs time, which is the whole trade-off


def test_pareto_comparison_flags_dominated_routes():
    routes = compare_weightings(hump_grid(), (4, 0), (4, 8), weightings=((1, 0), (1, 50), (0, 1)))
    fast, safe, risk_only = routes
    assert not fast.dominated and not safe.dominated  # each wins on one axis
    assert risk_only.risk == 0
    # risk-only has the same (zero) risk as `safe`, so it is dominated iff it is slower
    assert risk_only.dominated == (risk_only.time_s > safe.time_s + 1e-9)


def test_identical_routes_are_not_dominated():
    # A tiny risk weight picks the same route as 1:0; equal on both axes means neither dominates.
    routes = compare_weightings(hump_grid(), (4, 0), (4, 8), weightings=((1, 0), (1, 0.001)))
    assert [r.dominated for r in routes] == [False, False]


def test_astar_matches_dijkstra_on_random_terrain():
    rng = random.Random(7)
    for trial in range(40):
        slope = np.array([[rng.choice([0, 0, 3, 8, 15, 24, 40]) for _ in range(12)] for _ in range(12)], dtype=float)
        r = rasters_for(slope)
        w = rng.choice([(1, 0), (1, 10), (1, 200), (0, 1), (0.2, 1)])
        start = (rng.randrange(12), rng.randrange(12))
        goal = (rng.randrange(12), rng.randrange(12))
        route = astar(r, start, goal, *w)
        reference = dijkstra_cost(r, start, goal, *w)
        if reference is None:
            assert route is None
        else:
            assert route.cost == pytest.approx(reference, rel=1e-9, abs=1e-9), (trial, w, start, goal)


def test_heuristic_is_admissible_and_prunes_search():
    rng = random.Random(11)
    slope = np.array([[rng.choice([0, 2, 4, 6]) for _ in range(40)] for _ in range(40)], dtype=float)
    r = rasters_for(slope)
    start, goal = (0, 0), (39, 39)
    informed = astar(r, start, goal, 1, 0)
    # heuristic at the start can never exceed the true optimal cost
    h0 = float(r.time_per_m.min()) * CELL * octile(39, 39)
    assert h0 <= informed.cost + 1e-9
    # a guided search should not have to touch the whole grid
    assert informed.expanded < slope.size
