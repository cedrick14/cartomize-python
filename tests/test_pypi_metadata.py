"""Guard the public description before sending an additional release file."""
from contextlib import closing
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import zipfile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_pypi_metadata.py"
SPEC = importlib.util.spec_from_file_location("check_pypi_metadata", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


DESCRIPTION = "# Cartomize\n\nAnalyse géospatiale et cartographie.\n"


def make_wheel(directory, *, description=DESCRIPTION, filename=None):
    path = directory / (filename or "cartomize-1.0-2026103101-py3-none-any.whl")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("cartomize-1.0.dist-info/METADATA", (
            "Metadata-Version: 2.4\nName: cartomize\nVersion: 1.0\n"
            "Description-Content-Type: text/markdown\n\n" + description
        ).encode("utf-8"))
    return path


def json_response(payload):
    stream = BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    stream.status = 200
    return closing(stream)


def matching_response(_request, **_kwargs):
    return json_response({"info": {"description": DESCRIPTION}})


@pytest.mark.parametrize("stored", [DESCRIPTION, DESCRIPTION.replace("\n", "\r\n"),
                                     DESCRIPTION.rstrip("\n")])
def test_description_comparison_preserves_content(stored):
    assert checker.descriptions_equal(stored, DESCRIPTION)
    assert not checker.descriptions_equal(stored.replace("géospatiale", "raster"), DESCRIPTION)


def test_existing_matching_description_allows_upload_with_utf8_metadata(tmp_path):
    make_wheel(tmp_path)
    result = checker.check_upload(tmp_path, opener=matching_response)
    assert result["status"] == "description_matches"
    assert result["name"] == "cartomize"
    assert result["version"] == "1.0"
    assert result["description_sha256"] == hashlib.sha256(DESCRIPTION.encode()).hexdigest()


def test_changed_existing_description_blocks_upload(tmp_path):
    make_wheel(tmp_path)
    def opener(_request, **_kwargs):
        return json_response({"info": {"description": "An older presentation."}})
    with pytest.raises(checker.MetadataCheckError,
                       match="Uploading another file will not update that description"):
        checker.check_upload(tmp_path, opener=opener)


def test_changed_existing_description_can_be_explicitly_allowed(tmp_path):
    make_wheel(tmp_path)
    def opener(_request, **_kwargs):
        return json_response({"info": {"description": "An older presentation."}})
    result = checker.check_upload(
        tmp_path,
        opener=opener,
        allow_existing_description_mismatch=True,
    )
    assert result["status"] == "description_mismatch_allowed"


def test_absent_release_is_allowed_only_for_404(tmp_path):
    make_wheel(tmp_path)
    def opener(request, **_kwargs):
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)
    assert checker.check_upload(tmp_path, opener=opener)["status"] == "release_not_found"


@pytest.mark.parametrize("error", [HTTPError("https://pypi.org", 403, "Forbidden", {}, None),
                                   HTTPError("https://pypi.org", 503, "Unavailable", {}, None),
                                   URLError("Connection failed"), TimeoutError()])
def test_fetch_errors_fail_closed(tmp_path, error):
    make_wheel(tmp_path)
    def opener(_request, **_kwargs):
        raise error
    with pytest.raises(checker.MetadataCheckError, match="Cannot (verify|fetch)"):
        checker.check_upload(tmp_path, opener=opener)


@pytest.mark.parametrize("index,host", [("pypi", "pypi.org"),
                                       ("testpypi", "test.pypi.org")])
def test_request_uses_selected_official_index_and_description_hash(tmp_path, index, host):
    make_wheel(tmp_path)
    def opener(request, *, timeout):
        url = urlsplit(request.full_url)
        assert (url.scheme, url.netloc, url.path) == ("https", host, "/pypi/cartomize/1.0/json")
        query = parse_qs(url.query)
        assert set(query) == {"description_sha256", "checked_at"}
        assert query["description_sha256"] == [hashlib.sha256(DESCRIPTION.encode()).hexdigest()]
        assert int(query["checked_at"][0]) > 0
        assert request.get_header("Cache-control") == "no-cache"
        assert request.get_header("Accept") == "application/json"
        assert timeout == 30
        return json_response({"info": {"description": DESCRIPTION}})
    assert checker.check_upload(tmp_path, index, opener=opener)["index"] == index


@pytest.mark.parametrize("payload", [{}, {"info": {}}, {"info": {"description": None}}, []])
def test_invalid_json_shape_does_not_approve_upload(tmp_path, payload):
    make_wheel(tmp_path)
    with pytest.raises(checker.MetadataCheckError, match="invalid release metadata"):
        checker.check_upload(tmp_path, opener=lambda *_a, **_k: json_response(payload))


@pytest.mark.parametrize("wheel_count", [0, 2])
def test_ambiguous_staging_directory_is_rejected_without_request(tmp_path, wheel_count):
    for number in range(wheel_count):
        make_wheel(tmp_path, filename=f"cartomize-1.0-{number}-py3-none-any.whl")
    def opener(*_args, **_kwargs):
        pytest.fail("No request is allowed before selecting one wheel")
    with pytest.raises(checker.MetadataCheckError, match="exactly one wheel"):
        checker.check_upload(tmp_path, opener=opener)


def test_cli_exits_nonzero_for_description_mismatch(tmp_path, monkeypatch, capsys):
    make_wheel(tmp_path)
    monkeypatch.setattr(checker, "urlopen", lambda *_a, **_k:
                        json_response({"info": {"description": "Old description"}}))
    assert checker.main([str(tmp_path), "--index", "pypi"]) == 1
    output = capsys.readouterr()
    assert "will not update that description" in output.err
    assert output.out == ""


def test_cli_can_explicitly_allow_existing_description_mismatch(tmp_path, monkeypatch, capsys):
    make_wheel(tmp_path)
    monkeypatch.setattr(
        checker,
        "urlopen",
        lambda *_a, **_k: json_response({"info": {"description": "Old description"}}),
    )
    assert checker.main([
        str(tmp_path),
        "--index",
        "pypi",
        "--allow-existing-description-mismatch",
    ]) == 0
    output = capsys.readouterr()
    assert "description_mismatch_allowed" in output.out
    assert output.err == ""


def test_cli_disallows_arbitrary_index_urls(tmp_path):
    with pytest.raises(SystemExit) as error:
        checker.main([str(tmp_path), "--index", "https://example.com"])
    assert error.value.code == 2
