"""Explicit spectral assets and discovery of standard Landsat/Sentinel files."""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np


@dataclass(frozen=True)
class Band:
    path: str | Path
    index: int = 1
    scale: float = 1.0
    offset: float = 0.0
    nodata: float | None = None
    unit: str = "source units"

    def __post_init__(self):
        if not isinstance(self.index, int) or self.index < 1:
            raise ValueError("Band index must be a positive integer.")
        if not np.isfinite([self.scale, self.offset]).all() or self.scale <= 0:
            raise ValueError("Band scale must be positive and scale/offset finite.")
        if self.nodata is not None and np.isinf(self.nodata):
            raise ValueError("Band NoData must be finite or NaN.")
        object.__setattr__(self,"scale",float(self.scale))
        object.__setattr__(self,"offset",float(self.offset))
        if self.nodata is not None:
            object.__setattr__(self,"nodata",float(self.nodata))


@dataclass(frozen=True)
class Scene:
    """One acquisition/tile; band keys are semantic names (red, nir, etc.).

    Use Band to declare calibration for custom data. Files are read locally.
    quality_kind supports landsat_qa, sentinel_scl and valid_mask (nonzero valid).
    """
    scene_id: str
    bands: dict[str, Band | str | Path]
    sensor: str
    acquired: str | None = None
    level: str = "custom"
    quality: str | Path | None = None
    quality_kind: str | None = None
    saturation: str | Path | None = None
    spectral_cloud: str | Path | None = None
    spectral_cloud_method: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.scene_id or not self.sensor or not self.bands:
            raise ValueError("Scene id, sensor and bands are required.")
        if self.acquired is not None:
            if not isinstance(self.acquired,str):
                raise ValueError("Acquisition date must be ISO date text or None.")
            acquired=self.acquired.strip()
            object.__setattr__(self,"acquired",date.fromisoformat(acquired).isoformat() if acquired else None)
        if self.quality is not None and self.quality_kind not in {"landsat_qa", "sentinel_scl", "valid_mask"}:
            raise ValueError("Declare the quality mask kind.")
        if any(not isinstance(k, str) or not k for k in self.bands):
            raise ValueError("Band names must be nonempty strings.")
        object.__setattr__(self, "bands", {k: v if isinstance(v, Band) else Band(v) for k, v in self.bands.items()})


LANDSAT_OLI = {"B1":"coastal", "B2":"blue", "B3":"green", "B4":"red", "B5":"nir", "B6":"swir1", "B7":"swir2"}
LANDSAT_TM = {"B1":"blue", "B2":"green", "B3":"red", "B4":"nir", "B5":"swir1", "B7":"swir2"}
SENTINEL = {"B01":"coastal", "B02":"blue", "B03":"green", "B04":"red", "B05":"rededge1", "B06":"rededge2", "B07":"rededge3", "B08":"nir", "B8A":"nir_narrow", "B09":"water_vapour", "B11":"swir1", "B12":"swir2"}
_S2_BANDS = ["B01","B02","B03","B04","B05","B06","B07","B08","B8A","B09","B10","B11","B12"]
_LANDSAT = re.compile(r"^(L[CET]\d{2}_L2(?:SP|SR)_\d{6}_(\d{8})_\d{8}_02_[A-Z0-9]+)_(?:SR_(B\d+)|(QA_PIXEL|QA_RADSAT))\.(?:tif|tiff)$", re.I)
_LANDSAT_L1 = re.compile(r"^(L[CET]\d{2}_L1(?:TP|GT|GS)_\d{6}_(\d{8})_\d{8}_02_[A-Z0-9]+)_(?:(B\d+)|(QA_PIXEL|QA_RADSAT))\.(?:tif|tiff)$", re.I)
_LANDSAT_THERMAL = re.compile(
    r"^((?:LC0[89]|LE07|LT0[45])_L2SP_\d{6}_\d{8}_\d{8}_02_[A-Z0-9]+)_"
    r"ST_(B6|B10|ATRAN|CDIST|DRAD|EMIS|EMSD|QA|TRAD|URAD)\.(?:tif|tiff)$", re.I)
