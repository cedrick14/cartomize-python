# Cartomize

**Version 1.0**

Cartomize is a Python library for geospatial processing and cartographic production. It provides a Python API, a command-line interface and an optional desktop application for satellite image preparation, raster and vector analysis, map layouts and atlas export.

The library and desktop application run independently of QGIS and ArcGIS Pro. Optional native project bridges require the corresponding GIS installation.

## Installation

The core library requires Python 3.11 or later. The desktop application requires Python 3.11 to 3.13.

```bash
python -m pip install "cartomize==1.0.1"
```

To install and open the desktop application:

```bash
python -m pip install "cartomize[gui]==1.0.1"
python -m cartomize gui
```

From Python:

```python
import cartomize as cm

window = cm.launch()
```

In a local Jupyter notebook, install the notebook dependencies, restart the kernel and call `cm.launch()`:

```python
%pip install "cartomize[notebook]==1.0.1"
```

The desktop window opens on the computer running the kernel. Remote notebooks without a graphical desktop can use the processing API.

## Integrated workspace

The application has two resizable panels: processing controls and parameters on the left, results on the right. Raster and vector layers, PDF and SVG maps, images, tables, plots and reports open in embedded tabs.

The viewer supports zoom, pan, pixel inspection, legends, metadata and side-by-side comparison with linked geographic extents. Raster rendering reads the visible source window at the appropriate resolution. Display settings preserve source values. An optional common colour scale supports comparison of compatible measurements.

## Capabilities

- Satellite band import, calibration, quality masking, mosaicking, multiband assembly, clipping and RGB composition.
- Raster algebra, 18 spectral indices, focal and zonal statistics, multiraster reductions and change matrices.
- Vector overlay, spatial joins, buffers, clipping, dissolution, measurement and geometry repair.
- Supervised classification with random forests or extra trees, and unsupervised K-means classification.
- Terrain derivatives, convolution, D8 drainage, watersheds and shortest paths on prepared networks.
- Cartographic layouts, labels, legends, scale bars, 24 templates, atlas generation and PDF/PNG/SVG export.
- Processing plans, reusable recipes, batch production, saved sessions and portable projects.
- Optional Dask execution for supported raster operators and CUDA execution for algebra, indices and reductions.

## Satellite image preparation

```python
import cartomize as cm

result = cm.process_imagery(
    ["scene_A", "scene_B"],
    "outputs/preparation",
    aoi="study_area.shp",
    mosaic=True,
    multiband=True,
    separate_bands=True,
    composition=("nir", "red", "green"),
)
print(result.manifest)
```

Landsat Collection 2 Level 2 and Sentinel-2 Level 2A products are recognized from their original filenames and metadata. Other products require explicit scene and band mappings. Calibration and quality masking precede resampling. Scientific multiband values are stored separately from stretched display values.

## Cartographic output

```python
import cartomize as cm

map_output = cm.Map(title="Village locations", crs="EPSG:32733")
map_output.add_layer("villages.gpkg", name="Villages", labels="name")
map_output.export("villages.pdf", dpi=300)
```

Vector operations return standard GeoPandas objects. Raster processing uses Rasterio and NumPy. Scientific processing and rendering also use SciPy, scikit-learn and Matplotlib.

## Documentation and support

- [Source repository](https://github.com/cedrick14/cartomize-python)
- [Desktop guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/DESKTOP.md)
- [Results viewer](https://github.com/cedrick14/cartomize-python/blob/main/docs/RESULTS_WORKSPACE.md)
- [Python examples](https://github.com/cedrick14/cartomize-python/blob/main/docs/PYTHON_API.md)
- [Processing methods and scope](https://github.com/cedrick14/cartomize-python/blob/main/docs/TOOL_AUDIT.md)
- [Validation](https://github.com/cedrick14/cartomize-python/blob/main/docs/VALIDATION.md)
- [Issue tracker](https://github.com/cedrick14/cartomize-python/issues)

Automated checks cover Linux, Windows and Windows Conda, including a Jupyter kernel. CUDA hardware execution and ArcGIS Pro integration require validation on compatible installations. Synthetic tests do not replace thematic validation or performance measurements on representative datasets.

## Author and license

Developed by **ONDON NKOUA Cédrick Belmich**.

Source code: **GPL-3.0-only**. Original layout templates: **CC BY 4.0**, attributed to Cartomize / ONDON NKOUA Cédrick Belmich. License and provenance notices are included in the distribution.
