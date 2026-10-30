# Cartomize

Cartomize est une bibliothèque Python et une application de bureau pour l’analyse géospatiale et la production cartographique. Elle réunit les traitements raster et vectoriels, la préparation d’images satellites et la mise en page de cartes. Ses fonctions s’utilisent dans des scripts Python, des notebooks Jupyter ou depuis l’interface graphique.

## Fonctionnalités

Les outils raster couvrent les indices spectraux, les calculs entre rasters, la classification, l’analyse du terrain et les statistiques zonales. La préparation des images satellites comprend le contrôle de couverture, l’alignement des grilles, la mosaïque, le découpage et les compositions colorées. Les outils vectoriels proposent reprojection, validation des géométries, sélection spatiale, superposition, jointure, zones tampons et bilans de superficies.

Les mises en page associent couches raster et vectorielles, symbologie, étiquettes, légendes, échelles et cadres cartographiques. Les cartes sont exportables en PDF, PNG et SVG, sous forme individuelle, en atlas ou par lot. Les plans de traitement et les projets enregistrés permettent de réutiliser les analyses.

L’application de bureau dispose de panneaux déplaçables, de vues de résultat détachables et de dispositions mémorisées. Elle utilise les mêmes traitements que l’API Python. Les formats courants comprennent GeoTIFF, GeoPackage, GeoJSON et Shapefile. Cartomize s’appuie sur NumPy, GeoPandas, Rasterio, pyproj et Matplotlib.

## Installation

Cartomize nécessite Python 3.11 ou ultérieur. Python 3.11 ou 3.12 est recommandé pour l’application de bureau.

Installer la bibliothèque Python :

```bash
python -m pip install cartomize
```

Installer et ouvrir l’interface graphique :

```bash
python -m pip install "cartomize[gui]"
python -m cartomize gui
```

L’option `notebook` ajoute JupyterLab, un noyau Python et les composants de l’interface :

```bash
python -m pip install "cartomize[notebook]"
python -m jupyter lab
```

Les moteurs de calcul optionnels sont présentés dans le [guide d’exécution](docs/EXECUTION.md).

## Exemple

Créer une carte à partir d’une couche vectorielle et l’exporter en PDF :

```python
import cartomize as cm

carte = cm.Map(title="Zone d’étude", crs="EPSG:32733")
carte.add_layer("zone_etude.gpkg", name="Limite")
carte.export("zone_etude.pdf")
```

## Documentation et assistance

Consulter l’[API Python](docs/PYTHON_API.md), le [guide de l’interface](docs/WORKBENCH.md) et le [guide de préparation des images satellites](docs/IMAGERY_AUTOMATIC.md) pour les usages et les paramètres. Les anomalies peuvent être signalées dans le [suivi du projet](https://github.com/cedrick14/cartomize-python/issues), avec un exemple reproductible et les informations sur l’environnement utilisé.

## Licence

Développé par **ONDON NKOUA Cédrick Belmich**.

Le code est distribué sous **GPL-3.0-only**. Les maquettes cartographiques originales sont sous **CC BY 4.0**, attribuées à Cartomize / ONDON NKOUA Cédrick Belmich. Voir [LICENSE](LICENSE) et [NOTICE.md](NOTICE.md).
