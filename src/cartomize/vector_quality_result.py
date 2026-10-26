"""In-memory results shared by the vector quality procedures."""
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd


@dataclass
class VectorQualityResult:
    """A scientific result with a row-level audit and optional related layers.

    ``data`` is the principal layer. ``report`` is a non-spatial decision table,
    and ``summary`` records the parameters, counts and measurement conventions.
    Original attributes remain on data/rejected; diagnostic fields live in the
    separate report and issues layers so no input column is overwritten.
    """

    data: gpd.GeoDataFrame
    report: pd.DataFrame
    summary: dict
    issues: gpd.GeoDataFrame | None = None
    rejected: gpd.GeoDataFrame | None = None
