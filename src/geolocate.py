"""
Resolve where a school's campus actually is.

The CCD lat/lon we're given is "the federal record, not a survey" -- per the
assignment brief it's sometimes a mailing address or district office instead
of the campus itself. Before we crop a satellite image around a point, we try
to confirm that point (or find a better one) against OpenStreetMap, which
often has the school mapped as a real building or grounds polygon with a name
we can match against.

Strategy, in order of preference:
  1. Look for an OSM feature tagged amenity=school within search radius of
     the CCD point, whose name roughly matches the CCD school name. This can
     be a way/relation (a traced campus outline -- we size the image crop to
     it directly) or a node (a single mapped point, common for smaller
     schools nobody has traced a building for -- we get a confirmed center
     but fall back to a default crop size).
  2. Failing that, look for a building=school with a matching name. OSM only
     gives us a single building footprint here, not the full campus, so we
     use its centroid as the point but fall back to a default crop size.
  3. Failing that, we just use the CCD point as-is, with a default crop size
     and a low confidence flag so downstream steps (and the memo) know this
     school's location was never independently confirmed.
"""

import difflib
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests

import config
from geo_utils import bbox_from_points, expand_bbox


@dataclass
class ResolvedLocation:
    lat: float
    lon: float
    bbox: Optional[tuple]  # (min_lon, min_lat, max_lon, max_lat) in degrees, or None
    source: str  # 'osm_school_grounds', 'osm_school_point', 'osm_building', or 'ccd_raw'
    confidence: float
    matched_name: Optional[str] = None


def _name_similarity(a, b):
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


_HEADERS = {
    # Overpass's public instance 406's the default python-requests user-agent.
    # It also asks heavy users to identify themselves, so we do that here.
    "User-Agent": "school-facilities-imagery-pipeline/1.0 (student take-home task)"
}


def _query_overpass(query, attempts=3):
    """
    The public Overpass instance is shared and free, which means it's prone
    to timeouts under load. We retry a couple of times, but if it's still
    down we return an empty result rather than raising -- a school whose OSM
    lookup failed should fall back to the CCD point, not crash the batch.
    """
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                config.OVERPASS_URL, data={"data": query}, timeout=30, headers=_HEADERS
            )
            response.raise_for_status()
            return response.json()["elements"]
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(3 * (attempt + 1))
    print(f"  Overpass unavailable after {attempts} attempts ({last_error}); "
          f"falling back to CCD coordinates", file=sys.stderr)
    return []


def _fetch_candidates(lat, lon, tag_key, tag_value, want_geometry, include_nodes=False):
    """
    One Overpass query for a given tag (e.g. amenity=school) near (lat, lon).
    include_nodes matters: smaller/rural schools are often mapped as a single
    point (a node) rather than a traced building outline, and a query that
    only asks for way/relation silently misses them -- discovered by hand
    on a real school in this dataset (see memo).
    """
    out_clause = "out geom;" if want_geometry else "out center tags;"
    node_clause = f'node["{tag_key}"="{tag_value}"](around:{config.OSM_SEARCH_RADIUS_M},{lat},{lon});' \
        if include_nodes else ""
    query = f"""
    [out:json][timeout:25];
    (
      {node_clause}
      way["{tag_key}"="{tag_value}"](around:{config.OSM_SEARCH_RADIUS_M},{lat},{lon});
      relation["{tag_key}"="{tag_value}"](around:{config.OSM_SEARCH_RADIUS_M},{lat},{lon});
    );
    {out_clause}
    """
    return _query_overpass(query)


def _element_center(element):
    if "lat" in element and "lon" in element:  # a node is its own position
        return element["lat"], element["lon"]
    if "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    if "geometry" in element and element["geometry"]:
        lats = [p["lat"] for p in element["geometry"]]
        lons = [p["lon"] for p in element["geometry"]]
        return sum(lats) / len(lats), sum(lons) / len(lons)
    return None


def _best_match(elements, school_name):
    """Pick the element whose name best matches school_name. Returns (element, score) or (None, 0)."""
    best_element, best_score = None, 0.0
    for element in elements:
        name = element.get("tags", {}).get("name")
        score = _name_similarity(name, school_name)
        if score > best_score:
            best_element, best_score = element, score
    return best_element, best_score


def resolve_location(school_name, ccd_lat, ccd_lon):
    # Preference 1: a named amenity=school feature -- a way/relation with a
    # traced outline, or a node with just a point. Both are a direct "this
    # is a school" tag from a human mapper, which is why even the node case
    # outranks the building=school fallback below.
    grounds = _fetch_candidates(
        ccd_lat, ccd_lon, "amenity", "school", want_geometry=True, include_nodes=True
    )
    time.sleep(config.OVERPASS_DELAY_SECONDS)
    match, score = _best_match(grounds, school_name)
    if match and score >= config.OSM_NAME_MATCH_THRESHOLD:
        center_lat, center_lon = _element_center(match)
        if "geometry" in match and match["geometry"]:
            points = [(p["lat"], p["lon"]) for p in match["geometry"]]
            bbox = expand_bbox(bbox_from_points(points), config.CROP_BUFFER_FRACTION)
            return ResolvedLocation(
                lat=center_lat,
                lon=center_lon,
                bbox=bbox,
                source="osm_school_grounds",
                confidence=0.6 + 0.3 * score,  # name match quality nudges this up
                matched_name=match["tags"].get("name"),
            )
        if center_lat is not None:
            # A confirmed amenity=school tag, but only a point (typically a
            # node) -- no outline to size the crop against, so it falls back
            # to the same default box as an unconfirmed CCD point. Still
            # meaningfully better than ccd_raw: a human mapper actually
            # confirmed a school exists here, under this name.
            return ResolvedLocation(
                lat=center_lat,
                lon=center_lon,
                bbox=None,
                source="osm_school_point",
                confidence=0.5 + 0.25 * score,
                matched_name=match["tags"].get("name"),
            )

    # Preference 2: a single building tagged building=school with a matching
    # name. Useful as a location fix, but not a campus outline -- one
    # building isn't the whole campus (fields, courts, etc. are outside it).
    buildings = _fetch_candidates(
        ccd_lat, ccd_lon, "building", "school", want_geometry=False, include_nodes=True
    )
    time.sleep(config.OVERPASS_DELAY_SECONDS)
    match, score = _best_match(buildings, school_name)
    if match and score >= config.OSM_NAME_MATCH_THRESHOLD:
        center_lat, center_lon = _element_center(match)
        return ResolvedLocation(
            lat=center_lat,
            lon=center_lon,
            bbox=None,
            source="osm_building",
            confidence=0.45 + 0.2 * score,
            matched_name=match["tags"].get("name"),
        )

    # Preference 3: give up and trust the CCD point, but say so plainly.
    return ResolvedLocation(
        lat=ccd_lat,
        lon=ccd_lon,
        bbox=None,
        source="ccd_raw",
        confidence=0.3,
        matched_name=None,
    )
