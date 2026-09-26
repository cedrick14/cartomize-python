"""Validate an installed distribution in a fresh interpreter, outside pytest."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap


CORE = '''
import cartomize as cm
from xml.parsers import expat
from xml.etree import ElementTree as ET
from pathlib import Path
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from shapely.geometry import Point

assert ET.fromstring('<map><layer /></map>').find('layer') is not None
source = Path('source.tif')
pixels = np.arange(16, dtype='uint8').reshape(4, 4)
with rasterio.open(source, 'w', driver='GTiff', width=4, height=4,
                   count=1, dtype='uint8', crs='EPSG:32733',
                   transform=from_origin(300000, 9500000, 10, 10)) as dst:
    dst.write(pixels, 1)
with rasterio.open(source) as src, WarpedVRT(src, crs='EPSG:32733') as vrt:
    np.testing.assert_array_equal(vrt.read(1), pixels)
points = gpd.GeoDataFrame({'name': ['Locality']},
                          geometry=[Point(300020, 9499980)], crs=32733)
points.to_file('points.gpkg', driver='GPKG')
assert len(cm.read_file('points.gpkg')) == 1
cm.Map(title='Startup validation').add_layer(source).add_layer(points).export('map.png', dpi=50)
assert Path('map.png').stat().st_size > 1000
assert 'arcpy' not in __import__('sys').modules and 'qgis' not in __import__('sys').modules
print('CARTOMIZE_STARTUP_OK', cm.__version__, 'Expat', expat.EXPAT_VERSION, flush=True)
'''

GUI = '''
window = cm.launch(block=False)
window._application.processEvents()
assert window.isVisible() and not window.windowIcon().isNull()
assert len(window.tool_pages) == 20
window.close()
window._application.processEvents()
print('CARTOMIZE_GUI_OK', flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui', action='store_true')
    args = parser.parse_args()
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    with tempfile.TemporaryDirectory(prefix='cartomize-startup-') as directory:
        # No pytest plugins, repository path, or preloaded XML/GDAL modules.
        result = subprocess.run([sys.executable, '-I', '-c', textwrap.dedent(CORE + (GUI if args.gui else ''))],
                                cwd=directory, env=environment, timeout=120)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
