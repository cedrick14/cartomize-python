# Architecture

## Provenance technique

Dépôt : https://github.com/cedrick14/cartomize-qgis

Branche source : `arcgispro-build-10.5.1.3`.
Commit : `4790f0e152834725d989e336199f799782bc3680`.
Édition : Cartomize for ArcGIS Pro 10.5.1.

Le dossier `arcgis-build/source` contient l'extension C#/WPF, les services
natifs Esri et une boîte à outils Python ArcPy. La bibliothèque reprend les
modules Python indépendants d'ArcPy et les maquettes de cette édition.
Les dix modules repris sont conservés dans `_core`, à usage interne.
Leur version interne 10.5.1 exprime leur provenance; la version du
paquet est 1.7.0. Les fichiers originaux ne sont pas modifiés.

## Fonctionnalités

| Composant | Responsabilités |
|---|---|
| Maquettes | 24 JSON originaux, validation et conversion en millimètres conservées |
| Analyse des champs | Règles de rôle, champ d'étiquette et champ thématique d'ArcGIS Pro, adaptateur GeoPandas |
| Analyse raster | Profils et inférence originaux, lecture/masque Rasterio |
| Cartographie | Rendu Matplotlib, cadres multiples, échelle géodésique locale, nord vrai, légendes |
| Géométrie | GeoPandas/Shapely : clip, overlay, sjoin, dissolve, buffer, réparation et audit |
| Reprojection vectorielle | Découverte multicouche, catalogue PROJ, choix géodésique par couche, emprises et publication atomique du lot |
| Harmonisation vectorielle | Inspection des schémas, correspondances, conversions et valeurs manquantes explicites, concaténation avec provenance et relecture typée |
| Mesures | Distances en mètres, surfaces m²/ha/km² et conversion des unités projetées |
| Raster | NDVI/différence normalisée, reclassification, découpage, reprojection, statistiques zonales, surfaces et transitions |
| Imagerie | Découverte des scènes, contrôle de couverture, sélection et compléments STAC facultatifs, calibration, masques, mosaïque cohérente, multibande, AOI, compositions RGB/RGBA et traçabilité |
| Superposition | Ordre par rôle, styles des routes/limites/localités et explication par layer_plan |
| Algèbre raster | Interpréteur AST sans exécution Python, traitement par blocs, lecture commune et calculs concurrents |
| Indices spectraux | 18 formules documentées, paramètres et registre extensible |
| Statistiques | Voisinages avec marges de blocs et synthèse multirasters |
| Interface graphique | Qt facultatif, assistant cartographique et catalogue des outils, tâches en arrière-plan, progression et annulation |
| Production | Atlas, CLI, wheel, distribution source et procédure PyPI |

## Choix techniques

- Aucun import `arcpy`, `qgis` ou composant natif Esri à l'exécution.
- Objets GeoPandas standards, sans nouvelle classe concurrente de GeoDataFrame.
- CRS explicite, entrées copiées pour les opérations vectorielles.
- Masques déclarés prioritaires; le diagnostic individuel reste en lecture seule. La préparation du projet applique les fonds périphériques retenus dans des copies réversibles.
- Écritures raster temporaires puis remplacement atomique de chaque fichier, sources protégées. Les trois fichiers d’un produit multiscène sont remplacés successivement; une panne système pendant cette phase peut interrompre l’enregistrement du groupe de fichiers.
- Le module automatique M07 prépare ses produits dans un nouveau dossier temporaire, vérifie leur couverture puis publie le dossier complet. Une couverture refusée conserve un diagnostic distinct sans publier le produit scientifique.
- Les grands calculs NDVI/reclassification et comptages sont lus par fenêtres.
- Les exports utilisent des images raster rééchantillonnées à 2048 pixels par
  dimension par défaut. `max_raster_size` ajuste cette limite d'affichage.
- La taille physique A4/A3 n'est pas recadrée à l'export.
- Aucun téléchargement de fond de carte ni télémétrie. Les accès STAC nécessitent une demande explicite ou un catalogue configuré pour compléter la couverture ; les recherches transmettent la zone et les filtres choisis au fournisseur.

## Limites explicites

Le moteur autonome utilise Matplotlib pour les mises en page. Il ne produit pas de fichiers PAGX et ne reprend pas les composants C# Esri. Les projets APRX sont accessibles par la passerelle ArcGIS Pro facultative. Le rendu et le transfert des styles sont limités aux propriétés documentées.

La suppression de collisions d'étiquettes est une heuristique simple et peut
masquer des étiquettes dans les zones denses. Les titres longs peuvent exiger
une adaptation de la maquette. Les passages de l'antiméridien et les cartes
polaires demandent une projection et des emprises préparées par l'utilisateur.

Les surfaces sont planaires et dépendent du choix de projection. La barre
d'échelle exprime une distance géodésique locale, pas une échelle uniforme
sur toute une carte à grande étendue. Les statistiques zonales recoupent
chaque zone indépendamment, sans supprimer les chevauchements.

Les calculs à grande étendue peuvent nécessiter beaucoup de mémoire pour
les géométries, le découpage raster, ou une zone individuelle. Les configurations et résultats de test sont décrits dans [VALIDATION.md](VALIDATION.md).

## Références techniques

- https://geopandas.org/en/stable/docs/reference/api/geopandas.overlay.html
- https://geopandas.org/en/stable/docs/reference/api/geopandas.sjoin.html
- https://rasterio.readthedocs.io/en/stable/topics/masks.html
- https://packaging.python.org/en/latest/tutorials/packaging-projects/

Le [guide imagerie](IMAGERY_WORKFLOW.md) précise les formats reconnus, les masques,
les contraintes scientifiques et les fonctionnalités encore à développer.

