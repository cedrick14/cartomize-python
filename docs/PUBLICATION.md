# Distribution et publication

Paquet : `cartomize`. Version : **1.0**. Auteur : ONDON NKOUA Cédrick Belmich.

## Version 1.0

Publication effectuée le 26 septembre 2026 depuis le commit `933f9e269ac29ab98e488faa3ac554c3269781cd`. Le [workflow de publication](https://github.com/cedrick14/cartomize-python/actions/runs/36272251727) et la [matrice de tests](https://github.com/cedrick14/cartomize-python/actions/runs/36272251506) ont réussi. Le détail des contrôles figure dans [VALIDATION.md](VALIDATION.md).

## Installation

```bash
python -m pip install "cartomize[gui]==1.0"
```

La bibliothèque requiert Python 3.11 ou une version ultérieure. L’interface graphique requiert Python 3.11 à 3.13. Les options `gui` et `notebook` sélectionnent la série Qt 6.9.

## Distributions

Distributions contrôlées par l’intégration continue et transmises à PyPI :

| Fichier | Taille (octets) | SHA256 |
|---|---:|---|
| `cartomize-1.0-py3-none-any.whl` | 335815 | `35e86b37f8088cc11701ac31101c64d57a689d6b29eebaf56475659e1897d619` |
| `cartomize-1.0.tar.gz` | 390925 | `6712af18eaf8ff2d11675904459becbd3420eb1949d912431de824a7a3646887` |

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
