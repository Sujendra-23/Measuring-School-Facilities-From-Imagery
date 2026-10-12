"""
Spatial index over campus footprints and facilities, built on Shapely's STRtree.

Campuses and facilities live in GeoJSON (lon/lat, WGS84). The index answers:

  * schools_within(lat, lon, radius_km)  -- every campus whose footprint comes
    within radius_km of a point
  * nearest_school(lat, lon)             -- the closest campus footprint
  * facilities_in_campus(school_id)      -- facility features lying inside a
    campus polygon
  * campus_containing(lat, lon)          -- which campus polygon holds a point

Distances are in meters, measured in a local flat-earth frame centered on the
query point (see _local_meters). The STRtree itself is built on raw lon/lat
envelopes, which is only an approximation of meters, so every query uses the
tree to pick candidates and then re-checks them with the real metric --
results are exact, the tree just keeps the candidate set small.

Run `python src/spatial_index.py` to build data/schools_points.geojson from
output/measurements.csv (read-only) and print a few sample queries.
"""

import json
import math
import sys

import numpy as np
import shapely
from shapely.geometry import Point, box, mapping, shape
from shapely.strtree import STRtree

from geo_utils import EARTH_RADIUS_M

_M_PER_DEG = math.pi * EARTH_RADIUS_M / 180  # meters per degree of latitude


def _local_meters(geom, lat0, lon0):
    """Project a lon/lat geometry into meters east/north of (lat0, lon0)."""
    kx = _M_PER_DEG * math.cos(math.radians(lat0))
    return shapely.transform(geom, lambda c: np.column_stack(((c[:, 0] - lon0) * kx, (c[:, 1] - lat0) * _M_PER_DEG)))


def distance_m(geom, lat, lon):
    """Distance in meters from a point to the nearest edge/interior of a lon/lat geometry (0 if inside)."""
    return _local_meters(geom, lat, lon).distance(Point(0, 0))


def load_geojson(path):
    """Read a FeatureCollection into a list of (shapely geometry, properties dict)."""
    with open(path) as f:
        data = json.load(f)
    return [(shape(feat["geometry"]), feat.get("properties") or {}) for feat in data["features"]]


def save_geojson(path, features):
    """Write (geometry, properties) pairs as a FeatureCollection."""
    collection = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": mapping(g), "properties": p} for g, p in features],
    }
    with open(path, "w") as f:
        json.dump(collection, f, indent=1)


