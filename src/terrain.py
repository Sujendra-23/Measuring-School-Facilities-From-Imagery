"""
Composite DEM per campus from USGS 3DEP, plus elevation range and mean slope.

Same pattern as imagery.py: Esri's public ImageServer REST API, no key. The
campus extent is cut into a grid of small tiles, each fetched with exportImage
as a float32 GeoTIFF, then mosaicked back into one array (one overlapping
pixel row/column per seam, averaged where tiles overlap). Elevation range and
slope are computed on that composite.

Run with (from the repo root):  python src/terrain.py
Writes output/terrain.csv; output/measurements.csv is only read, never touched.
"""

import io
import math
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd
from PIL import Image

import config
from geo_utils import bbox_ground_dimensions_m, meters_to_degrees, square_bbox_around
from imagery import _get_with_retries

NODATA_BELOW_M = -1000.0  # 3DEP marks no-data with large negative sentinels; nothing real is this low


@dataclass
class Tile:
    bbox: tuple  # (min_lon, min_lat, max_lon, max_lat)
    shape: tuple  # (rows, cols)
    row_off: int  # offset of the tile's top row within the composite (row 0 = north edge)
    col_off: int


@dataclass
class Dem:
    array: np.ndarray  # float32 meters, NaN where no data; row 0 is the north edge
    bbox: tuple
    dx_m: float  # ground size of one pixel, east-west
    dy_m: float  # ground size of one pixel, north-south
    tiles_fetched: int


