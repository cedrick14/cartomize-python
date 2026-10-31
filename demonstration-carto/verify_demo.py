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
        RESULTS / "ndvi.png",
        RESULTS / "ndbi.png",
        RESULTS / "evi.png",
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

    # The GitHub notebook must already contain the visual results.
    notebook = json.loads((ROOT / "Tutoriel_Demonstration_Cartomize.ipynb").read_text(encoding="utf-8"))
    embedded_png_outputs = 0
    executed_cells = 0
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        if cell.get("execution_count") is not None:
            executed_cells += 1
        for output in cell.get("outputs", []):
            if "image/png" in output.get("data", {}):
                embedded_png_outputs += 1
    assert executed_cells == sum(1 for cell in notebook["cells"] if cell.get("cell_type") == "code")
    assert embedded_png_outputs >= 4  # composite + NDVI + NDBI + EVI

    # The main demo must not manufacture a classification product.
    assert not (RESULTS / "classification.tif").exists()

    report = {
        "status": "passed",
        "scene": provenance["selected_item_id"],
        "usable_percent": metrics["preprocessing"]["usable_percent"],
        "indices": EXPECTED,
        "checked_outputs": [
            "multiband", "natural_color.png", "indices.tif",
            "ndvi.png", "ndbi.png", "evi.png", "indices_stats.csv",
        ],
        "classification_executed": False,
        "executed_notebook_cells": executed_cells,
        "embedded_png_outputs": embedded_png_outputs,
        "note": "Les indices et statistiques proviennent des rasters Sentinel-2 L2A réellement téléchargés et traités.",
    }
    (RESULTS / "verification.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
