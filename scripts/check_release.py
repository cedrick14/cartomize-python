"""Validate package metadata, complete desktop contents and release checksums."""
from pathlib import Path
from email.parser import BytesParser
from email import policy
from configparser import ConfigParser
import hashlib
import json
import os
import sys
import tarfile
import tomllib
import zipfile

root=Path(__file__).resolve().parents[1]
project=tomllib.loads((root/'pyproject.toml').read_text())['project']
name,version=project['name'],project['version']
build_config = ConfigParser()
build_config.read(root / 'setup.cfg')
wheel_build = build_config.get('bdist_wheel', 'build_number', fallback='').strip()
wheel_name = f'{name}-{version}' + (f'-{wheel_build}' if wheel_build else '') + '-py3-none-any.whl'
required_modules=(
    'desktop','desktop_imagery','imagery_pipeline','viewer_data','desktop_canvas',
    'desktop_tables','desktop_results','desktop_workbench','desktop_theme',
    'desktop_console','desktop_kernel','desktop_explorer','desktop_session',
    'desktop_tools','desktop_processing','imagery_audit','imagery','scenes','quality',
    'nodata','raster','relations','vector','vector_workflows','classification',
    'routing','processing','storage','cli','imagery_automatic','catalogs','automation','workflow',
    'vector_quality','vector_quality_result','vector_topology','vector_duplicates','desktop_vector_quality',
    'vector_reprojection','desktop_reprojection',
    'vector_merge','vector_io','desktop_merge',
    'vector_conversion','raster_conversion','desktop_conversion',
    'vector_selection','desktop_selection',
    'vector_tabulation','desktop_tabulation',
    'vector_rings','desktop_rings',
)
directory=Path(sys.argv[1]) if len(sys.argv)>1 else root/'pypi-dist'
expected={wheel_name,f'{name}-{version}.tar.gz'}
assert {p.name for p in directory.iterdir() if p.is_file()}==expected, 'The distribution directory must contain only the current wheel and source archive.'
if os.environ.get('GITHUB_REF_TYPE')=='tag':
    assert os.environ['GITHUB_REF_NAME']==f'python-v{version}', 'Release tag and package version differ.'
wheel=directory/wheel_name
with zipfile.ZipFile(wheel) as z:
    metadata=BytesParser(policy=policy.default).parsebytes(z.read(f'{name}-{version}.dist-info/METADATA'))
    assert metadata['Name']==name and metadata['Version']==version
    wheel_metadata=BytesParser(policy=policy.default).parsebytes(z.read(f'{name}-{version}.dist-info/WHEEL'))
    assert wheel_metadata.get('Build', '') == wheel_build, 'Wheel build identifier differs from setup.cfg.'
    assert metadata['License-Expression']=='GPL-3.0-only'
    assert metadata['Requires-Python']=='>=3.11'
    assert metadata['Description-Content-Type']=='text/markdown'
    assert {'gui','notebook','distributed','gpu'}<=set(metadata.get_all('Provides-Extra'))
    assert 'ONDON NKOUA' in metadata['Author']
    urls=dict(value.split(', ',1) for value in metadata.get_all('Project-URL',[]))
    assert urls==project['urls'], 'Distribution project links differ from pyproject.toml.'
    assert urls['Repository']=='https://github.com/cedrick14/cartomize-python'
    assert '## Installation' in metadata.get_payload()
    names=set(z.namelist())
    for module in required_modules:
        assert f'cartomize/{module}.py' in names, f'Missing wheel module: {module}'
    assert 'cartomize/assets/cartomize.png' in names
    source=z.read('cartomize/__init__.py').decode('utf-8')
    assert f'__version__ = "{version}"' in source, 'Runtime and package versions differ.'
