"""Atmospheric-correction fallbacks with explicit scientific provenance."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from .imagery import _check_cancel, _quality_valid
from .scenes import Band, Scene


def _sample_reflectance(band, scene, *, mask_clouds=True, mask_saturation=True,
                        max_samples=1_000_000, cancel=None):
    """Deterministically sample calibrated TOA reflectance from a source band."""
    path = Path(band.path)
    with ExitStack() as stack:
        source = stack.enter_context(rasterio.open(path))
        quality = None
        saturation = None
        if mask_clouds and scene.quality is not None:
            q = stack.enter_context(rasterio.open(scene.quality))
            quality = stack.enter_context(WarpedVRT(
                q, crs=source.crs, transform=source.transform,
                width=source.width, height=source.height,
                resampling=Resampling.nearest, dtype="float64", nodata=np.nan,
            ))
        if mask_saturation and scene.saturation is not None:
            s = stack.enter_context(rasterio.open(scene.saturation))
            saturation = stack.enter_context(WarpedVRT(
                s, crs=source.crs, transform=source.transform,
                width=source.width, height=source.height,
                resampling=Resampling.nearest, dtype="float64", nodata=np.nan,
            ))
        total_pixels = max(1, source.width * source.height)
        stride = max(1, int(np.sqrt(total_pixels / max_samples)))
        samples = []
        count = 0
        for _, window in source.block_windows(band.index):
            _check_cancel(cancel)
            values = source.read(band.index, window=window, masked=True).astype("float64")
            valid = ~np.ma.getmaskarray(values)
            if band.nodata is not None:
                valid &= values.data != band.nodata
            if quality is not None:
                qa = quality.read(1, window=window, masked=True)
                valid &= _quality_valid(qa, scene.quality_kind)
            if saturation is not None:
                sat = saturation.read(1, window=window, masked=True)
                valid &= _quality_valid(sat, "saturation")
            calibrated = values.data * band.scale + band.offset
            valid &= np.isfinite(calibrated)
            block = calibrated[valid]
            if block.size:
                if stride > 1:
                    block = block[::stride]
                remaining = max_samples - count
                if remaining <= 0:
                    break
                block = block[:remaining]
                samples.append(block)
                count += block.size
        if not samples:
            raise ValueError(f"No valid TOA reflectance pixels available for DOS1: {path.name}")
        return np.concatenate(samples)


def dos1_scene(scene, *, dark_percentile=1.0, dark_surface_reflectance=0.01,
               mask_clouds=True, mask_saturation=True, max_samples=1_000_000,
               cancel=None):
    """Return a Scene whose offsets include a documented DOS1 approximation.

    The method operates only on already calibrated TOA reflectance. For each
    band it estimates a dark-object percentile and subtracts positive path
    reflectance above the assumed 1% dark-object surface reflectance. This is a
    simple image-based fallback, not a replacement for a provider Level-2
    atmospheric processor.
    """
    if not isinstance(scene, Scene):
        raise TypeError("scene must be a Scene.")
    if str(scene.level or "").upper() not in {"L1C-TOA", "L1-TOA", "C2-L1"}:
        raise ValueError("DOS1 fallback requires a declared TOA/Level-1 scene.")
    if not np.isfinite(dark_percentile) or not 0 <= dark_percentile <= 10:
        raise ValueError("dark_percentile must be finite and between 0 and 10.")
    if not np.isfinite(dark_surface_reflectance) or not 0 <= dark_surface_reflectance <= .1:
        raise ValueError("dark_surface_reflectance must be between 0 and 0.1.")
    if type(max_samples) is not int or max_samples < 100:
        raise ValueError("max_samples must be an integer >= 100.")

    corrected = {}
    diagnostics = []
    for name, band in scene.bands.items():
        if str(band.unit).lower() != "toa_reflectance":
            raise ValueError(
                f"DOS1 requires calibrated TOA reflectance for every band; {name} is {band.unit!r}."
            )
        sample = _sample_reflectance(
            band, scene, mask_clouds=mask_clouds, mask_saturation=mask_saturation,
            max_samples=max_samples, cancel=cancel,
        )
        dark = float(np.percentile(sample, dark_percentile))
        path_reflectance = max(0.0, dark - float(dark_surface_reflectance))
        corrected[name] = Band(
            band.path, index=band.index, scale=band.scale,
            offset=band.offset - path_reflectance, nodata=band.nodata,
            unit="reflectance",
        )
        diagnostics.append(
            f"DOS1 {name}: p{dark_percentile:g}={dark:.8g}, "
            f"path_reflectance={path_reflectance:.8g}."
        )

    return Scene(
        scene.scene_id,
        corrected,
        sensor=scene.sensor,
        acquired=scene.acquired,
        level="DOS1-SR",
        quality=scene.quality,
        quality_kind=scene.quality_kind,
        saturation=scene.saturation,
        notes=tuple(scene.notes) + (
            "Atmospheric fallback: DOS1 reflectance-domain approximation; "
            "provider Level-2 surface reflectance remains preferred.",
            *diagnostics,
        ),
    )
