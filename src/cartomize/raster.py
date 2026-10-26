"""Rasterio processing with source masks, explicit grids and windowed writes."""
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
import math
import os
import tempfile

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask as raster_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform
from rasterio.features import geometry_mask
from rasterio.transform import Affine
from rasterio.windows import Window
from shapely import box as pixel_boxes, intersects, intersects_xy, prepare
from shapely.affinity import affine_transform

from ._core.raster_sampling import profile_array
from ._core.raster_intelligence_core import RasterEvidence, infer_raster
from ._validation import frame, linear_factor, output_path


def _band(src, band):
    if not isinstance(band, int) or not 1 <= band <= src.count:
        raise ValueError(f"band must be an integer in 1..{src.count}.")


def _read(src, band, **kwargs):
    return np.ma.masked_invalid(src.read(band, masked=True, **kwargs))


def _profile(src, **changes):
    profile = dict(driver="GTiff", width=src.width, height=src.height,
                   crs=src.crs, transform=src.transform, count=1,
                   dtype="float32", nodata=np.nan, compress="lzw")
    profile.update(changes)
    return profile


@contextmanager
def _writer(path, profile, *, overwrite=False, sources=()):
    """Write to a temporary GeoTIFF and replace the destination after success."""
    path = output_path(path, overwrite, sources)
    fd, temporary = tempfile.mkstemp(prefix=".cartomize-", suffix=".tif", dir=path.parent)
    os.close(fd)
    try:
        with rasterio.open(temporary, "w", **profile) as dst:
            yield dst
        os.replace(temporary, path)
        # Old GDAL sidecars must not override a replacement raster's new mask
        # or georeferencing. They are invalidated only after a successful write.
        for suffix in ('.msk','.aux.xml','.ovr'):
            Path(str(path)+suffix).unlink(missing_ok=True)
    finally:
        for suffix in ("", ".msk", ".aux.xml"):
            Path(temporary + suffix).unlink(missing_ok=True)


def inspect(path, *, band=1, max_pixels=250_000):
    """Sample a raster and run the preserved Cartomize inference engine.

    Frequencies describe the sample. Suggested NoData values are diagnostic
    only: they are never applied to the raster or to computed statistics.
    """
    if not isinstance(max_pixels, int) or max_pixels < 1:
        raise ValueError("max_pixels must be a positive integer.")
    with rasterio.open(path) as src:
        _band(src, band)
        ratio = min(1, math.sqrt(max_pixels / (src.width * src.height)))
        height, width = max(1, int(src.height * ratio)), max(1, int(src.width * ratio))
        sample = _read(src, band, out_shape=(height, width), resampling=Resampling.nearest)
        summary = profile_array(sample.data, mask=~np.ma.getmaskarray(sample))
        values = sample.compressed()
        colors = {}
        try:
            colors = src.colormap(band)
        except ValueError:
            pass
        evidence = RasterEvidence(
            band_count=src.count, data_type=src.dtypes[band-1],
            total_pixels=sample.size, valid_pixels=summary.valid_pixels,
            unique_count=summary.observed_unique_count, values=summary.profiles,
            minimum=float(values.min()) if values.size else None,
            maximum=float(values.max()) if values.size else None,
            source_nodata=src.nodatavals[band-1], has_mask=bool(np.ma.getmaskarray(sample).any()),
            has_color_table=bool(colors),
            band_color_interpretations=tuple(c.name for c in src.colorinterp),
            metadata_text=" ".join([Path(path).name, *map(str, src.tags().values())]),
            sample_fraction=sample.size/(src.width*src.height),
        )
        return {"path": str(path), "width": src.width, "height": src.height,
                "bands": src.count, "crs": str(src.crs), "dtype": src.dtypes[band-1],
                "nodata": src.nodatavals[band-1], "sample_fraction": evidence.sample_fraction,
                "sample": asdict(summary), "inference": infer_raster(evidence).to_dict()}


