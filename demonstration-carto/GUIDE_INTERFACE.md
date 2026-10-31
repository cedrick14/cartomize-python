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
- Bandes : `blue`, `green`, `red`, `nir`, `swir1`.
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

Après le prétraitement et la création du composite, ouvrir **Indices spectraux**.

L'interface **ne calcule aucun indice automatiquement**. L'utilisateur choisit lui-même dans la liste l'indice qu'il souhaite produire, par exemple :

- NDVI ;
- NDBI ;
- EVI ;
- NDWI ;
- SAVI ;
- ou tout autre indice compatible avec les bandes réellement présentes.

Il sélectionne l'indice, choisit le fichier de sortie, puis clique **Exécuter**.

Cartomize vérifie les bandes nécessaires. Par exemple, NDBI nécessite NIR + SWIR1 ; c'est pour cela que B11 est incluse dans ce jeu de démonstration.

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

**bandes → contrôle automatique → couverture → découpage → mosaïque si nécessaire → multibande → composite → choix manuel d’un indice → exécution → résultat → statistiques → export.**

La mise en page Cartomize n'est pas utilisée dans cette démonstration.
