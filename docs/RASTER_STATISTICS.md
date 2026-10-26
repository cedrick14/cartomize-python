# Statistiques raster : calibration, couverture et valeurs absentes

`cm.raster.zonal_stats` calcule une ligne par zone, conserve les attributs, l’ordre,
l’index et le système de coordonnées de cette couche. Les zones qui se recouvrent
sont analysées indépendamment. Les champs ajoutés sont `count`, `min`, `max`,
`mean`, `sum` et `std` ; `std` est l’écart-type de population. Les zones non vides
doivent être des polygones ou multipolygones. Les géométries absentes ou vides
restent présentes dans le résultat avec un compte nul et des statistiques manquantes.

## Choisir les valeurs analysées

Par défaut, `value_mode="physical"` applique les facteurs GDAL enregistrés dans
la bande :

```text
valeur physique = valeur stockée × scale + offset
```

Par exemple, les valeurs stockées 1000 et 2000 avec `scale=0.001` et `offset=-0.5`
donnent 0.5 et 1.5. Leur moyenne est 1.0 et leur somme 2.0. Avec
`value_mode="raw"`, les statistiques portent explicitement sur les valeurs
stockées, soit une moyenne de 1500 dans cet exemple.

La calibration utilise uniquement les métadonnées présentes dans le raster.
Elle ne découvre pas un fichier de métadonnées satellite voisin et ne réalise
pas de correction atmosphérique. Pour Landsat/Sentinel, préparer d’abord les
bandes avec le module de prétraitement. Sur un raster déjà calibré, les facteurs
1 et 0 conservent les valeurs.

La validité suit le masque fourni par GDAL/Rasterio : un masque explicite est
prioritaire ; en son absence, le NoData déclaré détermine les pixels invalides.
Les valeurs non finies sont toujours exclues. Un zéro marqué valide reste une
observation, même lorsqu’un masque explicite corrige une ancienne déclaration
NoData à zéro. Une zone sans pixel valide reçoit
`count=0` et des statistiques manquantes, y compris `sum` : l’absence de mesure
ne devient pas une somme de mesures nulles.

## Mesurer ce qui est réellement couvert

`include_coverage=True` ajoute trois champs :

| Champ | Définition |
|---|---|
| `zone_pixels` | Pixels sélectionnés par la zone sur la grille du raster prolongée au-delà de son emprise. |
| `raster_pixels` | Pixels de cette zone situés dans l’emprise du raster, avant exclusion du NoData. |
| `coverage_percent` | `100 × count / zone_pixels`, ou valeur manquante si la zone ne sélectionne aucun pixel. |

La règle par défaut sélectionne les pixels dont le centre est couvert par la zone,
frontière comprise. `all_touched=True` retient les cellules fermées qui intersectent
la zone dans sa fenêtre candidate, obtenue en arrondissant les bornes en coordonnées
pixel vers l’extérieur (`floor`/`ceil`). Les pixels sont évalués sur la même grille
globale, quelle que soit la taille des blocs. Une vérification géométrique des
pixels proches de la frontière stabilise les cas où une diagonale passe exactement
par des coins ou des centres de pixels.

Cette convention explicite peut différer de la rasterisation GDAL sur les contacts
exacts avec une frontière ; elle est enregistrée dans le rapport. Il s’agit d’une couverture sur une
grille, pas d’une proportion exacte de superficie vectorielle. Les valeurs
dépendent donc de la résolution et de cette règle d’inclusion. Une petite zone
peut ne sélectionner aucun pixel.

Une zone dont la moitié se trouve hors du raster ne peut pas obtenir 100 % de
couverture simplement parce que tous ses pixels intérieurs au raster sont valides.
Les emprises tournées suivent les quatre coins de la transformation affine.

## Python, terminal et fenêtre

```python
import cartomize as cm

statistiques = cm.raster.zonal_stats(
    "temperature.tif", "communes.gpkg",
    band=1, value_mode="physical", include_coverage=True,
    prefix="temperature_", all_touched=False,
)
print(statistiques[["temperature_mean", "temperature_coverage_percent"]])
print(statistiques.attrs["cartomize"])
```

Le préfixe permet de conserver plusieurs résultats sur la même couche. Les noms
en collision sont refusés avant le calcul. L’opération enregistrée
`raster.zonal_stats` accepte les mêmes paramètres dans `cm.execute_operation`,
`cm.processing_plan` et `cartomize process`. Dans ce cas, le fichier
`operation.json` conserve la calibration et les règles de calcul sous `metadata`.
Un export direct vers GeoPackage ne conserve pas les attributs Python `attrs` ;
utiliser l’opération enregistrée pour garder ce rapport avec le produit.

Dans **Traitements raster → Statistiques zonales**, sélectionner le raster, la
couche des zones, la bande, le mode de valeurs et, si nécessaire, la couverture
et le préfixe. Les mêmes réglages sont accessibles dans **Chaîne de traitements**.

## Volume de calcul et compatibilité

Le calcul parcourt les fenêtres par blocs et combine les statistiques sans
charger tout le rectangle de chaque zone en mémoire. `block_size` règle la taille
des blocs (de 1 à 2048 pixels par côté). `max_zone_pixels` limite le nombre de pixels candidats dans le rectangle
de traitement d’une zone, avant l’exécution. Une grande zone extérieure peut donc
atteindre cette limite si le calcul de couverture est demandé. Réviser l’emprise
ou augmenter explicitement le budget après estimation du coût.

Le passage au mode physique par défaut corrige le calcul sur les rasters quantifiés.
Pour reproduire volontairement un ancien calcul sur les valeurs stockées, utiliser
`value_mode="raw"`. Les surfaces par classes et les matrices de transition
continuent à traiter les codes de classes ; cette calibration statistique ne
renumérote pas les catégories.

Les points et lignes sont désormais refusés comme zones non vides : ils demandent
un échantillonnage ou un profil, dont la règle est différente d’une statistique de
surface. Cette validation évite qu’une géométrie de dimension nulle reçoive
silencieusement une statistique vide selon sa position sur la grille.

## Références de la convention

- [GDAL RasterBand : scale, offset et unités](https://gdal.org/en/stable/doxygen/classGDALRasterBand.html).
- [Rasterio : lecture des bandes et des fenêtres](https://rasterio.readthedocs.io/en/stable/api/rasterio.io.html).

Les résultats attendus et la cohérence Python/terminal/chaînes sont vérifiés dans
`tests/test_raster_integrity.py` et `tests/test_zonal_stats_integration.py`.
