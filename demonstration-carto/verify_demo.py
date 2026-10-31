"""Vérifications factuelles de la démonstration Cartomize centrée sur l'automatisation."""
from pathlib import Path
import json
import math

import rasterio

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

EXPECTED = ["NDVI", "NDBI", "EVI"]


def main():
    provenance = json.loads((DATA / "provenance.json").read_text(encoding="utf-8"))
    metrics = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))

    assert provenance["data_are_synthetic"] is False
    assert provenance["collection"] == "sentinel-2-l2a"
    assert provenance["selected_item_id"] == metrics["scene"]["id"]
    assert provenance["source_assets"]
    assert metrics["preprocessing"]["threshold_met"] is True
    assert metrics["preprocessing"]["usable_percent"] >= 95.0
    assert metrics["selected_indices"] == EXPECTED

    multiband = RESULTS / "preprocessed" / metrics["products"]["multiband"]
    indices = RESULTS / "indices.tif"
    required = [
        multiband, indices,
        RESULTS / "natural_color.png",
        RESULTS / "indices_overview.png",
        RESULTS / "indices_stats.csv",
    ]
    for path in required:
        assert path.is_file() and path.stat().st_size > 0, path

    with rasterio.open(multiband) as src:
        assert src.count == 5
        assert tuple(name.lower() for name in src.descriptions) == ("blue", "green", "red", "nir", "swir1")
        assert src.crs is not None

    with rasterio.open(indices) as src:
        assert src.count == len(EXPECTED)
        assert list(src.descriptions) == EXPECTED

    for name in EXPECTED:
        stats = metrics["indices"][name]
        assert stats["count"] > 0
        assert all(math.isfinite(float(stats[key])) for key in ("min", "max", "mean", "std", "p05", "p50", "p95"))

    # The main demo must not manufacture a classification product.
    assert not (RESULTS / "classification.tif").exists()

    report = {
        "status": "passed",
        "scene": provenance["selected_item_id"],
        "usable_percent": metrics["preprocessing"]["usable_percent"],
        "indices": EXPECTED,
        "checked_outputs": [
            "multiband", "natural_color.png", "indices.tif",
            "indices_stats.csv", "indices_overview.png",
        ],
        "classification_executed": False,
        "note": "Les indices et statistiques proviennent des rasters Sentinel-2 L2A réellement téléchargés et traités.",
    }
    (RESULTS / "verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
