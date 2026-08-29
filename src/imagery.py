"""
Fetch a satellite image crop for a resolved campus location, and look up the
NAIP tile metadata (acquisition date, native resolution) that covers it.

Everything here talks to USGS's public ImageServer REST API -- no API key,
no cost, no rate-limit headaches at our scale (25 schools).
"""

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

import config
from geo_utils import bbox_ground_dimensions_m, square_bbox_around


def _get_with_retries(url, params, timeout, attempts=3):
    """
    USGS's ImageServer is free, public, and occasionally throws a transient
    502/503 under load -- the same kind of hiccup we saw from Overpass.
    A couple of retries clears it without any real cost.
    """
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(3 * (attempt + 1))
    raise last_error


@dataclass
class ImageResult:
    file_path: str
    bbox: tuple  # (min_lon, min_lat, max_lon, max_lat) actually requested
    meters_per_pixel: float
    acquisition_date: Optional[str]  # ISO date string, or None if lookup failed
    native_resolution_m: Optional[float]


def _crop_bbox(resolved_location):
    """Decide the bbox to request: the campus polygon if we have one, else a default square."""
    if resolved_location.bbox is not None:
        return resolved_location.bbox
    return square_bbox_around(
        resolved_location.lat, resolved_location.lon, config.DEFAULT_CROP_METERS / 2
    )


def _lookup_tile_metadata(lat, lon):
    """
    Ask the ImageServer which NAIP tile covers this point, and pull its
    acquisition date + native resolution. Category=1 filters out the
    low-resolution "overview" mosaic entries, which have these fields null.
    """
    try:
        response = _get_with_retries(
            f"{config.NAIP_IMAGE_SERVER}/query",
            params={
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "where": "Category=1",
                "outFields": "acquisition_date,resolution_value",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=15,
        )
        features = response.json().get("features", [])
        if not features:
            return None, None
        attrs = features[0]["attributes"]
        date_ms = attrs.get("acquisition_date")
        date_str = None
        if date_ms is not None:
            date_str = datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc).date().isoformat()
        return date_str, attrs.get("resolution_value")
    except requests.RequestException:
        return None, None


def fetch_image(school_id, resolved_location):
    """Download a square PNG crop centered on the resolved location and return an ImageResult."""
    bbox = _crop_bbox(resolved_location)
    width_m, height_m = bbox_ground_dimensions_m(bbox)
    meters_per_pixel = max(width_m, height_m) / config.IMAGE_PIXELS

    response = _get_with_retries(
        f"{config.NAIP_IMAGE_SERVER}/exportImage",
        params={
            "bbox": ",".join(str(v) for v in bbox),
            "bboxSR": 4326,
            "imageSR": 4326,
            "size": f"{config.IMAGE_PIXELS},{config.IMAGE_PIXELS}",
            "format": "png",
            "f": "image",
        },
        timeout=30,
    )

    os.makedirs(config.IMAGE_CACHE_DIR, exist_ok=True)
    file_path = os.path.join(config.IMAGE_CACHE_DIR, f"{school_id}.png")
    with open(file_path, "wb") as f:
        f.write(response.content)

    acquisition_date, native_resolution_m = _lookup_tile_metadata(
        resolved_location.lat, resolved_location.lon
    )

    return ImageResult(
        file_path=file_path,
        bbox=bbox,
        meters_per_pixel=meters_per_pixel,
        acquisition_date=acquisition_date,
        native_resolution_m=native_resolution_m,
    )
