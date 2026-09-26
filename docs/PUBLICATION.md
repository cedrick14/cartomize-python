# Distribution et publication

Paquet : `cartomize`. Version : **1.0**. Auteur : ONDON NKOUA Cédrick Belmich.

## Installation

```bash
python -m pip install "cartomize[gui]==1.0"
```

La bibliothèque requiert Python 3.11 ou une version ultérieure. L’interface graphique requiert Python 3.11 à 3.13. Les options `gui` et `notebook` sélectionnent la série Qt 6.9.

## Distributions

- `cartomize-1.0-py3-none-any.whl`
- `cartomize-1.0.tar.gz`

Les fichiers et leurs empreintes SHA256 sont disponibles sur [PyPI](https://pypi.org/project/cartomize/1.0/#files).

## Construction

```bash
python -m pip install -e ".[dev,notebook,distributed]"
python -m pytest
python -m build --outdir pypi-dist
python -m twine check --strict pypi-dist/*
python scripts/check_release.py pypi-dist
```

## Intégration continue

Le workflow `.github/workflows/pypi-publish.yml` construit les distributions et exécute les contrôles Linux et Windows Conda. La publication dépend de la réussite de ces contrôles. La matrice `.github/workflows/python-library.yml` vérifie Linux et Windows avec Python 3.11 et 3.12.

La publication utilise un éditeur de confiance PyPI avec GitHub Actions et l’environnement `pypi`. Elle est déclenchée par un commit de publication contenant `[publish pypi]`, un tag de version compatible avec le workflow ou une exécution manuelle configurée pour PyPI. Le numéro de version du paquet et celui de `cartomize.__version__` doivent correspondre.

Chaque distribution PyPI est immuable. Une modification publiée nécessite un nouveau numéro de version.
