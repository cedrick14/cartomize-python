"""Automatic assessment of radiometric, atmospheric and quality preprocessing."""
from __future__ import annotations

from pathlib import Path

from .scenes import Scene, discover_scenes


_SURFACE_LEVELS = {"C2-L2-SR", "L2A-SR", "DOS1-SR"}
_TOA_LEVELS = {"L1C-TOA", "L1-TOA", "C2-L1"}


def _radiometry(scene):
    bands = []
    needs_scale = False
    missing = []
    for name, band in scene.bands.items():
        declared = not (band.scale == 1.0 and band.offset == 0.0)
        reflectance = str(band.unit).lower() == "reflectance"
        needs_scale |= declared
        if not reflectance and not declared:
            missing.append(name)
        bands.append({
            "band": name,
            "unit": band.unit,
            "scale": band.scale,
            "offset": band.offset,
            "action": "apply_scale_offset" if declared else "none",
        })
    if missing:
        status = "insufficient_metadata"
        action = "provide_calibration_metadata"
    elif needs_scale:
        status = "ready"
        action = "apply_declared_scale_offset"
    else:
        status = "already_calibrated"
        action = "none"
    return {
        "level": 1,
        "name": "radiometric_calibration",
        "status": status,
        "action": action,
        "missing_bands": missing,
        "bands": bands,
    }


def _atmosphere(scene):
    level = str(scene.level or "").upper()
    if level in _SURFACE_LEVELS:
        return {
            "level": 2,
            "name": "atmospheric_correction",
            "status": "already_applied",
            "action": "none",
            "method": "dos1_reflectance_approximation" if level == "DOS1-SR" else "provider_surface_reflectance",
            "missing": [],
        }
    if level in _TOA_LEVELS:
        return {
            "level": 2,
            "name": "atmospheric_correction",
            "status": "required_but_unavailable",
            "action": "provide_surface_reflectance_or_atmospheric_parameters",
            "method": None,
            "missing": ["surface_reflectance_product_or_atmospheric_parameters"],
        }
    if all(str(b.unit).lower() == "reflectance" for b in scene.bands.values()):
        return {
            "level": 2,
            "name": "atmospheric_correction",
            "status": "undetermined",
            "action": "verify_input_reflectance_level",
            "method": None,
            "missing": ["declared_processing_level"],
        }
    return {
        "level": 2,
        "name": "atmospheric_correction",
        "status": "not_assessed",
        "action": "provide_processing_level_and_atmospheric_metadata",
        "method": None,
        "missing": ["declared_processing_level", "atmospheric_metadata"],
    }


def _quality(scene, required=True):
    if not required:
        return {
            "level": 3,
            "name": "quality_detection",
            "status": "disabled",
            "action": "none",
            "quality_mask": str(Path(scene.quality)) if scene.quality is not None else None,
            "quality_kind": scene.quality_kind,
            "saturation_mask": str(Path(scene.saturation)) if scene.saturation is not None else None,
            "missing": [],
        }
    missing = []
    if scene.quality is None:
        missing.append("quality_mask")
    if scene.quality is not None and scene.quality_kind is None:
        missing.append("quality_mask_kind")
    return {
        "level": 3,
        "name": "quality_detection",
        "status": "ready" if not missing else "missing_inputs",
        "action": "use_declared_quality_mask" if not missing else "provide_qa_scl_or_valid_mask",
        "quality_mask": str(Path(scene.quality)) if scene.quality is not None else None,
        "quality_kind": scene.quality_kind,
        "saturation_mask": str(Path(scene.saturation)) if scene.saturation is not None else None,
        "missing": missing,
    }


def _clouds(scene, mask_clouds):
    if not mask_clouds:
        return {
            "level": 4,
            "name": "cloud_masking",
            "status": "disabled",
            "action": "none",
            "missing": [],
        }
    if scene.quality is None or scene.quality_kind is None:
        return {
            "level": 4,
            "name": "cloud_masking",
            "status": "unavailable",
            "action": "add_quality_mask_then_restart_assessment",
            "missing": ["quality_mask"],
        }
    return {
        "level": 4,
        "name": "cloud_masking",
        "status": "ready",
        "action": "mask_before_resampling",
        "quality_kind": scene.quality_kind,
        "missing": [],
    }


def assess_preprocessing(scenes, *, mask_clouds=True, mask_saturation=True):
    """Build an automatic four-level preprocessing plan for every scene.

    The assessment never invents a correction. Missing inputs are reported
    explicitly so a caller can add them and rerun the assessment.
    """
    if isinstance(scenes, (str, Path)):
        scenes = discover_scenes(scenes)
    scenes = list(scenes)
    if not scenes or not all(isinstance(scene, Scene) for scene in scenes):
        raise ValueError("Provide one or more Scene objects or supported imagery inputs.")

    planned = []
    overall_ready = True
    for scene in scenes:
        levels = [
            _radiometry(scene),
            _atmosphere(scene),
            _quality(scene, required=mask_clouds),
            _clouds(scene, mask_clouds),
        ]
        blockers = []
        for item in levels:
            if item["status"] in {"insufficient_metadata", "required_but_unavailable", "missing_inputs", "unavailable", "undetermined", "not_assessed"}:
                blockers.extend(item.get("missing", []))
        # Surface-reflectance L2 products are ready when QA/SCL requirements are met.
        scene_ready = not blockers
        overall_ready &= scene_ready
        execution = {
            "level": 5,
            "name": "orchestration",
            "status": "ready" if scene_ready else "blocked",
            "action": "execute_pipeline" if scene_ready else "resolve_missing_inputs_then_restart",
            "missing": sorted(set(blockers)),
        }
        planned.append({
            "scene_id": scene.scene_id,
            "sensor": scene.sensor,
            "processing_level": scene.level,
            "acquired": scene.acquired,
            "ready": scene_ready,
            "levels": [*levels, execution],
            "missing": sorted(set(blockers)),
        })

    return {
        "schema": "cartomize.preprocessing.plan.v1",
        "automatic": True,
        "ready": overall_ready,
        "mask_clouds": bool(mask_clouds),
        "mask_saturation": bool(mask_saturation),
        "scenes": planned,
        "execution": {
            "level": 5,
            "name": "orchestration",
            "status": "ready" if overall_ready else "blocked",
            "action": "execute_pipeline" if overall_ready else "resolve_missing_inputs_then_restart",
        },
        "policy": {
            "never_assume_atmospheric_correction": True,
            "prefer_provider_surface_reflectance": True,
            "never_disable_cloud_mask_silently": True,
            "restart_after_missing_inputs_are_added": True,
            "no_scientific_output_when_blocked": True,
        },
    }
