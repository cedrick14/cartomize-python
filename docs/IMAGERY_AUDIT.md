# Diagnostic de couverture des images

Le diagnostic répond à trois questions avant la préparation : les scènes
atteignent-elles la zone d'étude, contiennent-elles des données à cet endroit,
et ces données restent-elles utilisables après les masques de qualité ?
Il utilise les mêmes bandes, la même grille cible et les mêmes règles de
validité que le moteur de préparation multispectrale.

## Depuis Python ou un notebook

```python
import cartomize as cm

diagnostic = cm.audit_imagery(
    "donnees/scenes",               # dossier ou manifeste de scènes
    "resultats/diagnostic",         # nouveau dossier
    aoi="donnees/zone_etude.gpkg",
    band_order=["blue", "green", "red", "nir"],
    target_crs="EPSG:32733",        # choisir le système adapté à l'étude
    resolution=30,                 # mètres
)

print(diagnostic.report["usable_percent"])
print(diagnostic.report["recommended_action"])
print(diagnostic.report["recommended_scene_ids"])
print(diagnostic.gaps)
```

Les objets `Scene` et `Band` restent utilisables pour des données personnalisées.
Les fichiers standard Landsat C2 L2 et Sentinel-2 L2A doivent conserver les
métadonnées et masques requis. Pour des données dépourvues de masque de qualité,
`mask_clouds=False` est un choix explicite à documenter.

## Depuis le terminal

```bash
cartomize audit-imagery donnees/scenes resultats/diagnostic --aoi donnees/zone_etude.gpkg --bands blue,green,red,nir --crs EPSG:32733 --resolution 30
```

L'opérateur `imagery.audit` est également disponible dans les chaînes de
traitement et dans `cartomize process`. Ses produits nommés sont `primary`
(rapport), `coverage` et `gaps`. Un traitement suivant peut référencer
`@diagnostic:gaps` si l'identifiant de l'étape est `diagnostic`.

## Lire les résultats

Les pourcentages portent sur les cellules de la zone d'étude représentées sur
la grille choisie. La règle normale retient les centres des pixels ;
`all_touched=True` inclut toutes les cellules touchées par le polygone. La
résolution et cette règle sont donc à conserver lors des comparaisons.

| Couverture | Signification |
|---|---|
| Emprise (`footprint`) | Emprise commune aux bandes demandées d'une acquisition, puis réunion entre acquisitions admissibles. |
| Données présentes (`present`) | Pixels disposant de toutes les bandes, après prise en compte des masques source, NoData et valeurs non finies. |
| Données utiles (`usable`) | Pixels conservés avec les masques de qualité demandés, selon les mêmes règles de calibration et de rééchantillonnage que la préparation. |

Un spectre complet doit provenir d'une même scène. Deux acquisitions ayant
chacune une bande absente au même emplacement ne créent pas ensemble un pixel
multispectral valide. Les valeurs nulles valides ne sont pas assimilées à NoData.

`coverage.tif` contient trois bandes binaires, dans cet ordre, avec 255 hors
zone. `gaps.tif` localise les causes de lacunes :

| Code | Signification |
|---:|---|
| 0 | Données utiles disponibles. |
| 1 | Hors de l'emprise commune des bandes. |
| 2 | Dans l'emprise, mais données nécessaires absentes ou invalides. |
| 3 | Données présentes exclues par les critères de qualité. |
| 255 | Hors zone d'étude. |

Le rapport conserve les paramètres et les couvertures par scène et pour
l'ensemble. La recommandation dépend du seuil `coverage_threshold` (100 % par
défaut) : scène unique suffisante, mosaïque nécessaire, ou scènes complémentaires
à rechercher. Une couverture nulle est un résultat de diagnostic valide ; elle
ne produit pas une image scientifique artificiellement remplie.

Le diagnostic est publié dans un dossier neuf. L'annulation ou une erreur ne
publie pas de dossier partiel. La production d'images reste une action distincte,
avec les réglages de l'expert. Recalculer le diagnostic après modification des
fichiers source, des bandes, de la zone, de la résolution ou des masques.

## Dans l'interface

La page **Prétraitement multispectral** propose le diagnostic sur les scènes et
bandes sélectionnées. Les calculs utilisent le travailleur en arrière-plan et
peuvent être annulés. Le rapport et les cartes sont accessibles dans les
résultats du projet. L'application de la proposition ajuste la sélection des
scènes et l'option de mosaïque ; les autres paramètres restent consultables.

Après préparation, l'index de provenance des scènes et le rapport de traitement
accompagnent les produits scientifiques et les compositions colorées.

## Références de méthode

- [Masques de données Rasterio](https://rasterio.readthedocs.io/en/stable/topics/masks.html)
- [Produits Sentinel-2](https://sentiwiki.copernicus.eu/web/s2-products)
- [Masques de qualité Landsat Collection 2](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands)
- [Préparation multispectrale Cartomize](IMAGERY_WORKFLOW.md)
