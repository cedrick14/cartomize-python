# Cartomize 1.9.0 — M11 / G06, conversion et conditionnement

Cette version termine la procédure **G06 — Conversion et conditionnement des
données** dans le périmètre décrit par le [guide G06](DATA_CONVERSION.md).
Elle relie les formats de livraison, les paramètres explicites et la
comparaison intégrale des fichiers relus à Python, au terminal, aux plans,
aux notebooks et à une page dédiée de l’interface.

## Problème traité

Les lectures et exports des opérateurs existants ne constituaient pas une
procédure de conversion : il manquait le choix cohérent du format et des
couches, les paramètres de précision et de NoData, ainsi qu’un contrôle de
fidélité après enregistrement. Un succès du pilote d’écriture ne garantissait
pas que le fichier livré avait conservé les attributs, coordonnées, masques
et métadonnées attendus.

## Comportement livré

- **Vecteurs :** GeoPackage, GeoJSON, Shapefile et FlatGeobuf ; couche source
  explicite pour un fichier multicouche, encodage et correspondance des noms
  de champs, relecture complète et rapport des différences.
- **Rasters :** GeoTIFF et COG ; type numérique, compression sans perte,
  NoData et pyramides explicites. Chaque pixel valide et chaque masque de
  bande est comparé, avec projection et grille inchangées.
- **Métadonnées scientifiques :** descriptions, unités, échelles, décalages,
  couleurs, tags, catégories et tables attributaires raster sont contrôlés.
  Les compagnons nécessaires font partie de la livraison et du manifeste.
- **Fidélité :** pertes refusées par défaut ; la politique `report` autorise
  uniquement les changements mesurés et consignés. Débordements numériques,
  collisions NoData, altérations des coordonnées et incohérences des codes
  classés restent refusés.
- **Publication :** nouveau dossier atomique, conservant les sources ; pas
  de résultat partiel après erreur ou annulation. Les produits nommés
  `data`, `manifest` et `report` sont réutilisables dans les plans.
- **Fenêtre :** page **Projet → Conversion et formats**, inspection
  asynchrone, tableau de renommage, réglages raster, affichage des données et
  ouverture du rapport. Paramètres capturés au lancement et restaurés en
  session ; sources et compagnons conservés dans les projets portables.

## Correctifs découverts par les contrôles

Le lecteur FlatGeobuf évite le chemin Arrow de géométrie qui pouvait provoquer
un arrêt natif en présence de géométries nulles. Il associe les attributs Arrow
exacts et les WKB natifs avec vérification des FID, y compris pour les filtres
et les sélections vides. Les grands entiers nullables restent exacts.

Les contrôles indépendants des quartiers de Paris ont également révélé la
perte d’un attribut métier `id` lors de l’utilisation des identifiants natifs
GDAL, ainsi qu’un arrondi de coordonnées par le formatage GeoJSON. La lecture
sépare désormais les attributs et les FID natifs, puis vérifie la présence de
tous les champs annoncés. Le réglage d’écriture GeoJSON conserve les valeurs
binaires des coordonnées et des attributs flottants ; la comparaison finale
reste exacte, y compris pour les très petites valeurs.

Les comparaisons de nombres normalisent les scalaires NumPy avant de vérifier
la précision : un grand entier arrondi en flottant apparaît dans le rapport
avec sa valeur exacte d’origine. La valeur native du NoData 64 bits est lue
avant la décision de conservation et ne peut pas être remplacée par son alias
flottant arrondi.

Les catégories et tables attributaires GDAL, absentes du dictionnaire de tags
ordinaire de Rasterio, sont conservées et contrôlées séparément. Le COG n’est
pas rouvert en écriture après sa création ; un compagnon PAM conserve les
métadonnées que le pilote ne copie pas dans le binaire. Le rapport indique
explicitement si cette livraison dépend de fichiers associés.

La matrice Windows a révélé un débordement du formulaire vectoriel aux tailles
de texte 12 et 16 px : Qt utilisait toute la consigne du sélecteur de couche
pour calculer sa largeur minimale. Le sélecteur affiche désormais une consigne
courte ; l’aide complète reste dans le formulaire. Deux cas avec caractères
élargis reproduisent l’échec de l’ancien code et contrôlent la correction,
sans autoriser de défilement horizontal ni de texte illisible. Ce formulaire
fait aussi partie du contrôle Windows exécuté avant la suite complète.

## Validation

| Contrôle local final | Résultat |
|---|---|
| Suite complète sur Linux / Python 3.12.14 | **1 283 réussis, 2 exclus, 0 échec**, en 371,923 s |
| Cas ajoutés depuis 1.8.0 | **152**, tous inclus dans la suite complète |
| Parcours Jupyter autonome | **17 cours, 115 cellules, 0 erreur** |
| Wheel installée dans un environnement neuf hors du dépôt | **23 contrôles réussis**, 96 modules identiques aux sources |
| Données réelles et contrôle analytique portable | **12 contrôles réussis**, entrées inchangées |

Les exclusions locales concernent le matériel CUDA et le moteur QGIS natif.
Le contrôle QGIS distant et la matrice Windows/Ubuntu restent associés au
commit de la demande d’intégration. Les deux cours demandant `Tuto.zip` ne
font pas partie de la passe autonome.

Le [rapport de livraison](VALIDATION_1.9.0.json) conserve les résultats de la
suite complète, des notebooks et du paquet installé, ainsi que les empreintes
des sources vérifiées. Les [contrôles sur données réelles](VALIDATION_G06_REAL.json)
comparent les quartiers parisiens et les extraits Sentinel du projet à leurs
références, avec conservation des entrées. Les cas synthétiques sont distingués
des données observées.

Les contrôles de fenêtres ont également vérifié la largeur utile des champs,
la lisibilité du tableau et l’absence de défilement horizontal du formulaire,
avec texte agrandi à la taille minimale de la fenêtre existante.

## Cours et inventaire

Le [cours 18](../tutorials/notebooks/18_conversion_conditionnement.ipynb)
exécute neuf cellules autonomes : inspection multicouche, conversions
vectorielles, contrôle SQLite, conversion COG, comparaison des pixels,
refus de dépassement numérique, chaîne et conservation d’un masque sans
NoData déclaré.

Le registre compte **52 opérateurs** et la fenêtre **21 outils**. L’inventaire
conserve **123 procédures** et **88 références** ; G06 passe de partiel à
disponible : **17 disponibles, 44 partielles et 62 absentes**. M11 s’ajoute aux
modules M01–M10 ; les preuves historiques de ces modules sont conservées.

La prochaine procédure de l’inventaire est **G07 — Extraction attributaire et
spatiale**. Ses opérations existantes devront être complétées et vérifiées dans
leur propre périmètre. La version 1.9.0 du dépôt et du paquet construit ne
constitue pas, à elle seule, une publication sur PyPI.