def normalized_difference(source, destination, *, positive_band, negative_band,
                          scale=None, offset=None, overwrite=False):
    """Write (positive-negative)/(positive+negative), respecting masks.

    Applies per-band GDAL scales/offsets unless common scale/offset values
    are supplied. Zero denominators become NoData; valid zero results survive.
    Input bands must belong to the same dataset/grid.
    """
    with rasterio.open(source) as src:
        _band(src, positive_band); _band(src, negative_band)
        if positive_band == negative_band:
            raise ValueError("Choose two distinct bands.")
        with _writer(destination, _profile(src), overwrite=overwrite, sources=(source,)) as dst:
            for _, window in src.block_windows(positive_band):
                a, b = (_read(src, k, window=window).astype("float64") for k in (positive_band, negative_band))
                a = a * (src.scales[positive_band-1] if scale is None else scale) + (src.offsets[positive_band-1] if offset is None else offset)
                b = b * (src.scales[negative_band-1] if scale is None else scale) + (src.offsets[negative_band-1] if offset is None else offset)
                with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                    result = np.ma.masked_invalid((a - b) / (a + b))
                    converted=result.filled(np.nan).astype('float32')
                dst.write(np.where(np.isfinite(converted),converted,np.nan), 1, window=window)
            dst.update_tags(operation="normalized_difference", positive_band=positive_band,
                            negative_band=negative_band)
    return Path(destination)


def ndvi(source, destination, *, red, nir, **kwargs):
    return normalized_difference(source, destination, positive_band=nir, negative_band=red, **kwargs)


def _copy_band_metadata(src,band,dst):
    dst.descriptions=(src.descriptions[band-1],)
    dst.scales=(src.scales[band-1],);dst.offsets=(src.offsets[band-1],)
    if src.units[band-1]:dst.set_band_unit(1,src.units[band-1])
    dst.update_tags(**src.tags());dst.update_tags(1,**src.tags(band))


def reclassify(source, destination, mapping, *, band=1, unmatched="nodata", overwrite=False):
    """Recode exact categorical values; preserve source masks and valid zeros.

    Unmapped valid pixels become NoData, or remain unchanged with unmatched='keep'.
    Float64 output preserves exact integer codes up to 2**53.
    """
    if unmatched not in {"nodata", "keep"}:
        raise ValueError("unmatched must be 'nodata' or 'keep'.")
    mapping = {float(k): float(v) for k, v in mapping.items()}
    if not mapping or not all(np.isfinite([k, v]).all() for k, v in mapping.items()):
        raise ValueError("mapping must contain finite input and output values.")
    with rasterio.open(source) as src:
        _band(src, band)
        with _writer(destination, _profile(src, dtype="float64"), overwrite=overwrite, sources=(source,)) as dst:
            for _, window in src.block_windows(band):
                original = _read(src, band, window=window).astype("float64")
                result = original.filled(np.nan) if unmatched == "keep" else np.full(original.shape, np.nan)
                for old, new in mapping.items():
                    result[(original.data == old) & ~np.ma.getmaskarray(original)] = new
                dst.write(result, 1, window=window)
    return Path(destination)


def clip(source, mask, destination, *, band=1, all_touched=False, overwrite=False):
    """Crop one band to a vector mask; output is a float64 GeoTIFF."""
    vectors = frame(mask)
    with rasterio.open(source) as src:
        _band(src, band)
        if src.crs is None:
            raise ValueError("Raster has no CRS.")
        vectors = vectors.to_crs(src.crs)
        geometries = [g for g in vectors.geometry if g is not None and not g.is_empty]
        if not geometries:
            raise ValueError("The clipping mask contains no geometry.")
        data, transform = raster_mask(src, geometries, indexes=band, crop=True,
                                      filled=False, all_touched=all_touched)
        data = np.ma.masked_invalid(data.astype("float64"))
        profile = _profile(src, dtype="float64", transform=transform, height=data.shape[0], width=data.shape[1])
        sources=(source,mask) if isinstance(mask,(str,Path)) else (source,)
        with _writer(destination, profile, overwrite=overwrite, sources=sources) as dst:
            dst.write(data.filled(np.nan), 1)
            _copy_band_metadata(src,band,dst)
    return Path(destination)


