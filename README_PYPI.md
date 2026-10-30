# Cartomize

Cartomize is a Python library and desktop application for geospatial analysis and map production. It combines raster and vector processing, satellite image preparation and cartographic layouts in an API that can be used from Python scripts, Jupyter notebooks or the desktop interface.

## Capabilities

Raster tools cover spectral indices, raster calculations, classification, terrain analysis and zonal statistics. Satellite image preparation supports coverage assessment, grid alignment, mosaics, clipping and colour composites. Vector tools provide reprojection, geometry validation, spatial selection, overlays, joins, buffers and area summaries.

Cartographic layouts combine raster and vector layers with symbology, labels, legends, scale bars and map frames. Maps can be exported to PDF, PNG and SVG, including atlas and batch outputs. Processing plans and saved projects support repeated analyses.

The desktop application provides a map workspace with movable panels, detachable result views and saved layouts. Its tools use the same processing functions as the Python API. Common data formats include GeoTIFF, GeoPackage, GeoJSON and Shapefile. Cartomize builds on NumPy, GeoPandas, Rasterio, pyproj and Matplotlib.

## Installation

Cartomize requires Python 3.11 or later. Python 3.11 or 3.12 is recommended for the desktop application.

Install the Python library:

```bash
python -m pip install cartomize
```

Install and open the desktop application:

```bash
python -m pip install "cartomize[gui]"
python -m cartomize gui
```

The `notebook` extra includes JupyterLab, a Python kernel and the desktop components:

```bash
python -m pip install "cartomize[notebook]"
python -m jupyter lab
```

Optional execution backends are documented in the [execution guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/EXECUTION.md).

## Example

Create a map from a vector layer and export it as a PDF:

```python
import cartomize as cm

layout = cm.Map(title="Study area", crs="EPSG:32733")
layout.add_layer("study_area.gpkg", name="Boundary")
layout.export("study_area.pdf")
```

## Documentation and support

See the [Python API](https://github.com/cedrick14/cartomize-python/blob/main/docs/PYTHON_API.md), [desktop guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/WORKBENCH.md) and [satellite image preparation guide](https://github.com/cedrick14/cartomize-python/blob/main/docs/IMAGERY_AUTOMATIC.md) for usage and parameters. Source code and bug reports are available in the [GitHub repository](https://github.com/cedrick14/cartomize-python).

## License

Developed by **ONDON NKOUA Cédrick Belmich**.

Code is licensed under **GPL-3.0-only**. Original cartographic templates are licensed under **CC BY 4.0**, attributed to Cartomize / ONDON NKOUA Cédrick Belmich. See [LICENSE](https://github.com/cedrick14/cartomize-python/blob/main/LICENSE) and [NOTICE.md](https://github.com/cedrick14/cartomize-python/blob/main/NOTICE.md).
