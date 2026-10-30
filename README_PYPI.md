# Cartomize

**Version 1.10.0**

Cartomize provides a Python API, a command-line interface and a desktop application for geospatial processing and cartographic production. It runs independently of QGIS and ArcGIS Pro. Native project bridges are optional.

## Installation

The library requires Python 3.11 or later. Python 3.11 or 3.12 is recommended for the desktop application.

For the latest release available on PyPI:

```bash
python -m pip install "cartomize[gui]"
python -m cartomize gui
```

For a downloaded wheel:

```bash
python -m pip install "./cartomize-1.10.0-py3-none-any.whl[gui]"
```

For the current GitHub sources:

```bash
git clone https://github.com/cedrick14/cartomize-python.git
cd cartomize-python
python -m pip install -e ".[gui]"
python -m cartomize gui
```

A version in the repository is not necessarily published on PyPI yet. The API alone can be installed with `python -m pip install -e .`, without Qt. To install Jupyter and the executable course from these same sources, run `python -m pip install -r tutorials/requirements.txt` from the repository root.

From Python, after installing the GUI extra:

```python
import cartomize as cm
window = cm.launch()
```

Notebook cells can call processing functions directly without Qt. To open the desktop window from a local notebook, install the `notebook` extra and restart the kernel. The window opens on the machine running Python.

## Desktop workspace

The project explorer and categorized tool catalogue occupy the left side, map and result tabs the centre, and processing parameters the right side. The lower panel provides a Python console, logs, loaded data and environment diagnostics.

Light, dark and system appearance modes, text size and panel positions are saved locally. Map symbology and scientific raster values are independent of interface appearance. The Python console runs in a separate process and can be interrupted without closing the application.

Imported files are available for viewing and transfer to compatible processing tools. JSON sessions and portable CMZ projects retain tool parameters, data references and result views. Existing sessions remain compatible.

## Processing

| Domain | Operations |
|---|---|
| Satellite imagery | Exact grid coverage diagnostics, scene recommendations, band import, calibration, quality masking, mosaics, multiband assembly, clipping and RGB composition |
| Raster | Algebra, 18 spectral indices, focal and zonal statistics, reductions, reclassification and change matrices |
| Vector | Schema harmonization and merging with provenance, geometry audits and repairs, polygon/line topology, duplicate selection, overlay, spatial joins, buffers, clipping, dissolution, reprojection and measurement |
| Classification | Random forests, extra trees, K-means, validation and saved models |
| Terrain and networks | Terrain derivatives, convolution, D8 drainage, watersheds and shortest paths |
| Cartography | 24 templates, symbology, labels, legends, scale bars, multiple frames, atlases and PDF/PNG/SVG export |
| Automation | 53 registered operators, processing plans, reusable recipes, batch production and saved sessions |

Optional Dask and CUDA execution is available for supported operators. Native GIS bridges and CUDA hardware execution require the corresponding runtime.

Version 1.9.0 adds verified data conversion: selected vector layers to GeoPackage, GeoJSON, Shapefile and FlatGeobuf, and rasters to GeoTIFF or COG. Encoding, field names, numeric precision, compression and NoData are explicit. Complete readback verifies saved attributes, geometries, pixels, masks and georeferencing. The workflow is available through Python, the CLI, plans and the dedicated Conversion and formats desktop page. See the [G06 guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/DATA_CONVERSION.md).

Version 1.8.0 completes the G01 geometry quality workflow: select a file layer, diagnose original geometries, choose explicit repair and retention policies, and optionally apply an XY precision grid in the source projected CRS units. Reports distinguish repair from precision changes and link every original record to its retained or rejected output. A complete before layer supports direct comparison in the desktop. GeoPackages are read back and checked for exact attribute and geometry preservation before the bundle is published. The same workflow is available in Python, the CLI, processing plans and the desktop. See the [G01 guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/G01_GEOMETRY_QUALITY.md).

Version 1.6.0 added automatic vector batch reprojection: discover files, folders and multi-layer datasets; inspect and select geodetic operations; retain source attributes and geometry; and publish one GeoPackage per layer with coordinate bounds, a CSV and a transformation manifest. The default policy requires the best available operation and rejects ballpark transformations. Layer IDs expose each result to later processing-plan steps. See the [batch reprojection guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/VECTOR_REPROJECTION.md).

Version 1.5.0 added row-level geometry audits and repairs, polygon and line topology checks, and explicit duplicate selection. Each operation keeps decision tables, retained and rejected records, and source identifiers across the API, CLI, processing plans and desktop. See the [vector quality guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/VECTOR_QUALITY.md).

Version 1.4.0 added a complete automatic optical-imagery workflow: a fixed-grid coverage check controls scene selection, mosaicking and optional bounded STAC replenishment. Blocked runs preserve actionable diagnostics, and partial output requires an explicit policy. STAC scientific bands, QA/SCL, saturation and calibration metadata are connected through the same engine in Python, the CLI, plans and the desktop. See the [automatic workflow](https://github.com/cedrick14/cartomize-python/blob/main/docs/IMAGERY_AUTOMATIC.md).

Version 1.3.0 also preserves large integer vector keys and typed classification labels, applies raster scale/offset in zonal statistics by default, and attaches route endpoints to the nearest segment by default. Explicit raw-value and vertex-snapping modes remain available. See the [release and migration notes](https://github.com/cedrick14/cartomize-python/blob/main/docs/RELEASE_1.3.0.md).

## Python example

```python
import cartomize as cm

map_output = cm.Map(title="Village locations", crs="EPSG:32733")
map_output.add_layer("villages.gpkg", name="Villages", labels="name")
map_output.export("villages.pdf", dpi=300)
```

Vector operations use GeoPandas objects. Raster processing uses Rasterio and NumPy; scientific analysis and rendering also use SciPy, scikit-learn and Matplotlib.

## Documentation and support

[Desktop workspace](https://github.com/cedrick14/cartomize-python/blob/main/docs/WORKBENCH.md), [processing guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/DESKTOP.md), [Python API](https://github.com/cedrick14/cartomize-python/blob/main/docs/PYTHON_API.md), [result viewer](https://github.com/cedrick14/cartomize-python/blob/main/docs/RESULTS_WORKSPACE.md), [issue tracker](https://github.com/cedrick14/cartomize-python/issues).

Validation covers Windows and Linux, Python 3.11 and 3.12, desktop operations on geospatial files, the existing algorithm suite and a clean installation of the built wheel. Hardware-specific CUDA and native GIS checks are separate.

## Author and license

Developed by **ONDON NKOUA Cédrick Belmich**.

Code: **GPL-3.0-only**. Original layout templates: **CC BY 4.0**, attributed to Cartomize / ONDON NKOUA Cédrick Belmich. License and provenance notices are included in the distribution.

Version 1.10.0 completes auditable attribute and spatial extraction: multiple criteria, AND/OR and final inversion, unchanged selected and rejected layers, per-row reasons and a cross-tabulated summary. Native dates and exact integer identifiers remain typed. Both partitions are verified after writing and delivered atomically through Python, the CLI, plans and the vector desktop page. See the [G07 guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/VECTOR_SELECTION.md).