Le moteur de calcul, ses paramètres de mémoire et ses limites sont décrits
dans [Algèbre raster](RASTER_CALCULATIONS.md). Les commandes graphiques sont
décrites dans [Interface graphique](DESKTOP.md).

## Chaîne cartographique

`workflow.cartographic_workflow` enchaîne l'identification des scènes,
`prepare_imagery`, `color_composite`, `compose_map` et les exports. Un
répertoire de production neuf est publié après la réussite de toutes les
opérations. L'annulation et les erreurs nettoient les produits temporaires.
La page Production automatisée appelle la même API que les scripts Python.
L'icône originale est distribuée dans `cartomize/assets`.

## Accès aux fonctions cartographiques

`desktop_layout` expose les maquettes, les cadres et les contenus au moteur
`Map`. `desktop_tools` expose les diagnostics et les traitements existants.
La page Mise en page et la page Atlas partagent la même configuration.
Leur aperçu utilise le moteur de rendu cartographique dans un travailleur en arrière-plan.
Le [tableau fonctionnel](FUNCTIONAL_COVERAGE.md) distingue la disponibilité
dans Python des fonctions nécessitant encore un portage natif.

## Préparation d’un projet de couches

`project.analyze_project` rassemble les diagnostics. `project.prepare_project`
appelle `nodata.mask_background`, dénombre les classes présentes et prépare un
plan JSON. `nodata` associe un échantillonnage spatial conservateur à un
étiquetage des composantes connexes par tuiles. Seules les composantes de fond
reliées au bord sont supprimées du masque de validité ; les bandes restent
identiques. Les valeurs NoData explicitement saisies ont une portée globale.
Le masque interne GeoTIFF accompagne le fichier lors des déplacements.
`desktop_project` expose l’analyse, la nomenclature et le rétablissement des
sources. Le plan charge les classes dans `MappingPage`, puis dans `Map`.

Les tableaux raster sont limités aux tuiles ; les métadonnées de composantes
croissent avec leur nombre et celui des tuiles. La limite de composantes ne
constitue pas une limite stricte de mémoire du processus.

## Reprojection vectorielle par lot

`vector_reprojection` sépare la découverte des couches, l’inspection des
transformations et leur exécution. Le catalogue sérialisable conserve les
identifiants et définitions des opérations PROJ ; aucun objet Transformer ne
doit être transmis entre les contrôles graphiques et leur travailleur.
Chaque couche est transformée par une seule opération choisie, puis écrite
et relue avant publication du dossier entier.

`processing` expose `vector.reproject_batch` avec les mêmes paramètres que
l’API. Les identifiants des couches deviennent des noms de produits secondaires
dans les plans. Le manifeste conserve les SCR, les emprises issues des sommets
réels, les opérations, les grilles, les politiques et l’environnement.
Le [guide M09](VECTOR_REPROJECTION.md) décrit les contrats de coordonnées,
les contrôles de fidélité et la portée horizontale du traitement.

## Harmonisation et fusion de couches

`vector_merge` sépare l’inspection des sources de la conversion vers le schéma
cible et de la concaténation. Les correspondances sont des objets sérialisables
indexés par les identifiants des sources ; elles ne contiennent aucun widget
ni objet de moteur externe. Le même contrat alimente Python, le terminal,
les plans et les formulaires de `desktop_merge`.

`vector_io` utilise Arrow pour la lecture, puis des tableaux typés et leurs
masques de valeurs nulles pour l’écriture. Les entiers et types attributaires
ne transitent pas par une représentation flottante implicite. La relecture du
GeoPackage contrôle les données enregistrées avant publication atomique du
nouveau dossier. Le manifeste conserve schéma, correspondances, politiques,
provenance et transformations éventuelles. Une reprojection explicitement
demandée réutilise M09 ; la fusion attributaire n’effectue aucune union de
géométries. Voir le [contrat M10](VECTOR_MERGE.md).

## Extraction attributaire et spatiale — M12

`vector_selection.extract_features` compose des masques positionnels, conserve
les deux partitions intactes et produit un rapport par ligne. Le masque
attributaire commun avec `vector_workflows.select_attributes` traite entiers,
booléens, dates natives et horodatages sans conversion implicite destructrice.
Le schéma source est établi avant séparation afin de conserver les types des
partitions vides ou entièrement nulles. `processing.execute_operation`
enregistre les deux GeoPackage avec relecture exacte, le CSV et son schéma,
l'audit JSON typé et la synthèse dans un dossier atomique. Les plans peuvent
consommer indépendamment `data` et `rejected`. `desktop_selection` raccorde ce
moteur au formulaire Vecteur et à ses résultats persistants.

## Conversion et conditionnement — M11

`vector_conversion.py` et `raster_conversion.py` publient des livraisons atomiques après comparaison exhaustive du résultat relu. Les objets `ConvertedVector` et `ConvertedRaster` sont raccordés à `processing.py` par les opérateurs `vector.convert` et `raster.convert`. La CLI, les plans et `desktop_conversion.py` partagent ces moteurs.

Le lecteur `vector_io.py` sépare les attributs Arrow et les WKB natifs pour FlatGeobuf, puis aligne les enregistrements par FID vérifié : ce chemin évite un crash natif sur les géométries nulles en conservant les entiers nullables exacts et les sélections. Les autres pilotes conservent leur chemin existant.

Le moteur raster vérifie les pixels par blocs, les masques et les métadonnées avant publication. Les compagnons nécessaires à une livraison font partie de son manifeste et des projets portables. Le binaire COG n’est pas rouvert en écriture après sa création. Voir le [contrat G06](DATA_CONVERSION.md).
