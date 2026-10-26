# Cartomize

Cartomize associe une bibliothèque Python, une interface graphique et des commandes pour le traitement géospatial et la production cartographique.

La version des sources est **1.3.0**. La bibliothèque, les cellules Jupyter, les commandes du terminal et l’interface de bureau appellent les mêmes traitements. Cette version ajoute le diagnostic de couverture des scènes et complète les modules vectoriels, les statistiques zonales, la classification, le routage et leur automatisation. Voir la [note de version](docs/RELEASE_1.3.0.md) pour les changements de comportement.

## Installation

Python 3.11 ou 3.12 est recommandé pour l’interface. QGIS et ArcGIS Pro ne sont pas nécessaires au fonctionnement de Cartomize ; seules les passerelles natives les utilisent.

Cloner les sources, puis créer un environnement dans le dossier du dépôt :

```bash
git clone https://github.com/cedrick14/cartomize-python.git
cd cartomize-python
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

### API Python et cellules Jupyter

Depuis le répertoire du projet, installer le cœur Python :

```bash
python -m pip install --upgrade pip
python -m pip install -e .
```

Les fonctions s’utilisent directement dans un script ou une cellule :

```python
import cartomize as cm
print(cm.__version__)
diagnostic = cm.audit_imagery(
    "donnees/scenes", "resultats/diagnostic_01", aoi="zone_etude.gpkg"
)
print(diagnostic.report["recommended_action"])
```

Qt est facultatif pour ces calculs. Pour installer Jupyter et le parcours exécutable depuis les mêmes sources : `python -m pip install -r tutorials/requirements.txt`. Le [guide Jupyter](docs/NOTEBOOKS.md) explique le choix du noyau et l’installation dans un environnement existant.

### Interface de bureau sans code

Depuis le même répertoire :

```bash
python -m pip install -e ".[gui]"
python -m cartomize gui
```

La commande `cartomize-desktop` ouvre également la fenêtre. Elle réunit un explorateur, un catalogue de traitements, une carte centrale, les paramètres et une console Python.

Depuis Python, après installation de l’option graphique :

```python
import cartomize as cm
fenetre = cm.launch()
```

Pour ouvrir cette fenêtre depuis un notebook local, installer `.[notebook]`, redémarrer le noyau puis appeler `cm.launch()`. Les notebooks distants peuvent utiliser l’API sans ouvrir de fenêtre native.

Les versions publiées sont indiquées sur [PyPI](https://pypi.org/project/cartomize/). La présence de 1.3.0 dans ce dépôt ne signifie pas sa publication sur cet index. Le [guide d’installation](docs/WORKBENCH.md) décrit également l’installation d’un paquet wheel.

## Espace de travail

L’explorateur ouvre les fichiers locaux et les projets Cartomize. Le catalogue classe les vingt pages de traitement par domaine et propose une recherche. Les paramètres restent à droite de la carte. Les résultats s’ouvrent dans des onglets intégrés.

Le panneau inférieur réunit la console Python, les journaux, les données chargées et le diagnostic de l’environnement. La console utilise un processus distinct pour permettre l’interruption du code sans fermer l’application. Les thèmes Clair, Sombre et Système, la taille du texte et la disposition des panneaux sont mémorisés.

Les cartes proposent zoom, déplacement, valeurs de pixels, légendes, métadonnées et comparaison avec emprises liées. Les projets enregistrés dans l’ancienne disposition restent lisibles.

## Fonctionnalités

| Domaine | Opérations |
|---|---|
| Préparation multispectrale | Diagnostic de couverture et de lacunes, proposition de scènes, calibration, masques QA/SCL, mosaïque, assemblage multibande, extraction, composition colorée, export des bandes |
| Raster | 18 indices spectraux, calculatrice, reclassification, statistiques focales, zonales et multirasters, superficies, transitions |
| Classification | Forêts aléatoires, arbres extrêmement aléatoires, K-moyennes, validation et modèles enregistrés |
| Vecteur | Sélections, superpositions, jointures, synthèses par zone, découpage, tampons, dissolution avec agrégation, mesures, reprojection, réparation, géométries dérivées, coordonnées XY et derniers relevés |
| Terrain et réseaux | Dérivées topographiques, convolution, drainage D8, bassins versants et plus court chemin |
| Cartographie | Couches, symbologie, étiquettes, 24 maquettes, cadres, légendes, échelles, atlas, PDF/PNG/SVG |
| Automatisation | Plans, 43 opérateurs chaînables, recettes et production en série |
| Projets | Sessions JSON, archives CMZ, catalogue des résultats et restauration des vues |

## Exemple Python

```python
import cartomize as cm

