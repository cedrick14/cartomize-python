"""Cartomize: cartography, spatial analysis and automated map production."""
# Initialize Python's XML runtime before loading GDAL wheels. On Windows,
# their DLL search directories can otherwise shadow Conda's Expat library.
from xml.parsers import expat as _expat
from xml.etree import ElementTree as _element_tree
_element_tree.XMLParser()
del _expat, _element_tree

from geopandas import GeoDataFrame, GeoSeries, points_from_xy
from .mapping import Map, Layer
from .vector import read_file, from_xy, reproject, clip, overlay, sjoin, nearest, dissolve, buffer, area, length, validate, make_valid
from .templates import list_templates, get_template, layout_plan
from .batch import atlas
from . import raster, vector
from .scenes import Scene, Band, discover_scenes
from .imagery import PreparedImage, prepare_imagery
from .color import color_composite, read_rgb
from .composition import compose_map
from .algebra import calculate, reduce_rasters, ProcessingCancelled
from .indices import spectral_indices, list_indices, get_index, register_index
from .focal import focal
from .workflow import CartographicProduct, cartographic_workflow
from .nodata import detect_background, mask_background
from .project import analyze_project, prepare_project, load_project, PreparedProject
from .assistant import assess_project
from .classification import SpectralModel,fit_classifier,load_classifier,classify_landcover,cluster_raster
from .session import save_session,load_session,save_map,load_map
from .relations import analyze_relations
from .automation import plan_cartography,run_plan,propose_layouts
from .mapops import snapshot_project,compare_snapshots,record_review,verify_review

__version__ = "1.11.0"
__display_version__ = ".".join(__version__.split(".")[:2])


def launch(*,block=None):
    """Open the optional desktop interface; scripts remain usable without Qt."""
    from .desktop import launch as open_desktop
    return open_desktop(block=block)


# Retain convenient access through the raster module without import cycles.
raster.calculate=calculate
raster.reduce=reduce_rasters
raster.focal=focal
raster.indices=spectral_indices
__all__ = ["Map", "Layer", "GeoDataFrame", "GeoSeries", "points_from_xy", "read_file",
           "from_xy", "reproject", "clip", "overlay", "sjoin", "dissolve", "buffer",
           "area", "length", "validate", "make_valid", "list_templates", "get_template",
           "layout_plan", "atlas", "raster", "vector", "Scene", "Band", "discover_scenes",
           "PreparedImage", "prepare_imagery", "color_composite", "read_rgb", "compose_map",
           "calculate", "reduce_rasters", "ProcessingCancelled", "spectral_indices", "list_indices",
           "get_index", "register_index", "focal", "launch", "CartographicProduct", "cartographic_workflow", "detect_background", "mask_background",
           "analyze_project", "prepare_project", "load_project", "PreparedProject", "assess_project", "nearest"]
__all__ += ['SpectralModel','fit_classifier','load_classifier','classify_landcover','cluster_raster',
            'save_session','load_session','save_map','load_map','analyze_relations','plan_cartography','run_plan',
            'propose_layouts','snapshot_project','compare_snapshots','record_review','verify_review']

from .recipes import save_recipe,load_recipe,instantiate_recipe,run_recipe,run_batch
from .native import native_project,inspect_qgis_project
from .terrain import terrain,convolve
__all__ += ["save_recipe","load_recipe","instantiate_recipe","run_recipe","run_batch",
            "native_project","inspect_qgis_project","terrain","convolve"]
raster.terrain=terrain
raster.convolve=convolve

from .processing import operation_catalog,execute_operation
from .automation import processing_plan,validate_plan
__all__ += ['operation_catalog','execute_operation','processing_plan','validate_plan']
from .native import import_native_project
__all__ += ['import_native_project']
from .hydrology import hydrology
from .routing import shortest_path
from .catalogs import search_stac,download_stac,scene_from_stac,load_scenes_manifest
__all__ += ['hydrology','shortest_path','search_stac','download_stac','scene_from_stac','load_scenes_manifest']
from .execution import execution_capabilities
from .native import validate_native_runtime
__all__ += ["execution_capabilities", "validate_native_runtime"]
from .imagery_pipeline import ImageryProducts, process_imagery, split_bands
__all__ += ["ImageryProducts", "process_imagery", "split_bands"]
from .imagery_audit import ImageryAudit, audit_imagery
__all__ += ["ImageryAudit", "audit_imagery"]
from .imagery_automatic import PreprocessedImagery, ImageryCoverageError, preprocess_imagery
__all__ += ["PreprocessedImagery", "ImageryCoverageError", "preprocess_imagery"]
from .vector_workflows import (select_attributes, select_location, geometry_operation,
                               spatial_summary, join_attributes, latest_records)
__all__ += ['select_attributes', 'select_location', 'geometry_operation',
            'spatial_summary', 'join_attributes', 'latest_records']
from .vector_selection import VectorSelectionResult, extract_features
__all__ += ['VectorSelectionResult', 'extract_features']
from .vector_tabulation import AreaTabulationResult, tabulate_area
__all__ += ['AreaTabulationResult', 'tabulate_area']
from .vector_quality_result import VectorQualityResult
from .vector_quality import audit_geometries, repair_geometries
from .vector_topology import check_topology
from .vector_duplicates import deduplicate
__all__ += ['VectorQualityResult', 'audit_geometries', 'repair_geometries',
            'check_topology', 'deduplicate']
from .vector_reprojection import (ReprojectedBatch, discover_vector_layers,
                                  inspect_reprojection, reproject_batch)
__all__ += ['ReprojectedBatch', 'discover_vector_layers', 'inspect_reprojection', 'reproject_batch']
from .vector_merge import MergedVectors, inspect_merge, merge_layers
__all__ += ['MergedVectors', 'inspect_merge', 'merge_layers']
from .vector_conversion import (ConvertedVector, VectorConversionError, vector_conversion_formats,
                                inspect_vector_conversion, convert_vector)
from .raster_conversion import ConvertedRaster, inspect_raster_conversion, convert_raster
__all__ += ['ConvertedVector', 'inspect_vector_conversion', 'convert_vector',
            'VectorConversionError', 'vector_conversion_formats',
            'ConvertedRaster', 'inspect_raster_conversion', 'convert_raster']
