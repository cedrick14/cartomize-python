"""Create small, explicitly synthetic Landsat-shaped inputs for a live demo.

These educational rasters are NOT satellite observations. They use the USGS
Collection 2 Level 2 file naming and calibration conventions so that the same
directory/band selection used for extracted USGS products can be rehearsed
offline. No download, account or network connection is required.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject, Resampling
from shapely.geometry import box


def create_demo(destination, *, gap=None, different_crs=False):
    """Create two complementary scenes and AOIs for clipping and mosaicking.

    The west scene has 30 m cells and the east scene 60 m cells. ``gap`` may
    be ``"cloud"`` or ``"nodata"`` to leave a gap outside their overlap.
    ``different_crs=True`` also stores the east scene in the adjacent UTM
    zone, for a demonstration of reprojection to the west scene's grid.
    ``destination`` must not exist, protecting previous demo outputs.
    """
    if gap not in (None, "cloud", "nodata"):
        raise ValueError("gap must be None, 'cloud' or 'nodata'.")
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Use a new demonstration directory: {destination}")
    destination.mkdir(parents=True)
    scene_paths, selected_bands = [], []
    # Integer DNs are calibrated by the normal Landsat C2 L2 input reader.
    digital_numbers = {2: 12000, 3: 14000, 4: 16000, 5: 24000, 6: 19000, 7: 18000}
    top = 9500040

    for name, wrs, left, resolution, width, offset in (
        ("west", "181063", 300000, 30, 64, 0),
        ("east", "182063", 301440, 60, 32, 100),
    ):
        directory = destination / "scenes" / name
        directory.mkdir(parents=True)
        scene_paths.append(str(directory))
        prefix = f"LC08_L2SP_{wrs}_20260817_20260820_02_T1"
        transform = from_origin(left, top, resolution, resolution)
        rows, columns = np.indices((width, width))
        quality = np.zeros((width, width), dtype="uint16")
        saturation = np.zeros_like(quality)
        if gap == "cloud" and name == "west":
            quality[12:18, 12:18] = 8  # QA_PIXEL cloud bit, within the AOI.

        def write(suffix, values, *, nodata):
            path = directory / f"{prefix}_{suffix}.TIF"
            profile = dict(driver="GTiff", width=width, height=width,
                           count=1, dtype="uint16", crs="EPSG:32733",
                           transform=transform, nodata=nodata, compress="lzw")
            if different_crs and name == "east":
                dst_transform, dst_width, dst_height = calculate_default_transform(
                    "EPSG:32733", "EPSG:32734", width, width,
                    left, top - width * resolution, left + width * resolution, top,
                )
                warped = np.full((dst_height, dst_width), nodata, dtype="uint16")
                reproject(values, warped, src_transform=transform, src_crs="EPSG:32733",
                          src_nodata=nodata, dst_transform=dst_transform,
                          dst_crs="EPSG:32734", dst_nodata=nodata,
                          resampling=Resampling.nearest)
                values = warped
                profile.update(width=dst_width, height=dst_height,
                               transform=dst_transform, crs="EPSG:32734")
            with rasterio.open(path, "w", **profile) as target:
                target.write(values, 1)
                target.update_tags(DATA_ORIGIN="synthetic educational demonstration",
                                   NOT_SATELLITE_OBSERVATIONS="true")
            return path

        for band, value in digital_numbers.items():
            values = (value + offset + rows * 20 + columns * 5).astype("uint16")
            if gap == "nodata" and name == "west":
                values[12:18, 12:18] = 0
            selected_bands.append(str(write(f"SR_B{band}", values, nodata=0)))
        write("QA_PIXEL", quality, nodata=65535)
        write("QA_RADSAT", saturation, nodata=65535)
        metadata = ["GROUP = LANDSAT_METADATA_FILE",
                    '  COMMENT = "SYNTHETIC EDUCATIONAL DATA, NOT SATELLITE OBSERVATIONS"',
                    f'  LANDSAT_PRODUCT_ID = "{prefix}"',
                    '  SPACECRAFT_ID = "LANDSAT_8"',
                    '  PROCESSING_LEVEL = "L2SP"',
                    "  DATE_ACQUIRED = 2026-08-17"]
        for band in digital_numbers:
            metadata.extend([f'  FILE_NAME_BAND_{band} = "{prefix}_SR_B{band}.TIF"',
                             f"  REFLECTANCE_MULT_BAND_{band} = 0.0000275",
                             f"  REFLECTANCE_ADD_BAND_{band} = -0.2"])
        metadata.extend(["END_GROUP = LANDSAT_METADATA_FILE", "END"])
        (directory / f"{prefix}_MTL.txt").write_text("\n".join(metadata) + "\n", encoding="utf-8")

    zones = {}
    for name, geometry in (
        ("one_scene", box(300300, 9498840, 301500, 9499740)),
        ("mosaic", box(300300, 9498840, 303060, 9499740)),
    ):
        path = destination / f"zone_{name}.gpkg"
        gpd.GeoDataFrame({"zone": [name], "origin": ["synthetic educational data"]},
                         geometry=[geometry], crs=32733).to_file(path, layer="zone")
        zones[name] = str(path)

    report = dict(data_origin="synthetic educational demonstration; NOT satellite observations",
                  scenes_directory=str(destination / "scenes"), scene_directories=scene_paths,
                  selected_band_paths=selected_bands, zones=zones,
                  band_order=["blue", "green", "red", "nir", "swir1", "swir2"],
                  target_crs="EPSG:32733", native_resolutions_m=[30, 60],
                  different_crs=different_crs, gap=gap)
    (destination / "demo_inputs.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="New directory for the educational inputs")
    parser.add_argument("--gap", choices=("cloud", "nodata"))
    parser.add_argument("--different-crs", action="store_true")
    args = parser.parse_args()
    print(json.dumps(create_demo(args.destination, gap=args.gap,
                                 different_crs=args.different_crs), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
