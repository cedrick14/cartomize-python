# Cartomize

**Version 1.0**

Cartomize est une bibliothèque Python de traitement géospatial et de production cartographique. Elle associe une API, une interface graphique et des commandes pour préparer les images satellitaires, analyser les couches raster et vectorielles, puis produire des cartes et des atlas.

La bibliothèque et son interface fonctionnent sans QGIS ni ArcGIS Pro. Les passerelles vers ces logiciels sont facultatives et nécessitent leur installation pour les opérations natives. Le plugin QGIS est maintenu dans un dépôt distinct.

## Installation

La bibliothèque nécessite Python 3.11 ou une version ultérieure. L’interface graphique nécessite Python 3.11 à 3.13.

```bash
python -m pip install "cartomize==1.0.1"
```

Pour installer et ouvrir l’interface graphique :

```bash
python -m pip install "cartomize[gui]==1.0.1"
python -m cartomize gui
```

Depuis Python :

```python
import cartomize as cm

fenetre = cm.launch()
```

Dans un notebook local, installer `cartomize[notebook]==1.0.1` avec `%pip`, redémarrer le noyau, puis appeler `cm.launch()`. Voir le [guide Jupyter](docs/NOTEBOOKS.md).

## Tutoriels et projets pratiques

Le [parcours Cartomize](tutorials/README.md) présente 13 notebooks : préparation multispectrale, indices, classification, traitements vectoriels, terrain, cartes, atlas et production automatisée. Les cas Mvouti et réserve à okapis montrent comment analyser des fichiers réels avec leurs métadonnées et limites.

[Produire une première carte](tutorials/notebooks/00_premiere_carte.ipynb) · [Automatiser les livrables](tutorials/notebooks/08_automatisation.ipynb) · [Consulter le parcours complet](tutorials/README.md)

## Espace de travail

L’interface comprend deux panneaux redimensionnables. Le panneau de contrôle rassemble les outils, leurs paramètres et les commandes d’exécution. Le panneau de visualisation affiche les résultats dans des onglets intégrés : rasters, couches vectorielles, cartes PDF ou SVG, tableaux, graphiques et rapports.

Les vues permettent le zoom, le déplacement, la lecture des valeurs de pixels et l’examen des légendes et métadonnées. La comparaison juxtapose deux résultats avec des emprises géographiques liées et une échelle colorimétrique commune facultative. Le rendu relit la zone visible à la résolution adaptée, dans la limite de la résolution des données sources.

## Fonctionnalités

| Domaine | Opérations |
|---|---|
| Préparation multispectrale | Importation des bandes, calibration, masques QA/SCL, mosaïque, assemblage multibande, extraction par masque, composition colorée, export des bandes séparées |
| Analyse raster | 18 indices spectraux, algèbre raster, reclassification, statistiques focales et zonales, réductions multirasters, surfaces et matrices de changement |
| Classification | Forêts aléatoires, arbres extrêmement aléatoires, K-moyennes, validation et export des modèles |
| Analyse vectorielle | Superposition, jointure spatiale, découpage, zones tampons, dissolution, mesures et réparation géométrique |
| Terrain et réseaux | Dérivées topographiques, convolution, drainage D8, bassins versants et plus court chemin sur réseau préparé |
| Cartographie | Superposition des couches, symbologie, étiquettes, 24 maquettes, cadres multiples, légendes, échelles, atlas et exports PDF/PNG/SVG |
| Automatisation | Plans de traitement, 34 opérateurs chaînables, recettes, production en série et révision cartographique |
| Projets | Sessions JSON, archives portables CMZ, catalogue des résultats et restauration des vues |

L’assistant cartographique construit un plan à partir de l’objectif, des données et de la zone d’étude. Il vérifie les prérequis et transmet les résultats aux étapes compatibles. La [logique des traitements](docs/SIG_WORKFLOWS.md) distingue la préparation scientifique, les analyses et la composition cartographique.

## Préparer des images satellitaires

```python
import cartomize as cm

resultat = cm.process_imagery(
    ["scene_A", "scene_B"],
    "resultats/preparation",
    aoi="zone_etude.shp",
    mosaic=True,
    multiband=True,
    separate_bands=True,
    composition=("nir", "red", "green"),
)
print(resultat.manifest)
```

Les produits Landsat Collection 2 Level 2 et Sentinel-2 Level 2A sont reconnus à partir de leurs noms et métadonnées. Les autres données nécessitent une correspondance explicite des scènes et bandes. Les valeurs scientifiques du GeoTIFF multibande sont conservées séparément des valeurs étirées pour l’affichage.

## Produire une carte

```python
import cartomize as cm

carte = cm.Map(title="Localisation des villages", crs="EPSG:32733")
carte.add_layer("villages.gpkg", name="Villages", labels="nom")
carte.export("villages.pdf", dpi=300)
```

Les [exemples Python](docs/PYTHON_API.md) présentent les indices, traitements, maquettes et atlas. Les objets vectoriels retournés sont des GeoDataFrame ou GeoSeries compatibles avec GeoPandas.

## Documentation

- [Interface graphique](docs/DESKTOP.md)
- [Visualisation des résultats](docs/RESULTS_WORKSPACE.md)
- [Prétraitement multispectral](docs/IMAGERY_SELECTION.md)
- [Algèbre et indices raster](docs/RASTER_CALCULATIONS.md)
- [Chaînes de traitements](docs/PROCESSING.md)
- [Moteurs de calcul](docs/EXECUTION.md)
- [Catalogue des outils et limites](docs/TOOL_AUDIT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Tests et validation](docs/VALIDATION.md)

## Développement

```bash
python -m pip install -e ".[dev,notebook,distributed]"
python -m pytest
python -m build
python -m twine check --strict dist/*
```

Les workflows GitHub Actions contrôlent Linux et Windows avec Python 3.11 et 3.12, ainsi qu’un environnement Windows Conda et un noyau Jupyter. La validation CUDA nécessite un GPU compatible ; la passerelle ArcGIS Pro nécessite une installation licenciée. Les tests synthétiques vérifient le comportement des algorithmes sans remplacer la validation thématique des données d’une étude.

Les anomalies peuvent être signalées dans le [suivi des problèmes](https://github.com/cedrick14/cartomize-python/issues), avec la version, l’environnement et un exemple reproductible.

## Auteur et licence

Cartomize est développé par **ONDON NKOUA Cédrick Belmich**.

Code sous licence **GPL-3.0-only**. Maquettes sous licence **CC BY 4.0**, attribuées à Cartomize / ONDON NKOUA Cédrick Belmich. Voir [LICENSE](LICENSE), [NOTICE.md](NOTICE.md) et la [provenance des composants](docs/PROVENANCE.json).