def reproject(source, destination, crs, *, band=1, resolution=None, resampling="nearest", overwrite=False):
    """Reproject a band; nearest-neighbour is the default for categorical safety."""
    if resampling not in {"nearest", "bilinear", "cubic", "average", "mode"}:
        raise ValueError("Unsupported resampling method.")
    with rasterio.open(source) as src:
        _band(src, band)
        if src.crs is None:
            raise ValueError("Raster has no CRS.")
        transform, width, height = calculate_default_transform(
            src.crs, crs, src.width, src.height, *src.bounds, resolution=resolution)
        with WarpedVRT(src, crs=crs, transform=transform, width=width, height=height,
                       dtype="float64", nodata=np.nan, resampling=Resampling[resampling]) as vrt:
            with _writer(destination, _profile(vrt, dtype="float64"), overwrite=overwrite, sources=(source,)) as dst:
                for _, window in dst.block_windows(1):
                    dst.write(_read(vrt, band, window=window).filled(np.nan), 1, window=window)
                _copy_band_metadata(src,band,dst)
    return Path(destination)


def _zonal_window(src, pixel_geometry, include_coverage):
    """Bound a geometry already transformed to the global source pixel grid."""
    left, top, right, bottom = pixel_geometry.bounds
    if not np.isfinite([left, top, right, bottom]).all():
        raise ValueError("Zone coordinates must be finite in the raster CRS.")
    col_start, row_start = math.floor(left), math.floor(top)
    col_stop, row_stop = math.ceil(right), math.ceil(bottom)
    if not include_coverage:
        col_start, row_start = max(0, col_start), max(0, row_start)
        col_stop, row_stop = min(src.width, col_stop), min(src.height, row_stop)
    if col_start >= col_stop or row_start >= row_stop:
        return None
    return Window(col_start, row_start, col_stop-col_start, row_stop-row_start)


def _zonal_blocks(window, size):
    col_stop, row_stop = int(window.col_off+window.width), int(window.row_off+window.height)
    for row in range(int(window.row_off), row_stop, size):
        for col in range(int(window.col_off), col_stop, size):
            yield Window(col, row, min(size, col_stop-col), min(size, row_stop-row))


def _zonal_mask(geometry, boundary_band, block, all_touched, cancel):
    """Rasterize interiors quickly; resolve boundary cells by exact predicates.

    GDAL's clipped all_touched rasterization can depend on the block size, even
    with a halo. The one-pixel boundary buffer safely exceeds a cell's half
    diagonal (sqrt(.5)), so every cell needing refinement is included. Its
    low-resolution round arcs remain wider than that diagonal. Only boundary
    cells create temporary Shapely boxes, in bounded batches.
    """
    from .imagery import _check_cancel

    shape = (int(block.height), int(block.width))
    transform = Affine.translation(block.col_off, block.row_off)
    inside = geometry_mask([geometry], out_shape=shape, transform=transform, invert=True)
    boundary = geometry_mask([boundary_band], out_shape=shape, transform=transform, invert=True)
    rows, cols = np.nonzero(boundary)
    for start in range(0, len(rows), 65_536):
        _check_cancel(cancel)
        r, c = rows[start:start+65_536], cols[start:start+65_536]
        x, y = c+block.col_off, r+block.row_off
        if all_touched:
            selected = intersects(geometry, pixel_boxes(x, y, x+1, y+1))
        else:
            # Includes a center exactly on a boundary, an otherwise unspecified
            # GDAL edge case. The predicate is independent of the tile origin.
            selected = intersects_xy(geometry, x+.5, y+.5)
        inside[r, c] = selected
    return inside


