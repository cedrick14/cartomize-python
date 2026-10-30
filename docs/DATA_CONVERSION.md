# Conversion et conditionnement des données — M11 / G06

G06 prépare une livraison vectorielle ou raster dans un format choisi, puis
relit intégralement cette livraison avant de la rendre disponible. Python,
Jupyter, le terminal, les plans et la page **Conversion et formats** utilisent
les mêmes moteurs. Les sources sont conservées. Chaque exécution produit un
nouveau dossier comprenant les données, leurs éventuels fichiers associés,
un manifeste et un rapport de comparaison.

## Correspondance avec l’inventaire

| Exigence G06 | Comportement |
|---|---|
| Choisir le format et la couche | Inspection des couches et des pilotes ; sélection explicite pour un fichier multicouche |
| Contrôler les noms et l’encodage | Correspondance explicite des noms de champs ; encodage Shapefile configurable ; UTF-8 pour les autres formats |
| Contrôler les types et la précision | Comparaison des types et des valeurs vectorielles ; contrôle de plage et de précision pour les pixels |
| Régler compression et NoData | Compression sans perte ; conservation, remplacement ou retrait explicite du NoData avec conservation de la validité |
| Vérifier la relecture | Toutes les lignes et géométries ; tous les pixels valides et masques, par blocs ; projection, grille et métadonnées |
| Décrire les pertes éventuelles | Refus par défaut ; politique `report` explicite et bilan détaillé des changements acceptés |

La conversion conserve le système de coordonnées. Pour changer de projection,
exécuter d’abord G04 pour les vecteurs, ou la reprojection raster existante.

## Formats de livraison

| Données | Pilote | Extension | Particularités |
|---|---|---|---|
| Vecteur | `GPKG` | `.gpkg` | Types, valeurs nulles et identifiants métier vérifiés ; couche nommée |
| Vecteur | `GeoJSON` | `.geojson` | Encodage UTF-8 ; valeurs et coordonnées relues ; représentation GDAL conservant le SCR source |
| Vecteur | `ESRI Shapefile` | `.shp` et associés | Noms, largeur des champs, types, précision et encodage contrôlés ; conserver tout le dossier |
| Vecteur | `FlatGeobuf` | `.fgb` | UTF-8 ; ordre des enregistrements conservé sans index spatial de sortie |
| Raster | `GTiff` | `.tif` | GeoTIFF tuilé, types et compression explicites |
| Raster | `COG` | `.tif` | Organisation Cloud Optimized GeoTIFF créée par GDAL et vérifiée après publication |

La disponibilité est vérifiée dans les pilotes GDAL effectivement installés.
Les formats qui ne figurent pas dans cette liste ne sont pas annoncés comme
pris en charge à l’écriture. Les entrées peuvent utiliser les autres formats
lisibles par les moteurs installés, dans le périmètre des données ci-dessous.

Le GeoJSON de livraison conserve le SCR d’origine et n’active aucune
reprojection RFC 7946 implicite. Pour un usage web en longitude/latitude,
préparer une source dans le SCR requis avant cette conversion.

## Depuis Python ou Jupyter

```python
import cartomize as cm

# L’inspection d’un fichier multicouche permet de voir les couches disponibles.
inspection = cm.inspect_vector_conversion("donnees.gpkg")
print(inspection)

vecteur = cm.convert_vector(
    "donnees.gpkg", "livraison_vecteur",
    layer="villages", driver="GPKG", output_layer="villages",
    field_map={"nom_du_village": "nom"},
)
print(vecteur.data, vecteur.report, vecteur.manifest)

raster = cm.convert_raster(
    "occupation_sol.tif", "livraison_raster",
    driver="COG", dtype="uint16", nodata=65535,
    compression="deflate",
)
print(raster.data, raster.report, raster.manifest)
```

`destination` est un **dossier neuf**, pas le nom d’un fichier. Un dossier
existant est refusé. Un fichier multicouche sans `layer` est refusé par le
moteur de conversion ; l’inspection peut en donner la liste sans le convertir.
Une conversion vectorielle publie une couche. Pour plusieurs couches, créer
plusieurs étapes dans un plan ou une recette.

`ConvertedVector` et `ConvertedRaster` exposent `data`, `report`, `manifest`
et `summary`. Les chemins du résultat pointent sur le dossier final ; ils
restent utilisables après la fin du traitement. Une erreur ou une annulation
avant publication supprime le dossier temporaire.

