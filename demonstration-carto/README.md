# Démonstration Cartomize — automatisation sur Sentinel-2 L2A réel

Ce dossier contient une démonstration technique reproductible de Cartomize utilisant **des données Sentinel-2 Level-2A réelles**. Aucun raster synthétique ni résultat scientifique n'est inventé.

## Objectif

La démonstration montre le workflow principal :

**contrôle automatique des bandes → contrôle de couverture → découpage sur la zone d'étude → mosaïque si nécessaire → raster multibande → composite → indices choisis par l'utilisateur → statistiques.**

La classification n'est pas exécutée. Elle reste disponible comme extension si l'utilisateur fournit des ROI d'apprentissage et, pour l'évaluation, des données de validation indépendantes.

## Données

Le dossier `data/` contient les sous-jeux réels B02, B03, B04, B08, B11 et SCL téléchargés depuis Earth Search, ainsi que :

- `aoi.geojson` : fenêtre d'analyse de démonstration ;
- `source_item.json` : métadonnées STAC de la scène ;
- `scenes.json` : manifeste explicite Cartomize ;
- `provenance.json` : identifiant, date, URLs sources, couverture et SHA-256.

L'emprise est une fenêtre d'analyse située à Kinshasa ; elle n'est pas présentée comme une limite administrative.

## Notebook

Ouvrir :

`Tutoriel_Demonstration_Cartomize.ipynb`

Il exécute :

1. lecture de la provenance ;
2. contrôle des bandes, CRS, résolution et calibration ;
3. prétraitement automatique avec SCL et découpage ;
4. composite en couleurs naturelles ;
5. calcul de NDVI, NDBI et EVI ;
6. statistiques de ces indices ;
8. enregistrement du rapport `metrics.json`.

Dans le notebook, NDVI, NDBI et EVI sont calculés directement. Dans l'interface graphique, aucun indice n'est imposé : l'utilisateur choisit celui qu'il veut calculer après le prétraitement.

## Interface graphique

Le même parcours est décrit dans [GUIDE_INTERFACE.md](GUIDE_INTERFACE.md).

## Résultats vérifiés

Le dossier `results/` contient notamment :

- le raster scientifique multibande ;
- le composite couleur ;
- `indices.tif` ;
- `indices_stats.csv` ;
- `indices_overview.png` ;
- `metrics.json` ;
- `verification.json`.

## Classification

Elle est volontairement hors du parcours principal. Si l'utilisateur possède des ROI correctement étiquetés, il peut ensuite utiliser les fonctions de classification de Cartomize. Aucun score de classification n'est présenté sans données de référence indépendantes.

## Reproductibilité

Le workflow GitHub Actions `.github/workflows/demonstration-carto.yml` télécharge les données réelles, exécute le notebook puis contrôle les produits avant publication.
