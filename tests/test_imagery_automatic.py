"""End-to-end coverage decisions on real raster files and a bounded STAC service."""
import importlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

import cartomize as cm


def _zone():
    return gpd.GeoDataFrame(geometry=[box(300000, 9499980, 300040, 9500000)], crs=32733)


def _scene(write_raster, name, *, left=300000, width=2, resolution=10, mask=1, acquired="2026-10-26"):
    transform = from_origin(left, 9500000, resolution, resolution)
    spectral = write_raster(name + ".tif", np.array([
        np.full((2, width), 1000), np.full((2, width), 3000)], dtype="int16"), transform=transform)
    qa = write_raster(name + "_qa.tif", np.full((2, width), mask, dtype="uint8"),
                      nodata=255, transform=transform)
    return cm.Scene(name, {role: cm.Band(spectral, index=index, scale=.001, offset=-.1, unit="reflectance")
                          for index, role in enumerate(("red", "nir"), 1)},
                    sensor="test-sensor", acquired=acquired, quality=qa, quality_kind="valid_mask")


def _image(result):
    return result.products[0]["multiband"]


def test_automatically_selects_best_scene_and_keeps_original_grid(write_raster, tmp_path):
    # Discarding the coarse candidate must not change the diagnosed target grid.
    coarse = _scene(write_raster, "coarse", width=1, resolution=20)
    complete = _scene(write_raster, "fine", width=8, resolution=5)
    # Both source rows do not cover AOI height: make the fine file four rows.
    path = Path(complete.bands["red"].path)
    with rasterio.open(path) as src:
        profile = src.profile
    with rasterio.open(path, "w", **{**profile, "height": 4}) as dst:
        dst.write(np.array([np.full((4, 8), 1000), np.full((4, 8), 3000)], dtype="int16"))
    with rasterio.open(complete.quality) as src:
        profile = src.profile
    with rasterio.open(complete.quality, "w", **{**profile, "height": 4}) as dst:
        dst.write(np.ones((1, 4, 8), dtype="uint8"))
    result = cm.preprocess_imagery([coarse, complete], tmp_path / "automatic", aoi=_zone())
    assert result.report["selected_scene_ids"] == ["fine"]
    assert result.report["mosaic"] is False
    with rasterio.open(_image(result)) as src:
        assert src.res == (20, 20) and src.shape == (1, 2)
        np.testing.assert_allclose(src.read(1), .9)
    assert result.diagnostic.report["parameters"]["resolution_m"] == 20


def test_mosaic_keeps_complete_spectra_quality_and_real_gap_codes(write_raster, tmp_path):
    left = _scene(write_raster, "left")
    right = _scene(write_raster, "right", left=300020)
    result = cm.preprocess_imagery([left, right], tmp_path / "mosaic", aoi=_zone(), separate_bands=True)
    assert result.report["mosaic"] is True and result.report["usable_percent"] == 100
    with rasterio.open(_image(result)) as src:
        np.testing.assert_allclose(src.read(1), .9)
        np.testing.assert_allclose(src.read(2), 2.9)
    with rasterio.open(result.products[0]["source_index"]) as src:
        np.testing.assert_array_equal(src.read(1), [[1, 1, 2, 2], [1, 1, 2, 2]])
    with rasterio.open(result.diagnostic.gaps) as src:
        assert np.all(src.read(1) == 0)


@pytest.mark.parametrize("allow_partial", [False, True])
def test_all_clouds_always_blocks_and_preserves_quality_diagnostic(write_raster, tmp_path, allow_partial):
    scene = _scene(write_raster, "cloud", width=4, mask=0)
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery([scene], tmp_path / "science", aoi=_zone(), allow_partial=allow_partial)
    assert not (tmp_path / "science").exists()
    error = caught.value
    assert error.report["footprint_percent"] == 100 and error.report["usable_percent"] == 0
    with rasterio.open(error.diagnostic.gaps) as src:
        assert np.all(src.read(1) == 3)


def test_repeated_refusal_does_not_overwrite_a_previous_diagnostic(write_raster, tmp_path):
    scene = _scene(write_raster, "half")
    paths = []
    for _ in range(2):
        with pytest.raises(cm.ImageryCoverageError) as caught:
            cm.preprocess_imagery([scene], tmp_path / "science", aoi=_zone())
        paths.append(caught.value.manifest)
    assert paths[0] != paths[1] and all(path.is_file() for path in paths)