### Paramètres vectoriels

| Paramètre | Valeur par défaut | Effet |
|---|---|---|
| `layer` | `None` | Couche source ; obligatoire si plusieurs couches sont présentes |
| `driver` | `"GPKG"` | Un des quatre pilotes vectoriels pris en charge |
| `encoding` | `"UTF-8"` | Encodage de sortie ; un autre encodage est réservé au Shapefile |
| `output_layer` | `"features"` | Nom demandé pour la couche de sortie ; le Shapefile utilise `data`, d’après `data.shp` |
| `field_map` | `None` | Dictionnaire de renommage ; pas de suppression implicite de champs |
| `loss_policy` | `"error"` | Refuser les changements de représentation ; `"report"` les accepte en les consignant |

Les champs métier nommés `fid` ou `geometry`, les identifiants avec zéros
initiaux, les grands entiers et les valeurs nulles font partie des comparaisons.
Les géométries ne sont ni réparées, ni fusionnées, ni reprojetées pendant la
conversion. Les changements de coordonnées, de SCR, de type ou de dimension
géométrique, les pertes d’entités et les champs sans correspondance complète
restent des erreurs même avec `loss_policy="report"`. Une géométrie vide ne
peut pas devenir nulle, ni l’inverse. Pour les géométries, `report` permet
seulement un changement de représentation dont la normalisation conserve
exactement les coordonnées et le type.

Lorsqu’un changement de représentation est refusé par la politique `error`,
l’exception `VectorConversionError` expose le rapport complet dans son
attribut `report`. Son message identifie les premières différences. Les
incohérences structurelles ou géométriques non admissibles arrêtent le
traitement avec un message explicite.
Choisir un format plus expressif ou préparer les noms de champs permet souvent
une livraison sans perte. Le mode `report` est une décision explicite : lire
son rapport avant de réutiliser des données dont des valeurs ou types ont changé.

### Paramètres raster

| Paramètre | Valeur par défaut | Effet |
|---|---|---|
| `driver` | `"GTiff"` | `GTiff` ou `COG` |
| `dtype` | `None` | Type source conservé ; type numérique cible sinon |
| `nodata` | `"preserve"` | Conserver le NoData source |
| `compression` | `"lzw"` | `none`, `lzw`, `deflate` ou `zstd`, selon le pilote installé |
| `block_size` | `512` | Taille des blocs de traitement et des tuiles de sortie, selon les contraintes du pilote |
| `overviews` | `None` | Conserver les niveaux de pyramides source ; liste explicite pour les définir |
| `resampling` | `"nearest"` | Méthode des pyramides ; la grille et les pixels de base restent inchangés |
| `loss_policy` | `"error"` | Refuser une perte numérique ; `"report"` accepte les arrondis mesurés et consignés |

Pour `nodata`, une valeur numérique remplace la valeur source. `None` demande
son retrait en conservant le masque de validité lorsqu’il est représentable.
La chaîne `"nan"` est utilisable dans Python, JSON et les plans pour demander
un NoData NaN dans un type flottant. Ces choix sont distincts de zéro.

Une valeur NoData cible qui entre en collision avec un pixel valide est
refusée. Le dépassement de la plage du type cible est également refusé : passer
de `uint16` à `uint8` ne doit pas transformer une valeur 300 en 44. Le mode
`report` consigne le nombre de valeurs arrondies et leur erreur maximale ; il
ne remplace pas le contrôle de plage ni celui des masques.

La relecture contrôle la projection, la transformation affine, les dimensions,
les bandes, les pixels valides, les masques et les paramètres choisis. Les
descriptions, unités, échelles, décalages, interprétations des couleurs et
métadonnées conservées sont vérifiés. Les noms de catégories et tables
attributaires raster GDAL sont également conservés et relus. Les codes de
classes portant ces métadonnées ne peuvent pas être quantifiés ni remplacés
silencieusement, y compris sous les masques. Les statistiques devenues obsolètes
après un changement numérique ne sont pas présentées comme encore valides.

Un COG est préparé puis créé dans son organisation finale. Il n’est pas rouvert
en écriture pour lui ajouter des tags après sa création. Si le pilote exige un
fichier associé pour conserver certaines métadonnées, ce fichier fait partie
de la livraison et du manifeste ; déplacer le dossier complet.

## Terminal

