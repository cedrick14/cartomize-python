# Cartomize

Cartomize associe une bibliothèque Python, une interface graphique et des commandes pour le traitement géospatial et la production cartographique.

La version 1.1 introduit un espace de travail à panneaux : explorateur, catalogue des traitements, carte centrale, paramètres et console Python. Les outils raster, vectoriels, de classification, de terrain et de mise en page restent accessibles par l’API.

## Installation

Python 3.11 ou 3.12 est recommandé pour l’interface. QGIS et ArcGIS Pro ne sont pas nécessaires au fonctionnement de Cartomize ; seules les passerelles natives les utilisent.

Pour installer les sources de ce dépôt :

```bash
python -m venv .venv
```

Activer l’environnement sous Windows :

```powershell
.venv\Scripts\Activate.ps1
```

Sous Linux ou macOS :

```bash
source .venv/bin/activate
```

Depuis le répertoire du projet :

```bash
python -m pip install --upgrade pip
python -m pip install ".[gui]"
python -m cartomize gui
```

Les versions publiées sont indiquées sur [PyPI](https://pypi.org/project/cartomize/). Une version présente dans le dépôt n’est pas nécessairement déjà publiée sur cet index. Le [guide d’installation](docs/WORKBENCH.md) décrit également l’installation d’un paquet wheel.

Depuis Python :

```python
import cartomize as cm
fenetre = cm.launch()
```

Dans un notebook local, installer l’option `notebook` à la place de `gui`, redémarrer le noyau et appeler `cm.launch()`. Voir [Jupyter](docs/NOTEBOOKS.md).

## Espace de travail

L’explorateur ouvre les fichiers locaux et les projets Cartomize. Le catalogue classe les vingt pages de traitement par domaine et propose une recherche. Les paramètres restent à droite de la carte. Les résultats s’ouvrent dans des onglets intégrés.

Le panneau inférieur réunit la console Python, les journaux, les données chargées et le diagnostic de l’environnement. La console utilise un processus distinct pour permettre l’interruption du code sans fermer l’application. Les thèmes Clair, Sombre et Système, la taille du texte et la disposition des panneaux sont mémorisés.

Les cartes proposent zoom, déplacement, valeurs de pixels, légendes, métadonnées et comparaison avec emprises liées. Les projets enregistrés dans l’ancienne disposition restent lisibles.

## Fonctionnalités

| Domaine | Opérations |
|---|---|
| Préparation multispectrale | Calibration, masques QA/SCL, mosaïque, assemblage multibande, extraction, composition colorée, export des bandes |
| Raster | 18 indices spectraux, calculatrice, reclassification, statistiques focales, zonales et multirasters, superficies, transitions |
| Classification | Forêts aléatoires, arbres extrêmement aléatoires, K-moyennes, validation et modèles enregistrés |
| Vecteur | Superposition, jointure spatiale, découpage, tampons, dissolution, mesures, reprojection et réparation |
| Terrain et réseaux | Dérivées topographiques, convolution, drainage D8, bassins versants et plus court chemin |
| Cartographie | Couches, symbologie, étiquettes, 24 maquettes, cadres, légendes, échelles, atlas, PDF/PNG/SVG |
| Automatisation | Plans, 34 opérateurs chaînables, recettes et production en série |
| Projets | Sessions JSON, archives CMZ, catalogue des résultats et restauration des vues |

## Exemple Python

```python
import cartomize as cm

carte = cm.Map(title="Localisation des villages", crs="EPSG:32733")
carte.add_layer("villages.gpkg", name="Villages", labels="nom")
carte.export("villages.pdf", dpi=300)
```

Les opérations vectorielles utilisent les objets GeoPandas. Les fichiers GeoTIFF conservent leurs valeurs scientifiques séparément des réglages d’affichage.

## Documentation

[Interface 1.1](docs/WORKBENCH.md), [traitements graphiques](docs/DESKTOP.md), [visualisation](docs/RESULTS_WORKSPACE.md), [API Python](docs/PYTHON_API.md), [prétraitement multispectral](docs/IMAGERY_SELECTION.md), [chaînes de traitements](docs/PROCESSING.md), [moteurs de calcul](docs/EXECUTION.md).

Le [parcours de tutoriels](tutorials/README.md) contient les notebooks de préparation multispectrale, d’analyse et de production cartographique. La [note de version](docs/RELEASE_1.1.0.md) présente les modifications de l’interface.

## Développement et validation

```bash
python -m pip install -e ".[dev,notebook,distributed]" pytest-timeout
python -m pytest
python -m build
python -m twine check --strict dist/*
python scripts/check_release.py dist
python scripts/verify_installed_release.py --wheel dist/cartomize-1.1.0-py3-none-any.whl --output reports/installed.json
```

La validation utilise Windows et Linux avec Python 3.11 et 3.12. Elle couvre les traitements, l’interface, les projets, les exports, la console et une installation isolée du paquet construit. Les essais CUDA et QGIS natif demandent leurs environnements respectifs.

## Auteur et licence

Développé par **ONDON NKOUA Cédrick Belmich**.

Code : **GPL-3.0-only**. Maquettes : **CC BY 4.0**, attribuées à Cartomize / ONDON NKOUA Cédrick Belmich. Voir [LICENSE](LICENSE), [NOTICE.md](NOTICE.md) et [PROVENANCE.json](docs/PROVENANCE.json).

Signaler une anomalie dans le [suivi du projet](https://github.com/cedrick14/cartomize-python/issues), avec la version, l’environnement et un exemple reproductible.
