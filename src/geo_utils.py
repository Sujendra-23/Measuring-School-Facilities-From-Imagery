"""Small geometry helpers shared by geolocate.py and imagery.py."""

import math

EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def meters_to_degrees(meters, at_latitude):
    """
    Convert a distance in meters to (delta_lat_deg, delta_lon_deg) at a given
    latitude. Longitude degrees shrink as you move away from the equator, so
    this isn't a single constant -- it depends on where on Earth we are.
    """
    delta_lat = meters / 111_320  # ~constant everywhere
    delta_lon = meters / (111_320 * math.cos(math.radians(at_latitude)))
    return delta_lat, delta_lon


def bbox_from_points(points):
    """points: list of (lat, lon). Returns (min_lon, min_lat, max_lon, max_lat)."""
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def square_bbox_around(lat, lon, half_width_m):
    """A square bbox centered on (lat, lon), returned as (min_lon, min_lat, max_lon, max_lat)."""
    d_lat, d_lon = meters_to_degrees(half_width_m, lat)
    return lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat


def bbox_ground_dimensions_m(bbox):
    """
    Actual width/height of a lon/lat bbox in meters, measured along its own
    edges rather than assumed from the degree span. Needed because a box
    that's square in degrees is not square in meters (except at the equator).
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    width_m = haversine_m(mid_lat, min_lon, mid_lat, max_lon)
    height_m = haversine_m(min_lat, min_lon, max_lat, min_lon)
    return width_m, height_m


def expand_bbox(bbox, fraction):
    """Grow a bbox by `fraction` on each side (0.25 = 25% bigger each direction)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    w = max_lon - min_lon
    h = max_lat - min_lat
    return (
        min_lon - w * fraction,
        min_lat - h * fraction,
        max_lon + w * fraction,
        max_lat + h * fraction,
    )