class CampusIndex:
    """
    campuses:   list of (geometry, properties); properties must include 'school_id'
    facilities: optional list of (geometry, properties); properties should
                include 'type' (e.g. 'track', 'pool') and may include 'school_id'
    """

    def __init__(self, campuses, facilities=()):
        self.campuses = list(campuses)
        self.facilities = list(facilities)
        self._campus_geoms = np.array([g for g, _ in self.campuses], dtype=object)
        self._facility_geoms = np.array([g for g, _ in self.facilities], dtype=object)
        self._campus_tree = STRtree(self._campus_geoms) if len(self.campuses) else None
        self._facility_tree = STRtree(self._facility_geoms) if len(self.facilities) else None
        self._by_id = {props["school_id"]: i for i, (_, props) in enumerate(self.campuses)}

    @classmethod
    def from_geojson(cls, campus_path, facility_path=None):
        facilities = load_geojson(facility_path) if facility_path else ()
        return cls(load_geojson(campus_path), facilities)

    # -- internals ---------------------------------------------------------

    def _candidates_within(self, lat, lon, radius_m):
        """Indices of campuses whose lon/lat envelope touches the query's lon/lat bounding box."""
        if self._campus_tree is None:
            return []
        # Same meters-per-degree as _local_meters, so the box is exactly the
        # radius in the metric used to re-check candidates (geo_utils uses a
        # slightly different constant, which would clip ~0.1% at long range).
        d_lat = radius_m / _M_PER_DEG
        d_lon = d_lat / math.cos(math.radians(lat))
        return self._campus_tree.query(box(lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat))

    # -- queries -----------------------------------------------------------

    def schools_within(self, lat, lon, radius_km):
        """[(properties, distance_m)] for campuses within radius_km, nearest first."""
        radius_m = radius_km * 1000
        hits = []
        for i in self._candidates_within(lat, lon, radius_m):
            d = distance_m(self._campus_geoms[i], lat, lon)
            if d <= radius_m:
                hits.append((self.campuses[i][1], d))
        return sorted(hits, key=lambda h: h[1])

    def nearest_school(self, lat, lon):
        """(properties, distance_m) of the closest campus, or None if the index is empty."""
        if self._campus_tree is None:
            return None
        # Planar-degree nearest is only a guess at the metric nearest (longitude
        # degrees shrink with latitude), so use it to set a search radius, then
        # settle it exactly among everything inside that radius.
        guess = self._campus_tree.query_nearest(Point(lon, lat))[0]
        radius_m = distance_m(self._campus_geoms[guess], lat, lon)
        best_i, best_d = guess, radius_m
        for i in self._candidates_within(lat, lon, radius_m * 1.0001 + 1e-6):
            d = distance_m(self._campus_geoms[i], lat, lon)
            if d < best_d:
                best_i, best_d = i, d
        return self.campuses[best_i][1], best_d

    def campus_containing(self, lat, lon):
        """Properties of the campus polygon containing the point, or None."""
        if self._campus_tree is None:
            return None
        pt = Point(lon, lat)
        for i in self._campus_tree.query(pt, predicate="intersects"):
            return self.campuses[i][1]
        return None

    def facilities_in_campus(self, school_id, facility_type=None):
        """Facility features lying fully inside the campus polygon, optionally filtered by type."""
        if self._facility_tree is None or school_id not in self._by_id:
            return []
        campus_geom = self._campus_geoms[self._by_id[school_id]]
        hits = self._facility_tree.query(campus_geom, predicate="contains")
        out = [self.facilities[i][1] for i in hits]
        if facility_type is not None:
            out = [p for p in out if p.get("type") == facility_type]
        return out


# --- Linear-scan reference (used by tests and the benchmark) ----------------

def schools_within_linear(campuses, lat, lon, radius_km):
    radius_m = radius_km * 1000
    hits = [(p, distance_m(g, lat, lon)) for g, p in campuses]
    return sorted([h for h in hits if h[1] <= radius_m], key=lambda h: h[1])


def nearest_school_linear(campuses, lat, lon):
    return min(((p, distance_m(g, lat, lon)) for g, p in campuses), key=lambda h: h[1], default=None)


def facilities_in_campus_linear(campuses, facilities, school_id, facility_type=None):
    campus_geom = next(g for g, p in campuses if p["school_id"] == school_id)
    out = [p for g, p in facilities if campus_geom.contains(g)]
    return [p for p in out if facility_type is None or p.get("type") == facility_type]


def build_points_geojson(measurements_csv, out_path):
    """Turn the 25 resolved campus points in measurements.csv into a GeoJSON file (read-only on the CSV)."""
    import pandas as pd

    df = pd.read_csv(measurements_csv, dtype={"school_id": str})
    features = [
        (Point(r.location_lon, r.location_lat), {"school_id": r.school_id, "name": r.school_name})
        for r in df.itertuples()
    ]
    save_geojson(out_path, features)
    return features


if __name__ == "__main__":
    import config

    feats = build_points_geojson(config.MEASUREMENTS_CSV, "data/schools_points.geojson")
    index = CampusIndex(feats)
    lat, lon = 39.95, -75.16  # downtown Philadelphia
    props, d = index.nearest_school(lat, lon)
    print(f"{len(feats)} schools indexed -> data/schools_points.geojson", file=sys.stderr)
    print(f"nearest to ({lat}, {lon}): {props['name']} at {d / 1000:.1f} km")
    for p, dist in index.schools_within(lat, lon, 150):
        print(f"  within 150 km: {p['name']} ({dist / 1000:.1f} km)")