with tarfile.open(directory/f'{name}-{version}.tar.gz') as archive:
    names=set(archive.getnames())
    for module in required_modules:
        assert f'{name}-{version}/src/cartomize/{module}.py' in names, f'Missing source archive module: {module}'
    for file in ('README_PYPI.md','LICENSE','NOTICE.md','pyproject.toml','setup.cfg',
                 'docs/RELEASE_1.0.md','docs/DEMONSTRATION_1.0.md',
                 'examples/create_imagery_demo.py','scripts/stage_pypi_upload.py',
                 'tests/test_imagery_demo_workflow.py',
                 'tutorials/notebooks/22_demonstration_pretraitement_automatique.ipynb',
                 'tests/test_imagery_pipeline.py',
                 'tests/test_startup.py','tests/test_results_workspace.py','tests/test_desktop_workbench.py',
                 'tests/test_workbench_viewports.py','docs/RESULTS_WORKSPACE.md','docs/WORKBENCH.md',
                 'tests/test_imagery_audit.py','tests/test_raster_integrity.py',
                 'tests/test_vector_workflows.py','tests/test_vector_data_integrity.py',
                 'tests/test_classification_integrity.py','tests/test_routing_integrity.py',
                 'docs/IMAGERY_AUDIT.md','docs/RASTER_STATISTICS.md','docs/CLASSIFICATION.md',
                 'docs/IMAGERY_AUTOMATIC.md','docs/RELEASE_1.4.0.md','docs/VALIDATION_1.4.0.json',
                 'tests/test_catalog_quality.py','tests/test_imagery_automatic.py',
                 'tests/test_imagery_automatic_interfaces.py','tests/test_desktop_imagery_automatic.py',
                 'tests/test_real_sentinel.py','tests/data/sentinel2_mvouti/scenes.json',
                 'tests/data/sentinel2_mvouti/provenance.json','tests/data/sentinel2_mvouti/README.md',
                 'tests/data/sentinel2_mvouti/red.tif','tests/data/sentinel2_mvouti/nir.tif',
                 'tests/data/sentinel2_mvouti/scl.tif','tests/data/sentinel2_mvouti/reference/red.tif',
                 'tests/data/sentinel2_mvouti/reference/nir.tif',
                 'docs/EXPERT_PROCEDURES.md','docs/EXPERT_PROCEDURES.json',
                 'docs/VECTOR_QUALITY.md','docs/RELEASE_1.5.0.md','docs/VALIDATION_1.5.0.json',
                 'docs/VALIDATION_M08_REAL.json','tests/test_vector_quality.py',
                 'tests/test_vector_topology.py','tests/test_vector_duplicates.py',
                 'tests/test_vector_quality_interfaces.py','scripts/validate_vector_quality_real.py',
                 'docs/VECTOR_REPROJECTION.md','docs/RELEASE_1.6.0.md','docs/VALIDATION_1.6.0.json',
                 'docs/VALIDATION_M09_REAL.json','tests/test_vector_reprojection.py',
                 'tests/test_vector_reprojection_interfaces.py','tests/test_desktop_reprojection.py',
                 'scripts/validate_vector_reprojection_real.py',
                 'docs/VECTOR_MERGE.md','docs/RELEASE_1.7.0.md','docs/VALIDATION_1.7.0.json',
                 'docs/VALIDATION_M10_REAL.json','tests/test_vector_merge.py',
                 'tests/test_vector_merge_interfaces.py','tests/test_desktop_merge.py','tests/test_vector_io.py',
                 'scripts/validate_vector_merge_real.py',
                 'docs/G01_GEOMETRY_QUALITY.md','docs/RELEASE_1.8.0.md','docs/VALIDATION_1.8.0.json',
                 'docs/VALIDATION_G01_REAL.json','scripts/validate_g01_real.py',
                 'tests/test_g01_precision.py','tests/test_g01_publication.py','tests/test_g01_desktop.py','tests/test_g01_interfaces.py',
                 'tutorials/course.py','tutorials/requirements.txt','tutorials/scripts/execute.py',
                 'tutorials/notebooks/15_reprojection_vectorielle_par_lot.ipynb',
                 'tutorials/notebooks/16_harmonisation_fusion_vectorielle.ipynb',
                 'tutorials/notebooks/17_g01_controle_reparation_geometries.ipynb',
                 'tutorials/notebooks/18_conversion_conditionnement.ipynb',
                 'docs/DATA_CONVERSION.md','docs/RELEASE_1.9.0.md','docs/VALIDATION_1.9.0.json',
                 'tests/test_vector_conversion.py','tests/test_raster_conversion.py',
                 'tests/test_conversion_interfaces.py','tests/test_desktop_conversion.py',
                 'scripts/validate_data_conversion_real.py','docs/VALIDATION_G06_REAL.json',
                 'docs/VECTOR_SELECTION.md','docs/RELEASE_1.10.0.md','docs/VALIDATION_1.10.0.json',
                 'docs/VALIDATION_G07_REAL.json','scripts/validate_vector_selection_real.py',
                 'tests/test_vector_selection.py','tests/test_vector_selection_interfaces.py',
                 'tests/test_g07_desktop.py','tests/test_g07_real_oracle.py',
                 'tutorials/notebooks/19_extraction_attributaire_spatiale.ipynb',
                 'docs/VECTOR_TABULATION.md','docs/RELEASE_1.11.0.md','docs/VALIDATION_1.11.0.json',
                 'docs/VALIDATION_G09_REAL.json','scripts/validate_vector_tabulation_real.py',
                 'tests/test_vector_tabulation.py','tests/test_vector_tabulation_interfaces.py',
                 'tests/test_g09_desktop.py','tests/test_g09_real_oracle.py',
                 'tutorials/notebooks/20_table_croisee_surfaces.ipynb',
                 'docs/VECTOR_RINGS.md','docs/RELEASE_1.12.0.md','docs/VALIDATION_1.12.0.json',
                 'docs/VALIDATION_G12_REAL.json','scripts/validate_vector_rings_real.py',
                 'tests/test_vector_rings.py','tests/test_vector_rings_interfaces.py',
                 'tests/test_g12_desktop.py','tests/test_g12_real_oracle.py',
                 'tutorials/notebooks/21_anneaux_distance.ipynb',
                 'scripts/check_startup.py','scripts/check_release.py','scripts/verify_installed_release.py'):
        assert f'{name}-{version}/{file}' in names,file
print(json.dumps({'name':name,'version':version,'files':[
    {'filename':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    for p in sorted(directory.iterdir()) if p.is_file()]},indent=2))