def plan_tiles(bbox, resolution_m, max_tile_px, overlap_px=1):
    """
    Cut bbox into a grid of tiles on a common pixel grid of ~resolution_m.
    Returns (grid_shape, snapped_bbox, tiles). The bbox is snapped outward to
    whole pixels so every tile lands on integer offsets in the composite.
    Neighboring tiles share overlap_px extra pixels so the seam is averaged.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    d_lat, d_lon = meters_to_degrees(resolution_m, (min_lat + max_lat) / 2)
    cols = max(1, math.ceil((max_lon - min_lon) / d_lon - 1e-9))
    rows = max(1, math.ceil((max_lat - min_lat) / d_lat - 1e-9))
    snapped = (min_lon, max_lat - rows * d_lat, min_lon + cols * d_lon, max_lat)

    tiles = []
    for r0 in range(0, rows, max_tile_px):
        for c0 in range(0, cols, max_tile_px):
            r_start, r_end = max(0, r0 - overlap_px), min(rows, r0 + max_tile_px + overlap_px)
            c_start, c_end = max(0, c0 - overlap_px), min(cols, c0 + max_tile_px + overlap_px)
            tile_bbox = (
                min_lon + c_start * d_lon,
                snapped[3] - r_end * d_lat,
                min_lon + c_end * d_lon,
                snapped[3] - r_start * d_lat,
            )
            tiles.append(Tile(tile_bbox, (r_end - r_start, c_end - c_start), r_start, c_start))
    return (rows, cols), snapped, tiles


def mosaic(tiles_and_arrays, grid_shape):
    """Place tile arrays into one composite; overlapping pixels are averaged, NaN stays NaN."""
    total = np.zeros(grid_shape, dtype=np.float64)
    count = np.zeros(grid_shape, dtype=np.int32)
    for tile, arr in tiles_and_arrays:
        r, c = tile.row_off, tile.col_off
        window = (slice(r, r + arr.shape[0]), slice(c, c + arr.shape[1]))
        valid = ~np.isnan(arr)
        total[window] += np.where(valid, arr, 0.0)
        count[window] += valid
    out = np.full(grid_shape, np.nan, dtype=np.float32)
    np.divide(total, count, out=out, where=count > 0, casting="unsafe")
    return out


def decode_tiff(content):
    """Bytes of a float32 GeoTIFF from exportImage -> 2D array with no-data as NaN."""
    arr = np.array(Image.open(io.BytesIO(content)), dtype=np.float32)
    arr[arr < NODATA_BELOW_M] = np.nan
    return arr


def fetch_tile(tile):
    """Download one tile of bare-earth elevation (meters) from 3DEP."""
    rows, cols = tile.shape
    response = _get_with_retries(
        f"{config.DEM_IMAGE_SERVER}/exportImage",
        params={
            "bbox": ",".join(str(v) for v in tile.bbox),
            "bboxSR": 4326,
            "imageSR": 4326,
            "size": f"{cols},{rows}",
            "format": "tiff",
            "pixelType": "F32",
            "interpolation": "RSP_BilinearInterpolation",
            "f": "image",
        },
        timeout=30,
    )
    return decode_tiff(response.content)


def composite_dem(bbox, resolution_m=None, max_tile_px=None, fetcher=fetch_tile):
    """
    Fetch every tile covering bbox and mosaic them into one Dem.
    `fetcher(tile) -> 2D array` is injectable so tests can run offline.
    """
    resolution_m = resolution_m or config.DEM_RESOLUTION_M
    max_tile_px = max_tile_px or config.DEM_MAX_TILE_PIXELS
    grid_shape, snapped, tiles = plan_tiles(bbox, resolution_m, max_tile_px)
    fetched = []
    for tile in tiles:
        arr = np.asarray(fetcher(tile), dtype=np.float32)
        if arr.shape != tile.shape:
            raise ValueError(f"tile came back {arr.shape}, expected {tile.shape}")
        fetched.append((tile, arr))
    width_m, height_m = bbox_ground_dimensions_m(snapped)
    return Dem(
        array=mosaic(fetched, grid_shape),
        bbox=snapped,
        dx_m=width_m / grid_shape[1],
        dy_m=height_m / grid_shape[0],
        tiles_fetched=len(tiles),
    )


def slope_degrees(elevation, dx_m, dy_m):
    """Slope angle per pixel in degrees, from central differences (one-sided at the edges)."""
    if min(elevation.shape) < 2:
        return np.full(elevation.shape, np.nan, dtype=np.float32)
    dz_dy, dz_dx = np.gradient(elevation.astype(np.float64), dy_m, dx_m)
    # rows increase southward, which flips the sign of dz_dy; slope magnitude doesn't care
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype(np.float32)


def terrain_stats(dem):
    """Elevation range and slope summary for one composite DEM."""
    z = dem.array
    if np.isnan(z).all():
        return {"status": "no elevation data returned"}
    slope = slope_degrees(z, dem.dx_m, dem.dy_m)
    return {
        "elev_min_m": float(np.nanmin(z)),
        "elev_max_m": float(np.nanmax(z)),
        "elev_range_m": float(np.nanmax(z) - np.nanmin(z)),
        "elev_mean_m": float(np.nanmean(z)),
        "mean_slope_deg": float(np.nanmean(slope)),
        "max_slope_deg": float(np.nanmax(slope)),
        "dem_resolution_m": round((dem.dx_m + dem.dy_m) / 2, 2),
        "dem_pixels": int(z.size),
        "tiles_fetched": dem.tiles_fetched,
        "nodata_fraction": float(np.isnan(z).mean()),
        "status": "ok",
    }


TERRAIN_COLUMNS = [
    "school_id", "school_name",
    "elev_min_m", "elev_max_m", "elev_range_m", "elev_mean_m",
    "mean_slope_deg", "max_slope_deg",
    "dem_resolution_m", "dem_pixels", "tiles_fetched", "nodata_fraction",
    "dem_source", "status",
]


def main():
    schools = pd.read_csv(config.MEASUREMENTS_CSV, dtype={"school_id": str})
    rows = []
    for s in schools.itertuples():
        print(f"[{s.school_id}] {s.school_name} ...", file=sys.stderr)
        # Same extent the vision model saw when the campus polygon was unknown:
        # a default square around the resolved point.
        bbox = square_bbox_around(s.location_lat, s.location_lon, config.DEFAULT_CROP_METERS / 2)
        row = {"school_id": s.school_id, "school_name": s.school_name, "dem_source": "USGS 3DEP"}
        try:
            row.update(terrain_stats(composite_dem(bbox)))
        except Exception as exc:  # one bad school shouldn't kill the run
            print(f"  FAILED: {exc}", file=sys.stderr)
            row["status"] = f"dem fetch failed: {exc}"
        rows.append(row)
    pd.DataFrame(rows, columns=TERRAIN_COLUMNS).to_csv(config.TERRAIN_CSV, index=False)
    print(f"wrote {config.TERRAIN_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
