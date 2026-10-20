# Analyses sur les données des tutoriels GeoPandas et Earth Lab

## Sources et reproduction

Le programme `scripts/validate_real_projects.py` compare Cartomize à des calculs de référence sur des fichiers de formation publiés. Il télécharge les données, exécute les analyses, utilise les commandes graphiques, vérifie les résultats et produit les rapports dans `reports/real-projects`.

Le tutoriel vectoriel est [geopandas-tutorial](https://github.com/jorisvandenbossche/geopandas-tutorial), de Joris Van den Bossche, fixé au commit `72c7f3168e1e4e257caf84eb7b3fcaa47ade09c0`. Les données raster proviennent du jeu [Colorado Flood d’Earth Lab](https://ndownloader.figshare.com/files/16371473), utilisé dans le [cours de traitement raster](https://www.earthdatascience.org/courses/use-data-open-source-python/intro-raster-data-python/raster-data-processing/crop-raster-data-with-shapefile-in-python/).

```bash
python -m pip install -e ".[dev,notebook,distributed]"
python scripts/validate_real_projects.py --data .real-project-data --output reports/real-projects
python -m pytest
```

Les données originales ne sont pas ajoutées au dépôt. Le manifeste conserve leurs URLs, tailles et empreintes SHA-256. Les empreintes des fichiers sources sont contrôlées avant et après les traitements. Les notebooks externes sont lus pour identifier les exercices ; leur code n’est pas exécuté automatiquement.

## Correspondance avec le tutoriel GeoPandas

| Chapitre ou projet | Étapes reproduites | Accès Cartomize |
|---|---|---|
| 01. Introduction | Shapefile, GeoJSON, GeoPackage, sélection de lignes, jointure attributaire, coordonnées XY | Explorateur, Traitements vectoriels, API |
| 02. Systèmes de coordonnées | Reprojection, superficies et périmètres, unités métriques | Traitements vectoriels, API |
| 03. Relations spatiales | Prédicats, sélection spatiale, jointure spatiale, comptage et somme par zone, plus proche voisin | Traitements vectoriels, API |
| 04. Opérations géométriques | Tampon, intersection, découpage, dissolution, centroïde, limites, enveloppe, simplification, séparation des parties | Traitements vectoriels, API |
| 05. Visualisation | Cartes thématiques statiques et exports PNG/PDF/SVG | Mise en page, API |
| Cas des sites miniers | Filtrage, dernier relevé par identifiant, réparation, reprojection, sélection par parc, distance, couronnes et indicateurs agrégés | Traitements vectoriels, API |
| Earth Lab | Hauteur de canopée, différence de MNT, extraction, statistiques zonales, classes, superficies, transitions, rééchantillonnage et pente | Calculatrice, Traitements raster, Terrain, API |

La colonne d’accès décrit les points d’entrée du logiciel. Le rapport `etapes.csv` précise lesquels ont effectivement été exécutés pour chaque contrôle : `API`, `API + export` ou `GUI`. Une opération disponible dans un formulaire n’est pas présentée comme un test de clic lorsqu’elle a uniquement été appelée par l’API.

Le contrôle ne reproduit pas l’intégralité des cellules des notebooks. Les démonstrations Folium, contextily, Cartopy, geoplot, ipyleaflet et Dask-GeoPandas ne sont pas couvertes comme outils natifs de Cartomize. L’accès au serveur WFS historique et le raster facultatif absent du dépôt du tutoriel ne sont pas exécutés. Les fonctions Dask raster de Cartomize ne constituent pas un remplacement de Dask-GeoPandas pour les vecteurs.

## Projet Paris : équipements et occupation du sol

Les sources comprennent 80 quartiers, 1 226 stations de vélos, 7 856 arbres et 3 243 polygones d’occupation du sol. Ces effectifs décrivent l’instantané du tutoriel, pas la situation actuelle.

1. Importer les quartiers et stations dans l’explorateur.
2. Reprojeter en Lambert-93 (`EPSG:2154`) pour les distances et superficies.
3. Dans **Traitements vectoriels**, choisir **Synthèse par zone**. La couche source contient les quartiers, la couche de comparaison les stations. Choisir `within`, la statistique **Nombre** et le champ de sortie `stations`.
4. Utiliser la statistique **Somme** sur `bike_stands` pour la capacité totale. Répéter le comptage avec la couche d’arbres.
5. Créer un tampon de 150 mètres sur la ligne de la Seine fournie par le tutoriel, puis sélectionner les quartiers qui l’intersectent.
6. Sélectionner `district_name = Muette`. Aligner ce quartier sur le SCR de l’occupation du sol et découper les polygones. Calculer leurs superficies, puis les agréger par `class`.
7. Produire la carte thématique et exporter les résultats.

Les références du jeu sont 996 stations à l’intérieur des quartiers, 7 799 arbres appariés, 21 quartiers intersectant le tampon de la Seine et 136 fragments d’occupation du sol dans Muette. Les proportions sont calculées sur la somme des surfaces découpées du jeu d’occupation du sol ; elles ne supposent pas une couverture exhaustive du territoire.

## Projet RDC : sites miniers et aires protégées

Le jeu contient 3 687 relevés et 50 aires protégées. Le filtre sur le projet IPIS et les effectifs positifs conserve 2 816 relevés. La sélection du dernier relevé complet conserve 2 151 sites distincts.

**Dernier relevé par identifiant** conserve une ligne entière après tri stable des dates. Cette convention diffère de `groupby.last()` dans le tutoriel : cette dernière méthode peut prendre les dernières valeurs non nulles de plusieurs relevés et les réunir dans une même ligne. L’analyse ne mélange pas ces conventions.

L’audit des géométries détecte et répare un polygone invalide. Les couches sont ensuite reprojetées en `EPSG:32735`, comme dans le scénario de référence. Les sélections utilisent explicitement `within` : un point exactement sur une limite n’est pas compté à l’intérieur.

Les contrôles portent sur l’appartenance aux parcs, les agrégations par aire protégée, les distances minimales calculées pour chacun des 2 151 sites et les couronnes extérieures de dix kilomètres. Le rapport distingue les sites distincts des correspondances multiples avec des couronnes qui se chevauchent. Les résultats sont historiques et ne constituent ni un inventaire actualisé ni une conclusion juridique sur l’activité des sites.

## Projet LiDAR : surface, terrain et canopée

Quatre GeoTIFF MNT/MNS de 4 000 × 2 000 pixels sont lus. Le SCR, la transformation affine, les dimensions et les masques sont comparés avant les opérations.

| Résultat | Calcul et contrôle |
|---|---|
| Hauteur de canopée | MNS − MNT, avant et après, comparé aux tableaux masqués NumPy |
| Variation altimétrique | MNT après − MNT avant, sur les pixels valides communs |
| Extraction | Masque du shapefile d’origine, comparé à `rasterio.mask` |
| Statistiques zonales | Effectif, minimum, maximum, moyenne, somme, écart-type |
| Classes de hauteur | `< 2 m`, `2 à < 10 m`, `≥ 10 m`, avec conservation du masque |
| Superficies et transitions | Comptage exact des pixels et des couples de classes |
| Grille de 5 mètres | Rééchantillonnage bilinéaire, comparé à Rasterio |
| Pente | Filtre de Horn, avec référence matricielle explicite et contrôle des bordures |

Les valeurs négatives brutes de MNS − MNT ne sont pas supprimées silencieusement. Les différences altimétriques ne sont pas interprétées comme un effet causal de la crue sans examen de la précision verticale et du recalage.

Le scénario graphique ouvre aussi l’orthophoto de 16 000 × 8 000 pixels, soit 128 millions de pixels spatiaux et trois bandes. Le test vérifie un rendu effectif de la vue, puis enregistre des captures en thèmes clair et sombre.

## Critères d’acceptation

Les comparaisons contrôlent les effectifs, les noms et l’ordre des attributs, leurs valeurs, les géométries, les SCR, les dimensions, les transformations et les masques. Pour les résultats GeoPackage relus, seule la position de la colonne géométrique est normalisée ; les colonnes attributaires et leurs valeurs restent contrôlées. Des tests de régression vérifient qu’une différence de valeur, de champ, de ligne, de SCR ou de géométrie est refusée.

Les références vectorielles partagent GeoPandas/GEOS avec Cartomize et certains contrôles raster partagent Rasterio/GDAL. Il s’agit d’une validation d’intégration et de cohérence des résultats, non d’une certification indépendante de ces moteurs.

Le fichier `validation.json` constitue le résultat machine, `etapes.csv` la matrice des contrôles et `RAPPORT.md` leur synthèse. Les captures et les cartes produites sont conservées avec les rapports. Les conclusions doivent toujours être associées au commit inscrit dans ces fichiers.