def test_mask_is_never_disabled_silently(write_raster, tmp_path):
    scene = _scene(write_raster, "unmasked", width=4)
    without_mask = cm.Scene(scene.scene_id, scene.bands, sensor=scene.sensor, acquired=scene.acquired)
    with pytest.raises(ValueError, match="quality mask"):
        cm.preprocess_imagery([without_mask], tmp_path / "science", aoi=_zone())
    result = cm.preprocess_imagery([without_mask], tmp_path / "explicit", aoi=_zone(), mask_clouds=False)
    assert result.report["parameters"]["mask_clouds"] is False


def test_cancel_during_preparation_does_not_publish_any_scientific_result(write_raster, tmp_path):
    scene = _scene(write_raster, "full", width=4)
    cancel = threading.Event()
    def stage(message):
        if "Préparation des scènes retenues" in message:
            cancel.set()
    with pytest.raises(cm.ProcessingCancelled):
        cm.preprocess_imagery([scene], tmp_path / "cancelled", aoi=_zone(), stage=stage, cancel=cancel)
    assert not (tmp_path / "cancelled").exists()
    assert not list(tmp_path.glob("cancelled_diagnostic*"))


def test_changed_source_between_audit_and_preparation_cannot_be_published(write_raster, tmp_path):
    scene = _scene(write_raster, "full", width=4)
    def stage(message):
        if "Préparation des scènes retenues" in message:
            with rasterio.open(scene.bands["red"].path, "r+") as dst:
                dst.write(np.full((2, 4), 2000, dtype="int16"), 1)
    with pytest.raises(ValueError, match="changé"):
        cm.preprocess_imagery([scene], tmp_path / "changed", aoi=_zone(), stage=stage)
    assert not (tmp_path / "changed").exists()