carte = cm.Map(title="Localisation des villages", crs="EPSG:32733")
carte.add_layer("villages.gpkg", name="Villages", labels="nom")
carte.export("villages.pdf", dpi=300)
```

Les opérations vectorielles utilisent les objets GeoPandas. Les fichiers GeoTIFF conservent leurs valeurs scientifiques séparément des réglages d’affichage.

## Couverture et procédures expertes

Le [diagnostic d’imagerie](docs/IMAGERY_AUDIT.md) mesure séparément l’emprise, la présence des bandes et les pixels utilisables après les masques. Il propose une scène unique, une mosaïque ou la recherche de scènes complémentaires. Le [tutoriel 13](tutorials/notebooks/13_diagnostic_automatique.ipynb) exécute cette décision puis le prétraitement, le NDVI et les statistiques zonales sur des données simulées.

L’[inventaire de 123 procédures](docs/EXPERT_PROCEDURES.md), également disponible en [JSON](docs/EXPERT_PROCEDURES.json), relie les procédures QGIS/ArcGIS aux fonctions réellement présentes : **11 disponibles, 48 partielles et 64 absentes**. Ces statuts portent sur des procédures expertes complètes ; ils ne sont pas un comptage des opérateurs du logiciel. Les fonctions partielles gardent leurs limites explicites, notamment pour le radar, les corrections atmosphériques de niveau 1, la validation avancée et les réseaux soumis à des restrictions.

## Projets réels

La [validation sur projets réels](docs/REAL_PROJECTS.md) reprend des analyses des tutoriels GeoPandas et Earth Lab : équipements et occupation du sol à Paris, sites miniers et aires protégées en RDC, MNT/MNS et hauteur de canopée au Colorado. Elle compare les valeurs, géométries, SCR et masques et exerce également les commandes graphiques sur les données téléchargées.

```bash
python scripts/validate_real_projects.py --data .real-project-data --output reports/real-projects
```

Le dossier de sortie contient la correspondance des étapes, les résultats numériques, la provenance des sources, les cartes et les captures de l’interface. Le rapport précise les opérations exécutées et les démonstrations externes non couvertes.

## Documentation

[Interface](docs/WORKBENCH.md), [traitements graphiques](docs/DESKTOP.md), [visualisation](docs/RESULTS_WORKSPACE.md), [API Python](docs/PYTHON_API.md), [prétraitement multispectral](docs/IMAGERY_SELECTION.md), [statistiques zonales](docs/RASTER_STATISTICS.md), [classification](docs/CLASSIFICATION.md), [chaînes de traitements](docs/PROCESSING.md), [moteurs de calcul](docs/EXECUTION.md), [projets réels](docs/REAL_PROJECTS.md).

Le [parcours de tutoriels](tutorials/README.md) contient les notebooks de préparation multispectrale, d’analyse et de production cartographique. Les [changements 1.3.0](docs/RELEASE_1.3.0.md) complètent la [refonte de l’interface 1.1](docs/RELEASE_1.1.0.md).

## Développement et validation

```bash
python -m pip install -e ".[dev,notebook,distributed]" pytest-timeout
python -m pytest
python -m build
python -m twine check --strict dist/*
python scripts/check_release.py dist
python scripts/verify_installed_release.py --wheel dist/cartomize-1.3.0-py3-none-any.whl --output reports/installed.json
```

La validation automatise les contrôles Windows et Linux, les traitements, l’interface, les projets, les exports, la console et une installation isolée du paquet construit. Les essais CUDA et QGIS natif demandent leurs environnements respectifs. Les résultats sont associés aux versions, aux données et aux commits inscrits dans les rapports.

## Auteur et licence

Développé par **ONDON NKOUA Cédrick Belmich**.

Code : **GPL-3.0-only**. Maquettes : **CC BY 4.0**, attribuées à Cartomize / ONDON NKOUA Cédrick Belmich. Voir [LICENSE](LICENSE), [NOTICE.md](NOTICE.md) et [PROVENANCE.json](docs/PROVENANCE.json).

Signaler une anomalie dans le [suivi du projet](https://github.com/cedrick14/cartomize-python/issues), avec la version, l’environnement et un exemple reproductible.
