"""Stage publishable files while retaining the complete delivery separately.

The historical cartomize-1.0.tar.gz name is permanently reserved on PyPI.
The consolidated 1.0 edition can therefore upload only its uniquely built wheel,
after the owner has resolved the existing release through PyPI's authenticated UI.
This script does not contact PyPI, remove a release or perform an upload.
"""
from email import policy
from email.parser import BytesParser
from pathlib import Path
import argparse
import json
import shutil
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    wheels = sorted(args.source.glob('*.whl'))
    if len(wheels) != 1:
        parser.error('The validated delivery must contain exactly one wheel.')
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(name for name in archive.namelist()
                             if name.endswith('.dist-info/METADATA'))
        metadata = BytesParser(policy=policy.default).parsebytes(archive.read(metadata_path))
        wheel_metadata = BytesParser(policy=policy.default).parsebytes(
            archive.read(metadata_path.removesuffix('METADATA') + 'WHEEL'))
    if metadata['Name'] != 'cartomize':
        parser.error('The distribution is not Cartomize.')
    version = metadata['Version']
    if version == '1.0':
        if not wheel_metadata.get('Build'):
            parser.error('The consolidated 1.0 wheel must have a unique build identifier.')
        selected = [wheel]
        reason = 'wheel-only: the historical 1.0 source filename cannot be reused on PyPI'
    else:
        source_archive = args.source / f'cartomize-{version}.tar.gz'
        if not source_archive.is_file():
            parser.error('The matching source archive is missing.')
        selected = [wheel, source_archive]
        reason = 'wheel and source archive'
    if args.destination.exists() and any(args.destination.iterdir()):
        parser.error('The publication destination must be empty; no files are removed automatically.')
    args.destination.mkdir(parents=True, exist_ok=True)
    for path in selected:
        shutil.copy2(path, args.destination / path.name)
    print(json.dumps({'version': version, 'files': [path.name for path in selected],
                      'selection': reason, 'uploaded': False}, indent=2))


if __name__ == '__main__':
    main()
