"""Build a portable Cartomize 1.0 presentation ZIP from verified distributions.

This creates a downloadable release asset; it does not publish to PyPI or
piwheels. Generated rasters are explicitly synthetic educational data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0"
NOTEBOOK = "tutorials/notebooks/22_demonstration_pretraitement_automatique.ipynb"
DOCUMENTS = (
    "examples/create_imagery_demo.py",
    NOTEBOOK,
    "docs/DEMONSTRATION_1.0.md",
    "docs/RELEASE_1.0.md",
    "docs/PUBLICATION.md",
    "README_PYPI.md",
    "LICENSE",
    "NOTICE.md",
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distributions(directory):
    """Require one matching wheel/source pair, including a real wheel build ID."""
    directory = Path(directory).expanduser().resolve()
    wheels, sources = sorted(directory.glob("*.whl")), sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("--dist-dir must contain exactly one wheel and one source .tar.gz.")
    wheel, source = wheels[0], sources[0]
    with zipfile.ZipFile(wheel) as archive:
        metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(f"cartomize-{VERSION}.dist-info/METADATA"))
        wheel_metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(f"cartomize-{VERSION}.dist-info/WHEEL"))
    build = wheel_metadata.get("Build", "")
    if metadata.get("Name") != "cartomize" or metadata.get("Version") != VERSION:
        raise ValueError("The presentation requires the cartomize 1.0 distribution.")
    if not re.fullmatch(r"[0-9][A-Za-z0-9_]*", build):
        raise ValueError("The presentation wheel must have an explicit build identifier.")
    if wheel.name != f"cartomize-{VERSION}-{build}-py3-none-any.whl":
        raise ValueError("Wheel filename and its version/build metadata differ.")
    if "notebook" not in metadata.get_all("Provides-Extra", []):
        raise ValueError("The presentation wheel must provide the notebook extra.")
    if source.name != f"cartomize-{VERSION}.tar.gz":
        raise ValueError("The source archive must have the same public version as the wheel.")
    with tarfile.open(source, "r:gz") as archive:
        handle = archive.extractfile(f"cartomize-{VERSION}/PKG-INFO")
        if handle is None:
            raise ValueError("Source package metadata is missing.")
        with handle:
            source_metadata = BytesParser(policy=policy.default).parsebytes(handle.read())
    if (source_metadata.get("Name"), source_metadata.get("Version")) != ("cartomize", VERSION):
        raise ValueError("Source archive metadata and wheel metadata differ.")
    return wheel, source, build, metadata.get("Requires-Python")


def make_relative(value, root):
    """Rebase generated manifest paths against that dataset's own directory."""
    if isinstance(value, dict):
        return {key: make_relative(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [make_relative(item, root) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        return Path(value).relative_to(root).as_posix()
    return value


def readme(wheel_name, build):
    return f"""# Cartomize 1.0 — Présentation

Édition consolidée, construction **{build}**. Décompresser entièrement ce ZIP,
puis ouvrir un terminal dans son dossier. Utiliser Python 3.11 ou 3.12.

## Installation et lancement sous Windows

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install \"./{wheel_name}[notebook]\"
.\\.venv\\Scripts\\python.exe -m cartomize gui
.\\.venv\\Scripts\\python.exe -m jupyter lab {NOTEBOOK}
```

Adapter `-3.12` à `-3.11` si nécessaire. Sous Linux/macOS, créer l'environnement
avec `python3 -m venv .venv`, puis utiliser `./.venv/bin/python` pour les trois
commandes suivantes. Préparer l'installation avant la séance : pip peut
télécharger les dépendances. La démonstration utilise ensuite des fichiers locaux.

## Données et parcours

**Toutes les images fournies sont pédagogiques et simulées ; ce ne sont pas des
observations satellitaires.** Dans « Prétraitement multispectral », garder le
mode automatique, sélectionner `demo_complete/scenes` et la zone souhaitée :

- `demo_complete/zone_one_scene.gpkg` : une scène suffit, puis découpage ;
- `demo_complete/zone_mosaic.gpkg` : harmonisation, mosaïque et découpage ;
- pour cette grande zone, sélectionner seulement `demo_complete/scenes/west`
  afin de montrer le diagnostic de couverture incomplète.

Les dossiers `demo_nuages`, `demo_nodata` et `demo_projections` fournissent les
variantes qualité, données absentes et projections différentes. Chaque fichier
`demo_inputs.json` utilise des chemins relatifs à son propre dossier.

Le notebook crée ses propres sorties ; conserver les dossiers `examples`,
`tutorials` et `docs` ensemble. Guide : `docs/DEMONSTRATION_1.0.md`.
Les empreintes des deux distributions figurent dans `SHA256SUMS` ; les détails
de la livraison figurent dans `delivery_manifest.json`.
"""


def build_delivery(dist_dir, output):
    wheel, source, build, requires_python = distributions(dist_dir)
    output = Path(output).expanduser().resolve()
    if output.suffix.lower() != ".zip":
        raise ValueError("--output must be a new .zip file.")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite an existing delivery: {output}")
    for relative in DOCUMENTS:
        if not (ROOT / relative).is_file():
            raise FileNotFoundError(ROOT / relative)
    spec = importlib.util.spec_from_file_location("cartomize_demo_inputs", ROOT / DOCUMENTS[0])
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    with tempfile.TemporaryDirectory(prefix="cartomize-delivery-") as temporary:
        staging = Path(temporary) / "presentation"
        staging.mkdir()
        for distribution in (wheel, source):
            shutil.copyfile(distribution, staging / distribution.name)
        for relative in DOCUMENTS:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

        scenarios = []
        for folder, options, cases in (
            ("demo_complete", {}, ["single_scene_and_clip", "mosaic_and_clip", "missing_scene_diagnostic"]),
            ("demo_nuages", {"gap": "cloud"}, ["cloud_quality_gap_diagnostic"]),
            ("demo_nodata", {"gap": "nodata"}, ["nodata_gap_diagnostic"]),
            ("demo_projections", {"different_crs": True}, ["reprojection_mosaic_and_clip"]),
        ):
            dataset = staging / folder
            manifest = make_relative(helper.create_demo(dataset, **options), dataset)
            (dataset / "demo_inputs.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            scenarios.append(dict(directory=folder, manifest=f"{folder}/demo_inputs.json",
                                  data_origin="synthetic educational data, not satellite observations",
                                  options=options, demonstration_cases=cases))

        (staging / "LISEZ_MOI.md").write_text(readme(wheel.name, build), encoding="utf-8")
        records = [dict(filename=path.name, bytes=(staging / path.name).stat().st_size,
                        sha256=sha256(staging / path.name)) for path in (wheel, source)]
        (staging / "SHA256SUMS").write_text(
            "".join(f"{record['sha256']}  {record['filename']}\n" for record in records), encoding="ascii")
        manifest = dict(schema="cartomize.demo.delivery.v1", name="cartomize", version=VERSION,
                        wheel_build=build, requires_python=requires_python,
                        created_at_utc=datetime.now(timezone.utc).isoformat(),
                        delivery_type="portable presentation archive for a GitHub release asset",
                        package_indexes_modified=False, distributions=records,
                        notebook=NOTEBOOK, synthetic_data=True, scenarios=scenarios)
        (staging / "delivery_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Finish and verify in a temporary location before publishing the ZIP.
        archive_path = Path(temporary) / "delivery.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for path in sorted(staging.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(staging).as_posix())
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("The generated ZIP failed its integrity check.")
            file_count = len(archive.namelist())
        output.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            # Exclusive creation also rejects another process creating output
            # after the initial existence check.
            with output.open("xb") as target, archive_path.open("rb") as origin:
                created = True
                shutil.copyfileobj(origin, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            if created:
                output.unlink(missing_ok=True)
            raise
    return dict(output=str(output), bytes=output.stat().st_size, sha256=sha256(output),
                version=VERSION, wheel_build=build, files=file_count,
                datasets=len(scenarios), distributions=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", required=True, type=Path,
                        help="Directory containing the built wheel and source archive")
    parser.add_argument("--output", required=True, type=Path,
                        help="New presentation ZIP; existing files are never replaced")
    args = parser.parse_args()
    print(json.dumps(build_delivery(args.dist_dir, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
