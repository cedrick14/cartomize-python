"""Check that uploading a wheel will preserve its intended public description.

PyPI retains the first metadata uploaded for a release. A later wheel can be
accepted while its description is not applied to the public project page.
This read-only check permits a new release or an existing matching description.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from email import policy
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import zipfile


INDEXES = {
    "pypi": ("PyPI", "https://pypi.org"),
    "testpypi": ("TestPyPI", "https://test.pypi.org"),
}


class MetadataCheckError(RuntimeError):
    """The upload must not proceed without a verified matching description."""


@dataclass(frozen=True)
class WheelMetadata:
    filename: str
    name: str
    version: str
    description: str


def descriptions_equal(stored: str, expected: str) -> bool:
    """Ignore newline encoding and final blank lines, preserving other text."""
    def normalized(value: str) -> str:
        return value.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")

    return normalized(stored) == normalized(expected)


def read_wheel_metadata(directory: Path) -> WheelMetadata:
    """Read the sole staged wheel without extracting archive members."""
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise MetadataCheckError("The upload directory must contain exactly one wheel.")
    wheel = wheels[0]
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist()
                     if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise MetadataCheckError("The wheel must contain exactly one METADATA file.")
            # Core Metadata is UTF-8, including a description without MIME headers.
            metadata = Parser(policy=policy.default).parsestr(
                archive.read(names[0]).decode("utf-8")
            )
    except (OSError, zipfile.BadZipFile, UnicodeError) as error:
        raise MetadataCheckError("Cannot read the staged wheel metadata.") from error

    name, version = metadata.get("Name"), metadata.get("Version")
    if not name or not version:
        raise MetadataCheckError("The wheel metadata must specify Name and Version.")
    description = metadata.get_payload()
    if not isinstance(description, str):
        raise MetadataCheckError("The wheel description must be plain metadata text.")
    if not description:
        description = str(metadata.get("Description", ""))
    return WheelMetadata(wheel.name, str(name), str(version), description)


def fetch_description(wheel: WheelMetadata, index: str, *, opener=None) -> str | None:
    """Return a stored description, or None only when the release returns 404."""
    if index not in INDEXES:
        raise MetadataCheckError("Select either pypi or testpypi.")
    label, base_url = INDEXES[index]
    digest = hashlib.sha256(wheel.description.encode("utf-8")).hexdigest()
    # A release can be removed between two checks of the same wheel. Include
    # an attempt identifier as well as the expected content hash so that a
    # previously cached conflict cannot outlive that owner action.
    url = (f"{base_url}/pypi/{quote(wheel.name, safe='')}/"
           f"{quote(wheel.version, safe='')}/json?description_sha256={digest}"
           f"&checked_at={time.time_ns()}")
    request = Request(url, headers={
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "Cartomize-metadata-check/1.0",
    })
    open_request = opener if opener is not None else urlopen
    try:
        with open_request(request, timeout=30) as response:
            if response.status != 200:
                raise MetadataCheckError(
                    f"Cannot verify {label} metadata (HTTP {response.status})."
                )
            payload = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise MetadataCheckError(
            f"Cannot verify {label} metadata (HTTP {error.code})."
        ) from error
    except (URLError, OSError, TimeoutError) as error:
        raise MetadataCheckError(f"Cannot fetch metadata from {label}.") from error
    except (ValueError, UnicodeError) as error:
        raise MetadataCheckError(f"{label} returned invalid release metadata.") from error

    info = payload.get("info") if isinstance(payload, dict) else None
    description = info.get("description") if isinstance(info, dict) else None
    if not isinstance(description, str):
        raise MetadataCheckError(f"{label} returned invalid release metadata.")
    return description


def check_upload(directory: Path, index: str = "pypi", *, opener=None) -> dict:
    """Reject a later upload that cannot apply the wheel's long description."""
    wheel = read_wheel_metadata(directory)
    stored = fetch_description(wheel, index, opener=opener)
    if stored is not None and not descriptions_equal(stored, wheel.description):
        label = INDEXES[index][0]
        raise MetadataCheckError(
            f"{label} already has {wheel.name} {wheel.version} with a different "
            "description. Uploading another file will not update that description. "
            "Resolve the existing release before publishing."
        )
    return {
        "index": index,
        "name": wheel.name,
        "version": wheel.version,
        "wheel": wheel.filename,
        "description_sha256": hashlib.sha256(
            wheel.description.encode("utf-8")
        ).hexdigest(),
        "status": "release_not_found" if stored is None else "description_matches",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory containing the staged wheel")
    parser.add_argument("--index", choices=INDEXES, default="pypi")
    args = parser.parse_args(argv)
    try:
        result = check_upload(args.directory, args.index)
    except MetadataCheckError as error:
        print(f"Metadata check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