```bash
cartomize vector-conversion-options donnees.gpkg
cartomize convert-vector donnees.gpkg livraison_vecteur --layer villages --driver GPKG

cartomize raster-conversion-options occupation_sol.tif
cartomize convert-raster occupation_sol.tif livraison_cog --driver COG --dtype uint16 --nodata 65535 --compression deflate
```

`--field-map` prend un fichier JSON de correspondance des noms. Les commandes
d’inspection ne produisent pas de livraison. `--loss-policy report` exprime
l’acceptation des changements tracés ; l’absence de cette option conserve la
politique stricte. `--nodata none`, `--nodata nan` et `--nodata preserve` ont
des significations différentes.

Les commandes génériques `cartomize process vector.convert ...` et
`cartomize process raster.convert ...` utilisent les mêmes paramètres.

## Plans, recettes et résultats

```python
plan = cm.processing_plan([
    {"id": "conversion", "operation": "vector.convert", "parameters": {
        "source": "donnees.gpkg", "layer": "villages", "driver": "GPKG"}},
    {"id": "tampons", "operation": "vector.buffer", "parameters": {
        "data": "@conversion:data", "distance": 100}},
])
cm.run_plan(plan, "livraison_plan")
```

Les deux opérateurs fournissent les produits nommés `primary`, `data`,
`manifest` et `report`. `primary` et `data` désignent le fichier géographique
principal. Tous les fichiers associés sont enregistrés dans le résultat de
l’opération et suivis par les projets portables.

## Interface graphique

1. Ouvrir **Projet → Conversion et formats** et choisir le type de données.
2. Sélectionner la source, analyser ses couches ou bandes et choisir la couche
   vectorielle si nécessaire.
3. Choisir le format et les paramètres de livraison ; pour les champs, saisir
   les nouveaux noms dans le tableau. Indiquer un nouveau dossier de sortie.
4. Lancer la conversion, ouvrir le résultat et consulter le rapport.

Les paramètres sont capturés au lancement : modifier ensuite un widget ne
change pas un traitement déjà engagé. Les sessions conservent les choix.
Les sorties peuvent alimenter les autres traitements et être ajoutées au
projet. Une inspection devenue obsolète après un changement de source n’est
pas réutilisée silencieusement.

## Périmètre et références

La conversion vectorielle demande une couche spatiale dont le SCR est connu.
Ses attributs doivent être scalaires : chaînes, entiers signés 64 bits, réels
finis, booléens, dates ou horodatages. Les champs binaires, structurés ou
mélangeant des types incompatibles sont refusés.

Elle conserve les géométries simples prises en charge par le moteur,
avec contrôle de Z ; les dimensions mesurées M ou les représentations qui ne
peuvent être préservées sont refusées. Les contraintes du Shapefile sont
contrôlées par la relecture effective. Les entrées raster à géoréférencement
non affine ou aux masques qui ne peuvent être représentés dans la livraison
choisie demandent une préparation explicite.

Les valeurs NoData source `int64`/`uint64` sont lues exactement avant la
conversion. Une sentinelle dépassant la précision vérifiable du lecteur n’est
pas acceptée sous un alias flottant arrondi : choisir explicitement une valeur
représentable compatible avec les pixels valides. Le rapport conserve la valeur
source exacte. Les pixels entiers 64 bits ne sont pas, eux, convertis en
flottants par défaut.

Les [tests du moteur vectoriel](../tests/test_vector_conversion.py), du
[moteur raster](../tests/test_raster_conversion.py), des
[interfaces publiques](../tests/test_conversion_interfaces.py) et de la
[fenêtre](../tests/test_desktop_conversion.py) vérifient les cas représentables
et les refus. Le [cours 18](../tutorials/notebooks/18_conversion_conditionnement.ipynb)
exécute le parcours avec des données pédagogiques clairement identifiées.

Références primaires pour les règles des formats :

- [GDAL — GeoPackage](https://gdal.org/en/stable/drivers/vector/gpkg.html).
- [GDAL — Shapefile](https://gdal.org/en/stable/drivers/vector/shapefile.html).
- [GDAL — GeoJSON](https://gdal.org/en/stable/drivers/vector/geojson.html).
- [GDAL — FlatGeobuf](https://gdal.org/en/stable/drivers/vector/flatgeobuf.html).
- [GDAL — COG](https://gdal.org/en/stable/drivers/raster/cog.html).
- [Rasterio — masques NoData](https://rasterio.readthedocs.io/en/stable/topics/masks.html).
