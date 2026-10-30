# Cartomize 1.0

Cartomize combines a Python library, Jupyter workflows, a command-line interface and a desktop application for geospatial processing and cartographic production. This consolidated edition includes the completed imagery and vector modules through **G12 — Distance rings and verified surface balances**.

## Installation

Python 3.11 or 3.12 is recommended for the desktop. Cartomize runs independently of QGIS and ArcGIS Pro; native project bridges are optional.

Install Cartomize in a new environment:

```bash
python -m venv cartomize-env
```

Activate that environment, then install one of the following options:

```bash
# Desktop application
python -m pip install --index-url https://pypi.org/simple "cartomize[gui]==1.0"
python -m cartomize gui

# Desktop application, JupyterLab and a Python kernel
python -m pip install --index-url https://pypi.org/simple "cartomize[notebook]==1.0"
python -m jupyter lab
```

The Python API alone is installed with `cartomize==1.0`. All options use the same processing code. This dynamic desktop edition keeps public version **1.0** and uses wheel build **2026103001**. If another edition numbered 1.0 is already installed, replace it explicitly:

```bash
python -m pip install --index-url https://pypi.org/simple --force-reinstall --no-cache-dir "cartomize[notebook]==1.0"
python -c "from importlib.metadata import distribution; print(distribution('cartomize').read_text('WHEEL'))"
```

The installed wheel must report `Build: 2026103001`. Release availability and verification are tracked in the [publication guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/PUBLICATION.md). Complete sources, the wheel and a portable demonstration are available through [GitHub releases](https://github.com/cedrick14/cartomize-python/releases).

## Dynamic desktop workspace

The default arrangement keeps the explorer and tools on the left, results in the centre, parameters on the right and the console below. Panels and result views can be detached, resized, maximized, docked on any side or grouped into tabs. Dragging a title bar displays placement guides and a preview of the target position.

**F11** enlarges the central view. **Escape** restores a focused workspace or cancels a drag. **Affichage → Rétablir la disposition** restores the default arrangement and returns detached results to the central tabs. Tool values and existing map canvases are preserved when moving panels. Local layout preferences and project view positions are saved separately.

The light, dark and system themes are retained. Long descriptions are collapsed into **Aide**, while required units, validation messages and processing diagnostics remain visible. See the [dynamic workspace guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/DYNAMIC_WORKSPACE.md).

## Automatic satellite preprocessing

Choose the downloaded scenes, the bands to process and a polygon study area. The automatic workflow then:

1. Recognizes supported Landsat Collection 2 Level-2 and Sentinel-2 Level-2A products, calibration and quality masks.
2. Establishes a common projected grid and resolution.
3. Measures footprint coverage, available data and usable observations within the study area.
4. Selects one sufficient scene or the contributing scenes needed for a mosaic.
5. Applies calibration and quality masks, aligns the grids, mosaics when needed and clips to the study polygon.
6. Writes the scientific multiband raster, optional separate bands, an optional colour composite and a decision report.

The coverage decision is recalculated when processing starts. An incomplete selection yields a map of missing areas and an actionable diagnostic. An explicitly configured catalogue can supply additional scenes. Partial output and mosaics mixing acquisition dates require explicit choices. All bands of a mosaic pixel come from the same valid acquisition.

Keep each downloaded product's original filenames, metadata and QA/SCL files together. Surface-reflectance Level-2 inputs use their supplied calibration; this workflow does not substitute an atmospheric-correction processor for Level-1 products.

### In Jupyter or a Python script

```python
import cartomize as cm

result = cm.preprocess_imagery(
    "data/scenes",
    "results/study_area_01",       # A new output directory
    aoi="data/study_area.gpkg",
    band_order=["blue", "green", "red", "nir"],
    coverage_threshold=100,
    separate_bands=True,
    composition="natural",
)
print(result.report["status"])
print(result.report["selected_scene_ids"])
print(result.manifest)
```

### In the desktop application

Open **Prétraitement multispectral**, keep **Automatique : contrôler et préparer**, select the bands or product folders, load the study polygon and choose an output directory. **Exécuter** performs the decision and processing steps. **Diagnostiquer la couverture** is an optional preview of coverage and missing areas.

From a local Python notebook with the `notebook` extra installed:

```python
import cartomize as cm
window = cm.launch()
```

The native desktop opens on the computer running Python. Remote notebooks can use the processing API directly.

## Included processing modules

| Domain | Included functionality |
|---|---|
| Imagery | Product recognition, calibration, QA/SCL masking, coverage diagnostics, scene selection, grid alignment, mosaics, clipping, multiband assembly and colour composites |
| Raster | Raster algebra, 18 spectral indices, focal and zonal statistics, reductions, reclassification, areas and change matrices |
| Vector quality — G01–G03 | Geometry diagnosis and repair, explicit precision handling, polygon/line topology and duplicate selection with retained and rejected records |
| Reprojection — G04 | Batch reprojection, geodetic-operation choices, original attributes, coordinate checks and transformation manifests |
| Harmonization — G05 | Schema matching, controlled conversions, merging, null-value handling and per-record provenance |
| Conversion — G06 | Selected vector layers to GeoPackage, GeoJSON, Shapefile or FlatGeobuf; rasters to GeoTIFF or COG, with full readback verification |
| Extraction — G07 | Attribute and spatial criteria, AND/OR, inversion, selected/rejected layers, typed identifiers and decision reports |
| Surface tables — G09 | Polygon-area cross-tabulation, complete long/wide tables, category identities, gaps and overlap balances |
| Distance rings — G12 | Explicit metre bounds, global or per-feature rings, polygon-interior choice, original identifiers and checked surface balances |
| Classification | Random forests, extra trees, K-means, validation and saved models |
| Terrain and networks | Terrain derivatives, convolution, D8 drainage, watersheds and shortest paths |
| Cartography | 24 templates, symbology, labels, legends, scale bars, multiple frames, atlases and PDF/PNG/SVG export |
| Automation and projects | Processing plans, reusable recipes, batch production, Python console, JSON sessions and portable CMZ projects |

The completed modules share their engines between Python, the CLI, processing plans and the desktop. Optional Dask and CUDA execution is available for supported operations in the corresponding environments. The expert-procedure inventory distinguishes completed procedures from future work.

## Documentation

- [Demonstration: scenes, bands and study area](https://github.com/cedrick14/cartomize-python/blob/main/docs/DEMONSTRATION_1.0.md)
- [Desktop workspace](https://github.com/cedrick14/cartomize-python/blob/main/docs/WORKBENCH.md)
- [Movable panels and result views](https://github.com/cedrick14/cartomize-python/blob/main/docs/DYNAMIC_WORKSPACE.md)
- [Automatic imagery workflow](https://github.com/cedrick14/cartomize-python/blob/main/docs/IMAGERY_AUTOMATIC.md)
- [Python API](https://github.com/cedrick14/cartomize-python/blob/main/docs/PYTHON_API.md)
- [Executable Jupyter courses](https://github.com/cedrick14/cartomize-python/tree/main/tutorials)
- [Consolidated edition](https://github.com/cedrick14/cartomize-python/blob/main/docs/RELEASE_1.0.md)
- [Issue tracker](https://github.com/cedrick14/cartomize-python/issues)

## Author and license

Developed by **ONDON NKOUA Cédrick Belmich**.

Code: **GPL-3.0-only**. Original layout templates: **CC BY 4.0**, attributed to Cartomize / ONDON NKOUA Cédrick Belmich. License and provenance notices are included in the distribution.
