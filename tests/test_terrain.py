"""DEM compositing and terrain stats, entirely offline: tiles come from a fake fetcher or an in-memory TIFF."""

import io

import numpy as np
import pytest
from PIL import Image

import config
import terrain
from terrain import Tile, composite_dem, mosaic, plan_tiles, slope_degrees, terrain_stats

BBOX = (-100.0, 40.0, -99.99, 40.01)  # ~850 m x ~1110 m


def truth(rows, cols):
    """A known surface: elevation depends only on pixel position, so any tile can be 'fetched' exactly."""
    r, c = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    return (100 + 2.0 * r + 3.0 * c).astype(np.float32)


def fake_fetcher(grid_shape):
    ground = truth(*grid_shape)

    def fetch(tile):
        rows, cols = tile.shape
        return ground[tile.row_off:tile.row_off + rows, tile.col_off:tile.col_off + cols]

    return fetch


def test_plan_tiles_covers_grid_with_overlap():
    grid, snapped, tiles = plan_tiles(BBOX, resolution_m=10, max_tile_px=32, overlap_px=1)
    rows, cols = grid
    assert snapped[0] == BBOX[0] and snapped[3] == BBOX[3]
    assert snapped[2] >= BBOX[2] and snapped[1] <= BBOX[1]  # snapped outward, never inward
    covered = np.zeros(grid, dtype=int)
    for t in tiles:
        covered[t.row_off:t.row_off + t.shape[0], t.col_off:t.col_off + t.shape[1]] += 1
    assert covered.min() >= 1
    assert covered.max() == 4  # four tiles meet at interior corners
    assert len(tiles) == int(np.ceil(rows / 32)) * int(np.ceil(cols / 32))


def test_plan_tiles_tile_bboxes_line_up_with_pixels():
    grid, snapped, tiles = plan_tiles(BBOX, 10, 32, overlap_px=0)
    d_lon = (snapped[2] - snapped[0]) / grid[1]
    d_lat = (snapped[3] - snapped[1]) / grid[0]
    for t in tiles:
        assert t.bbox[0] == pytest.approx(snapped[0] + t.col_off * d_lon)
        assert t.bbox[3] == pytest.approx(snapped[3] - t.row_off * d_lat)
        assert (t.bbox[2] - t.bbox[0]) / d_lon == pytest.approx(t.shape[1])
        assert (t.bbox[3] - t.bbox[1]) / d_lat == pytest.approx(t.shape[0])


def test_composite_reproduces_known_surface():
    grid, _, _ = plan_tiles(BBOX, 10, 32)
    dem = composite_dem(BBOX, resolution_m=10, max_tile_px=32, fetcher=fake_fetcher(grid))
    assert dem.tiles_fetched > 1
    np.testing.assert_array_equal(dem.array, truth(*grid))


def test_mosaic_averages_overlap_and_ignores_nan():
    a = np.array([[1.0, 2.0, np.nan]], dtype=np.float32)
    b = np.array([[4.0, 6.0, 8.0]], dtype=np.float32)
    out = mosaic([(Tile(None, a.shape, 0, 0), a), (Tile(None, b.shape, 0, 1), b)], (1, 4))
    # col0 only a; col1 mean(a=2,b=4); col2 a is NaN so only b=6; col3 only b=8
    np.testing.assert_array_equal(out, [[1.0, 3.0, 6.0, 8.0]])


def test_mosaic_gap_stays_nan():
    a = np.ones((1, 1), dtype=np.float32)
    out = mosaic([(Tile(None, (1, 1), 0, 0), a)], (1, 3))
    assert out[0, 0] == 1.0 and np.isnan(out[0, 1:]).all()


def test_composite_rejects_wrong_sized_tile():
    with pytest.raises(ValueError):
        composite_dem(BBOX, 10, 32, fetcher=lambda tile: np.zeros((1, 1)))


def test_slope_known_answers():
    ramp = np.tile(np.arange(10, dtype=np.float32), (10, 1))  # +1 m per pixel eastward
    assert slope_degrees(ramp, dx_m=10, dy_m=10) == pytest.approx(np.degrees(np.arctan(0.1)), abs=1e-4)
    assert np.allclose(slope_degrees(np.full((5, 5), 50.0, dtype=np.float32), 10, 10), 0)
    steep = np.tile(np.arange(10, dtype=np.float32) * 10, (10, 1))  # 10 m rise per 10 m run
    assert slope_degrees(steep, 10, 10) == pytest.approx(45.0, abs=1e-4)


def test_terrain_stats_on_known_surface():
    grid, snapped, _ = plan_tiles(BBOX, 10, 32)
    dem = composite_dem(BBOX, 10, 32, fetcher=fake_fetcher(grid))
    stats = terrain_stats(dem)
    rows, cols = grid
    assert stats["status"] == "ok"
    assert stats["elev_min_m"] == 100.0
    assert stats["elev_max_m"] == 100.0 + 2.0 * (rows - 1) + 3.0 * (cols - 1)
    assert stats["elev_range_m"] == stats["elev_max_m"] - stats["elev_min_m"]
    # plane tilts 3 m/pixel east and 2 m/pixel south: slope = atan(hypot(3/dx, 2/dy))
    expected = np.degrees(np.arctan(np.hypot(3 / dem.dx_m, 2 / dem.dy_m)))
    assert stats["mean_slope_deg"] == pytest.approx(expected, rel=1e-4)
    assert stats["nodata_fraction"] == 0.0


def test_terrain_stats_all_nodata():
    dem = composite_dem(BBOX, 10, 32, fetcher=lambda t: np.full(t.shape, np.nan, dtype=np.float32))
    assert terrain_stats(dem)["status"] == "no elevation data returned"


def test_decode_tiff_maps_nodata_to_nan():
    arr = np.array([[10.5, -9999.0], [12.25, 11.0]], dtype=np.float32)
    buf = io.BytesIO()
    Image.fromarray(arr, mode="F").save(buf, format="TIFF")
    out = terrain.decode_tiff(buf.getvalue())
    assert out.shape == (2, 2) and np.isnan(out[0, 1])
    assert out[0, 0] == 10.5 and out[1, 0] == 12.25


def test_fetch_tile_builds_the_expected_request(monkeypatch):
    seen = {}

    class FakeResponse:
        content = None

    buf = io.BytesIO()
    Image.fromarray(np.full((4, 3), 5.0, dtype=np.float32), mode="F").save(buf, format="TIFF")
    FakeResponse.content = buf.getvalue()

    def fake_get(url, params, timeout):
        seen.update(url=url, params=params)
        return FakeResponse

    monkeypatch.setattr(terrain, "_get_with_retries", fake_get)
    out = terrain.fetch_tile(Tile((-100.0, 40.0, -99.99, 40.01), (4, 3), 0, 0))
    assert seen["url"] == f"{config.DEM_IMAGE_SERVER}/exportImage"
    assert seen["params"]["size"] == "3,4"
    assert seen["params"]["format"] == "tiff" and seen["params"]["pixelType"] == "F32"
    assert out.shape == (4, 3) and (out == 5.0).all()
