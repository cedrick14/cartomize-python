# Diagnostic de couverture des images

Le diagnostic répond à trois questions avant la préparation : les scènes
atteignent-elles la zone d'étude, contiennent-elles des données à cet endroit,
et ces données restent-elles utilisables après les masques de qualité ?
Il utilise les mêmes bandes, la même grille cible et les mêmes règles de
validité que le moteur de préparation multispectrale.

`audit_imagery()` réalise ce diagnostic seul. Le [mode automatique M07](IMAGERY_AUTOMATIC.md)
le raccorde à la sélection, au contrôle du seuil et à la production avec
`preprocess_imagery()` ; c’est le mode par défaut de la fenêtre depuis la version 1.4.0.

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

La résolution par défaut conserve la longueur des axes des pixels natifs lorsque
le SCR est inchangé, y compris pour les images tournées. En cas de reprojection,
elle provient de la grille proposée par GDAL à partir de la transformation affine
réelle. La résolution sélectionnée la plus grossière est retenue ; une valeur
explicite en mètres permet de fixer la grille de l’étude.

Les dates ISO sont normalisées. Une date vide est inconnue : plusieurs scènes
sans date exigent `allow_mixed_dates=True`, comme des acquisitions de dates
différentes. Cette autorisation exprime un choix multitemporel et reste enregistrée.

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

`threshold_met` indique si ce seuil est atteint. `coverage_status` décrit la
couverture réelle : `empty` sans pixel utilisable, `complete` à 100 %, `partial`
entre les deux. Une couverture de 85 % avec un seuil de 80 % reste donc
`partial`, avec `threshold_met=True`. Ce découplage est explicite depuis la
version 1.4.0 ; les anciens rapports pouvaient employer `complete` pour
indiquer seulement l’atteinte du seuil demandé.

Le diagnostic est publié dans un dossier neuf. L'annulation ou une erreur ne
publie pas de dossier partiel. Avec cet appel de diagnostic seul, la production
d’images reste une action distincte. En mode automatique, le contrôle est
recalculé pendant chaque préparation et conditionne sa poursuite. Un diagnostic
ancien ne garantit pas l’état de fichiers ou de paramètres modifiés.

## Dans l'interface

La page **Prétraitement multispectral** propose **Automatique : contrôler et
préparer** par défaut. **Exécuter** vérifie la couverture, choisit les scènes
et la mosaïque, puis applique le seuil indiqué. **Accepter moins que le seuil**
est une décision explicite ; les résultats incomplets conservent leur statut
partiel. Un catalogue peut rechercher les compléments manquants.

**Diagnostiquer la couverture** reste disponible pour examiner les données
avant une production. **Appliquer la sélection proposée** ajuste les scènes
cochées ; ce geste ne dispense pas le mode automatique de recalculer le contrôle.
Le mode **Expert : choisir les opérations** conserve la préparation manuelle.
Les calculs fonctionnent en arrière-plan et peuvent être annulés. Le rapport
et les cartes sont accessibles dans les résultats, y compris lorsqu’un manque
de couverture bloque la production scientifique.

Après préparation, l'index de provenance des scènes et le rapport de traitement
accompagnent les produits scientifiques et les compositions colorées.

## Références de méthode

- [Masques de données Rasterio](https://rasterio.readthedocs.io/en/stable/topics/masks.html)
- [Produits Sentinel-2](https://sentiwiki.copernicus.eu/web/s2-products)
- [Masques de qualité Landsat Collection 2](https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands)
- [Préparation multispectrale Cartomize](IMAGERY_WORKFLOW.md)