_S2 = re.compile(r"^(T\d{2}[A-Z]{3})_(\d{8}T\d{6})_(B\d{2}|B8A|SCL)_(10|20|60)m\.(?:jp2|tif|tiff)$", re.I)
_S2_L1 = re.compile(r"^(T\d{2}[A-Z]{3})_(\d{8}T\d{6})_(B\d{2}|B8A)(?:_(10|20|60)m)?\.(?:jp2|tif|tiff)$", re.I)


def _landsat_l1_metadata(directory, ident):
    """Read Collection 2 Level-1 reflectance scaling and solar elevation."""
    directory = Path(directory)
    candidates = [
        directory / f"{ident}_MTL.txt",
        directory / f"{ident}_MTL.TXT",
    ]
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise ValueError(
            f"Missing Landsat Level-1 metadata for {ident}. Keep the MTL.txt file with the scene."
        )
    if path.stat().st_size > 10_000_000:
        raise ValueError("Landsat metadata is unexpectedly large.")
    values = {}
    for line in path.read_text(encoding="utf-8", errors="strict").splitlines():
        if "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        values[key] = value.strip('"')
    try:
        sun_elevation = float(values["SUN_ELEVATION"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"SUN_ELEVATION missing or invalid in {path}.") from exc
    sine = np.sin(np.deg2rad(sun_elevation))
    if not np.isfinite(sine) or sine <= 0:
        raise ValueError(f"Invalid solar elevation in {path}: {sun_elevation}.")
    calibration = {}
    for band in range(1, 12):
        mult = values.get(f"REFLECTANCE_MULT_BAND_{band}")
        add = values.get(f"REFLECTANCE_ADD_BAND_{band}")
        if mult is None and add is None:
            continue
        if mult is None or add is None:
            raise ValueError(f"Incomplete reflectance calibration for Landsat band {band} in {path}.")
        try:
            scale = float(mult) / sine
            offset = float(add) / sine
        except ValueError as exc:
            raise ValueError(f"Invalid reflectance calibration for Landsat band {band} in {path}.") from exc
        if not np.isfinite([scale, offset]).all() or scale <= 0:
            raise ValueError(f"Invalid reflectance scaling for Landsat band {band} in {path}.")
        calibration[f"B{band}"] = (scale, offset)
    if not calibration:
        raise ValueError(f"No reflective-band scaling coefficients found in {path}.")
    return path, calibration, sun_elevation


def _find_ancestor_file(path, name):
    for parent in Path(path).parents:
        candidate = parent / name
        if candidate.is_file():
            return candidate
    return None


def _sentinel_l1_metadata(path):
    for parent in path.parents:
        candidate = parent / "MTD_MSIL1C.xml"
        if not candidate.is_file():
            continue
        if candidate.stat().st_size > 20_000_000:
            raise ValueError("Sentinel Level-1C product metadata is unexpectedly large.")
        root = ET.parse(candidate).getroot()
        quantification, baseline, offsets = None, None, {}
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag == "QUANTIFICATION_VALUE":
                quantification = float(item.text)
            elif tag == "PROCESSING_BASELINE":
                baseline = float(item.text)
            elif tag == "RADIO_ADD_OFFSET":
                index = int(item.attrib["band_id"])
                if not 0 <= index < len(_S2_BANDS):
                    raise ValueError("Unknown Sentinel Level-1C metadata band_id.")
                offsets[_S2_BANDS[index]] = float(item.text)
        if quantification is None or not np.isfinite(quantification) or quantification <= 0:
            raise ValueError(f"Missing/invalid QUANTIFICATION_VALUE in {candidate}.")
        if not offsets and (baseline is None or baseline >= 4):
            raise ValueError(f"Missing RADIO_ADD_OFFSET for this Sentinel Level-1C baseline: {candidate}.")
        return candidate, quantification, offsets, baseline
    raise ValueError(
        f"Missing MTD_MSIL1C.xml for {path.name}. Keep the SAFE metadata with Sentinel-2 Level-1C."
    )


def _sentinel_metadata(path):
    for parent in path.parents:
        candidate = parent/"MTD_MSIL2A.xml"
        if candidate.is_file():
            if candidate.stat().st_size > 20_000_000:
                raise ValueError("Sentinel product metadata is unexpectedly large.")
            root = ET.parse(candidate).getroot()
            quantification, baseline, offsets = None, None, {}
            for item in root.iter():
                tag = item.tag.rsplit("}",1)[-1]
                if tag == "BOA_QUANTIFICATION_VALUE":
                    quantification = float(item.text)
                elif tag == "PROCESSING_BASELINE":
                    baseline = float(item.text)
                elif tag == "BOA_ADD_OFFSET":
                    index = int(item.attrib["band_id"])
                    if not 0 <= index < len(_S2_BANDS):
                        raise ValueError("Unknown Sentinel metadata band_id.")
                    offsets[_S2_BANDS[index]] = float(item.text)
            if quantification is None or not np.isfinite(quantification) or quantification <= 0:
                raise ValueError(f"Missing/invalid BOA_QUANTIFICATION_VALUE in {candidate}.")
            if not offsets and (baseline is None or baseline >= 4):
                raise ValueError(f"Missing BOA_ADD_OFFSET for this Sentinel baseline: {candidate}.")
            return candidate, quantification, offsets, baseline
    raise ValueError(f"Missing MTD_MSIL2A.xml for {path.name}. Keep the SAFE metadata or declare calibrated Band objects explicitly.")


def discover_scenes(inputs):
    """Discover Landsat Collection 2 L1/L2 and Sentinel-2 L1C/L2A bands.

    inputs is a directory, a file, or a sequence. Metadata/QA companions are
    discovered only in the selected products. Unknown band-like filenames
    raise an error instead of guessing their sensor or wavelength.
    Recognized L2SP thermal companions are ignored only when found in a
    directory alongside that product's reflectance bands; explicitly selected
    thermal files are rejected because this workflow prepares optical bands.
    Sentinel duplicates at 10/20/60 m use the finest *provided* variant.
    """
    if isinstance(inputs, (str, Path)):
        inputs = [inputs]
    paths = set();explicit=[]; selected_files=set()
    for item in inputs:
        if isinstance(item,Scene):explicit.append(item);continue
        p = Path(item).expanduser().resolve()
        if p.is_dir() and (p/'scenes.json').is_file():
            from .catalogs import load_scenes_manifest
            explicit.extend(load_scenes_manifest(p/'scenes.json'))
        elif p.is_dir():
            paths.update(q for q in p.rglob("*") if q.is_file() and q.suffix.lower() in {".tif", ".tiff", ".jp2"})
        elif p.is_file():
            if p.suffix.lower()=='.json':
                from .catalogs import load_scenes_manifest
                explicit.extend(load_scenes_manifest(p))
            else:
                paths.add(p)
                selected_files.add(p)
        else:
            raise FileNotFoundError(p)
    landsat, landsat_l1, sentinel, sentinel_l1, unknown, thermal = {}, {}, {}, {}, [], []
    for p in sorted(paths):
        match = _LANDSAT.match(p.name)
        if match:
            ident, acquired, code, qa = match.groups()
            key = (str(p.parent), ident)
            group = landsat.setdefault(key, {"files":{}, "date":acquired})
            if code or qa:
                label = (code or qa).upper()
                if label in group["files"]:
                    raise ValueError(f"Duplicate Landsat asset: {ident} {label}.")
                group["files"][label] = p
            continue
        match = _LANDSAT_L1.match(p.name)
        if match:
            ident, acquired, code, qa = match.groups()
            key = (str(p.parent), ident)
            group = landsat_l1.setdefault(key, {"files": {}, "date": acquired})
            label = (code or qa).upper()
            if label in group["files"]:
                raise ValueError(f"Duplicate Landsat Level-1 asset: {ident} {label}.")
            group["files"][label] = p
            continue
        match = _LANDSAT_THERMAL.match(p.name)
        if match:
            ident, code = match.groups()
            expected = "B10" if ident[2:4] in {"08", "09"} else "B6"
            if not code.upper().startswith("B") or code.upper() == expected:
                thermal.append((p, ident))
                continue
        match = _S2.match(p.name)
        if match:
            tile, acquired, code, resolution = match.groups()
            if _find_ancestor_file(p, "MTD_MSIL2A.xml") is not None:
                metadata = _sentinel_metadata(p)
                key = (str(metadata[0]), tile, acquired)
                group = sentinel.setdefault(key, {"files":{}, "metadata":metadata})
                code = code.upper(); candidate = (int(resolution), p)
                previous = group["files"].get(code)
                if previous and candidate[0] == previous[0] and candidate[1] != previous[1]:
                    raise ValueError(f"Duplicate Sentinel asset: {tile} {code} {resolution}m.")
                if previous is None or candidate[0] < previous[0]:
                    group["files"][code] = candidate
                continue
        match = _S2_L1.match(p.name)
        if match:
            tile, acquired, code, resolution = match.groups()
            if _find_ancestor_file(p, "MTD_MSIL1C.xml") is not None:
                metadata = _sentinel_l1_metadata(p)
                key = (str(metadata[0]), tile, acquired)
                group = sentinel_l1.setdefault(key, {"files": {}, "metadata": metadata})
                code = code.upper()
                native = int(resolution) if resolution else 999
                candidate = (native, p)
                previous = group["files"].get(code)
                if previous and candidate[0] == previous[0] and candidate[1] != previous[1]:
                    raise ValueError(f"Duplicate Sentinel Level-1C asset: {tile} {code}.")
                if previous is None or candidate[0] < previous[0]:
                    group["files"][code] = candidate
                continue
            if _S2.match(p.name):
                raise ValueError(
                    f"Missing MTD_MSIL2A.xml or MTD_MSIL1C.xml for {p.name}. "
                    "Keep the SAFE product metadata with the spectral bands."
                )
        if re.search(r"(?:^|_)(?:SR_)?B\d{1,2}[A-Z]?(?:_|\.)",p.name,re.I):
            unknown.append(p.name)
    if unknown:
        raise ValueError("Unrecognized band filenames; provide explicit Scene/Band mappings: "+", ".join(unknown[:8]))
    optical_products = {
        (directory, ident.casefold())
        for (directory, ident), group in landsat.items()
        if any(code in (LANDSAT_OLI if ident[2:4] in {"08", "09"} else LANDSAT_TM)
               for code in group["files"])
    }
    for path, ident in thermal:
        if path in selected_files or (str(path.parent), ident.casefold()) not in optical_products:
            raise ValueError(
                "Fichier thermique Landsat Level-2 non pris en charge par le prétraitement optique : "
                + path.name + ". Sélectionner les bandes de réflectance SR_B* avec leurs masques QA, "
                "ou leur dossier de produit complet. Les fichiers ST_* ne sont pas traités.")
    scenes = list(explicit)
    for (directory, ident), group in landsat_l1.items():
        sensor_code = ident[2:4]
        if sensor_code not in {"04","05","07","08","09"}:
            raise ValueError(f"Unsupported Landsat sensor {sensor_code}.")
        roles = LANDSAT_OLI if sensor_code in {"08","09"} else LANDSAT_TM
        files = group["files"]
        for quality in ("QA_PIXEL", "QA_RADSAT"):
            if quality not in files:
                candidates = [
                    p for p in Path(directory).iterdir()
                    if p.name.lower() in {
                        f"{ident}_{quality}.tif".lower(),
                        f"{ident}_{quality}.tiff".lower(),
                    }
                ]
                if len(candidates) == 1:
                    files[quality] = candidates[0]
        metadata, calibration, sun_elevation = _landsat_l1_metadata(directory, ident)
        bands = {}
        for code, path in files.items():
            if code not in roles:
                continue
            if code not in calibration:
                raise ValueError(f"Missing Landsat Level-1 reflectance calibration for {code} in {metadata}.")
            scale, offset = calibration[code]
            bands[roles[code]] = Band(
                path, scale=scale, offset=offset, nodata=0, unit="toa_reflectance"
            )
        if bands:
            acquired = group["date"]
            scenes.append(Scene(
                ident, bands, sensor=f"landsat-{int(sensor_code)}",
                acquired=f"{acquired[:4]}-{acquired[4:6]}-{acquired[6:8]}",
                level="C2-L1", quality=files.get("QA_PIXEL"),
                quality_kind="landsat_qa", saturation=files.get("QA_RADSAT"),
                notes=(f"TOA reflectance derived from Landsat Level-1 MTL; SUN_ELEVATION={sun_elevation:g}.",)
            ))
    for (directory, ident), group in landsat.items():
        sensor_code = ident[2:4]
        if sensor_code not in {"04","05","07","08","09"}:
            raise ValueError(f"Unsupported Landsat sensor {sensor_code}.")
        roles = LANDSAT_OLI if sensor_code in {"08","09"} else LANDSAT_TM
        files = group["files"]
        for quality in ("QA_PIXEL", "QA_RADSAT"):
            if quality not in files:
                candidates = [p for p in Path(directory).iterdir() if p.name.lower() in {f"{ident}_{quality}.tif".lower(),f"{ident}_{quality}.tiff".lower()}]
                if len(candidates) == 1:
                    files[quality] = candidates[0]
        bands = {roles[code]:Band(p, scale=.0000275, offset=-.2, nodata=0, unit="reflectance") for code,p in files.items() if code in roles}
        if bands:
            acquired = group["date"]
            scenes.append(Scene(ident,bands,sensor=f"landsat-{int(sensor_code)}",acquired=f"{acquired[:4]}-{acquired[4:6]}-{acquired[6:8]}",
                                level="C2-L2-SR",quality=files.get("QA_PIXEL"),quality_kind="landsat_qa",
                                saturation=files.get("QA_RADSAT")))
    for (metadata_path, tile, acquired), group in sentinel_l1.items():
        metadata, quantification, offsets, baseline = group["metadata"]
        bands = {}
        for code, (_, path) in group["files"].items():
            if code not in SENTINEL:
                continue
            if (baseline is None or baseline >= 4) and code not in offsets:
                raise ValueError(f"No RADIO_ADD_OFFSET for {code} in {metadata}.")
            bands[SENTINEL[code]] = Band(
                path,
                scale=1 / quantification,
                offset=offsets.get(code, 0) / quantification,
                nodata=0,
                unit="toa_reflectance",
            )
        if bands:
            scenes.append(Scene(
                f"{tile}_{acquired}_{metadata.parent.name}",
                bands,
                sensor="sentinel-2",
                level="L1C-TOA",
                acquired=f"{acquired[:4]}-{acquired[4:6]}-{acquired[6:8]}",
                notes=("Sentinel-2 Level-1C TOA reflectance calibrated from product metadata.",),
            ))
    for (metadata_path,tile,acquired),group in sentinel.items():
        metadata, quantification, offsets, baseline = group["metadata"]
        files = group["files"]
        if "SCL" not in files:
            candidates=[]
            for p in metadata.parent.rglob(f"{tile}_{acquired}_SCL_*"):
                match=_S2.match(p.name)
                if match:candidates.append((int(match.group(4)),p))
            if candidates:files["SCL"]=min(candidates)
        bands={}
        for code,(_,p) in files.items():
            if code not in SENTINEL:continue
            if (baseline is None or baseline >= 4) and code not in offsets:
                raise ValueError(f"No BOA offset for {code} in {metadata}.")
            bands[SENTINEL[code]]=Band(p,scale=1/quantification,offset=offsets.get(code,0)/quantification,nodata=0,unit="reflectance")
        if bands:
            scenes.append(Scene(f"{tile}_{acquired}_{metadata.parent.name}",bands,sensor="sentinel-2",level="L2A-SR",
                                acquired=f"{acquired[:4]}-{acquired[4:6]}-{acquired[6:8]}",
                                quality=files.get("SCL",(None,None))[1],quality_kind="sentinel_scl"))
    if not scenes:
        raise ValueError("No supported spectral scenes found. Use explicit Scene/Band mappings for custom data.")
    ids = [s.scene_id for s in scenes]
    if len(set(ids)) != len(ids):
        raise ValueError("The same scene appears in multiple directories; select one copy.")
    return sorted(scenes,key=lambda s: (s.acquired or "",s.scene_id))
