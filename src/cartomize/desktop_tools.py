"""Public desktop processing pages and shared output helpers.

The base implementations are separated from the extended vector page to keep
imports acyclic and preserve the existing desktop_tools import path.
"""
from .desktop_tools_base import (
    InspectionPage, RasterToolsPage, write_result, _json_value,
    Page, PathField, spin, real, RASTER_FILTER, VECTOR_FILTER,
)
from .desktop_vector import VectorPage

__all__ = ['InspectionPage', 'VectorPage', 'RasterToolsPage', 'write_result']
