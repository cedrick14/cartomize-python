"""Collect execution reports and actual window captures from matrix artifacts."""
from pathlib import Path
import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version as installed_version
import json
import os
import shutil
import xml.etree.ElementTree as ET


def summarize_xml(path):
    cases=list(ET.parse(path).getroot().iter('testcase'))
    failed=sum(case.find('failure') is not None for case in cases)
    errors=sum(case.find('error') is not None for case in cases)
    skipped=[case.find('skipped').get('message','') for case in cases if case.find('skipped') is not None]
    assert cases and not failed and not errors, str(path)
    return {'passed':len(cases)-len(skipped),'skipped':len(skipped),'failed':failed,'errors':errors,'skip_reasons':skipped}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--artifacts',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    source=Path(args.artifacts);output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    artifacts=sorted(source.glob('acceptance-*'))
    assert len(artifacts)==4
    installations={artifact:json.loads((artifact/'reports'/'installed.json').read_text(encoding='utf-8'))
                   for artifact in artifacts}
    versions={install.get('version') for install in installations.values()}
    assert len(versions)==1 and all(install.get('status')=='passed' for install in installations.values()), 'Installed runtime reports must pass and agree on one version.'
    package_version=versions.pop()
    assert isinstance(package_version,str) and package_version, 'Installed runtime version is missing.'
    try:
        local_version=installed_version('cartomize')
    except PackageNotFoundError:
        local_version=None
    if local_version is not None:
        assert local_version==package_version, 'Collector package metadata differs from the validated installed runtimes.'
    report={'version':package_version,'source_commit':os.environ['GITHUB_SHA'],
            'run_url':f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
            'environments':{}}
    for artifact in artifacts:
        name=artifact.name.removeprefix('acceptance-')
        reports=artifact/'reports'
        install=installations[artifact]
        record={'suite':summarize_xml(reports/'full-suite.xml'),
                'interface':summarize_xml(reports/'workbench.xml'),
                'installed_package':install}
        for capture in ('desktop','desktop-native'):
            info=json.loads((reports/capture/'capture.json').read_text(encoding='utf-8'))
            assert info['status']=='passed'
            record[capture]=info
            target=output/name/capture;target.mkdir(parents=True,exist_ok=True)
            for image in ('cartomize-light.png','cartomize-dark.png'):
                shutil.copy2(reports/capture/image,target/image)
        report['environments'][name]=record
    canonical=source/'acceptance-ubuntu-latest-py3.12'/'dist-validation'
    report['distribution']=[{'filename':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(canonical.iterdir()) if p.is_file()]
    (output/'validation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    lines=[f'# Cartomize {package_version} : validation exécutée','',f"Code testé : `{report['source_commit']}`",'',f"[Exécution GitHub Actions]({report['run_url']})",'',
           '| Environnement | Tests réussis | Tests spécialisés ignorés | Installation isolée |','|---|---:|---:|---|']
    for name,record in report['environments'].items():
        s=record['suite'];lines.append(f"| {name} | {s['passed']} | {s['skipped']} | Réussie |")
    lines+=['','Les images sont des captures de l’application exécutée, et non des maquettes. Les raisons des tests spécialisés ignorés figurent dans validation.json.','',
            '## Interface Windows','',
            '![Cartomize sombre](windows-latest-py3.12/desktop-native/cartomize-dark.png)','',
            '![Cartomize clair](windows-latest-py3.12/desktop-native/cartomize-light.png)','']
    (output/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
