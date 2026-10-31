"""Vérifications factuelles de la démonstration Cartomize."""
from pathlib import Path
import json
import math

import rasterio
import geopandas as gpd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"


def main():
    provenance = json.loads((DATA / "provenance.json").read_text(encoding="utf-8"))
    metrics = json.loads((RESULTS / "metrics.json").read_text(encoding="utf-8"))

    assert provenance["data_are_synthetic"] is False
    assert provenance["collection"] == "sentinel-2-l2a"
    assert provenance["selected_item_id"] == metrics["scene"]["id"]
    assert provenance["source_assets"]
    assert metrics["preprocessing"]["threshold_met"] is True
    assert metrics["preprocessing"]["usable_percent"] >= 95.0

    multiband = RESULTS / "preprocessed" / metrics["products"]["multiband"]
    indices = RESULTS / "indices.tif"
    visual_files = (
        RESULTS / "kinshasa_scene_input.png",
        RESULTS / "natural_color.png",
        RESULTS / "kinshasa_preprocessing_comparison.png",
        RESULTS / "indices.png",
        RESULTS / "scl.png",
    )
    for path in (multiband, indices, *visual_files):
        assert path.is_file() and path.stat().st_size > 0, path

    with rasterio.open(multiband) as src:
        assert src.count == 4
        assert tuple(name.lower() for name in src.descriptions) == ("blue", "green", "red", "nir")
        assert src.crs is not None

    before_red = DATA / "input_scene" / "B04.tif"
    assert before_red.is_file(), before_red
    aoi = gpd.read_file(DATA / "aoi.geojson")
    with rasterio.open(before_red) as src:
        bounds = aoi.to_crs(src.crs).total_bounds
        scene_width = src.bounds.right - src.bounds.left
        scene_height = src.bounds.top - src.bounds.bottom
        aoi_width = bounds[2] - bounds[0]
        aoi_height = bounds[3] - bounds[1]
        assert scene_width > aoi_width * 1.2
        assert scene_height > aoi_height * 1.2
    with rasterio.open(indices) as src:
        assert src.count == 3
        assert tuple(src.descriptions) == ("NDVI", "NDWI", "EVI")

    for name in ("NDVI", "NDWI", "EVI"):
        stats = metrics["indices"][name]
        assert stats["count"] > 0
        assert all(math.isfinite(float(stats[key])) for key in ("min", "max", "mean", "std", "p05", "p50", "p95"))

    notebook = json.loads((ROOT / "Tutoriel_Demonstration_Cartomize.ipynb").read_text(encoding="utf-8"))
    notebook_errors = [
        output
        for cell in notebook.get("cells", [])
        for output in cell.get("outputs", [])
        if output.get("output_type") == "error"
    ]
    notebook_image_outputs = sum(
        1
        for cell in notebook.get("cells", [])
        for output in cell.get("outputs", [])
        if isinstance(output.get("data", {}).get("image/png"), str)
        and output["data"]["image/png"].strip()
    )
    markdown = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
        if cell.get("cell_type") == "markdown"
    )
    notebook_source = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook.get("cells", [])
    )
    markdown_visuals = [
        path for path in visual_files
        if (
            f"./results/{path.name}" in markdown
            or f"results/{path.name}" in markdown
        )
    ]
    assert not notebook_errors
    assert notebook_image_outputs + len(markdown_visuals) >= 4, (
        "Le notebook doit rendre au moins 4 figures pédagogiques vérifiées."
    )
    assert "kinshasa_scene_input.png" in markdown
    assert "kinshasa_preprocessing_comparison.png" in markdown
    assert "Sentinel-2 L2A — Kinshasa" in notebook_source
    assert "Produit prétraité" in notebook_source

    total = sum(row["pixels"] for row in metrics["scl"])
    assert total > 0
    assert abs(sum(row["percent"] for row in metrics["scl"]) - 100.0) < 1e-6

    report = {
        "status": "passed",
        "scene": provenance["selected_item_id"],
        "usable_percent": metrics["preprocessing"]["usable_percent"],
        "checked_outputs": [
            "multiband", "indices", "kinshasa_scene_input.png",
            "natural_color.png", "kinshasa_preprocessing_comparison.png", "indices.png", "scl.png"
        ],
        "notebook_image_outputs": notebook_image_outputs,
        "notebook_markdown_visuals": [path.name for path in markdown_visuals],
        "note": (
            "Le tutoriel vérifie une scène candidate plus large que l'AOI, "
            "le journal du diagnostic automatique et le résultat final découpé."
        ),
    }
    (RESULTS / "verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
