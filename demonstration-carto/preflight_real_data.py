"""Diagnostic détaillé avant la démonstration, sans modifier les données."""
from pathlib import Path
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask

import cartomize as cm

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "preflight"

if OUT.exists():
    import shutil
    shutil.rmtree(OUT)
OUT.mkdir()

aoi = gpd.read_file(DATA / "aoi.geojson")
scene = cm.load_scenes_manifest(DATA / "scenes.json")[0]
records = []
for name, band in {**scene.bands, "scl": None}.items():
    path = Path(scene.quality) if name == "scl" else Path(band.path)
    with rasterio.open(path) as src:
        geom = [g.__geo_interface__ for g in aoi.to_crs(src.crs).geometry]
        arr, transform = mask(src, geom, crop=True, filled=False, indexes=1)
        observed = ~np.ma.getmaskarray(arr)
        values = arr.data[observed]
        record = {
            "name": name,
            "file": path.name,
            "crs": str(src.crs),
            "shape": [src.height, src.width],
            "bounds": list(src.bounds),
            "resolution": list(src.res),
            "nodata": src.nodata,
            "aoi_pixels_observed": int(observed.sum()),
            "aoi_pixels_total_crop": int(arr.size),
            "aoi_observed_percent": float(100 * observed.sum() / arr.size) if arr.size else 0,
            "zero_pixels": int((values == 0).sum()) if values.size else 0,
            "min": float(values.min()) if values.size else None,
            "max": float(values.max()) if values.size else None,
        }
        if name != "scl":
            record.update(scale=band.scale, offset=band.offset, unit=band.unit)
        else:
            unique, counts = np.unique(values.astype("int64"), return_counts=True)
            record["codes"] = {str(int(k)): int(v) for k, v in zip(unique, counts)}
        records.append(record)

audit = cm.audit_imagery(
    [scene], OUT / "audit",
    aoi=DATA / "aoi.geojson",
    band_order=["blue", "green", "red", "nir"],
    coverage_threshold=95,
    mask_clouds=True,
    mask_saturation=False,
)
report = {
    "sources": records,
    "audit": audit.report,
}
(OUT / "preflight.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({
    "source_summary": records,
    "audit_summary": {
        "aoi_pixels": audit.report["aoi_pixels"],
        "footprint_percent": audit.report["footprint_percent"],
        "present_percent": audit.report["present_percent"],
        "usable_percent": audit.report["usable_percent"],
        "scene": audit.report["scenes"],
    },
}, indent=2, ensure_ascii=False))
