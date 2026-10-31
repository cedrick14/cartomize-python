import numpy as np
import rasterio

from cartomize.nodata import detect_background
from cartomize.viewer_data import render_raster, raster_info


def test_classified_border_background_is_detected_and_transparent(write_raster, tmp_path):
    data = np.full((20, 20), 1, dtype="uint8")
    data[5:15, 5:15] = 2
    data[0, :] = 9
    data[-1, :] = 9
    data[:, 0] = 9
    data[:, -1] = 9
    path = write_raster("classified_border.tif", data, nodata=None)

    diagnosis = detect_background(path)
    assert diagnosis["automatic_border_values"] == [9.0]

    info = raster_info(path)
    assert info["automatic_nodata"] == [9.0]
    result = render_raster(
        path, (0, 0, 20, 20), (20, 20), bands=(1,),
        classes={1.0: ["Classe 1", "#00aa00"], 2.0: ["Classe 2", "#ffaa00"]},
        transparent_values=info["automatic_nodata"],
    )
    alpha = result["rgba"][..., 3]
    assert np.all(alpha[0, :] == 0)
    assert np.all(alpha[-1, :] == 0)
    assert np.all(alpha[:, 0] == 0)
    assert np.all(alpha[:, -1] == 0)
    assert alpha[10, 10] == 255


def test_binary_zero_is_never_auto_removed(write_raster):
    data = np.zeros((20, 20), dtype="uint8")
    data[4:16, 4:16] = 1
    path = write_raster("binary_zero.tif", data, nodata=None)

    diagnosis = detect_background(path)
    assert diagnosis["binary_zero_preserved"] is True
    assert diagnosis["automatic_border_values"] == []


def test_declared_nodata_remains_authoritative(write_raster):
    data = np.ones((10, 10), dtype="int16")
    data[[0, -1], :] = -9999
    data[:, [0, -1]] = -9999
    path = write_raster("declared_nodata.tif", data, nodata=-9999)

    info = raster_info(path)
    # Provider NoData is already carried by rasterio masks; no extra heuristic
    # is required for the viewer to make it transparent.
    result = render_raster(path, (0, 0, 10, 10), (10, 10), bands=(1,))
    assert result["rgba"][0, 0, 3] == 0
    assert result["rgba"][5, 5, 3] == 255
