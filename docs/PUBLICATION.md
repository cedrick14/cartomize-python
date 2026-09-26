# Distribution et publication

Paquet : `cartomize`. Version de l’application : **1.0**. Révision du paquet : **1.0.1**. Auteur : ONDON NKOUA Cédrick Belmich.

Publication du 26 septembre 2026 depuis le commit `b97e2193aee630b40740a621b1dafa625937514f`. Le [workflow de publication](https://github.com/cedrick14/cartomize-python/actions/runs/36273414966) et la [matrice de validation](https://github.com/cedrick14/cartomize-python/actions/runs/36273414787) ont réussi.

## Installation

```bash
python -m pip install "cartomize[gui]==1.0.1"
```

La bibliothèque requiert Python 3.11 ou une version ultérieure. L’interface graphique requiert Python 3.11 à 3.13. Les options `gui` et `notebook` sélectionnent la série Qt 6.9.

## Distributions

| Fichier | Taille (octets) | SHA256 |
|---|---:|---|
| `cartomize-1.0.1-py3-none-any.whl` | 335863 | `1b9db1a5585a68dd698a97f9b8d951539ffe576f720fab192d38d573777af31e` |
| `cartomize-1.0.1.tar.gz` | 390770 | `46ebc776a01c1a538d298124f8ac79c19253b1f462eba262bca547b5f49f30da` |

Les fichiers et leurs empreintes SHA256 sont disponibles sur [PyPI](https://pypi.org/project/cartomize/1.0.1/#files).

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
