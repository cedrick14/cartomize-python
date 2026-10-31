# Démonstration avec l'interface graphique

Ce guide utilise exactement les mêmes fichiers réels que le notebook.

## 1. Démarrer Cartomize

```cmd
python -m cartomize gui
```

## 2. Prétraitement automatique

Ouvrir **Prétraitement multispectral**.

- Mode : **Automatique : contrôler et préparer**.
- Source : sélectionner le dossier `demonstration-carto/data` ; le fichier `scenes.json` décrit explicitement la scène et les bandes.
- Zone d'étude : `demonstration-carto/data/aoi.geojson`.
- Bandes : `blue`, `green`, `red`, `nir`.
- Masque de qualité : activé. La couche SCL est déclarée comme `sentinel_scl`.
- Seuil de couverture : **95 %**.
- Multibande : activé.
- Bandes séparées : activé.
- Composition : **natural**.
- Sortie : choisir un nouveau dossier vide.

Cliquer d'abord sur **Diagnostiquer la couverture** si l'on veut montrer le contrôle, puis sur **Exécuter**.

À montrer aux participants : identifiant de scène, couverture utile mesurée, résolution, projection, bandes retenues et rapport de traitement.

## 3. Indices spectraux

Ouvrir **Indices spectraux**.

Utiliser le **raster scientifique multibande** produit par l'étape précédente, et non la composition RVB.

Calculer :

- NDVI ;
- NDWI ;
- EVI.

Le fichier produit dans le notebook est `results/indices.tif`, avec une bande par indice.

## 4. Statistiques zonales

Ouvrir **Statistiques zonales**.

- Raster : `indices.tif`.
- Bande : 1 pour NDVI.
- Zones : `data/aoi.geojson`.

Comparer les valeurs affichées aux résultats enregistrés dans `results/metrics.json`.

## 5. Couche SCL

La couche `data/SCL.tif` est une donnée Sentinel-2 L2A. Le tutoriel calcule la proportion réelle de chaque code SCL dans l'emprise. Les nuages, ombres et autres classes rejetées ne sont pas renommés en occupation du sol.

## 6. Classification

Ne pas présenter de **classification supervisée** pendant cette démonstration : aucun jeu indépendant d'apprentissage/validation n'est fourni avec cette scène.

La **classification non supervisée** peut être montrée comme regroupement spectral si nécessaire, mais les groupes ne doivent pas recevoir de noms thématiques sans interprétation et validation.

## 7. Sortie vers les SIG

Pour la démonstration de demain, terminer avec les produits vérifiés : GeoTIFF, GeoJSON/GeoPackage et CSV. La mise en page Cartomize n'est pas utilisée. Les cartes finales peuvent être montées dans QGIS, ArcGIS Pro ou CartoMAP.

La création/échange complet de projets QGIS/ArcGIS sera validé séparément avant d'être présenté comme fonction automatique.
