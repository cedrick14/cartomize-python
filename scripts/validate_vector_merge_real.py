"""Validate M10 schema harmonization against pinned real records.

The input geometries and values come from two historical GeoPandas teaching
datasets. Temporary schema variants explicitly exercise renaming, textual
numbers and missing fields; they are not presented as original source schemas.
The reference uses the standard-library JSON reader and Python records, not
Cartomize or pandas concatenation. SQLite reads attributes and OGC GeoPackage
binary geometry directly from the saved output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time

from validate_vector_quality_real import SOURCES, TUTORIAL_REF, download_source, sha, serial


REPO = Path(__file__).resolve().parents[1]
REFERENCES = [
    "https://doc.esri.com/en/arcgis-pro/latest/tool-reference/data-management/merge.html",
    "https://www.sqlite.org/datatype3.html",
    "https://docs.python.org/3/library/sqlite3.html",
    "https://www.geopackage.org/spec140/#gpb_format",
]


def atomic_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".m10-report-", suffix=".json", dir=path.parent)
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


def write_collection(path, features):
    """Create a schema-only fixture; retain source coordinates verbatim."""
    data = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def read_geometry(blob):
    """Read the XY Point/Polygon fixtures via the OGC GeoPackage/WKB layout.

    This intentionally small reference decoder does not use GDAL, Shapely or
    Cartomize. It is scoped to the non-empty two-dimensional fixture types.
    """
    assert isinstance(blob, bytes) and blob[:2] == b"GP" and blob[2] == 0
    flags = blob[3]
    assert not flags & 0b11110000, "Expected a standard non-empty geometry."
    envelope_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    header_order = "<" if flags & 1 else ">"
    assert struct.unpack_from(header_order + "i", blob, 4)[0] == 4326
    offset = 8 + envelope_size
    order_byte = blob[offset]
    assert order_byte in (0, 1)
    order = "<" if order_byte else ">"
    geometry_type = struct.unpack_from(order + "I", blob, offset + 1)[0]
    cursor = offset + 5
    if geometry_type == 1:
        coordinates = list(struct.unpack_from(order + "dd", blob, cursor))
        cursor += 16
        geometry = {"type": "Point", "coordinates": coordinates}
    elif geometry_type == 3:
        rings = struct.unpack_from(order + "I", blob, cursor)[0]
        cursor += 4
        coordinates = []
        for _ in range(rings):
            count = struct.unpack_from(order + "I", blob, cursor)[0]
            cursor += 4
            ring = []
            for _ in range(count):
                ring.append(list(struct.unpack_from(order + "dd", blob, cursor)))
                cursor += 16
            coordinates.append(ring)
        geometry = {"type": "Polygon", "coordinates": coordinates}
    else:
        raise AssertionError(f"Unexpected fixture geometry type: {geometry_type}")
    assert cursor == len(blob), "Unexamined bytes in saved geometry."
    return geometry


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def read_saved_records(path):
    """Read a single output layer through SQLite, preserving integer/null types."""
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        geometry_columns = connection.execute(
            "SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns").fetchall()
        assert len(geometry_columns) == 1
        table, geometry_column, crs = tuple(geometry_columns[0])
        assert crs == 4326
        table_info = connection.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
        primary = next(row["name"] for row in table_info if row["pk"] == 1)
        result = []
        for row in connection.execute(
                f"SELECT * FROM {quote_identifier(table)} ORDER BY {quote_identifier(primary)}"):
            values = dict(row)
            values.pop(primary)
            geometry = read_geometry(values.pop(geometry_column))
            result.append({"properties": values, "geometry": geometry})
        declared_types = {row["name"]: row["type"] for row in table_info
                          if row["name"] not in {primary, geometry_column}}
    return result, declared_types


def mining_variants(features, directory):
    """Split alternating real visits into declared experimental schema variants."""
    paths, expected, original_positions = [], [], []
    for variant in (0, 1):
        records = []
        source_expected = []
        positions = list(range(variant, len(features), 2))
        for position in positions:
            feature = features[position]
            p = feature["properties"]
            if variant == 0:
                values = {"vid": p["vid"], "pcode": p["pcode"], "name": p["name"],
                          "workers_numb": p["workers_numb"], "province": p["province"]}
            else:
                values = {"visit_code": str(p["vid"]), "site_code": p["pcode"],
                          "site_name": p["name"],
                          "effectif": None if p["workers_numb"] is None else str(p["workers_numb"])}
            records.append({"type": "Feature", "properties": values, "geometry": feature["geometry"]})
            source_expected.append({"properties": {
                "visit_id": p["vid"], "site": p["pcode"], "nom": p["name"],
                "effectif": p["workers_numb"],
                "province": p["province"] if variant == 0 else None,
            }, "geometry": feature["geometry"]})
        path = directory / f"mines_{variant + 1}.geojson"
        write_collection(path, records)
        paths.append(path)
        expected.append(source_expected)
        original_positions.append(positions)
    return paths, expected, original_positions


def paris_variants(features, directory):
    paths, expected = [], []
    for variant, selected in enumerate((features[:40], features[40:])):
        records = []
        source_expected = []
        for feature in selected:
            p = feature["properties"]
            values = (dict(p) if variant == 0 else
                      {"code_quartier": str(p["id"]), "nom_quartier": p["district_name"],
                       "habitants": str(p["population"])})
            records.append({"type": "Feature", "properties": values, "geometry": feature["geometry"]})
            source_expected.append({"properties": {"district_id": p["id"],
                "nom": p["district_name"], "population": p["population"]},
                "geometry": feature["geometry"]})
        path = directory / f"paris_{variant + 1}.geojson"
        write_collection(path, records)
        paths.append(path)
        expected.append(source_expected)
    return paths, expected


def source_maps(cm, paths, mappings):
    inspection = cm.inspect_merge(paths)
    layers = {str(Path(layer["path"]).resolve()): layer for layer in inspection["layers"]}
    ordered = [layers[str(path.resolve())] for path in paths]
    return ordered, {layer["id"]: mapping for layer, mapping in zip(ordered, mappings)}


def assert_saved(expected_by_source, saved, layers, provenance, *, compare_geometry=True):
    """Compare literal reference records and every provenance value, in order."""
    assert set(provenance) == {"source_id", "source_name", "source_path", "source_layer", "source_row"}
    assert len(set(provenance.values())) == 5
    assert len(saved) == sum(len(rows) for rows in expected_by_source)
    cursor = 0
    for layer, expected in zip(layers, expected_by_source):
        for row_number, record in enumerate(expected):
            actual = saved[cursor]
            values = actual["properties"].copy()
            for logical, value in {
                    "source_id": layer["id"], "source_name": layer["name"],
                    "source_path": layer["path"], "source_layer": layer["layer"],
                    "source_row": row_number}.items():
                assert values.pop(provenance[logical]) == value, (cursor, logical)
            assert values == record["properties"], (cursor, values, record["properties"])
            for field, expected_value in record["properties"].items():
                if expected_value is not None:
                    assert type(values[field]) is type(expected_value), (cursor, field, type(values[field]))
            if compare_geometry:
                assert actual["geometry"] == record["geometry"], cursor
            cursor += 1


def refuse_without_publication(function, destination):
    try:
        function()
    except ValueError as exc:
        assert not destination.exists(), "A refused merge published a destination."
        return str(exc)
    raise AssertionError("The intentionally invalid operation was not refused.")


def validate(cache, output):
    if not __debug__:
        raise RuntimeError("Run validation without Python -O; assertions must remain enabled.")
    if output.is_relative_to(cache / "data"):
        raise ValueError("Keep the validation report outside the source data directory.")
    sys.path.insert(0, str(REPO / "src"))
    os.environ.setdefault("MPLCONFIGDIR", str(cache / "matplotlib-cache"))
    import cartomize as cm

    started = time.perf_counter()
    head, code_hashes = source_identity()
    pinned = [item for item in SOURCES if item["file_name"].endswith(".geojson")]
    paths = {item["file_name"]: download_source(cache, item) for item in pinned}
    input_hashes = {str(path): sha(path) for path in paths.values()}
    paris = json.loads(paths["paris_districts.geojson"].read_text(encoding="utf-8"))["features"]
    mines = json.loads(paths["cod_mines_curated_all_opendata_p_ipis.geojson"].read_text(encoding="utf-8"))["features"]
    report = {
        "schema": "cartomize.validation_m10_real.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cartomize_version": cm.__version__,
        "repository_head_at_validation": head,
        "validation_script_sha256": sha(Path(__file__)),
        "tested_source_sha256": code_hashes,
        "code_state": "Module hashes identify the tested working sources; HEAD may precede the implementation.",
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "sqlite": sqlite3.sqlite_version,
                    "packages": {name: metadata.version(name) for name in
                                 ("geopandas", "shapely", "pandas", "numpy", "pyproj", "pyogrio", "pyarrow")}},
        "sources": pinned, "source_commit": TUTORIAL_REF,
        "source_repository": "https://github.com/jorisvandenbossche/geopandas-tutorial",
        "input_dataset_scope": "Historical teaching snapshots, not a current territorial inventory. Input schema variants are experimental derivatives; original pinned files remain unchanged and are not committed.",
        "method": "Expected records are built from standard-library JSON and Python lists/dictionaries, without pandas.concat or Cartomize merge. Saved attributes are read with sqlite3, including Python integer/null types. Saved XY Point/Polygon coordinates are decoded directly from OGC GeoPackage/WKB using struct, without GDAL, GEOS or Cartomize as a geometry reference.",
        "references": REFERENCES,
        "checks": [], "passed": 0, "failed": 0,
    }

    def passed(name, **values):
        entry = {"name": name, "status": "passed", **serial(values)}
        report["checks"].append(entry)
        report["passed"] += 1
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    active_check = "Pinned real source records and independent counts"
    try:
        mine_values = [feature["properties"] for feature in mines]
        assert len(mines) == len({p["vid"] for p in mine_values}) == 3687
        assert len({p["pcode"] for p in mine_values}) == 2403
        assert sum(p["workers_numb"] is None for p in mine_values) == 658
        assert sum(p["workers_numb"] == 0 for p in mine_values) == 44
        assert sum(p["workers_numb"] for p in mine_values if p["workers_numb"] is not None) == 552559
        assert len(paris) == 80
        assert sum(f["properties"]["population"] for f in paris) == 2125851
        passed(active_check, mining_visits=3687, unique_mining_sites=2403,
               missing_workforce_values=658, zero_workforce_values=44,
               sum_of_known_visit_workforce=552559, paris_districts=80,
               sum_of_source_population_values=2125851,
               interpretation="Workforce is summed over visits, not unique sites or contemporaneous population.")

        with tempfile.TemporaryDirectory(prefix="m10-merge-", dir=cache) as temporary:
            work = Path(temporary)
            mine_paths, mine_expected, original_positions = mining_variants(mines, work)
            mappings = [
                {"vid": "visit_id", "pcode": "site", "name": "nom", "workers_numb": "effectif"},
                {"visit_code": "visit_id", "site_code": "site", "site_name": "nom"},
            ]
            mine_schema = {
                "visit_id": {"type": "int64", "nullable": False},
                "site": {"type": "string", "nullable": False}, "nom": "string",
                "effectif": "int64", "province": "string",
            }
            active_check = "Schema inspection identifies mapped type conflicts"
            mine_layers, mine_maps = source_maps(cm, mine_paths, mappings)
            inspected = cm.inspect_merge(mine_paths, field_maps=mine_maps)
            assert len(inspected["layers"]) == 2 and inspected["conflicts"]
            assert [layer["features"] for layer in mine_layers] == [1844, 1843]
            passed(active_check, source_features=[1844, 1843],
                   mapped_targets=list(mine_schema), conflicts=inspected["conflicts"],
                   derived_schemas="Alternating original records; second source uses textual IDs/counts and omits province.")

            active_check = "Complete harmonized merge and saved products"
            result = cm.merge_layers(mine_paths, work / "mines_merged", schema=mine_schema,
                                     field_maps=mine_maps)
            manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
            assert manifest["schema"] == "cartomize.vector_merge.v1"
            assert manifest["status"] == "complete"
            assert manifest["source_count"] == 2 and manifest["feature_count"] == 3687
            assert all(path.is_file() for path in (result.data, result.manifest, result.report, result.issues))
            saved, types = read_saved_records(result.data)
            provenance = manifest["provenance_columns"]
            passed(active_check, source_count=2, feature_count=3687,
                   saved_sql_types=types, provenance_columns=provenance)

            active_check = "Independent per-record attributes, nulls and provenance"
            assert_saved(mine_expected, saved, mine_layers, provenance, compare_geometry=False)
            workforce = [row["properties"]["effectif"] for row in saved]
            assert sum(value is None for value in workforce) == 658
            assert sum(value == 0 for value in workforce) == 44
            assert sum(value for value in workforce if value is not None) == 552559
            assert all(value is None or type(value) is int for value in workforce)
            assert sum(row["properties"]["province"] is None for row in saved[1844:]) == 1843
            passed(active_check, records_compared=3687, attributes_compared_per_record=5,
                   provenance_values_per_record=5, null_counts_preserved=658,
                   zeros_preserved=44, sum_of_known_visit_workforce=552559,
                   rows_with_deliberately_absent_province=1843,
                   source_row_convention="Zero-based within each derived source; original records were split by alternating positions.")

            active_check = "All real point coordinates preserved in saved binary geometry"
            expected_sequence = [record for source in mine_expected for record in source]
            assert [row["geometry"] for row in saved] == [row["geometry"] for row in expected_sequence]
            passed(active_check, geometries_compared=3687, coordinate_pairs_compared=3687,
                   comparison="Exact decoded coordinate values and Point type; independent struct decoder.")

            active_check = "Polygon schema harmonization preserves complete original records"
            paris_paths, paris_expected = paris_variants(paris, work)
            paris_layers, paris_maps = source_maps(cm, paris_paths, [
                {"id": "district_id", "district_name": "nom"},
                {"code_quartier": "district_id", "nom_quartier": "nom", "habitants": "population"},
            ])
            paris_schema = {"district_id": {"type": "int64", "nullable": False},
                            "nom": "string", "population": {"type": "int64", "nullable": False}}
            paris_result = cm.merge_layers(paris_paths, work / "paris_merged", schema=paris_schema,
                                           field_maps=paris_maps)
            paris_saved, paris_types = read_saved_records(paris_result.data)
            assert_saved(paris_expected, paris_saved, paris_layers,
                         paris_result.summary["provenance_columns"])
            assert sum(row["properties"]["population"] for row in paris_saved) == 2125851
            coordinate_pairs = sum(len(ring) for feature in paris for ring in feature["geometry"]["coordinates"])
            assert coordinate_pairs == 8366
            passed(active_check, records_compared=80, coordinate_pairs_compared=coordinate_pairs,
                   sum_of_population=2125851, saved_sql_types=paris_types,
                   geometry_comparison="All original polygon rings and coordinate pairs, unchanged.")

            active_check = "Concatenation retains overlapping and repeated polygons"
            duplicate_paths = [work / "overlap_a.geojson", work / "overlap_b.geojson"]
            for path in duplicate_paths:
                write_collection(path, paris)
            duplicate_layers = cm.inspect_merge(duplicate_paths)["layers"]
            duplicate_result = cm.merge_layers(duplicate_paths, work / "overlap_merged")
            duplicated, _ = read_saved_records(duplicate_result.data)
            expected_duplicates = [[{"properties": f["properties"], "geometry": f["geometry"]}
                                    for f in paris] for _ in range(2)]
            assert_saved(expected_duplicates, duplicated, duplicate_layers,
                         duplicate_result.summary["provenance_columns"])
            passed(active_check, source_features=[80, 80], saved_features=160,
                   deliberate_duplicate_records_retained=80,
                   note="An intentional duplicated real fixture checks concatenation; no dissolve, union or deduplication is expected.")

            bad_data = json.loads(mine_paths[1].read_text(encoding="utf-8"))
            bad_row = next(i for i, feature in enumerate(bad_data["features"])
                           if feature["properties"]["effectif"] is not None)
            replaced_value = bad_data["features"][bad_row]["properties"]["effectif"]
            bad_data["features"][bad_row]["properties"]["effectif"] = "not-an-integer"
            bad_path = work / "mines_bad.geojson"
            write_collection(bad_path, bad_data["features"])
            bad_paths = [mine_paths[0], bad_path]
            bad_layers, bad_maps = source_maps(cm, bad_paths, mappings)

            active_check = "Strict conversion refusal leaves no published output"
            destination = work / "strict_conversion_refused"
            message = refuse_without_publication(
                lambda: cm.merge_layers(bad_paths, destination, schema=mine_schema, field_maps=bad_maps),
                destination)
            passed(active_check, deliberately_invalid_token="not-an-integer",
                   derived_source_row=bad_row, destination_published=False, message=message)

            active_check = "Explicit null conversion records the exact problematic value"
            nullable = cm.merge_layers(bad_paths, work / "conversion_to_null", schema=mine_schema,
                                       field_maps=bad_maps, conversion_errors="null")
            nullable_saved, _ = read_saved_records(nullable.data)
            nullable_expected = json.loads(json.dumps(mine_expected))
            nullable_expected[1][bad_row]["properties"]["effectif"] = None
            assert_saved(nullable_expected, nullable_saved, bad_layers,
                         nullable.summary["provenance_columns"])
            with nullable.issues.open(encoding="utf-8-sig", newline="") as handle:
                issues = list(csv.DictReader(handle))
            assert any("not-an-integer" in str(value) for issue in issues for value in issue.values())
            assert sum(row["properties"]["effectif"] is None for row in nullable_saved) == 659
            passed(active_check, issue_rows=len(issues), invalid_token_logged=True,
                   null_workforce_after_explicit_policy=659, replaced_source_value=replaced_value,
                   scope="The invalid token was deliberately inserted into a temporary schema variant, not the pinned data.")

            active_check = "Missing-field error policy refuses the incomplete schema"
            destination = work / "missing_field_refused"
            message = refuse_without_publication(
                lambda: cm.merge_layers(mine_paths, destination, schema=mine_schema,
                                         field_maps=mine_maps, missing_fields="error"), destination)
            passed(active_check, absent_field="province", destination_published=False, message=message)

            active_check = "Declared default fills missing values without rewriting valid values"
            default_schema = dict(mine_schema)
            default_schema["province"] = {"type": "string", "nullable": False, "default": "Non renseigné"}
            defaults = cm.merge_layers(mine_paths, work / "declared_defaults", schema=default_schema,
                                       field_maps=mine_maps)
            default_saved, _ = read_saved_records(defaults.data)
            default_expected = json.loads(json.dumps(mine_expected))
            filled = 0
            for records in default_expected:
                for record in records:
                    if record["properties"]["province"] is None:
                        record["properties"]["province"] = "Non renseigné"
                        filled += 1
            assert_saved(default_expected, default_saved, mine_layers,
                         defaults.summary["provenance_columns"])
            passed(active_check, field="province", declared_default="Non renseigné",
                   filled_values=filled, valid_source_values_preserved=True)

        active_check = "Pinned source files and tested modules unchanged"
        assert input_hashes == {path: sha(Path(path)) for path in input_hashes}
        assert code_hashes == source_identity()[1], "The sources changed during validation."
        passed(active_check, source_files=len(input_hashes), tested_modules=len(code_hashes))
    except Exception as exc:
        report["checks"].append({"name": active_check, "status": "failed",
                                 "error_type": type(exc).__name__, "message": str(exc)})
        report["failed"] += 1
    report["status"] = "passed" if not report["failed"] else "failed"
    report["duration_seconds"] = round(time.perf_counter() - started, 3)
    atomic_report(output, report)
    print(json.dumps({key: report[key] for key in ("status", "passed", "failed", "duration_seconds")}), flush=True)
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return validate(args.data.expanduser().resolve(), args.output.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