@pytest.fixture
def catalog_service(write_raster):
    state = {"items": [], "requests": [], "assets": {}, "search_error": False,
             "protocol_errors": {}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(("search", body))
            if self.protocol_failure("search"):
                return
            if state["search_error"]:
                self.send_error(503)
                return
            self.respond(json.dumps(dict(type="FeatureCollection", features=state["items"], links=[])).encode())
        def do_GET(self):
            name = urlsplit(self.path).path
            state["requests"].append(("asset", name))
            if self.protocol_failure(name):
                return
            if name not in state["assets"]:
                self.send_error(404)
                return
            self.respond(state["assets"][name])
        def protocol_failure(self, name):
            failure = state["protocol_errors"].get(name)
            if failure is None:
                return False
            if failure == "incomplete_chunk":
                self.send_response(200)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                # Advertise sixteen bytes, then close after only nine. This
                # exercises HTTPResponse's real IncompleteRead error path.
                self.wfile.write(b"10\r\ntruncated")
            elif failure == "bad_status":
                self.wfile.write(b"NOT_HTTP\r\n\r\n")
            else:
                raise AssertionError(failure)
            self.close_connection = True
            return True
        def respond(self, body):
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state["endpoint"] = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def add(name, left=300020, date="2026-10-26", width=2, mask=1):
        scene = _scene(write_raster, name, left=left, width=width, acquired=date, mask=mask)
        assets = {}
        for key, path in (("spectrum", scene.bands["red"].path), ("valid", scene.quality)):
            endpoint_path = f"/{name}_{key}.tif"
            state["assets"][endpoint_path] = Path(path).read_bytes()
            assets[key] = dict(href=state["endpoint"] + endpoint_path)
        assets["spectrum"]["bands"] = [dict(name=role, common_name=role, scale=.001, offset=-.1,
                                                    unit="reflectance", nodata=-9999) for role in ("red", "nir")]
        item = dict(type="Feature", stac_version="1.1.0", id=name, collection="custom",
                    properties=dict(platform="test-sensor", datetime=date + "T00:00:00Z"), assets=assets, links=[])
        state["items"].append(item)
        return item
    state["add"] = add
    state["config"] = dict(endpoint=state["endpoint"], collections=["custom"],
                           quality_asset="valid", quality_kind="valid_mask", max_bytes=1_000_000)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_local_gap_drives_bounded_download_masked_mosaic_and_provenance(write_raster, tmp_path, catalog_service):
    service = catalog_service
    service["add"]("right")
    service["add"]("never_download", left=300000)
    left = _scene(write_raster, "left")
    result = cm.preprocess_imagery([left], tmp_path / "complete", aoi=_zone(), catalog=service["config"])
    assert result.report["initial_usable_percent"] == 50 and result.report["usable_percent"] == 100
    assert result.report["selected_scene_ids"] == ["left", "right"]
    assert result.report["downloaded_bytes"] == sum(len(v) for key, v in service["assets"].items() if key.startswith("/right"))
    search = service["requests"][0][1]
    assert search["intersects"]["type"] == "Polygon"
    assert search["datetime"] == "2026-10-26" and search["collections"] == ["custom"]
    assert not any("never_download" in str(value) for kind, value in service["requests"] if kind == "asset")
    with rasterio.open(_image(result)) as src:
        np.testing.assert_allclose(src.read(1), .9)
        assert src.read_masks(1).min() == 255
    for asset in result.diagnostic.report["assets"]:
        assert Path(asset["path"]).is_file()
    assert not any(".cartomize-" in path.read_text(encoding="utf-8") for path in (tmp_path / "complete").rglob("*.json"))


def test_complete_local_inputs_do_not_contact_configured_catalog(write_raster, tmp_path, catalog_service):
    scene = _scene(write_raster, "full", width=4)
    cm.preprocess_imagery([scene], tmp_path / "complete", aoi=_zone(), catalog=catalog_service["config"])
    assert catalog_service["requests"] == []


def test_explicitly_disabled_cloud_mask_does_not_download_quality(write_raster, tmp_path, catalog_service):
    service = catalog_service
    service["add"]("complete", left=300000, width=4)
    result = cm.preprocess_imagery([], tmp_path / "unmasked", aoi=_zone(),
        catalog=service["config"], band_order=["red", "nir"], target_crs=32733,
        resolution=10, mask_clouds=False)
    assert result.report["status"] == "complete"
    assert not any("_valid" in str(value) for kind, value in service["requests"] if kind == "asset")
    assert result.diagnostic.report["parameters"]["mask_clouds"] is False


def test_unselected_missing_band_does_not_block_requested_roles(write_raster, tmp_path):
    original = _scene(write_raster, "full", width=4)
    scene = cm.Scene(original.scene_id, {**original.bands, "swir1": tmp_path / "not_selected.tif"},
        sensor=original.sensor, acquired=original.acquired, quality=original.quality, quality_kind="valid_mask")
    result = cm.preprocess_imagery([scene], tmp_path / "selected", aoi=_zone(), band_order=["red", "nir"])
    assert result.report["status"] == "complete"


def test_remote_only_uses_explicit_grid_and_rejects_unhelpful_dates(write_raster, tmp_path, catalog_service):
    service = catalog_service
    service["add"]("left", left=300000)
    service["add"]("wrong_date", date="2026-10-25")
    service["add"]("right")
    result = cm.preprocess_imagery([], tmp_path / "remote", aoi=_zone(), band_order=["red", "nir"],
        target_crs=32733, resolution=10, catalog=service["config"])
    assert result.report["selected_scene_ids"] == ["left", "right"]
    rejected = next(record for record in result.report["acquisitions"] if record["id"] == "wrong_date")
    assert rejected["status"] == "rejected" and "Date" in rejected["reason"]
    assert not (tmp_path / "remote" / "acquisitions" / "scene_0002").exists()


@pytest.mark.parametrize("remote_only", [False, True])
def test_failed_search_keeps_exact_diagnostics(write_raster, tmp_path, catalog_service, remote_only):
    catalog_service["search_error"] = True
    scenes = [] if remote_only else [_scene(write_raster, "left")]
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery(scenes, tmp_path / "blocked", aoi=_zone(), catalog=catalog_service["config"],
            band_order=["red", "nir"], target_crs=32733, resolution=10)
    error = caught.value
    assert error.report["usable_percent"] == (0 if remote_only else 50)
    assert error.report["aoi_pixels"] == 8
    assert error.workflow_report["acquisitions"][0]["status"] == "search_failed"
    assert error.manifest.exists() and not (tmp_path / "blocked").exists()


@pytest.mark.parametrize("remote_only", [False, True])
@pytest.mark.parametrize("failure", ["incomplete_chunk", "bad_status"])
def test_http_protocol_search_failure_preserves_diagnostics(
        write_raster, tmp_path, catalog_service, remote_only, failure):
    service = catalog_service
    service["protocol_errors"]["search"] = failure
    scenes = [] if remote_only else [_scene(write_raster, "left")]
    destination = tmp_path / "protocol_search"
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery(scenes, destination, aoi=_zone(), catalog=service["config"],
            band_order=["red", "nir"], target_crs=32733, resolution=10)
    error = caught.value
    assert not destination.exists()
    assert error.report["usable_percent"] == (0 if remote_only else 50)
    assert error.report["aoi_pixels"] == 8
    assert error.workflow_report["products"] == []
    assert error.workflow_report["acquisitions"][0]["status"] == "search_failed"
    reason = error.workflow_report["acquisitions"][0]["reason"]
    assert ("IncompleteRead" if failure == "incomplete_chunk" else "NOT_HTTP") in reason
    assert error.manifest.is_file() and error.diagnostic.coverage.is_file()
    expected = np.ones((2, 4), dtype="uint8")
    if not remote_only:
        expected[:, :2] = 0
    with rasterio.open(error.diagnostic.gaps) as source:
        np.testing.assert_array_equal(source.read(1), expected)
    assert not any(kind == "asset" for kind, _ in service["requests"])


@pytest.mark.parametrize("retained_first", [False, True])
@pytest.mark.parametrize("failure", ["incomplete_chunk", "bad_status"])
def test_http_protocol_transfer_failure_preserves_useful_acquisitions_and_stops(
        write_raster, tmp_path, catalog_service, retained_first, failure):
    service = catalog_service
    if retained_first:
        service["add"]("quarter", width=1)
    service["add"]("broken")
    service["add"]("must_not_download")
    # Fail after the spectrum was downloaded, while the QA companion is read.
    service["protocol_errors"]["/broken_valid.tif"] = failure
    destination = tmp_path / "protocol_transfer"
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery([_scene(write_raster, "left")], destination,
                             aoi=_zone(), catalog=service["config"])
    error = caught.value
    assert not destination.exists()
    assert error.report["usable_percent"] == (75 if retained_first else 50)
    assert error.workflow_report["products"] == []
    records = error.workflow_report["acquisitions"]
    assert len(records) == (2 if retained_first else 1)
    assert records[-1]["id"] == "broken"
    assert records[-1]["retained"] is False
    assert records[-1]["transfer_incomplete"] is True
    reason = records[-1]["reason"]
    assert ("IncompleteRead" if failure == "incomplete_chunk" else "NOT_HTTP") in reason
    assert not any("must_not_download" in str(value)
                   for kind, value in service["requests"] if kind == "asset")
    assert error.manifest.is_file() and error.diagnostic.coverage.is_file()
    expected = np.ones((2, 4), dtype="uint8")
    expected[:, :3 if retained_first else 2] = 0
    with rasterio.open(error.diagnostic.gaps) as source:
        np.testing.assert_array_equal(source.read(1), expected)
    assert all(Path(asset["path"]).is_file() for asset in error.report["assets"])
    if retained_first:
        assert records[0]["retained"] is True
        acquisitions = Path(error.workflow_report["download_directory"])
        manifest = acquisitions / "scene_0001" / "download.json"
        retained = json.loads(manifest.read_text(encoding="utf-8"))
        assert retained["assets"]
        for asset in retained["assets"]:
            assert (manifest.parent / asset["file"]).read_bytes() == service["assets"][
                f"/quarter_{asset['asset']}.tif"]
        assert not (acquisitions / "scene_0002").exists()
    assert not any(".cartomize-" in path.read_text(encoding="utf-8")
                   for path in error.manifest.parent.rglob("*.json"))


def test_below_threshold_downloads_remain_reusable_in_failure_diagnostic(write_raster, tmp_path, catalog_service):
    service = catalog_service
    service["add"]("quarter", width=1)
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery([_scene(write_raster, "left")], tmp_path / "blocked", aoi=_zone(), catalog=service["config"])
    error = caught.value
    assert error.report["usable_percent"] == 75
    for asset in error.report["assets"]:
        assert Path(asset["path"]).is_file()
    assert error.workflow_report["acquisitions"][0]["retained"] is True
    again = error.preserve(tmp_path / "another_diagnostic")
    assert all(Path(asset["path"]).is_file() for asset in again.report["assets"])
    assert not any(".cartomize-" in path.read_text(encoding="utf-8") for path in again.manifest.parent.rglob("*.json"))


def test_download_budget_failure_stops_following_transfers(write_raster, tmp_path, catalog_service):
    service = catalog_service
    service["add"]("too_large")
    service["add"]("do_not_fetch")
    with pytest.raises(cm.ImageryCoverageError) as caught:
        cm.preprocess_imagery([_scene(write_raster, "left")], tmp_path / "blocked", aoi=_zone(),
                              catalog={**service["config"], "max_bytes": 10})
    assert caught.value.workflow_report["acquisitions"][0]["transfer_incomplete"] is True
    assert not any("do_not_fetch" in str(value) for kind, value in service["requests"] if kind == "asset")


@pytest.mark.parametrize("kwargs", [dict(coverage_threshold=0), dict(coverage_threshold=float("nan")),
    dict(coverage_threshold=101), dict(allow_partial="false"), dict(band_order=["red", "red"]),
    dict(resolution=0), dict(max_pixels=0), dict(target_crs=4326)])
def test_invalid_policies_fail_before_creating_outputs(write_raster, tmp_path, kwargs):
    with pytest.raises(ValueError):
        cm.preprocess_imagery([_scene(write_raster, "full", width=4)], tmp_path / "invalid", aoi=_zone(), **kwargs)
    assert not (tmp_path / "invalid").exists()
