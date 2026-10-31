# Démonstration avec l'interface graphique

Ce guide utilise les mêmes bandes Sentinel-2 L2A réelles que le notebook. La démonstration est centrée sur **l'automatisation**, pas sur la classification.

## 1. Démarrer Cartomize

```cmd
python -m cartomize gui
```

## 2. Prétraitement automatique

Ouvrir **Prétraitement multispectral**.

- Source : `demonstration-carto/data`.
- Zone d'étude : `demonstration-carto/data/aoi.geojson`.
- Bandes : `blue`, `green`, `red`, `nir`.
- Masque de qualité : activé, avec la couche SCL Sentinel-2.
- Seuil de couverture : **95 %**.
- Multibande : activé.
- Bandes séparées : activé.
- Composition : **natural**.
- Sortie : choisir un nouveau dossier vide.

Cartomize contrôle les fichiers, les bandes, les projections, la résolution, la couverture réellement observée et la qualité. Il retient les scènes utiles, découpe sur la zone d'étude et **mosaïque automatiquement si plusieurs scènes complémentaires sont nécessaires**.

Pour la scène validée dans ce dossier, une seule scène suffit : le rapport indique donc `mosaic = false`. Ne pas annoncer une mosaïque si elle n'a pas été nécessaire.

## 3. Montrer le diagnostic

Afficher ou ouvrir le rapport de couverture avant traitement.

Les informations à commenter sont :

- scène(s) retenue(s) ;
- bandes disponibles ;
- couverture utile ;
- zones manquantes éventuelles ;
- projection et résolution de sortie ;
- décision : une scène suffisante ou mosaïque nécessaire.

## 4. Composite de bandes

Ouvrir le produit **composition colorée** généré automatiquement.

Le composite sert à la visualisation. Les calculs scientifiques utilisent le **raster multibande calibré**, pas l'image d'affichage.

## 5. Indices spectraux : choix de l'utilisateur

Ouvrir **Indices spectraux** et sélectionner un ou plusieurs indices compatibles avec les bandes disponibles.

Avec B02, B03, B04 et B08, le tutoriel a vérifié notamment :

- NDVI ;
- NDWI ;
- EVI ;
- EVI2 ;
- SAVI ;
- OSAVI ;
- MSAVI ;
- GNDVI ;
- ARVI ;
- VARI ;
- SR.

Un indice qui exige une bande absente, par exemple SWIR ou red-edge, ne doit pas être calculé en inventant une correspondance. Il faut d'abord disposer de la bande requise.

## 6. Statistiques

Les statistiques sont calculées sur les pixels valides de chaque indice : nombre de pixels, minimum, maximum, moyenne, écart-type et quantiles.

Le notebook enregistre ces valeurs dans :

`demonstration-carto/results/indices_stats.csv`

et les valeurs complètes de l'exécution dans :

`demonstration-carto/results/metrics.json`.

## 7. Classification — extension optionnelle avec ROI

La classification n'est pas une étape de la démonstration principale.

Si un utilisateur souhaite continuer :

1. créer ses régions d'intérêt (ROI) ;
2. attribuer une classe aux ROI ;
3. exporter les ROI ;
4. fournir ces échantillons à Cartomize ;
5. lancer l'apprentissage et la classification ;
6. utiliser, pour l'évaluation, un jeu de validation indépendant.

Sans ROI / vérité terrain, ne pas présenter une classification supervisée comme résultat scientifique.

## 8. Fin de la démonstration

La séquence à montrer est donc :

**bandes → contrôle automatique → couverture → découpage → mosaïque si nécessaire → multibande → composite → choix d'indices → statistiques → export.**

La mise en page Cartomize n'est pas utilisée dans cette démonstration.
