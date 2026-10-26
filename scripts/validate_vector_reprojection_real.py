"""Validate M09 on pinned real datasets and published projection references.

Run from the repository root::

    python scripts/validate_vector_reprojection_real.py --data CACHE --output REPORT.json

The three historical GeoPandas teaching datasets reuse the verified M08
cache. No downloaded code is executed. Web Mercator output is checked with
NumPy equations, independently of Cartomize's PROJ call. The custom RDC
Mercator comparison shares PROJ and is identified as an integration check.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely
from shapely.geometry import Point

from validate_vector_quality_real import prepare_inputs, sha, serial


REPO = Path(__file__).resolve().parents[1]
WEBMERC_REFERENCE = "https://proj.org/en/stable/operations/projections/webmerc.html"
UTM_REFERENCE = "https://proj.org/en/stable/operations/projections/utm.html"
RADIUS_M = 6378137.0


def webmerc_coordinates(coordinates):
    """Compute EPSG:3857 XY from longitude/latitude without calling PROJ."""
    angles = np.deg2rad(np.asarray(coordinates, dtype="float64")[:, :2])
    return np.column_stack((RADIUS_M * angles[:, 0],
                            RADIUS_M * np.log(np.tan(np.pi / 4 + angles[:, 1] / 2))))


def atomic_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".m09-report-", suffix=".json", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(serial(report), handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def source_identity():
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    modules = {str(path.relative_to(REPO)): sha(path)
               for path in sorted((REPO / "src/cartomize").rglob("*.py"))}
    return head, modules


def compare_layer(original, projected, expected_xy, *, atol=2e-6):
    """Compare saved data, preserving source row order and exact attributes."""
    assert len(projected) == len(original)
    assert projected.geometry.name == original.geometry.name
    assert projected.geom_type.tolist() == original.geom_type.tolist()
    pd.testing.assert_frame_equal(
        original.drop(columns=original.geometry.name).reset_index(drop=True),
        projected.drop(columns=projected.geometry.name).reset_index(drop=True),
        check_dtype=False, check_exact=True,
    )
    observed = shapely.get_coordinates(projected.geometry.to_numpy())
    assert observed.shape == expected_xy.shape
    assert np.isfinite(observed).all()
    np.testing.assert_allclose(observed, expected_xy, rtol=0, atol=atol)
    expected_bounds = np.concatenate((expected_xy.min(axis=0), expected_xy.max(axis=0)))
    np.testing.assert_allclose(projected.total_bounds, expected_bounds, rtol=0, atol=atol)
    return {
        "features": len(projected), "coordinates_checked": len(observed),
        "maximum_absolute_coordinate_error_m": float(np.max(np.abs(observed - expected_xy))),
        "absolute_tolerance_m": atol,
        "target_bounds": projected.total_bounds.tolist(),
        "attributes_equal": True,
    }


def validate(cache, output):
    if not __debug__:
        raise RuntimeError("Run validation without Python -O; assertions must remain enabled.")
    if output.is_relative_to(cache / "data"):
        raise ValueError("Keep the validation report outside the input data subdirectory.")
    sys.path.insert(0, str(REPO / "src"))
    import cartomize as cm

    started = time.perf_counter()
    head, code_hashes = source_identity()
    provenance = prepare_inputs(cache)
    paths = {
        "paris": cache / "data/paris_districts.geojson",
        "mines": cache / "data/cod_mines_curated_all_opendata_p_ipis.geojson",
        "parks": cache / "data/cod_conservation/Conservation/RDC_aire_protegee_2013.shp",
    }
    originals = {name: gpd.read_file(path) for name, path in paths.items()}
    input_files = {str(path): sha(path) for path in (cache / "data").rglob("*") if path.is_file()}
    report = {
        "schema": "cartomize.validation_m09_real.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cartomize_version": cm.__version__,
        "repository_head_at_validation": head,
        "validation_script_sha256": sha(Path(__file__)),
        "tested_source_sha256": code_hashes,
        "code_state": "The module hashes identify the tested working sources; the repository head alone may precede the implementation.",
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "proj": pyproj.proj_version_str,
                    "packages": {name: metadata.version(name) for name in
                                 ("geopandas", "shapely", "pandas", "numpy", "pyproj", "pyogrio")}},
        "sources": [{key: value for key, value in item.items() if key != "path"}
                    for item in provenance["sources"]],
        "source_repository": "https://github.com/jorisvandenbossche/geopandas-tutorial",
        "source_commit": provenance["tutorial_commit"],
        "input_dataset_scope": "Pinned historical teaching snapshots; no current protected-area or mining inventory is claimed. Source data are not committed.",
        "method": "All WGS84 source vertices are compared against independent NumPy Web Mercator equations. Custom RDC Mercator conversion shares PROJ through a separate direct call. Published rounded examples add external numeric references. File rereads check attributes, counts, CRS and bounds.",
        "references": [WEBMERC_REFERENCE, UTM_REFERENCE,
                       "https://pyproj4.github.io/pyproj/stable/advanced_examples.html#transformation-group"],
        "checks": [], "passed": 0, "failed": 0,
    }

    def passed(name, **values):
        entry = {"name": name, "status": "passed", **serial(values)}
        report["checks"].append(entry)
        report["passed"] += 1
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    active_check = "Initial source preparation"
    try:
        active_check = "Pinned sources, feature counts and source CRS"
        assert {name: len(data) for name, data in originals.items()} == {
            "paris": 80, "mines": 3687, "parks": 50}
        assert originals["paris"].crs.to_epsg() == originals["mines"].crs.to_epsg() == 4326
        assert originals["parks"].crs.is_projected
        passed(active_check, counts={name: len(data) for name, data in originals.items()})

        with tempfile.TemporaryDirectory(prefix="m09-reprojection-", dir=cache) as temporary:
            work = Path(temporary)
            sources = list(paths.values())
            active_check = "Stable automatic layer discovery and transformation inspection"
            discovered = cm.discover_vector_layers(sources)
            reverse = cm.discover_vector_layers(list(reversed(sources)))
            assert len(discovered) == 3
            assert {item["id"] for item in discovered} == {item["id"] for item in reverse}
            inspected = cm.inspect_reprojection(sources, "EPSG:3857")
            assert len(inspected["layers"]) == 3
            assert {item["id"] for item in inspected["layers"]} == {item["id"] for item in discovered}
            passed(active_check, layers=len(discovered), stable_ids=sorted(item["id"] for item in discovered))

            active_check = "Complete mixed-source-CRS batch and saved manifest"
            result = cm.reproject_batch(sources, work / "mixed", "EPSG:3857")
            manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
            assert manifest["schema"] == "cartomize.vector_reprojection.v1"
            assert len(result.layers) == len(manifest["layers"]) == 3
            assert pyproj.CRS(manifest["target_crs"]).to_epsg() == 3857
            assert result.report.is_file()
            csv = pd.read_csv(result.report)
            assert len(csv) == 3
            by_id = {item["id"]: item for item in manifest["layers"]}
            by_path = {str(path.resolve()): name for name, path in paths.items()}
            selected = {}
            projected_by_name = {}
            for identifier, destination in result.layers.items():
                record = by_id[identifier]
                name = by_path[str(Path(record["path"]).resolve())]
                projected = gpd.read_file(destination)
                projected_by_name[name] = projected
                assert projected.crs.to_epsg() == 3857
                operation = record["operation"]
                assert operation["id"] and operation["definition"] and operation["description"]
                assert operation["ballpark"] is False
                assert "grids" in operation and "accuracy" in operation
                selected[identifier] = operation["id"]
                np.testing.assert_allclose(record["bounds"], originals[name].total_bounds, rtol=0, atol=1e-9)
                np.testing.assert_allclose(record["target_bounds"], projected.total_bounds, rtol=0, atol=2e-6)
            passed(active_check, output_layers=3, csv_rows=len(csv), operations=selected,
                   settings=manifest["settings"], environment=manifest["environment"])

            for name in ("paris", "mines"):
                active_check = f"Independent Web Mercator equations for {name}"
                original = originals[name]
                expected = webmerc_coordinates(shapely.get_coordinates(original.geometry.to_numpy()))
                metrics = compare_layer(original, projected_by_name[name], expected)
                passed(active_check, **metrics, reference=WEBMERC_REFERENCE,
                       reference_method="NumPy equations with WGS84 semi-major axis; no reference call to PROJ.")

            active_check = "Custom RDC Mercator integration and source-record preservation"
            original = originals["parks"]
            coordinates = shapely.get_coordinates(original.geometry.to_numpy())
            direct = pyproj.Transformer.from_crs(original.crs, 3857, always_xy=True)
            expected = np.column_stack(direct.transform(coordinates[:, 0], coordinates[:, 1], errcheck=True))
            metrics = compare_layer(original, projected_by_name["parks"], expected)
            passed(active_check, **metrics, reference_method="Separate direct Transformer; shared PROJ engine, integration comparison.")

            active_check = "Explicit operation selection reproduces every layer"
            replay = cm.reproject_batch(sources, work / "selected", "EPSG:3857", operations=selected)
            replay_manifest = json.loads(replay.manifest.read_text(encoding="utf-8"))
            for record in replay_manifest["layers"]:
                assert record["operation"]["id"] == selected[record["id"]]
                reference = gpd.read_file(result.layers[record["id"]])
                repeated = gpd.read_file(replay.layers[record["id"]])
                compare_layer(reference, repeated, shapely.get_coordinates(reference.geometry.to_numpy()), atol=0)
            passed(active_check, explicitly_selected_operations=len(selected), identical_coordinates=True)

            active_check = "Automatic multi-layer GeoPackage discovery from a folder"
            folder = work / "multi-input"
            folder.mkdir()
            package = folder / "observations.gpkg"
            originals["paris"].to_file(package, layer="quartiers", driver="GPKG", index=False)
            originals["mines"].to_file(package, layer="visites", driver="GPKG", index=False)
            layers = cm.discover_vector_layers(folder)
            assert {entry["layer"] for entry in layers} == {"quartiers", "visites"}
            multiple = cm.reproject_batch(folder, work / "multi-result", 3857)
            assert len(multiple.layers) == 2
            for entry in multiple.summary["layers"]:
                name = "paris" if entry["layer"] == "quartiers" else "mines"
                original = originals[name]
                expected = webmerc_coordinates(shapely.get_coordinates(original.geometry.to_numpy()))
                compare_layer(original, gpd.read_file(multiple.layers[entry["id"]]), expected)
            passed(active_check, source_files=1, source_layers=2, output_layers=2,
                   note="The temporary GeoPackage is a derived input; pinned source bytes remain unchanged.")

            active_check = "Published forward-projection numeric references"
            references = [
                ("webmerc", 3857, (2., 49.), (222638.98, 6274861.39), WEBMERC_REFERENCE),
                ("utm32n", 32632, (12., 56.), (687071.44, 6210141.33), UTM_REFERENCE),
                ("utm59s", 32759, (174., -44.), (740526.32, 5123750.87), UTM_REFERENCE),
            ]
            results = []
            for name, crs, xy, expected, reference in references:
                data = gpd.GeoDataFrame({"reference": [name]}, geometry=[Point(*xy)], crs=4326)
                batch = cm.reproject_batch(data, work / name, crs)
                observed = gpd.read_file(next(iter(batch.layers.values()))).geometry.iloc[0]
                np.testing.assert_allclose([observed.x, observed.y], expected, rtol=0, atol=.01)
                results.append({"name": name, "source_lon_lat": xy, "target_epsg": crs,
                                "published_xy_m": expected, "observed_xy_m": [observed.x, observed.y],
                                "absolute_tolerance_m": .01, "reference": reference})
            passed(active_check, references=results,
                   note="Published values are rounded to centimetres. The PROJ UTM examples default to GRS80; WGS84 EPSG outputs agree at this documented precision.")

            active_check = "Horizontal reprojection preserves Z and exact integer attributes"
            data = gpd.GeoDataFrame({"identifier": pd.Series([2**53 + 1], dtype="int64")},
                                    geometry=[Point(15., -4., 123.456)], crs=4326)
            batch = cm.reproject_batch(data, work / "height", 3857)
            saved = gpd.read_file(next(iter(batch.layers.values())))
            assert int(saved.identifier.iloc[0]) == 2**53 + 1
            assert saved.geometry.iloc[0].z == 123.456
            passed(active_check, z_before=123.456, z_after=saved.geometry.iloc[0].z,
                   integer_preserved=int(saved.identifier.iloc[0]),
                   interpretation="Z is preserved numerically; no vertical-datum transformation is claimed.")

            active_check = "Missing source CRS refuses the complete batch without publication"
            missing = originals["paris"].copy().set_crs(None, allow_override=True)
            refused = work / "missing-crs"
            try:
                cm.reproject_batch([paths["mines"], missing], refused, 3857)
            except (ValueError, TypeError) as error:
                assert not refused.exists()
                message = str(error)
            else:
                raise AssertionError("A missing source CRS must be refused explicitly.")
            passed(active_check, destination_published=False, message=message)

        active_check = "Source files and tested modules unchanged throughout validation"
        assert all(sha(Path(path)) == digest for path, digest in input_files.items())
        assert all(sha(REPO / path) == digest for path, digest in code_hashes.items())
        passed(active_check, source_files=len(input_files), tested_modules=len(code_hashes))
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["failed"] += 1
        report["checks"].append({"name": active_check, "status": "failed",
                                  "error": f"{type(error).__name__}: {error}"})
        raise
    finally:
        report["duration_seconds"] = round(time.perf_counter() - started, 3)
        atomic_report(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.data.expanduser().resolve(), args.output.expanduser().resolve())
    print(json.dumps({key: result[key] for key in ("status", "passed", "failed", "duration_seconds")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
