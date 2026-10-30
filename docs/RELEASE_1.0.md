# Cartomize 1.0

Cartomize associe une bibliothèque Python et une application de bureau pour l’analyse géospatiale et la production cartographique. Les scripts Python, les notebooks Jupyter et l’interface graphique utilisent les mêmes fonctions de traitement.

## Analyse et cartographie

Les traitements couvrent les données raster et vectorielles : indices spectraux, classification, statistiques zonales, reprojection, validation des géométries, sélection spatiale, superposition, jointure et zones tampons. La préparation des images satellites comprend le contrôle de couverture, l’alignement des grilles, la mosaïque et le découpage sur une zone d’étude.

Les mises en page associent couches, symbologie, étiquettes, légendes et échelles. Les cartes peuvent être exportées en PDF, PNG et SVG, individuellement, en atlas ou par lot.

## Interface de bureau

Les panneaux et les vues de résultat sont déplaçables, détachables et redimensionnables. Des repères guident leur placement ; les fenêtres peuvent être ancrées sur un côté ou regroupées en onglets. Les paramètres, les cartes et leur disposition sont mémorisés.

Les descriptions techniques sont accessibles par le bouton **Aide**. Les thèmes clair, sombre et système ainsi que la taille du texte sont réglables dans l’application.

## Installation

Python 3.11 ou ultérieur est nécessaire. Python 3.11 ou 3.12 est recommandé pour l’interface.

```bash
python -m pip install "cartomize[gui]"
python -m cartomize gui
```

L’option `notebook` ajoute JupyterLab et son noyau Python. Les fichiers joints à cette release comprennent le wheel installable, les sources et un dossier d’exemples avec des données synthétiques.

## Documentation

Consulter la [documentation](https://github.com/cedrick14/cartomize-python/blob/main/docs/README.md), l’[API Python](https://github.com/cedrick14/cartomize-python/blob/main/docs/PYTHON_API.md) et le [guide de l’interface](https://github.com/cedrick14/cartomize-python/blob/main/docs/WORKBENCH.md).

## Licence

Code : **GPL-3.0-only**. Maquettes cartographiques originales : **CC BY 4.0**, attribuées à Cartomize / ONDON NKOUA Cédrick Belmich.
