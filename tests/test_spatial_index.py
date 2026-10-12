"""Spatial index tests: small hand-built fixtures with known answers, plus agreement with a linear scan."""

import random

import pytest
from shapely.geometry import Point, box

from geo_utils import meters_to_degrees
from spatial_index import (
    CampusIndex, facilities_in_campus_linear, load_geojson, nearest_school_linear,
    save_geojson, schools_within_linear,
)

LAT0, LON0 = 40.0, -100.0
STEP = 0.01  # degrees of latitude, ~1112 m


def square_campus(school_id, lat, lon, half_m=100):
    d_lat, d_lon = meters_to_degrees(half_m, lat)
    return box(lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat), {"school_id": school_id, "name": school_id}


@pytest.fixture
def column():
    """Four 200m campuses stacked due north of each other, one per 0.01 degrees of latitude."""
    return [square_campus(n, LAT0 + i * STEP, LON0) for i, n in enumerate("ABCD")]


def ids(hits):
    return [p["school_id"] for p, _ in hits]


def test_schools_within_known_answer(column):
    index = CampusIndex(column)
    # From A's center: A is 0 m away; B's near edge is ~1112 - 100 = ~1012 m; C's is ~2124 m.
    assert ids(index.schools_within(LAT0, LON0, 1.0)) == ["A"]
    hits = index.schools_within(LAT0, LON0, 1.1)
    assert ids(hits) == ["A", "B"]
    assert hits[0][1] == pytest.approx(0, abs=1e-6)
    assert hits[1][1] == pytest.approx(1012, abs=3)
    assert ids(index.schools_within(LAT0, LON0, 5.0)) == ["A", "B", "C", "D"]


def test_schools_within_nothing_in_range(column):
    assert CampusIndex(column).schools_within(LAT0 + 1, LON0, 1.0) == []


def test_nearest_school_known_answer(column):
    index = CampusIndex(column)
    props, d = index.nearest_school(LAT0 + 2.6 * STEP, LON0)  # between C and D, closer to D
    assert props["school_id"] == "D"
    assert d == pytest.approx(0.4 * 1112 - 100, abs=3)
    props, d = index.nearest_school(LAT0 + 0.0005, LON0)  # inside A
    assert (props["school_id"], d) == ("A", 0.0)


def test_empty_index():
    index = CampusIndex([])
    assert index.schools_within(LAT0, LON0, 10) == []
    assert index.nearest_school(LAT0, LON0) is None
    assert index.campus_containing(LAT0, LON0) is None
    assert index.facilities_in_campus("A") == []


def test_campus_containing(column):
    index = CampusIndex(column)
    assert index.campus_containing(LAT0 + STEP, LON0)["school_id"] == "B"
    assert index.campus_containing(LAT0 + STEP / 2, LON0) is None


def test_facilities_in_campus():
    campus = square_campus("A", LAT0, LON0, half_m=100)
    other = square_campus("B", LAT0 + STEP, LON0, half_m=100)
    d_lat, d_lon = meters_to_degrees(100, LAT0)
    facilities = [
        (Point(LON0, LAT0), {"type": "track", "id": "inside-track"}),
        (Point(LON0 + d_lon / 2, LAT0 + d_lat / 2), {"type": "pool", "id": "inside-pool"}),
        (Point(LON0, LAT0 + STEP), {"type": "track", "id": "in-B"}),
        (Point(LON0 + 5 * d_lon, LAT0), {"type": "pool", "id": "outside-everything"}),
        # straddles A's east edge: not fully inside, so not "in" the campus
        (box(LON0 + d_lon / 2, LAT0, LON0 + 2 * d_lon, LAT0 + d_lat / 4), {"type": "field", "id": "straddler"}),
    ]
    index = CampusIndex([campus, other], facilities)
    assert sorted(f["id"] for f in index.facilities_in_campus("A")) == ["inside-pool", "inside-track"]
    assert [f["id"] for f in index.facilities_in_campus("A", facility_type="pool")] == ["inside-pool"]
    assert [f["id"] for f in index.facilities_in_campus("B")] == ["in-B"]
    assert index.facilities_in_campus("nonexistent") == []


def random_campuses(n, seed, lat_range=(59.0, 61.0), lon_range=(-3.0, 3.0)):
    """Random small campuses at high latitude, where degree-space distance is most distorted."""
    rng = random.Random(seed)
    return [
        square_campus(f"S{i}", rng.uniform(*lat_range), rng.uniform(*lon_range), half_m=rng.uniform(50, 400))
        for i in range(n)
    ]


def test_matches_linear_scan_on_random_data():
    campuses = random_campuses(400, seed=1)
    index = CampusIndex(campuses)
    rng = random.Random(2)
    for _ in range(150):
        lat, lon = rng.uniform(59, 61), rng.uniform(-3, 3)
        radius = rng.uniform(1, 40)
        fast, slow = index.schools_within(lat, lon, radius), schools_within_linear(campuses, lat, lon, radius)
        assert [(p["school_id"], round(d, 6)) for p, d in fast] == [(p["school_id"], round(d, 6)) for p, d in slow]
        (fp, fd), (sp, sd) = index.nearest_school(lat, lon), nearest_school_linear(campuses, lat, lon)
        assert fp["school_id"] == sp["school_id"]
        assert fd == pytest.approx(sd)


def test_facilities_match_linear_scan():
    campuses = random_campuses(50, seed=3, lat_range=(40, 41), lon_range=(-100, -99))
    rng = random.Random(4)
    facilities = []
    for g, p in campuses:
        c = g.centroid
        facilities.append((Point(c.x, c.y), {"type": "track", "of": p["school_id"]}))
        facilities.append((Point(c.x + rng.uniform(-0.01, 0.01), c.y + rng.uniform(-0.01, 0.01)), {"type": "pool"}))
    index = CampusIndex(campuses, facilities)
    for _, p in campuses:
        sid = p["school_id"]
        assert sorted(map(str, index.facilities_in_campus(sid))) == sorted(
            map(str, facilities_in_campus_linear(campuses, facilities, sid))
        )


def test_geojson_round_trip(tmp_path, column):
    path = tmp_path / "campuses.geojson"
    save_geojson(path, column)
    loaded = load_geojson(path)
    assert [p for _, p in loaded] == [p for _, p in column]
    assert all(a.equals_exact(b, 1e-9) for (a, _), (b, _) in zip(loaded, column))
    index = CampusIndex.from_geojson(path)
    assert ids(index.schools_within(LAT0, LON0, 1.1)) == ["A", "B"]
