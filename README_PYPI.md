# Cartomize

**Version 1.1**

Cartomize provides a Python API, a command-line interface and a desktop application for geospatial processing and cartographic production. It runs independently of QGIS and ArcGIS Pro. Native project bridges are optional.

## Installation

The library requires Python 3.11 or later. Python 3.11 or 3.12 is recommended for the desktop application.

For a published release:

```bash
python -m pip install "cartomize[gui]==1.1.0"
python -m cartomize gui
```

For a downloaded wheel:

```bash
python -m pip install "./cartomize-1.1.0-py3-none-any.whl[gui]"
```

From Python:

```python
import cartomize as cm
window = cm.launch()
```

Local notebooks use the `notebook` extra. Restart the kernel after installation. The desktop window opens on the machine running Python.

## Desktop workspace

The project explorer and categorized tool catalogue occupy the left side, map and result tabs the centre, and processing parameters the right side. The lower panel provides a Python console, logs, loaded data and environment diagnostics.

Light, dark and system appearance modes, text size and panel positions are saved locally. Map symbology and scientific raster values are independent of interface appearance. The Python console runs in a separate process and can be interrupted without closing the application.

Imported files are available for viewing and transfer to compatible processing tools. JSON sessions and portable CMZ projects retain tool parameters, data references and result views. Existing sessions remain compatible.

## Processing

| Domain | Operations |
|---|---|
| Satellite imagery | Band import, calibration, quality masking, mosaics, multiband assembly, clipping and RGB composition |
| Raster | Algebra, 18 spectral indices, focal and zonal statistics, reductions, reclassification and change matrices |
| Vector | Overlay, spatial joins, buffers, clipping, dissolution, reprojection, measurement and geometry repair |
| Classification | Random forests, extra trees, K-means, validation and saved models |
| Terrain and networks | Terrain derivatives, convolution, D8 drainage, watersheds and shortest paths |
| Cartography | 24 templates, symbology, labels, legends, scale bars, multiple frames, atlases and PDF/PNG/SVG export |
| Automation | Processing plans, reusable recipes, batch production and saved sessions |

Optional Dask and CUDA execution is available for supported operators. Native GIS bridges and CUDA hardware execution require the corresponding runtime.

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
