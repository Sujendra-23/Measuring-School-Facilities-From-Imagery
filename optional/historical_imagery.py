"""
Fetch a satellite image crop for a school at an arbitrary point in time,
using Esri's Wayback Imagery archive -- a free, keyless service that keeps
dated snapshots of its World Imagery basemap going back to 2014, built
specifically for this kind of "what did this place look like before"
comparison.

USGS NAIP (used by the main pipeline in src/imagery.py) doesn't work for
this: its live ImageServer only serves the current mosaic for each area, not
a queryable history -- confirmed by querying it directly and getting back a
single tile regardless of how the query was framed. Wayback is a genuinely
different, purpose-built archive, which is why the optional multi-date
check uses it for both time points rather than mixing providers.

Wayback is tile-based (WMTS), not a bbox export API like NAIP's, so getting
a clean square crop means fetching a small grid of tiles around the target
point and stitching them -- the one piece of real complexity here.
"""

import io
import math

import requests
from PIL import Image

WAYBACK_CONFIG_URL = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
TILE_PX = 256
_HEADERS = {"User-Agent": "school-facilities-imagery-pipeline/1.0 (student take-home task, optional part)"}


def load_releases():
    """Returns a list of {date, title, url_template} for every available Wayback snapshot, oldest first."""
    response = requests.get(WAYBACK_CONFIG_URL, headers=_HEADERS, timeout=30)
    response.raise_for_status()
    releases = []
    for entry in response.json().values():
        title = entry["itemTitle"]  # e.g. "World Imagery (Wayback 2018-05-16)"
        date = title.rsplit("(Wayback ", 1)[1].rstrip(")")
        releases.append({"date": date, "title": title, "url_template": entry["itemURL"]})
    releases.sort(key=lambda r: r["date"])
    return releases


def closest_release(releases, target_date):
    """The release whose date is nearest to target_date (a 'YYYY-MM-DD' string), preferring not-later-than."""
    not_later = [r for r in releases if r["date"] <= target_date]
    return not_later[-1] if not_later else releases[0]


def _lonlat_to_tile(lon, lat, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _ground_resolution_m_per_px(lat, zoom):
    """Standard Web Mercator resolution formula for the default 0.28mm (256px) tile scheme."""
    return math.cos(math.radians(lat)) * 2 * math.pi * 6378137 / (TILE_PX * 2 ** zoom)


def fetch_crop(url_template, lat, lon, zoom=18, grid=3):
    """
    Downloads a grid x grid block of WMTS tiles centered on (lat, lon) at the
    given zoom, stitches them into one square image, and returns
    (PIL.Image, meters_per_pixel).
    """
    x_frac, y_frac = _lonlat_to_tile(lon, lat, zoom)
    center_col, center_row = int(x_frac), int(y_frac)
    half = grid // 2

    canvas = Image.new("RGB", (TILE_PX * grid, TILE_PX * grid))
    for row_offset in range(-half, half + 1):
        for col_offset in range(-half, half + 1):
            col, row = center_col + col_offset, center_row + row_offset
            url = url_template.format(level=zoom, row=row, col=col)
            response = requests.get(url, headers=_HEADERS, timeout=30)
            response.raise_for_status()
            tile = Image.open(io.BytesIO(response.content)).convert("RGB")
            canvas.paste(tile, ((col_offset + half) * TILE_PX, (row_offset + half) * TILE_PX))

    return canvas, _ground_resolution_m_per_px(lat, zoom)