def zonal_stats(source, zones, *, band=1, all_touched=False, value_mode="physical",
                prefix="", include_coverage=False, block_size=512,
                max_zone_pixels=250_000_000, progress=None, cancel=None):
    """Blockwise statistics per feature, preserving its index, attributes and CRS.

    Adds count, min, max, mean, sum and std (population standard deviation).
    Physical values apply the band's GDAL scale and offset after source masks;
    value_mode='raw' explicitly retains stored values. Empty/nonoverlapping
    zones have count=0 and NaN statistics. Overlapping zones are independent.
    Nonempty zones must be Polygon/MultiPolygon; points and lines are rejected.

    include_coverage adds zone_pixels, raster_pixels and coverage_percent.
    The denominator counts selected pixels on the source grid extended beyond
    the image; raster_pixels counts selected pixels inside the image, and count
    counts their valid observations. Coverage is 100*count/zone_pixels, or NaN
    when no pixel is selected. Pixels are not weighted by intersected area.
    By default a center on the zone boundary is included. all_touched includes
    each closed cell intersecting the zone within its floor/ceil candidate
    window. These explicit edge rules are independent of block_size; boundary
    results need not be bitwise identical to GDAL's rasterization convention.

    Every generated column receives prefix; existing columns are never replaced.
    max_zone_pixels bounds each candidate window before reads or rasterization:
    the full zone for coverage, otherwise its intersection with the raster.
    Calibration and selection provenance is returned in attrs['cartomize'].
    """
    from .imagery import _check_cancel

    if value_mode not in ("physical", "raw"):
        raise ValueError("value_mode must be 'physical' or 'raw'.")
    if not isinstance(prefix, str) or "\x00" in prefix:
        raise ValueError("prefix must be a string without null characters.")
    for name, value in (("all_touched", all_touched), ("include_coverage", include_coverage)):
        if not isinstance(value, (bool, np.bool_)):
            raise ValueError(f"{name} must be a boolean.")
    for name, value in (("block_size", block_size), ("max_zone_pixels", max_zone_pixels)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
            raise ValueError(f"{name} must be a positive integer.")
    if block_size > 2048:
        raise ValueError("block_size must be in 1..2048.")
    if progress is not None and not callable(progress):
        raise ValueError("progress must be a callable or None.")
    if cancel is not None and not callable(getattr(cancel, "is_set", None)):
        raise ValueError("cancel must provide an is_set() method.")
    _check_cancel(cancel)
    result = frame(zones)
    fields = ["count", "min", "max", "mean", "sum", "std"]
    if include_coverage:
        fields += ["zone_pixels", "raster_pixels", "coverage_percent"]
    columns = {name: prefix+name for name in fields}
    collisions = set(columns.values()) & set(result.columns)
    if collisions:
        raise ValueError("Output columns already exist; choose a different prefix: "+", ".join(sorted(collisions)))
    for position, geometry in enumerate(result.geometry):
        if geometry is not None and not geometry.is_empty:
            if geometry.geom_type not in ("Polygon", "MultiPolygon"):
                raise ValueError(f"Zone at position {position} must be a Polygon or MultiPolygon.")
            if not geometry.is_valid:
                raise ValueError(f"Zone at position {position} has an invalid geometry.")
    records = []
    with rasterio.open(source) as src:
        if isinstance(band, (bool, np.bool_)):
            raise ValueError("band must be an integer band number.")
        _band(src, band)
        if np.dtype(src.dtypes[band-1]).kind == "c":
            raise ValueError("Zonal statistics require a real-valued raster band, not complex values.")
        if src.crs is None:
            raise ValueError("Raster has no CRS.")
        determinant = src.transform.a*src.transform.e-src.transform.b*src.transform.d
        if not np.isfinite(tuple(src.transform)).all() or not np.isfinite(determinant) or determinant == 0:
            raise ValueError("Raster must have a finite, invertible affine grid.")
        scale = float(src.scales[band-1]) if value_mode == "physical" else 1.0
        offset = float(src.offsets[band-1]) if value_mode == "physical" else 0.0
        if not np.isfinite([scale, offset]).all():
            raise ValueError("Raster scale and offset must be finite for physical statistics.")
        geometries = result.to_crs(src.crs).geometry
        windows = []
        pixel_geometries = []
        inverse = ~src.transform
        pixel_transform = [inverse.a, inverse.b, inverse.d, inverse.e, inverse.c, inverse.f]
        # Check every candidate budget before allocating masks or reading pixels.
        for position, geometry in enumerate(geometries):
            _check_cancel(cancel)
            window = None
            pixel_geometry = None
            if geometry is not None and not geometry.is_empty:
                if not geometry.is_valid:
                    raise ValueError(f"Zone at position {position} is invalid in the raster CRS.")
                pixel_geometry = affine_transform(geometry, pixel_transform)
                if not pixel_geometry.is_valid:
                    raise ValueError(f"Zone at position {position} is invalid on the raster pixel grid.")
                window = _zonal_window(src, pixel_geometry, include_coverage)
                if window is not None and window.width*window.height > max_zone_pixels:
                    raise ValueError(f"Zone at position {position} exceeds max_zone_pixels ({max_zone_pixels}) in its candidate window.")
            windows.append(window)
            pixel_geometries.append(pixel_geometry)
        for position, (geometry, window) in enumerate(zip(pixel_geometries, windows)):
            _check_cancel(cancel)
            count = zone_pixels = raster_pixels = 0
            minimum, maximum = np.inf, -np.inf
            mean = moment = total = compensation = 0.0
            if window is not None:
                boundary_band = geometry.boundary.buffer(1, quad_segs=2)
                prepare(geometry)
                for block in _zonal_blocks(window, int(block_size)):
                    _check_cancel(cancel)
                    inside = _zonal_mask(geometry, boundary_band, block, bool(all_touched), cancel)
                    if include_coverage:
                        zone_pixels += int(inside.sum())
                    col_start, row_start = max(0, int(block.col_off)), max(0, int(block.row_off))
                    col_stop = min(src.width, int(block.col_off+block.width))
                    row_stop = min(src.height, int(block.row_off+block.height))
                    if col_start >= col_stop or row_start >= row_stop:
                        continue
                    selected = inside[row_start-int(block.row_off):row_stop-int(block.row_off),
                                      col_start-int(block.col_off):col_stop-int(block.col_off)]
                    if include_coverage:
                        raster_pixels += int(selected.sum())
                    if not selected.any():
                        continue
                    data = _read(src, band, window=Window(col_start, row_start, col_stop-col_start, row_stop-row_start))
                    values = data.data[selected & ~np.ma.getmaskarray(data)].astype("float64")
                    if not len(values):
                        continue
                    with np.errstate(over="ignore", invalid="ignore"):
                        values = values*scale+offset
                        if not np.isfinite(values).all():
                            raise ValueError("Calibrated values exceed the finite float64 range.")
                        block_count = len(values)
                        block_mean = float(np.mean(values))
                        block_moment = float(np.sum((values-block_mean)**2))
                        if count:
                            combined = count+block_count
                            delta = block_mean-mean
                            moment += block_moment+delta*delta*(count*block_count/combined)
                            mean += delta*(block_count/combined)
                        else:
                            mean, moment = block_mean, block_moment
                        count += block_count
                        # Compensate addition of block sums; variance uses centered
                        # moments, never the unstable E[x*x] - E[x]*E[x] formula.
                        increment = float(np.sum(values))-compensation
                        next_total = total+increment
                        compensation = (next_total-total)-increment
                        total = next_total
                    if not np.isfinite([mean, moment, total]).all():
                        raise ValueError("Zonal statistics exceed the finite float64 range.")
                    minimum = min(minimum, float(values.min()))
                    maximum = max(maximum, float(values.max()))
            statistics = [minimum, maximum, mean, total, math.sqrt(max(0.0, moment)/count)] if count else [np.nan]*5
            record = [count, *statistics]
            if include_coverage:
                record += [zone_pixels, raster_pixels, 100.0*count/zone_pixels if zone_pixels else np.nan]
            records.append(record)
            if progress:
                progress(position+1, len(geometries))
        _check_cancel(cancel)
        metadata = dict(schema="cartomize.zonal_stats.v1", source=str(Path(source).expanduser().resolve()),
                        band=band, value_mode=value_mode, applied_scale=scale, applied_offset=offset,
                        unit=src.units[band-1] if value_mode == "physical" else None,
                        raster_crs=str(src.crs), all_touched=bool(all_touched), prefix=prefix,
                        include_coverage=bool(include_coverage), columns=columns,
                        block_size=int(block_size), max_zone_pixels=int(max_zone_pixels),
                        mask_rule="GDAL source mask (explicit mask takes precedence over nodata); nonfinite excluded",
                        std_ddof=0, coverage_rule=dict(
                            selection="closed_cell_intersection" if all_touched else "pixel_center_covered",
                            boundary="included, within the floor/ceil geometry candidate window; deterministic across blocks",
                            gdal_boundary_parity=False,
                            denominator="zone_pixels on the extended source grid, including outside the raster",
                            numerator="count of finite, unmasked source observations",
                            formula="100 * count / zone_pixels; undefined when zone_pixels is zero",
                            fractional_area_weighting=False))
    # Assign positionally: duplicate input indices must remain distinct features.
    for i, name in enumerate(columns.values()):
        result[name] = [r[i] for r in records]
    result.attrs["cartomize"] = metadata
    return result


def class_areas(source, *, band=1, unit="ha"):
    """Exact pixel counts and planar areas by class, excluding declared NoData."""
    divisor = {"m2": 1, "ha": 1e4, "km2": 1e6}.get(unit)
    if divisor is None:
        raise ValueError("unit must be 'm2', 'ha' or 'km2'.")
    counts = Counter()
    with rasterio.open(source) as src:
        _band(src, band)
        factor = linear_factor(src.crs)
        pixel_area = abs(src.transform.a * src.transform.e - src.transform.b * src.transform.d) * factor**2
        for _, window in src.block_windows(band):
            values, frequencies = np.unique(_read(src, band, window=window).compressed(), return_counts=True)
            counts.update({float(v): int(n) for v, n in zip(values, frequencies)})
    return pd.DataFrame([(v, n, n*pixel_area/divisor) for v, n in sorted(counts.items())],
                        columns=["class", "pixels", f"area_{unit}"])


def change_matrix(before, after, *, band=1):
    """Exact from/to pixel counts on identical grids, excluding either mask."""
    counts = Counter()
    with rasterio.open(before) as a, rasterio.open(after) as b:
        _band(a, band); _band(b, band)
        if a.crs is None or b.crs is None:
            raise ValueError("Both rasters need a CRS.")
        if a.crs != b.crs or a.transform != b.transform or a.shape != b.shape:
            raise ValueError("Raster grids differ; align CRS, transform and dimensions first.")
        for _, window in a.block_windows(band):
            x, y = _read(a, band, window=window), _read(b, band, window=window)
            valid = ~np.ma.getmaskarray(x) & ~np.ma.getmaskarray(y)
            pairs, frequencies = np.unique(np.column_stack((x.data[valid], y.data[valid])), axis=0, return_counts=True)
            counts.update({(float(v[0]), float(v[1])): int(n) for v, n in zip(pairs, frequencies)})
    return pd.DataFrame([(a, b, n) for (a, b), n in sorted(counts.items())], columns=["from", "to", "pixels"])
